"""Campaign orchestration tests with RPC and capture subprocesses mocked."""
from argparse import Namespace
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import ptp_scope_campaign as campaign


def health(node=2):
    return dict(schema='ptp_scope_hardware_rpc_v1', status='ok',
                health_scope='connected_boards_only', expected_connected=['OBS001A', 'OBS003A'],
                cards=[dict(serial='OBS001A', available=True, nominal=True,
                            observer_hex=f'{node | 1 << 16:x}', output8_hex=f'{node:x}',
                            output9_hex='0', output10_hex='1'),
                       dict(serial='OBS003A', available=True, nominal=True),
                       dict(serial='OBS002A', available=False, nominal=None)])


class CampaignTests(unittest.TestCase):
    def setup_report(self, path, nodes='2'):
        rpc = path / 'hardware_rpc'
        rpc.mkdir()
        (rpc / 'ready.json').write_text(json.dumps(dict(
            status='ready', expected_connected=['OBS001A', 'OBS003A'])), encoding='utf-8')
        return Namespace(report=path, board='A', nodes=nodes, count=2, window=.01,
                         prefix=None, wiring_verified=False, verification_source=None)

    def mocks(self, report, *, capture_failure=False, empty_capture=False):
        report = report.resolve()
        calls = []

        def rpc(path, command, ready_hash):
            calls.append(command)
            node = int(command.split()[-1]) if command.startswith('observe') else int(calls[-2].split()[-1])
            receipt = health(node)
            marker = report / 'hardware_rpc' / f'mock_{len(calls)}.json'
            marker.write_text(json.dumps(receipt), encoding='utf-8')
            return marker, receipt

        def capture(command, *, check, shell):
            self.assertTrue(check)
            self.assertFalse(shell)
            if empty_capture:
                return subprocess.CompletedProcess(command, 0)
            directory = Path(command[2])
            directory.mkdir()
            node = int(command[command.index('--node') + 1])
            case = dict(id=f'A_M{node + 1}', board='A', observer_node=node, kind='module')
            (directory / 'case.json').write_text(json.dumps(case), encoding='utf-8')
            (directory / 'raw_evidence').write_bytes(b'preserve')
            (directory / 'acquisition.json').write_text(json.dumps(dict(
                status='acquired', fresh_single_acquisitions=2)), encoding='utf-8')
            if capture_failure:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)

        return calls, rpc, capture

    def test_success_attaches_health_without_inventing_wiring_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp); args = self.setup_report(report)
            calls, rpc, capture = self.mocks(report)
            with patch.object(campaign, 'rpc', rpc), patch.object(campaign.subprocess, 'run', capture):
                log = campaign.campaign(args)
            self.assertEqual(calls, ['observe OBS001A 2', 'status'])
            self.assertEqual(json.loads(log.read_text())['status'], 'acquired')
            case = json.loads((report / campaign.FOLDERS[2] / 'case.json').read_text())
            self.assertIs(case['wiring_verified'], False)
            self.assertEqual(case['health_before_receipt'], 'hardware_rpc/mock_1.json')
            self.assertEqual(case['health_after_receipt'], 'hardware_rpc/mock_2.json')

    def test_capture_failure_preserves_raw_and_aborts_before_next_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp); args = self.setup_report(report, '1,2')
            calls, rpc, capture = self.mocks(report, capture_failure=True)
            with patch.object(campaign, 'rpc', rpc), patch.object(campaign.subprocess, 'run', capture):
                with self.assertRaises(RuntimeError):campaign.campaign(args)
            self.assertEqual(calls, ['observe OBS001A 1', 'status'])
            self.assertEqual((report / campaign.FOLDERS[1] / 'raw_evidence').read_bytes(), b'preserve')
            self.assertFalse((report / campaign.FOLDERS[2]).exists())
            self.assertEqual(json.loads(next(report.glob('group_run_*.json')).read_text())['status'], 'failed')

    def test_empty_successful_subprocess_does_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp); args = self.setup_report(report)
            _, rpc, capture = self.mocks(report, empty_capture=True)
            with patch.object(campaign, 'rpc', rpc), patch.object(campaign.subprocess, 'run', capture):
                with self.assertRaises(FileNotFoundError):campaign.campaign(args)
            self.assertEqual(json.loads(next(report.glob('group_run_*.json')).read_text())['status'], 'failed')

    def test_health_requires_connected_pair_and_every_available_card_nominal(self):
        campaign.check_health(health(), 'OBS001A', ['OBS001A', 'OBS003A'], 2)
        for available, nominal in ((True, False), (False, None)):
            bad = health(); bad['cards'][1].update(available=available, nominal=nominal)
            with self.assertRaises(ValueError):
                campaign.check_health(bad, 'OBS001A', ['OBS001A', 'OBS003A'], 2)

    def test_unlocked_measurement_option_keeps_operational_faults_blocking(self):
        receipt=health();receipt['cards'][1].update(nominal=False,operational=True)
        with self.assertRaises(ValueError):campaign.check_health(receipt,'OBS001A',['OBS001A','OBS003A'],2)
        campaign.check_health(receipt,'OBS001A',['OBS001A','OBS003A'],2,require_locked=False)
        receipt['cards'][1]['operational']=False
        with self.assertRaises(ValueError):campaign.check_health(receipt,'OBS001A',['OBS001A','OBS003A'],2,require_locked=False)

    def test_pending_request_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp); self.setup_report(report)
            pending = report / 'hardware_rpc' / 'request.txt'
            pending.write_text('earlier status\n', encoding='ascii')
            ready_hash = hashlib.sha256(pending.with_name('ready.json').read_bytes()).hexdigest()
            with self.assertRaises(FileExistsError):campaign.rpc(report, 'status', ready_hash)
            self.assertEqual(pending.read_text(), 'earlier status\n')

    def test_rpc_rejects_mismatched_receipt_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp); self.setup_report(report)
            ready_hash = hashlib.sha256((report / 'hardware_rpc' / 'ready.json').read_bytes()).hexdigest()

            def answer(_):
                request = (report / 'hardware_rpc' / 'request.txt').read_text().strip()
                request_id = request.split()[0]
                (report / 'hardware_rpc' / f'{request_id}.json').write_text(json.dumps(dict(
                    request_id=request_id, request='different status')), encoding='utf-8')

            with patch.object(campaign.time, 'sleep', answer):
                with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                    campaign.rpc(report, 'status', ready_hash)

    def test_local_ownership_and_existing_case_fail_before_rpc(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp); args = self.setup_report(report, '3')
            with self.assertRaises(ValueError):campaign.campaign(args)
            args.nodes = '2'; (report / campaign.FOLDERS[2]).mkdir()
            with self.assertRaises(FileExistsError):campaign.campaign(args)


if __name__ == '__main__':
    unittest.main()
