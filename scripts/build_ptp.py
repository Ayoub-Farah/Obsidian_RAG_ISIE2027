"""Build a dedicated PTP image. No JTAG connection or hardware programming."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capacity', type=int, default=1)
    p.add_argument('--synth-only', action='store_true')
    p.add_argument('--project-only', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--vivado', default=os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat') or 'C:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat')
    a = p.parse_args()
    if not 1 <= a.capacity <= 20:
        p.error('capacity must be 1..20')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dest = (a.output or (ROOT/'build/ptp_single_node_final' if a.capacity==1 else ROOT/'build'/f'ptp_k{a.capacity}'/stamp)).resolve()
    if dest.exists() and any(dest.iterdir()):
        p.error('Use a new empty build directory')
    dest.mkdir(parents=True, exist_ok=True)
    def source_paths():
        return [*(ROOT/'rtl').rglob('*.vhd'), *(ROOT/'constraints').glob('*.xdc'),
                *(ROOT/'scripts'/n for n in ('build_ptp.tcl', 'build.tcl', 'create_ptp_project.tcl', 'aurora_common.tcl', 'generate_aurora_adapter.py'))]
    sources = source_paths()
    hashes = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    (dest/'source_sha256.json').write_text(json.dumps(hashes, indent=2)+'\n')
    env = os.environ.copy()
    env.update(OBSIDIAN_PTP_CAPACITY=str(a.capacity), OBSIDIAN_PTP_BUILD=dest.as_posix(), OBSIDIAN_BUILD_PYTHON=sys.executable)
    env['PATH'] = str(ROOT/'scripts/windows_compat') + os.pathsep + env.get('PATH', '')
    env.pop('OBSIDIAN_REUSE_IP', None)
    env.pop('OBSIDIAN_SYNTH_ONLY', None)
    if a.synth_only:
        env['OBSIDIAN_SYNTH_ONLY'] = '1'
    script = 'create_ptp_project.tcl' if a.project_only else 'build_ptp.tcl'
    command = [a.vivado, '-mode', 'batch', '-nojournal', '-nolog', '-source', str(ROOT/'scripts'/script)]
    record = dict(schema='ptp_emulation_v1', capacity=a.capacity, max_nodes=min(60, 3*a.capacity),
                  started_at_utc=stamp, command=command, status='running', hardware_programmed=False)
    proof = dest/'execution.json'
    proof.write_text(json.dumps(record, indent=2)+'\n')
    print(dest, flush=True)
    try:
        with (dest/'build.log').open('w') as log:
            result = subprocess.run(command, cwd=dest, env=env, stdout=log, stderr=subprocess.STDOUT)
        current = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in source_paths()}
        changed = sorted(n for n in set(hashes) | set(current) if hashes.get(n) != current.get(n))
        log = (dest/'build.log').read_text(errors='replace')
        manifest = (dest/'build_manifest.txt').read_text() if (dest/'build_manifest.txt').exists() else ''
        ok = result.returncode == 0 and 'ERROR:' not in log and not changed
        if a.project_only:
            expected = ('ptp_emulation.xpr', 'ip_status.rpt')
            ok &= 'status=project_generated_not_implemented' in manifest
        elif a.synth_only:
            expected = ('obsidian_ptp_synth.dcp', 'synthesis_utilization.rpt', 'synthesis_cdc.rpt')
            ok &= 'SYNTH_ONLY_COMPLETE' in log
        else:
            expected = ('obsidian_ptp.bit', 'obsidian_ptp.ltx', 'obsidian_ptp_routed.dcp',
                        'timing_summary.rpt', 'drc.rpt', 'gpio_test_ref_m1_o.rpt', 'gpio_test_obs_o.rpt')
            ok &= 'status=implemented_timing_pass_bitstream_generated' in manifest
        missing = [name for name in expected if not (dest/name).is_file() or (dest/name).stat().st_size == 0]
        ok &= not missing
        record.update(status='passed' if ok else 'failed', returncode=result.returncode, sources_changed=changed,
                      missing_artifacts=missing,
                      validation_stage='project' if a.project_only else 'synthesis' if a.synth_only else 'routed_bitstream')
    except OSError as e:
        record.update(status='failed', error=str(e))
        ok = False
    record['finished_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record['artifacts_sha256'] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in dest.iterdir() if f.suffix in ('.bit', '.ltx', '.rpt', '.dcp')}
    proof.write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
