"""Capacity selections require completed, source-matched implementation proof."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import report_ptp_capacity as capacity


class CapacityReport(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        names = ['rtl/example.vhd', 'constraints/example.xdc',
                 *('scripts/' + name for name in capacity.BUILD_SCRIPTS), *capacity.ROUTING_SCRIPTS]
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture ' + name)

    def write_json(self, path, value):
        path.write_text(json.dumps(value, indent=2) + '\n')

    def seal(self, folder, record=None):
        if record is None:
            record = json.loads((folder / 'execution.json').read_text())
        record['artifacts_sha256'] = {p.name: capacity.sha256(p) for p in folder.iterdir()
                                     if p.suffix in ('.rpt', '.bit', '.ltx', '.dcp')}
        self.write_json(folder / 'execution.json', record)
        return record

    def make_build(self, name, k, *, routed=True, luts=10000, ffs=18000,
                   wns=1.0, whs=0.03, wpws=2.0, status='passed', ramb36=10, ramb18=0):
        folder = self.root / 'build' / name
        folder.mkdir(parents=True)
        manifest = {p: capacity.sha256(self.root / p) for p in sorted(capacity.source_inventory(self.root))}
        self.write_json(folder / 'source_sha256.json', manifest)
        util = (f'| obsidian_ptp_top | (top) | {luts} | {luts} | 0 | 0 | {ffs} | '
                f'{ramb36} | {ramb18} | {k} |\n')
        (folder / 'synthesis_utilization.rpt').write_text(util)
        (folder / 'synthesis_cdc.rpt').write_text('Synthesis CDC fixture\n')
        with zipfile.ZipFile(folder / 'obsidian_ptp_synth.dcp', 'w') as checkpoint:
            checkpoint.writestr('design.xdc', 'create_clock -period 16 [get_ports clk_i]\n')
            checkpoint.writestr('netlist.bin', name + ' netlist')
        completed = routed and status == 'passed'
        (folder / 'build_manifest.txt').write_text(
            f'capacity={k}\nmax_nodes={3*k}\npart=xc7a35tcsg325-2\nVivado=2025.2\ncommon_image=1\nphysical_boards=3\n'
            'status=project_generated_not_implemented\n' +
            ('status=implemented_timing_pass_bitstream_generated\n' if completed else ''))
        if routed:
            (folder / 'implementation_utilization.rpt').write_text(util)
            (folder / 'timing_summary.rpt').write_text(
                'WNS(ns) TNS(ns) TNS Failing Endpoints TNS Total Endpoints WHS(ns) THS(ns) WPWS(ns)\n'
                '------- ------- -------\n'
                f'{wns:.3f} 0.000 0 1000 {whs:.3f} 0.000 0 1000 {wpws:.3f} 0.000 0 1000\n'
                'All user specified timing constraints are met.\n')
            (folder / 'timing_checks.rpt').write_text('checking no_clock (0)\nchecking unconstrained_internal_endpoints (0)\n')
            (folder / 'drc.rpt').write_text('Report DRC\n| DPIP-1 | Warning | Input pipelining | 1 |\n')
            (folder / 'bus_skew.rpt').write_text('Bus Skew Report\nAll constraints met.\n')
            for port in ('test_ref_m1_o', 'test_obs_o'):
                (folder / ('gpio_' + port + '.rpt')).write_text(
                    f'Slack (MET) : 1.000ns\nDestination: {port}\nRequirement: 8.000ns (MaxDelay Path 8.000ns)\n')
            for artifact in ('obsidian_ptp_routed.dcp', 'obsidian_ptp.bit', 'obsidian_ptp.ltx'):
                (folder / artifact).write_bytes((name + ' ' + artifact).encode())
        record = dict(schema='ptp_emulation_v1', capacity=k, max_nodes=3*k, status=status,
                      validation_stage='routed_bitstream' if routed else 'synthesis',
                      returncode=0 if status == 'passed' else 1,
                      sources_changed=[], missing_artifacts=[], hardware_programmed=False,
                      started_at_utc='20261029T120000000000Z', finished_at_utc='2026-10-29T12:30:00+00:00')
        self.seal(folder, record)
        return folder

    def inspect(self, folder, **criteria):
        return capacity.inspect_build(folder, root=self.root, **criteria)

    def summarize(self, folders, **criteria):
        return capacity.summarize(folders, root=self.root, **criteria)

    def make_derived(self, name='derived', k=3):
        upstream = self.make_build(name + '_upstream', k, routed=False)
        routed = self.make_build(name, k)
        for item in ('obsidian_ptp_synth.dcp', 'source_sha256.json', 'synthesis_utilization.rpt', 'synthesis_cdc.rpt'):
            (routed / item).write_bytes((upstream / item).read_bytes())
        with zipfile.ZipFile(upstream / 'obsidian_ptp_synth.dcp') as checkpoint:
            embedded = {'design.xdc': hashlib.sha256(checkpoint.read('design.xdc')).hexdigest()}
        record = json.loads((routed / 'execution.json').read_text())
        record['source_synthesis'] = dict(
            directory=str(upstream), capacity=k, max_nodes=3*k,
            execution_sha256=capacity.sha256(upstream / 'execution.json'),
            source_manifest_sha256=capacity.sha256(upstream / 'source_sha256.json'),
            dcp_sha256=capacity.sha256(upstream / 'obsidian_ptp_synth.dcp'),
            build_manifest_sha256=capacity.sha256(upstream / 'build_manifest.txt'),
            embedded_constraints_sha256=embedded,
            synthesis_reports_sha256={item: capacity.sha256(upstream / item) for item in ('synthesis_utilization.rpt', 'synthesis_cdc.rpt')})
        record['routing_scripts_sha256'] = {item: capacity.sha256(self.root / item) for item in capacity.ROUTING_SCRIPTS}
        self.seal(routed, record)
        return upstream, routed

    def test_selects_routed_maximum_and_smaller_margin_with_adjacent_resource_rejection(self):
        k1 = self.make_build('k1', 1, luts=7466, ffs=11421)
        k3 = self.make_build('k3', 3, luts=17000, ffs=30000, wns=0.5)
        k4 = self.make_build('k4', 4, luts=19000, ffs=36000, wns=0.2)
        k5 = self.make_build('k5_synth', 5, routed=False, luts=25000)
        report = self.summarize([k1, k3, k4, k5])
        self.assertEqual(report['largest_verified_routed']['capacity'], 4)
        self.assertEqual(report['recommended']['capacity'], 3)
        boundary = report['next_observed_rejection']
        self.assertEqual(boundary['capacity'], 5)
        self.assertTrue(boundary['adjacent_to_routed_maximum'])
        self.assertFalse(boundary['all_larger_capacities_tested'])
        self.assertFalse(report['hardware_validated'])

    def test_synthesis_fit_is_never_selected_even_with_unhashed_old_routed_reports(self):
        folder = self.make_build('synth', 4, routed=False, luts=12000)
        (folder / 'implementation_utilization.rpt').write_text('| obsidian_ptp_top | top | 99999 | 99999 | 0 | 0 | 1 | 1 | 0 | 1 |\n')
        row = self.inspect(folder)
        self.assertEqual(row['classification'], 'synthesis_candidate')
        report = self.summarize([folder])
        self.assertIsNone(report['largest_verified_routed'])
        self.assertIsNone(report['recommended'])

    def test_stale_source_or_incomplete_inventory_invalidates_apparent_pass(self):
        folder = self.make_build('stale', 2)
        (self.root / 'rtl/example.vhd').write_text('changed after implementation')
        self.assertFalse(self.inspect(folder)['routed_verified'])
        manifest = json.loads((folder / 'source_sha256.json').read_text())
        del manifest['rtl/example.vhd']
        self.write_json(folder / 'source_sha256.json', manifest)
        row = self.inspect(folder)
        self.assertFalse(row['source_evidence']['current_sources_match'])
        self.assertTrue(any('inventory' in issue.lower() for issue in row['reasons']))

    def test_actual_dcp_bit_and_ltx_fingerprints_are_required(self):
        for index, artifact in enumerate(('obsidian_ptp_synth.dcp', 'obsidian_ptp_routed.dcp',
                                          'obsidian_ptp.bit', 'obsidian_ptp.ltx')):
            with self.subTest(artifact=artifact):
                folder = self.make_build('tampered' + str(index), 2)
                with (folder / artifact).open('ab') as stream:
                    stream.write(b'stale replacement')
                row = self.inspect(folder)
                self.assertFalse(row['routed_verified'])
                self.assertTrue(any(artifact in issue for issue in row['reasons']))

    def test_fake_pass_missing_fingerprint_finish_or_declared_stage_is_not_selected(self):
        for index, change in enumerate(('fingerprint', 'finish', 'stage', 'returncode', 'running')):
            with self.subTest(change=change):
                folder = self.make_build('fake' + str(index), 2)
                record = json.loads((folder / 'execution.json').read_text())
                if change == 'fingerprint':
                    del record['artifacts_sha256']['obsidian_ptp.ltx']
                elif change == 'finish':
                    del record['finished_at_utc']
                elif change == 'stage':
                    record['validation_stage'] = 'project'
                elif change == 'returncode':
                    record['returncode'] = 1
                else:
                    record['status'] = 'running'
                self.write_json(folder / 'execution.json', record)
                self.assertFalse(self.inspect(folder)['routed_verified'])

    def test_negative_timing_and_missing_gpio_constraint_cannot_fake_pass(self):
        for index, options in enumerate((dict(wns=-0.1), dict(whs=-0.01), dict(wpws=-0.01))):
            row = self.inspect(self.make_build('timing' + str(index), 2, **options))
            self.assertFalse(row['routed_verified'])
        folder = self.make_build('gpio', 2)
        (folder / 'gpio_test_obs_o.rpt').write_text('Slack (MET) : 1.000ns\nDestination: test_obs_o\n')
        self.seal(folder)
        self.assertFalse(self.inspect(folder)['routed_verified'])

    def test_timing_rejection_is_bounded_only_when_completed_and_report_fingerprints_match(self):
        lower = self.make_build('lower', 2)
        failed = self.make_build('timing_failed', 4, status='failed', wns=-0.1)
        record = json.loads((failed / 'execution.json').read_text())
        record['missing_artifacts'] = ['obsidian_ptp.bit', 'obsidian_ptp.ltx']
        for name in record['missing_artifacts']:
            (failed / name).unlink()
        self.seal(failed, record)
        report = self.summarize([lower, failed])
        self.assertEqual(report['next_observed_rejection']['classification'], 'routed_timing_rejection')
        self.assertEqual(report['next_observed_rejection']['untested_between'], [3])
        self.assertFalse(report['next_observed_rejection']['adjacent_to_routed_maximum'])
        (failed / 'timing_summary.rpt').write_text('stale report replacement')
        self.assertIsNone(self.summarize([lower, failed])['next_observed_rejection'])

    def test_configurable_margin_includes_exact_boundary_and_checks_ff_independently(self):
        exact = self.make_build('exact', 3, luts=17680, ffs=35360, wns=0.5)
        larger = self.make_build('larger', 4, luts=18000, ffs=37000, wns=0.4)
        self.assertTrue(self.inspect(exact)['recommended'])
        self.assertFalse(self.inspect(larger)['recommended'])
        report = self.summarize([exact, larger], min_lut_free=0, min_ff_free=0, min_setup_ns=0)
        self.assertEqual(report['recommended']['capacity'], 4)
        ff_only = self.make_build('ff_only', 2, luts=10000, ffs=36000)
        self.assertFalse(self.inspect(ff_only)['recommended'])

    def test_ramb18_halves_count_toward_device_resource_rejection(self):
        folder = self.make_build('bram', 4, routed=False, ramb36=49, ramb18=3)
        row = self.inspect(folder)
        self.assertEqual(row['classification'], 'resource_rejection')
        self.assertEqual(row['resource_usage']['ramb36_equivalent']['used'], 50.5)

    def test_derived_route_checks_upstream_and_routing_sources(self):
        upstream, routed = self.make_derived()
        self.assertTrue(self.inspect(routed)['routed_verified'])
        (upstream / 'obsidian_ptp_synth.dcp').write_bytes(b'replaced checkpoint')
        self.assertFalse(self.inspect(routed)['routed_verified'])

    def test_derived_route_rejects_changed_routing_script(self):
        # A source stamp is checked against actual files, including the new
        # routing helper which is outside the old synthesis-source inventory.
        _, routed = self.make_derived()
        self.assertTrue(self.inspect(routed)['routed_verified'])
        (self.root / 'scripts/implement_ptp.tcl').write_text('changed constraint gate')
        self.assertFalse(self.inspect(routed)['routed_verified'])

    def test_optional_debug_cache_provenance_is_verified_and_stamped(self):
        baseline = self.make_build('cache_baseline', 1)
        cache_file = baseline / 'ptp_emulation.cache/ip/2025.2/debug_hub.dcp'
        cache_file.parent.mkdir(parents=True)
        cache_file.write_bytes(b'validated debug-IP fixture')
        _, routed = self.make_derived('uses_cache')
        record = json.loads((routed / 'execution.json').read_text())
        record['ip_cache_provenance'] = dict(
            directory=str(baseline), execution_sha256=capacity.sha256(baseline / 'execution.json'),
            source_manifest_sha256=capacity.sha256(baseline / 'source_sha256.json'),
            Vivado='2025.2', part='xc7a35tcsg325-2',
            files_sha256={'2025.2/debug_hub.dcp': capacity.sha256(cache_file)})
        self.write_json(routed / 'execution.json', record)
        self.assertTrue(self.inspect(routed)['routed_verified'])
        cache_file.write_bytes(b'stale debug-IP replacement')
        row = self.inspect(routed)
        self.assertFalse(row['routed_verified'])
        self.assertIn('ip_cache_provenance', row['evidence'])

    def test_running_resource_report_does_not_create_a_failed_boundary(self):
        lower = self.make_build('lower', 2)
        running = self.make_build('running', 4, routed=False, luts=25000)
        record = json.loads((running / 'execution.json').read_text())
        record['status'] = 'running'
        self.write_json(running / 'execution.json', record)
        report = self.summarize([lower, running])
        self.assertIsNone(report['next_observed_rejection'])

    def test_derived_route_cannot_omit_the_upstream_proof(self):
        _, routed = self.make_derived()
        record = json.loads((routed / 'execution.json').read_text())
        del record['source_synthesis']
        self.write_json(routed / 'execution.json', record)
        self.assertFalse(self.inspect(routed)['routed_verified'])


if __name__ == '__main__':
    unittest.main()
