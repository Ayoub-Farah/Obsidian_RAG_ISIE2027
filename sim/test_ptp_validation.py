"""Proof-gate regressions with synthetic files/processes; no Vivado or hardware."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = load_module('_ptp_build_proof_contract', ROOT/'scripts/build_ptp.py')
VALIDATE = load_module('_ptp_rtl_proof_contract', ROOT/'tools/validate_ptp.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BuildProofGates(unittest.TestCase):
    def check_empty_success_rejected(self, options, expected_artifact):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root/'scripts'
            scripts.mkdir()
            for name in ('build_ptp.tcl', 'build.tcl', 'create_ptp_project.tcl',
                         'aurora_common.tcl', 'generate_aurora_adapter.py'):
                (scripts/name).write_text('# synthetic build input\n')
            destination = root/'output'
            argv = ['build_ptp.py', '--vivado', 'mock-vivado', '--output', str(destination), *options]
            with patch.object(BUILD, 'ROOT', root), patch.object(sys, 'argv', argv), \
                    patch.object(BUILD.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(BUILD.main(), 1)
            run.assert_called_once()
            proof = json.loads((destination/'execution.json').read_text())
            self.assertEqual((proof['status'], proof['returncode']), ('failed', 0))
            self.assertIn(expected_artifact, proof['missing_artifacts'])

    def test_empty_success_is_not_a_generated_project(self):
        self.check_empty_success_rejected(['--project-only'], 'ptp_emulation.xpr')

    def test_empty_success_is_not_a_synthesis(self):
        self.check_empty_success_rejected(['--synth-only'], 'obsidian_ptp_synth.dcp')

    def test_empty_success_is_not_a_routed_image(self):
        self.check_empty_success_rejected([], 'obsidian_ptp.bit')


class RtlProofGates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rtl = self.root/'evidence'
        self.output = self.root/'report'
        self.rtl.mkdir()
        self.output.mkdir()
        self.source = self.root/'sim/tb_sync_system.vhd'
        self.source.parent.mkdir()
        self.source.write_text('entity tb_sync_system is end;\n')
        self.write_json('source_sha256.json', {str(self.source.relative_to(self.root)): digest(self.source)})
        self.write_json('results.json', [dict(name=prefix+'tb_sync_stalls', passed=True)
                                        for prefix in ('elab_', 'sim_')])
        self.proof = dict(status='passed', source_snapshot_sha256=digest(self.rtl/'source_sha256.json'),
                          results_sha256=digest(self.rtl/'results.json'),
                          cases={'tb_sync_stalls': dict(entity='tb_sync_system', generics='G_STALL=>true')})
        self.write_json('execution.json', self.proof)
        (self.rtl/'sim_tb_sync_stalls.log').write_text('PASS synthetic stall coverage\n')

    def write_json(self, name, value):
        (self.rtl/name).write_text(json.dumps(value))

    def invoke(self):
        def python_success(command, **arguments):
            # Collecting existing RTL must only run the Python contracts.
            self.assertEqual(command[1:3], ['-m', 'unittest'])
            arguments['stdout'].write('Ran 1 tests in 0.001s\n\nOK\n')
            return SimpleNamespace(returncode=0)

        argv = ['validate_ptp.py', '--collect-existing-rtl', '--rtl-dir', str(self.rtl),
                '--output', str(self.output)]
        with patch.object(VALIDATE, 'ROOT', self.root), \
                patch.object(VALIDATE, 'SINGLE_CASES', ['tb_sync_stalls']), \
                patch.object(sys, 'argv', argv), \
                patch.object(VALIDATE.subprocess, 'run', side_effect=python_success), \
                redirect_stdout(io.StringIO()):
            VALIDATE.main()

    def assert_rejected(self, message):
        with self.assertRaisesRegex(RuntimeError, message):
            self.invoke()
        self.assertEqual(json.loads((self.output/'validation.json').read_text())['status'], 'failed')

    def test_completed_matching_proof_is_accepted(self):
        self.invoke()
        report = json.loads((self.output/'validation.json').read_text())
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['rtl_cases'], ['tb_sync_stalls'])

    def test_running_execution_cannot_reuse_old_pass_logs(self):
        self.proof['status'] = 'running'
        self.write_json('execution.json', self.proof)
        self.assert_rejected('Incomplete or inconsistent RTL execution')

    def test_stale_success_does_not_cover_changed_rtl(self):
        self.source.write_text(self.source.read_text()+'-- source changed after execution\n')
        self.assert_rejected('Missing successful source-matched RTL case')

    def test_tampered_source_manifest_is_rejected(self):
        path = self.rtl/'source_sha256.json'
        path.write_text(path.read_text()+'\n')
        self.assert_rejected('Incomplete or inconsistent RTL execution')

    def test_tampered_results_are_rejected(self):
        path = self.rtl/'results.json'
        path.write_text(path.read_text()+'\n')
        self.assert_rejected('Incomplete or inconsistent RTL execution')

    def test_passing_wrong_generic_does_not_cover_requested_variant(self):
        self.proof['cases']['tb_sync_stalls']['generics'] = 'G_STALL=>false'
        self.write_json('execution.json', self.proof)
        self.assert_rejected('Missing successful source-matched RTL case')

    def test_new_rtl_file_invalidates_old_inventory(self):
        extra = self.root/'rtl/sync/new_unit.vhd'
        extra.parent.mkdir(parents=True)
        extra.write_text('entity new_unit is end;\n')
        self.assert_rejected('Compiled RTL source inventory differs')

    def test_failed_rerun_replaces_old_pass_marker(self):
        marker = self.output/'validation.json'
        marker.write_text(json.dumps(dict(status='passed')))

        def fail_execution(arguments):
            self.assertEqual(json.loads(marker.read_text())['status'], 'running')
            raise RuntimeError('synthetic execution failure')

        argv = ['validate_ptp.py', '--output', str(self.output)]
        with patch.object(sys, 'argv', argv), patch.object(VALIDATE, 'execute', side_effect=fail_execution), \
                self.assertRaisesRegex(RuntimeError, 'synthetic execution failure'):
            VALIDATE.main()
        proof = json.loads(marker.read_text())
        self.assertEqual(proof['status'], 'failed')
        self.assertIn('synthetic execution failure', proof['error'])


if __name__ == '__main__':
    unittest.main()
