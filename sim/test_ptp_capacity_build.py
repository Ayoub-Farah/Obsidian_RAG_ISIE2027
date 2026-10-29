"""Checkpoint-resume contracts using synthetic artifacts; no FPGA tools."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

try:
    import tkinter
except ImportError:
    tkinter = None

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_ptp_checkpoint_resume', ROOT/'scripts/implement_ptp.py')
ROUTE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ROUTE)


class ResumeProof(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root/'scripts').mkdir()
        for name in ROUTE.FROZEN_BUILD_SCRIPTS:
            (self.root/'scripts'/name).write_text('# synthetic frozen input\n')
        self.source = self.root/'rtl/sync/probe.vhd'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('entity probe is end;\n')
        self.root_patch = patch.object(ROUTE, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.synthesis = self.make_proof(self.root/'synthesis', 2, 'synthesis')

    def make_proof(self, folder, capacity, stage):
        folder.mkdir()
        (folder/'source_sha256.json').write_text(json.dumps(ROUTE.source_hashes()))
        (folder/'build_manifest.txt').write_text(
            f'capacity={capacity}\nmax_nodes={3*capacity}\npart=xc7a35tcsg325-2\nVivado=2025.2\n')
        with zipfile.ZipFile(folder/ROUTE.SYNTH_DCP, 'w') as archive:
            archive.writestr('obsidian_ptp_top.xdc', 'test_ref_m1_o test_obs_o\n')
            archive.writestr('obsidian_ptp_top_late.xdc', 'reset_pipe\n')
        for name in ('synthesis_utilization.rpt', 'synthesis_cdc.rpt'):
            (folder/name).write_text('synthetic report\n')
        artifacts = {name: ROUTE.sha(folder/name) for name in
                     (ROUTE.SYNTH_DCP, 'synthesis_utilization.rpt', 'synthesis_cdc.rpt')}
        if stage == 'routed_bitstream':
            for name in ('obsidian_ptp.bit', 'obsidian_ptp.ltx', 'obsidian_ptp_routed.dcp'):
                (folder/name).write_bytes(b'synthetic completed artifact')
                artifacts[name] = ROUTE.sha(folder/name)
        proof = dict(status='passed', returncode=0, capacity=capacity, max_nodes=3*capacity,
                     validation_stage=stage, sources_changed=[], missing_artifacts=[],
                     hardware_programmed=False, artifacts_sha256=artifacts,
                     finished_at_utc='2026-10-29T00:00:00+00:00')
        (folder/'execution.json').write_text(json.dumps(proof))
        return folder

    def change_proof(self, **values):
        path = self.synthesis/'execution.json'
        proof = json.loads(path.read_text())
        proof.update(values)
        path.write_text(json.dumps(proof))

    def test_valid_synthesis_preserves_embedded_constraint_fingerprints(self):
        _, _, hashes, provenance = ROUTE.validate_synthesis(self.synthesis)
        self.assertEqual(hashes, ROUTE.source_hashes())
        self.assertEqual(provenance['dcp_sha256'], ROUTE.sha(self.synthesis/ROUTE.SYNTH_DCP))
        self.assertEqual(len(provenance['embedded_constraints_sha256']), 2)

    def test_unfinished_failed_or_wrong_stage_is_rejected_before_vivado(self):
        original = json.loads((self.synthesis/'execution.json').read_text())
        for change in (dict(status='running'), dict(status='failed'),
                       dict(validation_stage='project'), dict(missing_artifacts=['synth.dcp']),
                       dict(finished_at_utc=None)):
            with self.subTest(change=change):
                (self.synthesis/'execution.json').write_text(json.dumps(original))
                self.change_proof(**change)
                output = self.root/('rejected_'+str(len(list(self.root.glob('rejected_*')))))
                argv = ['implement_ptp.py', '--synth-dir', str(self.synthesis), '--output', str(output)]
                with patch.object(sys, 'argv', argv), patch.object(ROUTE.subprocess, 'run') as run, \
                        redirect_stdout(io.StringIO()):
                    self.assertEqual(ROUTE.main(), 1)
                run.assert_not_called()
                self.assertEqual(json.loads((output/'execution.json').read_text())['status'], 'failed')

    def test_tampered_synthesis_checkpoint_is_rejected(self):
        with (self.synthesis/ROUTE.SYNTH_DCP).open('ab') as file:
            file.write(b'changed checkpoint')
        with self.assertRaisesRegex(RuntimeError, 'DCP fingerprint mismatch'):
            ROUTE.validate_synthesis(self.synthesis)

    def test_changed_sources_and_new_inventory_are_rejected(self):
        self.source.write_text('entity changed_probe is end;\n')
        with self.assertRaisesRegex(RuntimeError, 'Synthesis sources changed'):
            ROUTE.validate_synthesis(self.synthesis)
        (self.source.parent/'extra.vhd').write_text('entity extra is end;\n')
        with self.assertRaisesRegex(RuntimeError, 'source inventory changed'):
            ROUTE.validate_synthesis(self.synthesis)

    def test_missing_embedded_constraints_are_rejected_even_with_matching_dcp_hash(self):
        dcp = self.synthesis/ROUTE.SYNTH_DCP
        with zipfile.ZipFile(dcp, 'w') as archive:
            archive.writestr('obsidian_ptp_top.xdc', 'test_ref_m1_o test_obs_o\n')
        proof = json.loads((self.synthesis/'execution.json').read_text())
        proof['artifacts_sha256'][ROUTE.SYNTH_DCP] = ROUTE.sha(dcp)
        self.change_proof(artifacts_sha256=proof['artifacts_sha256'])
        with self.assertRaisesRegex(RuntimeError, 'missing embedded board/reset constraints'):
            ROUTE.validate_synthesis(self.synthesis)

    def test_empty_backend_success_is_not_a_routed_image(self):
        output = self.root/'empty_route'
        argv = ['implement_ptp.py', '--synth-dir', str(self.synthesis), '--output', str(output)]
        with patch.object(sys, 'argv', argv), \
                patch.object(ROUTE.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(ROUTE.main(), 1)
        run.assert_called_once()
        self.assertTrue(run.call_args.args[0][-1].endswith('implement_ptp.tcl'))
        proof = json.loads((output/'execution.json').read_text())
        self.assertEqual(proof['status'], 'failed')
        self.assertIn('obsidian_ptp.bit', proof['missing_artifacts'])
        self.assertEqual(proof['source_synthesis']['dcp_sha256'], ROUTE.sha(output/ROUTE.SYNTH_DCP))

    @staticmethod
    def write_xci(path, component, parameters):
        path.parent.mkdir(parents=True, exist_ok=True)
        values = ''.join(f'<v referenceId="{name}">{value}</v>' for name, value in parameters.items())
        path.write_text('<root><componentRef name="'+component+'"/>'+values.replace('<v ', '<configurableElementValue ')
                        .replace('</v>', '</configurableElementValue>')+'</root>')

    @staticmethod
    def write_json_xci(path, component, name, output_directory):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(schema='xilinx.com:schema:json_instance:1.0', ip_inst=dict(
            xci_name=name, component_reference='xilinx.com:ip:'+component, ip_revision='27',
            gen_directory=output_directory, parameters=dict(
                component_parameters={'Component_Name': [dict(value=name, resolve_type='user', usage='all')],
                                      'C_NUM_PROBE_OUT': [dict(value='13', format='long', usage='all')]},
                project_parameters={'DEVICE': [dict(value='xc7a35t')], 'PACKAGE': [dict(value='csg325')],
                                    'SPEEDGRADE': [dict(value='-2')]},
                runtime_parameters={'OUTPUTDIR': [dict(value=output_directory)],
                                    'SWVERSION': [dict(value='2025.2')]})))))

    def make_cache(self):
        baseline = self.make_proof(self.root/'baseline_k1', 1, 'routed_bitstream')
        for name in ('aurora_left', 'aurora_right', 'ptp_vio'):
            relative = Path('ptp_emulation.srcs/sources_1/ip')/name/(name+'.xci')
            for folder in (baseline, self.synthesis):
                component = 'vio:3.0' if name == 'ptp_vio' else 'aurora_8b10b:11.1'
                self.write_json_xci(folder/relative, component, name, str(folder/'generated'))
        entry = baseline/'ptp_emulation.cache/ip/2025.2/a/b/entry'
        entry.mkdir(parents=True)
        (entry/'dbg_hub.dcp').write_bytes(b'cached hub')
        self.write_xci(entry/'entry.xci', 'xsdbm', {'PARAM_VALUE.C_XSDB_NUM_SLAVES': '1',
                        'PROJECT_PARAM.DEVICE': 'xc7a35t', 'PROJECT_PARAM.PACKAGE': 'csg325',
                        'PROJECT_PARAM.SPEEDGRADE': '-2'})
        return baseline, entry

    def test_json_ip_normalization_preserves_revision_and_semantics_without_output_paths(self):
        left, right = self.root/'left.xci', self.root/'right.xci'
        self.write_json_xci(left, 'vio:3.0', 'ptp_vio', 'baseline/generated')
        self.write_json_xci(right, 'vio:3.0', 'ptp_vio', 'trial/generated')
        expected = ROUTE.ip_configuration(left)
        self.assertEqual(expected, ROUTE.ip_configuration(right))
        self.assertEqual(expected['componentRef']['name'], 'vio')
        self.assertEqual(expected['PROJECT_PARAM.DEVICE'], 'xc7a35t')
        document = json.loads(right.read_text())
        document['ip_inst']['ip_revision'] = '28'
        right.write_text(json.dumps(document))
        self.assertNotEqual(expected, ROUTE.ip_configuration(right))
        document['ip_inst']['ip_revision'] = '27'
        document['ip_inst']['parameters']['component_parameters']['C_NUM_PROBE_OUT'][0]['value'] = '14'
        right.write_text(json.dumps(document))
        self.assertNotEqual(expected, ROUTE.ip_configuration(right))

    def test_compatible_cache_is_copied_and_baseline_stays_unchanged(self):
        baseline, entry = self.make_cache()
        output = self.root/'cache_copy'
        output.mkdir()
        proof = ROUTE.cache_provenance(baseline, self.synthesis, output)
        copied = output/'ip_cache'/str((entry/'dbg_hub.dcp').relative_to(baseline/'ptp_emulation.cache/ip'))
        self.assertEqual(ROUTE.sha(copied), ROUTE.sha(entry/'dbg_hub.dcp'))
        copied.write_bytes(b'private change')
        self.assertEqual((entry/'dbg_hub.dcp').read_bytes(), b'cached hub')
        self.assertEqual(proof['execution_sha256'], ROUTE.sha(baseline/'execution.json'))

    def test_incompatible_ip_or_hub_cache_is_rejected(self):
        baseline, entry = self.make_cache()
        relative = Path('ptp_emulation.srcs/sources_1/ip/ptp_vio/ptp_vio.xci')
        self.write_xci(self.synthesis/relative, 'different_vio', {'PARAM_VALUE.Component_Name': 'different'})
        with self.assertRaisesRegex(RuntimeError, 'IP customization differs'):
            ROUTE.cache_provenance(baseline, self.synthesis, self.root/'unused')
        (self.synthesis/relative).write_bytes((baseline/relative).read_bytes())
        self.write_xci(entry/'entry.xci', 'xsdbm', {'PARAM_VALUE.C_XSDB_NUM_SLAVES': '2'})
        with self.assertRaisesRegex(RuntimeError, 'Debug-hub cache customization/version mismatch'):
            ROUTE.cache_provenance(baseline, self.synthesis, self.root/'unused')


@unittest.skipIf(tkinter is None, 'Python Tcl interpreter unavailable')
class ImplementationTcl(unittest.TestCase):
    def exercise(self, pulse_slack, bad_reference=False, missing_port=''):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            environment = dict(OBSIDIAN_PTP_ROOT=ROOT.as_posix(), OBSIDIAN_PTP_BUILD=output.as_posix(),
                               OBSIDIAN_PTP_ROUTE_SYNTH=(output/'synthetic.dcp').as_posix())
            with patch.dict(os.environ, environment):
                interpreter = tkinter.Tcl()
                interpreter.eval('unset -nocomplain ::env(OBSIDIAN_PTP_IP_CACHE)')
                sentinels = ('build', 'channel', 'text', 'paths', 'report', 'values', 'header',
                             'start', 'original', 'implementation', 'manifest')
                for name in sentinels:
                    interpreter.call('set', name, 'global sentinel')
                interpreter.call('set', 'mock_pulse', str(pulse_slack))
                interpreter.call('set', 'mock_reference', 'other_system' if bad_reference else 'ptp_emulation_system')
                interpreter.call('set', 'mock_missing_port', missing_port)
                interpreter.eval('''
set bit_written 0
proc version {args} {return 2025.2}
proc open_checkpoint {args} {}
proc current_project {} {return project}
proc current_design {} {return design}
proc get_property {property object} {
 if {$property eq "PART"} {return xc7a35tcsg325-2}
 if {$property eq "NAME"} {return obsidian_ptp_synth}
 if {$property eq "REF_NAME"} {return $::mock_reference}
 if {$property eq "SLACK"} {return 0.5}
 error "Unexpected property $property"
}
proc get_timing_paths {args} {return path}
proc get_cells {args} {return u_ptp}
proc get_ports {args} {if {[lindex $args end] eq $::mock_missing_port} {return {}};return port}
proc get_drc_violations {args} {return {}}
proc check_timing {args} {return "checking no_clock (0)\nchecking unconstrained_internal_endpoints (0)"}
foreach command {opt_design place_design phys_opt_design route_design} {proc $command {args} {}}
proc mock_report {args} {
 set index [lsearch -exact $args -file]
 if {$index<0} {error "Expected report filename"}
 set file [open [lindex $args [expr {$index+1}]] w]
 puts $file "synthetic report";close $file
}
foreach command {report_utilization report_bus_skew report_drc report_cdc report_pulse_width write_checkpoint write_debug_probes} {
 proc $command {args} {mock_report {*}$args}
}
proc write_checkpoint {args} {set file [open [lindex $args end] w];puts $file checkpoint;close $file}
proc write_debug_probes {args} {set file [open [lindex $args end] w];puts $file probes;close $file}
proc report_timing {args} {
 set file [open [lindex $args end] w];puts $file "Requirement: 8.000ns (MaxDelay Path)";close $file
}
proc report_timing_summary {args} {
 set file [open [lindex $args end] w]
 puts $file "WNS(ns) TNS(ns) Failing Total WHS(ns) THS(ns) Failing Total WPWS(ns) TPWS(ns) Failing Total"
 puts $file "0.5 0.0 0 100 0.1 0.0 0 100 $::mock_pulse 0.0 0 10"
 close $file
}
proc write_bitstream {args} {set ::bit_written 1;set file [open [lindex $args end] w];puts $file bit;close $file}
''')
                failure = ('Checkpoint PTP hierarchy mismatch' if bad_reference else
                           'Checkpoint board port missing' if missing_port else
                           'Pulse-width timing did not pass' if pulse_slack < 0 else None)
                if failure:
                    with self.assertRaisesRegex(tkinter.TclError, failure):
                        interpreter.call('source', str(ROOT/'scripts/implement_ptp.tcl'))
                    self.assertEqual(int(interpreter.call('set', 'bit_written')), 0)
                else:
                    interpreter.call('source', str(ROOT/'scripts/implement_ptp.tcl'))
                    self.assertEqual(int(interpreter.call('set', 'bit_written')), 1)
                    for name in sentinels:
                        self.assertEqual(interpreter.call('set', name), 'global sentinel')

    def test_checkpoint_basename_accepts_valid_netlist_signature_and_positive_timing(self):
        self.exercise(0.1)

    def test_wrong_ptp_reference_stops_before_bitstream(self):
        self.exercise(0.1, bad_reference=True)

    def test_missing_board_port_stops_before_bitstream(self):
        self.exercise(0.1, missing_port='test_obs_o')

    def test_negative_pulse_width_stops_before_bitstream(self):
        self.exercise(-0.1)


if __name__ == '__main__':
    unittest.main()
