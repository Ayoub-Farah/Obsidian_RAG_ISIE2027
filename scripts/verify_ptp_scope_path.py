"""Verify an operator-connected CH3 OBS path by disabling and reenabling GPIO.

Does not reset PTP, alter logical clock rates or program an FPGA. Diagnostic
AUTO-trigger acquisitions must actually contain reference edges to pass.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from ptp_scope_campaign import BOARDS,rpc,check_health
from ptp_scope_keysight import Scope
from ptp_scope_analysis import decode_preamble,decode_waveform,rising_edges


def snapshot(directory,*,flat):
    scope=Scope(directory)
    try:
        scope.configure(5e-5)
        scope.write(':TRIGger:SWEep AUTO')
        started=scope.single()
        try:scope.pair('identity_pair',started=started,expected_period=None if flat else 1e-4)
        except ValueError:
            if not flat:raise
        metadata=json.loads((directory/'identity_pair.json').read_text())
        with np.load(directory/'identity_pair.npz') as archive:
            traces={ch:decode_waveform(archive['ch'+ch].tobytes(),decode_preamble(metadata['channels'][ch]['preamble']),
                                       voltage_encoding='keysight_byte') for ch in ('1','3')}
        reference=rising_edges(*traces['1'],threshold_v=1.65)
        observed=traces['3'][1]
        result=dict(reference_edges=reference['edge_count'],observed_peak_to_peak_v=float(np.ptp(observed)),
                    observed_max_abs_v=float(np.max(np.abs(observed))),metadata=metadata)
        if flat and not (reference['edge_count']>=2 and np.ptp(observed)<.5 and np.max(np.abs(observed))<.5):
            raise ValueError('Disabling the selected OBS did not uniquely flatten CH3 while CH1 pulsed')
        if not flat and metadata['validation']['status']!='passed':
            raise ValueError('Reference/observed pulses did not return after enabling OBS')
        scope.screenshot('identity.png')
        return result
    except Exception:
        try:scope.device.clear();scope.write(':STOP')
        except Exception:pass
        raise
    finally:scope.close()


def verify(report,board,*,allow_unlocked=False):
    report=report.resolve();serial,node=BOARDS[board]
    ready=report/'hardware_rpc/ready.json'
    expected=json.loads(ready.read_text())['expected_connected']
    digest=hashlib.sha256(ready.read_bytes()).hexdigest()
    initial,health=rpc(report,f'observe {serial} {node}',digest)
    check_health(health,serial,expected,node,require_locked=not allow_unlocked)
    disabled=None
    try:
        disabled,health=rpc(report,f'disable {serial}',digest)
        check_health(health,serial,expected,require_locked=not allow_unlocked)
        off=snapshot(report/f'{board}_identity_disabled',flat=True)
    finally:
        restored,health=rpc(report,f'observe {serial} {node}',digest)
        check_health(health,serial,expected,node,require_locked=not allow_unlocked)
    on=snapshot(report/f'{board}_identity_reenabled',flat=False)
    record=dict(recorded_utc=datetime.now(timezone.utc).isoformat(),board=board,
                reference_channel=1,observed_channel=3,operator_wiring_confirmed=True,
                reference='A_TEST_SYNC_TP23_or_TP15',observed=f'{board}_TEST_OBS_MOSI_TP24_or_TP16',
                observed_ground=board+'_GND',path_identity_verified=True,
                allow_unlocked_measurements=allow_unlocked,
                initial_receipt=initial.relative_to(report).as_posix(),
                disabled_receipt=disabled.relative_to(report).as_posix(),
                reenabled_receipt=restored.relative_to(report).as_posix(),
                disabled=off,reenabled=on)
    output=report/'provenance'/f'{board}_wiring_verified.json'
    with output.open('x',encoding='utf-8') as stream:stream.write(json.dumps(record,indent=2)+'\n')
    print(json.dumps(dict(board=board,status='verified',disabled_reference_edges=off['reference_edges'],
                         disabled_observed_peak_to_peak_v=off['observed_peak_to_peak_v'],
                         reenabled_paired_edges=on['metadata']['validation']['paired_edges'])),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--board',choices=tuple(BOARDS),required=True)
    parser.add_argument('--operator-confirmed',action='store_true',required=True)
    parser.add_argument('--allow-unlocked-measurements',action='store_true')
    args=parser.parse_args()
    verify(args.report,args.board,allow_unlocked=args.allow_unlocked_measurements)


if __name__=='__main__':main()
