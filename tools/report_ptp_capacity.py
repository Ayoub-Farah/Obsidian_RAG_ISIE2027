"""Compare completed PTP capacity builds with source and artifact provenance.

Example: py -3 tools/report_ptp_capacity.py --build build/ptp_single_node_final
    --build build/ptp_capacity_search/k4_synth --output reports/ptp_capacity
Only a fingerprint-verified, completed routed build can enter either selection.
The report contains implementation evidence, never hardware validation.
"""
from pathlib import Path, PurePosixPath
import argparse
import datetime
import hashlib
import json
import re
import zipfile

try:
    from .report_ptp_builds import utilization, timing
except ImportError:
    from report_ptp_builds import utilization, timing

ROOT = Path(__file__).resolve().parents[1]
LIMITS = dict(luts=20800, flip_flops=41600, ramb36_equivalent=50, dsp=90)
BUILD_SCRIPTS = ('build_ptp.tcl', 'build.tcl', 'create_ptp_project.tcl',
                 'aurora_common.tcl', 'generate_aurora_adapter.py')
ROUTING_SCRIPTS = {'scripts/implement_ptp.py', 'scripts/implement_ptp.tcl'}
SYNTH_REQUIRED = ('obsidian_ptp_synth.dcp', 'synthesis_utilization.rpt')
ROUTED_REQUIRED = (*SYNTH_REQUIRED, 'obsidian_ptp_routed.dcp', 'obsidian_ptp.bit',
                   'obsidian_ptp.ltx', 'implementation_utilization.rpt',
                   'timing_summary.rpt', 'timing_checks.rpt', 'drc.rpt',
                   'bus_skew.rpt', 'gpio_test_ref_m1_o.rpt', 'gpio_test_obs_o.rpt')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object: ' + str(path))
    return value


def relative_name(name):
    if not isinstance(name, str):
        raise ValueError('Fingerprint path is not a string')
    portable = PurePosixPath(name.replace('\\', '/'))
    if portable.is_absolute() or '..' in portable.parts or ':' in name or not portable.parts:
        raise ValueError('Fingerprint path must be relative: ' + name)
    return portable.as_posix()


def check_hashes(base, expected, required=()):
    """Check all declared files, rejecting omitted required fingerprints too."""
    issues = []
    actual = {}
    if not isinstance(expected, dict) or not expected:
        return {}, ['Missing fingerprint map']
    normalized = {}
    for name, digest in expected.items():
        try:
            key = relative_name(name)
        except ValueError as error:
            issues.append(str(error))
            continue
        if key in normalized:
            issues.append('Duplicate fingerprint path: ' + key)
        normalized[key] = digest
    for name in required:
        if name not in normalized:
            issues.append('Missing fingerprint: ' + name)
    for name, digest in normalized.items():
        path = Path(base) / name
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-fA-F]{64}', digest):
            issues.append('Invalid SHA-256: ' + name)
        elif not path.is_file() or path.stat().st_size == 0:
            issues.append('Missing or empty file: ' + name)
        else:
            actual[name] = sha256(path)
            if actual[name] != digest.lower():
                issues.append('Fingerprint mismatch: ' + name)
    return actual, issues


def source_inventory(root):
    paths = [*(root / 'rtl').rglob('*.vhd'), *(root / 'constraints').glob('*.xdc'),
             *(root / 'scripts' / name for name in BUILD_SCRIPTS)]
    return {p.relative_to(root).as_posix() for p in paths}


def source_evidence(folder, root):
    path = folder / 'source_sha256.json'
    evidence = dict(manifest_sha256=None, current_sources_match=False)
    try:
        expected = read_json(path)
        evidence['manifest_sha256'] = sha256(path)
        actual, issues = check_hashes(root, expected)
        inventory = source_inventory(root)
        if set(actual) != inventory:
            issues.append('Source inventory differs from the current build inventory')
        evidence.update(source_count=len(expected), source_sha256=actual,
                        current_sources_match=not issues, issues=issues)
        return evidence
    except (OSError, ValueError) as error:
        evidence['issues'] = [str(error)]
        return evidence


def terminal_execution(record):
    if record.get('status') not in ('passed', 'failed') or type(record.get('returncode')) is not int:
        return False
    try:
        finished = datetime.datetime.fromisoformat(record.get('finished_at_utc', '').replace('Z', '+00:00'))
        return finished.tzinfo is not None
    except (ValueError, AttributeError):
        return False


def upstream_evidence(folder, record, root):
    """Derived routes must retain the exact completed synthesis they consumed."""
    proof = record.get('source_synthesis')
    if proof is None:
        missing = record.get('routing_scripts_sha256') is not None or record.get('ip_cache_provenance') is not None
        return None, ['Derived routing execution is missing source_synthesis'] if missing else []
    evidence = dict(source_synthesis=proof)
    issues = []
    try:
        upstream = Path(proof['directory'])
        if not upstream.is_absolute():
            upstream = root / upstream
        upstream = upstream.resolve()
        previous = read_json(upstream / 'execution.json')
        if not (terminal_execution(previous) and previous.get('schema') == 'ptp_emulation_v1'
                and previous.get('status') == 'passed' and previous.get('returncode') == 0
                and previous.get('validation_stage') == 'synthesis'
                and previous.get('sources_changed') == [] and previous.get('missing_artifacts') == []):
            issues.append('Upstream synthesis execution is not a completed verified pass')
        for key, filename in (('execution_sha256', 'execution.json'),
                              ('source_manifest_sha256', 'source_sha256.json'),
                              ('dcp_sha256', 'obsidian_ptp_synth.dcp'),
                              ('build_manifest_sha256', 'build_manifest.txt')):
            if proof.get(key) != sha256(upstream / filename):
                issues.append('Upstream fingerprint mismatch: ' + filename)
        for key in ('capacity', 'max_nodes'):
            if proof.get(key) != record.get(key) or previous.get(key) != record.get(key):
                issues.append('Upstream ' + key + ' differs from the routed execution')
        if sha256(folder / 'source_sha256.json') != proof.get('source_manifest_sha256'):
            issues.append('Copied source manifest differs from the upstream synthesis')
        if sha256(folder / 'obsidian_ptp_synth.dcp') != proof.get('dcp_sha256'):
            issues.append('Copied synthesis DCP differs from the upstream synthesis')
        _, failures = check_hashes(upstream, previous.get('artifacts_sha256'), SYNTH_REQUIRED)
        issues.extend('Upstream: ' + issue for issue in failures)
        scripts, failures = check_hashes(root, record.get('routing_scripts_sha256'), ROUTING_SCRIPTS)
        evidence['verified_routing_scripts_sha256'] = scripts
        issues.extend(failures)
        embedded = proof.get('embedded_constraints_sha256')
        if not isinstance(embedded, dict) or not embedded:
            issues.append('Missing embedded synthesis-constraint fingerprints')
        else:
            with zipfile.ZipFile(upstream / 'obsidian_ptp_synth.dcp') as checkpoint:
                for name, digest in embedded.items():
                    if not name.lower().endswith('.xdc') or hashlib.sha256(checkpoint.read(name)).hexdigest() != digest:
                        issues.append('Embedded constraint fingerprint mismatch: ' + name)
        reports = proof.get('synthesis_reports_sha256', {})
        if reports and not isinstance(reports, dict):
            issues.append('Invalid upstream synthesis-report fingerprint map')
        elif reports:
            _, failures = check_hashes(upstream, reports)
            issues.extend('Upstream report: ' + issue for issue in failures)
            for name, digest in reports.items():
                if sha256(folder / relative_name(name)) != digest:
                    issues.append('Copied synthesis report mismatch: ' + name)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        issues.append('Invalid upstream synthesis evidence: ' + str(error))
    return evidence, issues


def cache_evidence(record, root):
    """Retain and check optional debug-IP cache provenance from a derived route."""
    cache = record.get('ip_cache_provenance')
    if cache is None:
        return None, []
    issues = []
    try:
        folder = Path(cache['directory'])
        if not folder.is_absolute():
            folder = root / folder
        previous = read_json(folder / 'execution.json')
        if not (terminal_execution(previous) and previous.get('schema') == 'ptp_emulation_v1'
                and previous.get('status') == 'passed' and previous.get('sources_changed') == []
                and previous.get('missing_artifacts') == []
                and previous.get('returncode') == 0 and previous.get('validation_stage') == 'routed_bitstream'
                and previous.get('capacity') == 1 and cache.get('Vivado') == '2025.2'
                and cache.get('part') == 'xc7a35tcsg325-2'):
            issues.append('Debug-IP cache is not from the completed K1 baseline')
        for key, name in (('execution_sha256', 'execution.json'), ('source_manifest_sha256', 'source_sha256.json')):
            if cache.get(key) != sha256(folder / name):
                issues.append('Debug-IP cache fingerprint mismatch: ' + name)
        _, failures = check_hashes(folder / 'ptp_emulation.cache/ip', cache.get('files_sha256'))
        issues.extend('Debug-IP cache: ' + issue for issue in failures)
        _, failures = check_hashes(folder, previous.get('artifacts_sha256'),
                                  ('obsidian_ptp_routed.dcp', 'obsidian_ptp.bit', 'obsidian_ptp.ltx'))
        issues.extend('Debug-IP baseline: ' + issue for issue in failures)
        issues.extend('Debug-IP source: ' + issue for issue in source_evidence(folder, root)['issues'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        issues.append('Invalid debug-IP cache evidence: ' + str(error))
    return cache, issues


def resource_usage(values):
    if values is None:
        return None, []
    resources = {key: values[key] for key in ('luts', 'flip_flops', 'dsp')}
    resources['ramb36_equivalent'] = values['ramb36'] + values['ramb18'] / 2
    exceeded = [key for key, value in resources.items() if value > LIMITS[key]]
    return {key: dict(used=value, available=LIMITS[key],
                      used_percent=round(100 * value / LIMITS[key], 4),
                      free_percent=round(100 * (LIMITS[key] - value) / LIMITS[key], 4))
            for key, value in resources.items()}, exceeded


def gate_issues(folder, values):
    issues = []
    if values is None or any(value < 0 for value in values.values()):
        issues.append('Routed setup, hold or pulse-width timing did not pass')
    text = (folder / 'timing_summary.rpt').read_text(errors='replace')
    if 'All user specified timing constraints are met.' not in text:
        issues.append('Timing report does not confirm all constraints are met')
    checks = (folder / 'timing_checks.rpt').read_text(errors='replace')
    for name in ('no_clock', 'unconstrained_internal_endpoints'):
        counts = re.findall(r'checking ' + name + r' \((\d+)\)', checks)
        if not counts or any(int(value) != 0 for value in counts):
            issues.append('Timing check failed or missing: ' + name)
    if 'VIOLATED' in (folder / 'bus_skew.rpt').read_text(errors='replace').upper():
        issues.append('Bus skew report contains a violation')
    drc = (folder / 'drc.rpt').read_text(errors='replace')
    if re.search(r'\|\s*Error\s*\||^\S+#\d+\s+Error\b', drc, re.M | re.I):
        issues.append('DRC report contains an error-level violation')
    for port in ('test_ref_m1_o', 'test_obs_o'):
        gpio = (folder / ('gpio_' + port + '.rpt')).read_text(errors='replace')
        slack = re.search(r'Slack \(MET\)\s*:\s*(-?\d+(?:\.\d+)?)ns', gpio)
        if not (slack and float(slack[1]) >= 0
                and re.search(r'Requirement:\s+8\.000ns\s+\(MaxDelay Path', gpio)
                and re.search(r'Destination:\s*' + port + r'\b', gpio)):
            issues.append('Missing or failed 8 ns GPIO gate: ' + port)
    return issues


def inspect_build(directory, *, root=ROOT, min_lut_free=15.0, min_ff_free=15.0, min_setup_ns=0.5):
    folder = Path(directory).resolve()
    root = Path(root).resolve()
    result = dict(build_directory=str(folder), capacity=None, classification='verification_failed',
                  routed_verified=False, recommended=False, reasons=[])
    try:
        record = read_json(folder / 'execution.json')
        result.update(capacity=record.get('capacity'), max_nodes=record.get('max_nodes'),
                      status=record.get('status'), validation_stage=record.get('validation_stage'),
                      started_at_utc=record.get('started_at_utc'), finished_at_utc=record.get('finished_at_utc'))
        issues = result['reasons']
        if record.get('schema') != 'ptp_emulation_v1':
            issues.append('Unsupported execution schema')
        capacity = record.get('capacity')
        if type(capacity) is not int or not 1 <= capacity <= 20 or record.get('max_nodes') != min(60, 3 * capacity):
            issues.append('Invalid capacity or max_nodes in execution')
        completed = terminal_execution(record)
        result['completed'] = completed
        sources = source_evidence(folder, root)
        result['source_evidence'] = sources
        issues.extend(sources['issues'])
        artifact_hashes, failures = check_hashes(folder, record.get('artifacts_sha256'))
        issues.extend(failures)
        result['evidence'] = dict(execution_sha256=sha256(folder / 'execution.json'),
                                  artifacts_sha256=artifact_hashes)
        upstream, failures = upstream_evidence(folder, record, root)
        if upstream is not None:
            result['evidence']['upstream'] = upstream
        issues.extend(failures)
        cache, failures = cache_evidence(record, root)
        if cache is not None:
            result['evidence']['ip_cache_provenance'] = cache
        issues.extend(failures)
        if completed and record.get('sources_changed') != []:
            issues.append('Execution does not attest an empty sources_changed')
        if completed and record.get('status') == 'passed' and record.get('missing_artifacts') != []:
            issues.append('Passed execution does not attest an empty missing_artifacts')
        if completed and record.get('status') == 'passed' and record.get('returncode') != 0:
            issues.append('Passed execution has a nonzero return code')
        synth = utilization(folder / 'synthesis_utilization.rpt')
        implemented = utilization(folder / 'implementation_utilization.rpt') if 'implementation_utilization.rpt' in artifact_hashes else None
        clocks = timing(folder / 'timing_summary.rpt') if 'timing_summary.rpt' in artifact_hashes else None
        result.update(synthesis_utilization=synth, implementation_utilization=implemented,
                      routed_timing=clocks)
        if any(value < 0 for row in (synth, implemented) if row for value in row.values()):
            issues.append('Invalid negative utilization count')
        stage = record.get('validation_stage')
        values = (implemented or synth) if stage == 'routed_bitstream' else synth
        usage, exceeded = resource_usage(values)
        result.update(resource_usage=usage, resources_exceeded=exceeded)
        manifest = (folder / 'build_manifest.txt').read_text(errors='replace')
        manifest_values = dict(re.findall(r'^([^=\r\n]+)=([^\r\n]*)$', manifest, re.M))
        for key, expected in (('capacity', str(capacity)), ('max_nodes', str(record.get('max_nodes'))),
                              ('part', 'xc7a35tcsg325-2'), ('Vivado', '2025.2'),
                              ('physical_boards', '3'), ('common_image', '1')):
            if manifest_values.get(key) != expected:
                issues.append('Build manifest mismatch: ' + key)
        if not completed:
            result['classification'] = 'incomplete'
            issues.append('Execution has not completed with a return code and UTC finish time')
            return result
        if stage not in ('synthesis', 'routed_bitstream'):
            issues.append('Execution stage is neither synthesis nor routed bitstream')
        required = ROUTED_REQUIRED if stage == 'routed_bitstream' and record.get('status') == 'passed' else SYNTH_REQUIRED
        _, failures = check_hashes(folder, record.get('artifacts_sha256'), required)
        issues.extend(failures)
        if synth is None:
            issues.append('No complete synthesis utilization row')
        if issues:
            return result
        if exceeded:
            result['classification'] = 'resource_rejection'
            return result
        if stage == 'synthesis':
            result['classification'] = 'synthesis_candidate' if record.get('status') == 'passed' else 'failed'
            return result
        if record.get('status') == 'failed':
            if implemented is not None and clocks is not None and any(v < 0 for v in clocks.values()):
                _, failures = check_hashes(folder, record.get('artifacts_sha256'),
                                          ('obsidian_ptp_routed.dcp', 'implementation_utilization.rpt', 'timing_summary.rpt'))
                issues.extend(failures)
                result['classification'] = 'verification_failed' if failures else 'routed_timing_rejection'
            else:
                result['classification'] = 'failed'
            return result
        if implemented is None:
            issues.append('No complete implementation utilization row')
        if manifest_values.get('status') != 'implemented_timing_pass_bitstream_generated':
            issues.append('Build manifest does not attest a completed bitstream')
        issues.extend(gate_issues(folder, clocks))
        if issues:
            return result
        result.update(classification='routed_pass', routed_verified=True)
        margins = []
        for key, minimum in (('luts', min_lut_free), ('flip_flops', min_ff_free)):
            if usage[key]['free_percent'] + 1e-8 < minimum:
                margins.append(key + ' free margin is below ' + str(minimum) + '%')
        if clocks['setup_wns_ns'] < min_setup_ns:
            margins.append('Setup margin is below ' + str(min_setup_ns) + ' ns')
        result['engineering_margin_failures'] = margins
        result['recommended'] = not margins
        return result
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        result['reasons'].append(str(error))
        return result


def summarize(builds, *, root=ROOT, min_lut_free=15.0, min_ff_free=15.0, min_setup_ns=0.5):
    criteria = dict(min_lut_free=min_lut_free, min_ff_free=min_ff_free, min_setup_ns=min_setup_ns)
    attempts = [inspect_build(folder, root=root, **criteria) for folder in sorted({Path(p).resolve() for p in builds})]
    attempts.sort(key=lambda row: (row['capacity'] if type(row['capacity']) is int else -1, row['build_directory']))
    def select(rows):
        if not rows:
            return None
        selected = max(rows, key=lambda row: (row['capacity'], row['routed_timing']['setup_wns_ns']))
        return {key: selected[key] for key in ('capacity', 'max_nodes', 'build_directory')}
    maximum = select([row for row in attempts if row['routed_verified']])
    recommended = select([row for row in attempts if row['recommended']])
    boundary = None
    if maximum is not None:
        rejected = [row for row in attempts if row['classification'] in ('resource_rejection', 'routed_timing_rejection')
                    and row['capacity'] > maximum['capacity']]
        if rejected:
            rejected.sort(key=lambda row: row['capacity'])
            failed = rejected[0]
            tested = {row['capacity'] for row in attempts if row.get('completed') and not row['reasons']}
            boundary = dict(capacity=failed['capacity'], max_nodes=failed['max_nodes'],
                            build_directory=failed['build_directory'], classification=failed['classification'],
                            adjacent_to_routed_maximum=failed['capacity'] == maximum['capacity'] + 1,
                            untested_between=[k for k in range(maximum['capacity'] + 1, failed['capacity']) if k not in tested],
                            not_routed_between=list(range(maximum['capacity'] + 1, failed['capacity'])),
                            all_larger_capacities_tested=False)
    return dict(schema='ptp_capacity_report_v1', generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                resource_limits=LIMITS, engineering_criteria=criteria, attempts=attempts,
                largest_verified_routed=maximum, recommended=recommended, next_observed_rejection=boundary,
                attempted_capacities=sorted({row['capacity'] for row in attempts if type(row['capacity']) is int}),
                hardware_validated=False,
                scope='Selections apply only to the listed, source-matched builds. A synthesis fit is a candidate; '
                      'a failed next candidate does not establish that every larger capacity was tested. '
                      'Hardware synchronization and functional RTL validation are separate evidence.')


def markdown(report):
    def selected(name):
        value = report[name]
        return 'none' if value is None else f"K={value['capacity']} ({value['max_nodes']} modules across three boards)"
    criteria = report['engineering_criteria']
    lines = ['Largest verified routed capacity: ' + selected('largest_verified_routed') + '.',
             'Recommended engineering margin: ' + selected('recommended') + '.',
             f"Selection requires at least {criteria['min_lut_free']}% free LUT, "
             f"{criteria['min_ff_free']}% free FF and {criteria['min_setup_ns']} ns setup margin.",
             'Hardware validation: none; this report checks build artifacts.', '',
             '| K | Ring nodes | Classification | LUT (free %) | FF (free %) | BRAM36 equivalent | DSP | Setup ns | Sources match |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in report['attempts']:
        usage = row.get('resource_usage') or {}
        def used(key):
            return str(usage[key]['used']) if key in usage else '—'
        def with_margin(key):
            return f"{used(key)} ({usage[key]['free_percent']:.2f}%)" if key in usage else '—'
        clock = row.get('routed_timing') or {}
        lines.append(f"| {row['capacity']} | {row.get('max_nodes', '—')} | {row['classification']} | {with_margin('luts')} | "
                     f"{with_margin('flip_flops')} | {used('ramb36_equivalent')} | {used('dsp')} | {clock.get('setup_wns_ns', '—')} | "
                     f"{row.get('source_evidence', {}).get('current_sources_match', False)} |")
    boundary = report['next_observed_rejection']
    if boundary:
        lines += ['', f"Next observed rejection: K={boundary['capacity']} ({boundary['classification']}). "
                  f"Untested intermediate capacities: {boundary['untested_between']}; "
                  f"intermediate capacities without a verified route: {boundary['not_routed_between']}. "
                  "Larger capacities were not all tested."]
    lines += ['', report['scope'], '', 'Build evidence:', '']
    for row in report['attempts']:
        lines.append('- ' + row['build_directory'])
        for reason in row['reasons'] + row.get('engineering_margin_failures', []):
            lines.append('  ' + reason)
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='append', type=Path, default=[],
                        help='Build directory; repeat for each executed candidate (default: final K1 plus capacity search)')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/ptp_capacity', help='Output directory for capacity.json and capacity.md')
    parser.add_argument('--min-lut-free-percent', type=float, default=15.0)
    parser.add_argument('--min-ff-free-percent', type=float, default=15.0)
    parser.add_argument('--min-setup-ns', type=float, default=0.5)
    args = parser.parse_args(argv)
    if not (0 <= args.min_lut_free_percent <= 100 and 0 <= args.min_ff_free_percent <= 100
            and 0 <= args.min_setup_ns < float('inf')):
        parser.error('Margins must be finite, nonnegative; free percentages must be <=100')
    builds = args.build or [p.parent for p in (ROOT / 'build/ptp_capacity_search').rglob('execution.json')]
    if not args.build and (ROOT / 'build/ptp_single_node_final/execution.json').is_file():
        builds.append(ROOT / 'build/ptp_single_node_final')
    report = summarize(builds, min_lut_free=args.min_lut_free_percent,
                       min_ff_free=args.min_ff_free_percent, min_setup_ns=args.min_setup_ns)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'capacity.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (args.output / 'capacity.md').write_text(markdown(report), encoding='utf-8')
    print(markdown(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
