"""Route a validated PTP synthesis checkpoint without resynthesis or hardware access."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
FROZEN_BUILD_SCRIPTS = ('build_ptp.tcl', 'build.tcl', 'create_ptp_project.tcl',
                        'aurora_common.tcl', 'generate_aurora_adapter.py')
SYNTH_DCP = 'obsidian_ptp_synth.dcp'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    paths = [*(ROOT/'rtl').rglob('*.vhd'), *(ROOT/'constraints').glob('*.xdc'),
             *(ROOT/'scripts'/name for name in FROZEN_BUILD_SCRIPTS)]
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def routing_hashes():
    return {'scripts/'+name: sha(SCRIPT_DIR/name) for name in ('implement_ptp.py', 'implement_ptp.tcl')}


def manifest(folder):
    return dict(line.split('=', 1) for line in (folder/'build_manifest.txt').read_text().splitlines() if '=' in line)


def require_passed(folder, stage):
    proof = json.loads((folder/'execution.json').read_text())
    if (proof.get('status') != 'passed' or proof.get('validation_stage') != stage
            or proof.get('returncode') != 0 or proof.get('sources_changed') != []
            or proof.get('missing_artifacts') != [] or proof.get('hardware_programmed') is not False
            or not proof.get('finished_at_utc')):
        raise RuntimeError('Upstream build is not a completed, validated '+stage+': '+str(folder))
    info = manifest(folder)
    capacity = proof.get('capacity')
    if not isinstance(capacity, int) or isinstance(capacity, bool) or not 1 <= capacity <= 20:
        raise RuntimeError('Invalid upstream capacity')
    if (proof.get('max_nodes') != min(60, 3*capacity) or info.get('capacity') != str(capacity)
            or info.get('max_nodes') != str(proof['max_nodes'])
            or info.get('part') != 'xc7a35tcsg325-2' or info.get('Vivado') != '2025.2'):
        raise RuntimeError('Upstream capacity, part or Vivado manifest mismatch')
    return proof, info


def validate_synthesis(folder):
    proof, info = require_passed(folder, 'synthesis')
    expected = json.loads((folder/'source_sha256.json').read_text())
    current = source_hashes()
    if set(expected) != set(current):
        raise RuntimeError('Synthesis source inventory changed')
    changed = sorted(name for name in expected if expected[name] != current[name])
    if changed:
        raise RuntimeError('Synthesis sources changed: '+', '.join(changed))
    dcp = folder/SYNTH_DCP
    if proof.get('artifacts_sha256', {}).get(SYNTH_DCP) != sha(dcp):
        raise RuntimeError('Synthesis DCP fingerprint mismatch')
    reports = {}
    for name in ('synthesis_utilization.rpt', 'synthesis_cdc.rpt'):
        reports[name] = sha(folder/name)
        if proof.get('artifacts_sha256', {}).get(name) != reports[name]:
            raise RuntimeError('Synthesis report fingerprint mismatch: '+name)
    with zipfile.ZipFile(dcp) as archive:
        constraints = {name: archive.read(name) for name in archive.namelist() if name.lower().endswith('.xdc')}
    text = '\n'.join(data.decode(errors='replace') for data in constraints.values())
    if not constraints or any(name not in text for name in ('test_ref_m1_o', 'test_obs_o', 'reset_pipe')):
        raise RuntimeError('Synthesis DCP is missing embedded board/reset constraints')
    provenance = dict(directory=str(folder), capacity=proof['capacity'], max_nodes=proof['max_nodes'],
                      execution_sha256=sha(folder/'execution.json'),
                      source_manifest_sha256=sha(folder/'source_sha256.json'), dcp_sha256=sha(dcp),
                      build_manifest_sha256=sha(folder/'build_manifest.txt'),
                      synthesis_reports_sha256=reports,
                      embedded_constraints_sha256={name: hashlib.sha256(data).hexdigest() for name, data in constraints.items()})
    return proof, info, expected, provenance


def ip_configuration(path):
    """Normalize JSON source XCIs and XML cache XCIs without output metadata."""
    text = path.read_text(encoding='utf-8-sig')
    entries = {}
    if text.lstrip().startswith('{'):
        document = json.loads(text)
        if document.get('schema') != 'xilinx.com:schema:json_instance:1.0':
            raise RuntimeError('Unsupported JSON IP customization schema: '+str(path))
        instance = document['ip_inst']
        reference = instance['component_reference'].split(':')
        if len(reference) != 4:
            raise RuntimeError('Invalid JSON IP component reference: '+str(path))
        entries['componentRef'] = dict(zip(('vendor', 'library', 'name', 'version'), reference))
        entries['ip_revision'] = str(instance['ip_revision'])
        prefixes = {'component_parameters': 'PARAM_VALUE.', 'model_parameters': 'MODELPARAM_VALUE.',
                    'project_parameters': 'PROJECT_PARAM.', 'busif_parameters': 'BUSIFPARAM_VALUE.',
                    'bus_interface_parameters': 'BUSIFPARAM_VALUE.'}
        for group, prefix in prefixes.items():
            for name, values in instance['parameters'].get(group, {}).items():
                if not isinstance(values, list) or not values or any('value' not in value for value in values):
                    raise RuntimeError('Invalid JSON IP parameter values: '+str(path))
                normalized = [str(value['value']) for value in values]
                entries[prefix+name] = normalized[0] if len(normalized) == 1 else normalized
        runtime = instance['parameters'].get('runtime_parameters', {})
        if 'SWVERSION' in runtime:
            entries['tool_version'] = str(runtime['SWVERSION'][0]['value'])
        return entries
    root = ET.fromstring(text)
    for item in root.iter():
        tag = item.tag.rsplit('}', 1)[-1]
        if tag == 'componentRef':
            entries['componentRef'] = {key.rsplit('}', 1)[-1]: value for key, value in item.attrib.items()}
        elif tag == 'configurableElementValue':
            reference = next((value for key, value in item.attrib.items() if key.rsplit('}', 1)[-1] == 'referenceId'), '')
            if reference.startswith(('PARAM_VALUE.', 'MODELPARAM_VALUE.', 'PROJECT_PARAM.', 'BUSIFPARAM_VALUE.')):
                entries[reference] = item.text or ''
            elif reference == 'RUNTIME_PARAM.IPREVISION':
                entries['ip_revision'] = item.text or ''
            elif reference == 'RUNTIME_PARAM.SWVERSION':
                entries['tool_version'] = item.text or ''
    if 'componentRef' not in entries:
        raise RuntimeError('Invalid IP customization: '+str(path))
    return entries


def cache_provenance(folder, synth_folder, output):
    proof, info = require_passed(folder, 'routed_bitstream')
    if proof['capacity'] != 1:
        raise RuntimeError('Debug cache must come from the validated K1 baseline')
    for name in ('obsidian_ptp.bit', 'obsidian_ptp.ltx', 'obsidian_ptp_routed.dcp'):
        if proof.get('artifacts_sha256', {}).get(name) != sha(folder/name):
            raise RuntimeError('Debug-cache baseline artifact fingerprint mismatch: '+name)
    if json.loads((folder/'source_sha256.json').read_text()) != source_hashes():
        raise RuntimeError('Debug-cache baseline sources differ from the synthesis sources')
    configurations = {}
    for name in ('aurora_left', 'aurora_right', 'ptp_vio'):
        relative = Path('ptp_emulation.srcs/sources_1/ip')/name/(name+'.xci')
        baseline = ip_configuration(folder/relative)
        if baseline != ip_configuration(synth_folder/relative):
            raise RuntimeError('Debug-cache IP customization differs: '+name)
        configurations[name] = hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
    source = folder/'ptp_emulation.cache/ip'
    files = {}
    found_hub = False
    for path in source.rglob('*'):
        if path.is_symlink():
            raise RuntimeError('Cache inputs must not contain symbolic links')
        if path.is_file():
            if not path.resolve().is_relative_to(source.resolve()):
                raise RuntimeError('Cache input escapes the baseline cache')
            files[str(path.relative_to(source))] = sha(path)
            if path.name == 'dbg_hub.dcp':
                entries = [ip_configuration(metadata) for metadata in path.parent.glob('*.xci')]
                compatible = [entry for entry in entries if entry['componentRef'].get('name') == 'xsdbm'
                              and entry.get('PARAM_VALUE.C_XSDB_NUM_SLAVES') == '1'
                              and entry.get('PROJECT_PARAM.DEVICE') == 'xc7a35t'
                              and entry.get('PROJECT_PARAM.PACKAGE') == 'csg325'
                              and entry.get('PROJECT_PARAM.SPEEDGRADE') == '-2']
                if len(compatible) != 1 or '2025.2' not in path.relative_to(source).parts:
                    raise RuntimeError('Debug-hub cache customization/version mismatch')
                found_hub = True
    if not found_hub:
        raise RuntimeError('Validated baseline has no debug-hub cache checkpoint')
    # Copy the cache: neither Vivado nor its cache statistics may touch the K1
    # baseline. The Tcl consumer also sets cache permissions to read only.
    shutil.copytree(source, output/'ip_cache')
    return dict(directory=str(folder), execution_sha256=sha(folder/'execution.json'),
                source_manifest_sha256=sha(folder/'source_sha256.json'),
                Vivado=info['Vivado'], part=info['part'], files_sha256=files,
                ip_configuration_sha256=configurations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synth-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ip-cache-from', type=Path)
    parser.add_argument('--vivado', default=os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat')
                        or 'C:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat')
    args = parser.parse_args()
    source = args.synth_dir.resolve()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error('Use a new empty implementation directory')
    output.mkdir(parents=True, exist_ok=True)
    record = dict(schema='ptp_emulation_v1', capacity=None, max_nodes=None, status='running',
                  validation_stage='routed_bitstream', hardware_programmed=False,
                  started_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    execution = output/'execution.json'
    execution.write_text(json.dumps(record, indent=2)+'\n')
    ok = False
    try:
        upstream, info, hashes, provenance = validate_synthesis(source)
        record.update(capacity=upstream['capacity'], max_nodes=upstream['max_nodes'], source_synthesis=provenance,
                      routing_scripts_sha256=routing_hashes())
        shutil.copy2(source/'source_sha256.json', output/'source_sha256.json')
        shutil.copy2(source/'execution.json', output/'synthesis_execution.json')
        shutil.copy2(source/'build_manifest.txt', output/'synthesis_build_manifest.txt')
        shutil.copy2(source/SYNTH_DCP, output/SYNTH_DCP)
        for name in provenance['synthesis_reports_sha256']:
            shutil.copy2(source/name, output/name)
        if args.ip_cache_from:
            record['ip_cache_provenance'] = cache_provenance(args.ip_cache_from.resolve(), source, output)
        lines = ['schema=ptp_emulation_v1', 'common_image=1', 'physical_boards=3',
                 'capacity='+str(upstream['capacity']), 'max_nodes='+str(upstream['max_nodes']),
                 'part='+info['part'], 'Vivado='+info['Vivado'], 'line_rate=1.25Gbps', 'user_clock=62.5MHz',
                 'status=validated_synthesis_pending_implementation']
        (output/'build_manifest.txt').write_text('\n'.join(lines)+'\n')
        env = os.environ.copy()
        env.update(OBSIDIAN_PTP_ROOT=ROOT.as_posix(), OBSIDIAN_PTP_BUILD=output.as_posix(),
                   OBSIDIAN_PTP_ROUTE_SYNTH=(output/SYNTH_DCP).as_posix(), OBSIDIAN_BUILD_PYTHON=sys.executable)
        env['PATH'] = str(ROOT/'scripts/windows_compat')+os.pathsep+env.get('PATH', '')
        for name in ('OBSIDIAN_REUSE_IP', 'OBSIDIAN_SYNTH_ONLY', 'OBSIDIAN_PTP_IP_CACHE'):
            env.pop(name, None)
        if args.ip_cache_from:
            env['OBSIDIAN_PTP_IP_CACHE'] = (output/'ip_cache').as_posix()
        command = [args.vivado, '-mode', 'batch', '-nojournal', '-nolog', '-source', str(SCRIPT_DIR/'implement_ptp.tcl')]
        record['command'] = command
        execution.write_text(json.dumps(record, indent=2)+'\n')
        with (output/'build.log').open('w') as log:
            result = subprocess.run(command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT)
        current = source_hashes()
        current_routing = routing_hashes()
        changed = sorted(name for name in set(hashes) | set(current) if hashes.get(name) != current.get(name))
        changed += [name for name, value in record['routing_scripts_sha256'].items() if current_routing[name] != value]
        for name, expected in (('execution.json', provenance['execution_sha256']),
                               ('source_sha256.json', provenance['source_manifest_sha256']),
                               ('build_manifest.txt', provenance['build_manifest_sha256']),
                               (SYNTH_DCP, provenance['dcp_sha256'])):
            if sha(source/name) != expected:
                changed.append('upstream/'+name)
        for name, expected in provenance['synthesis_reports_sha256'].items():
            if sha(source/name) != expected:
                changed.append('upstream/'+name)
        if sha(output/SYNTH_DCP) != provenance['dcp_sha256']:
            changed.append('implementation_input/'+SYNTH_DCP)
        if args.ip_cache_from:
            cache = args.ip_cache_from.resolve()
            cache_info = record['ip_cache_provenance']
            if sha(cache/'execution.json') != cache_info['execution_sha256']:
                changed.append('debug_cache/execution.json')
            for name, expected in cache_info['files_sha256'].items():
                if sha(cache/'ptp_emulation.cache/ip'/name) != expected:
                    changed.append('debug_cache/'+name)
        log = (output/'build.log').read_text(errors='replace')
        complete = 'status=implemented_timing_pass_bitstream_generated' in (output/'build_manifest.txt').read_text()
        expected = (SYNTH_DCP, 'obsidian_ptp.bit', 'obsidian_ptp.ltx', 'obsidian_ptp_routed.dcp',
                    'implementation_utilization.rpt', 'timing_summary.rpt', 'timing_checks.rpt', 'bus_skew.rpt',
                    'cdc.rpt', 'drc.rpt', 'pulse_width.rpt', 'gpio_test_ref_m1_o.rpt', 'gpio_test_obs_o.rpt')
        missing = [name for name in expected if not (output/name).is_file() or not (output/name).stat().st_size]
        ok = result.returncode == 0 and 'ERROR:' not in log and 'ROUTE_FROM_SYNTH_COMPLETE' in log and complete and not changed and not missing
        record.update(returncode=result.returncode, sources_changed=changed, missing_artifacts=missing)
    except Exception as error:
        record['error'] = str(error)
    record.update(status='passed' if ok else 'failed', finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    record['artifacts_sha256'] = {path.name: sha(path) for path in output.iterdir() if path.suffix in ('.bit', '.ltx', '.rpt', '.dcp')}
    execution.write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
