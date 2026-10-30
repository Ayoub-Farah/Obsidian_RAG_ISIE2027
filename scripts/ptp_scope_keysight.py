"""Fresh paired RAW acquisitions from a Keysight DSO-X 3014T, CH1/CH3 by default.

Only scope acquisition is controlled here; PTP configuration and GPIO selection
are managed separately. Each saved pair comes from one completed DIGitize.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import time

import numpy as np
import pyvisa

from ptp_scope_analysis import parse_ieee_block, decode_preamble, decode_waveform, paired_delays

RESOURCE = 'USB0::0x2A8D::0x1768::MY58032112::INSTR'
GUIDE = 'https://www.keysight.com/us/en/assets/9023-40024/miscellaneous/3kT_X-Series_prog_guide.pdf'


def utc():
    return datetime.now(timezone.utc).isoformat()


class Scope:
    def __init__(self, directory, *, resource=RESOURCE, reference=1, observed=3):
        if reference == observed or any(ch not in (1,2,3,4) for ch in (reference,observed)):
            raise ValueError('Two distinct analog channels are required')
        self.reference, self.observed = reference, observed
        self.channels = (reference, observed)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.log = (self.directory/'scpi.jsonl').open('w', encoding='utf-8')
        self.rm = pyvisa.ResourceManager()
        self.device = self.rm.open_resource(resource)
        self.device.timeout = 15000
        self.device.read_termination = '\n'
        self.device.write_termination = '\n'
        self.device.chunk_size = 1048576
        self.completed = False
        self.identity = self.query('*IDN?')
        if 'DSO-X 3014T' not in self.identity:
            self.close()
            raise ValueError('Expected the DSO-X 3014T: ' + self.identity)

    def record(self, command, reply=None):
        self.log.write(json.dumps(dict(utc=utc(), command=command, reply=reply))+'\n')
        self.log.flush()

    def write(self, command):
        self.device.write(command)
        self.record(command)

    def query(self, command):
        result = self.device.query(command).strip()
        self.record(command, result)
        return result

    def binary(self, command):
        termination=self.device.read_termination
        self.device.read_termination=None
        try:
            self.device.write(command)
            payload = parse_ieee_block(self.device.read_raw())
        finally:
            self.device.read_termination=termination
        self.record(command, dict(payload_bytes=len(payload)))
        return payload

    def errors(self):
        errors = []
        for _ in range(32):
            error = self.query(':SYSTem:ERRor?')
            if error.startswith(('0,','+0,')):
                break
            errors.append(error)
        if errors:
            raise RuntimeError('SCPI errors: ' + repr(errors))

    def configure(self, scale):
        self.write(':STOP')
        self.completed = False
        for channel in (1,2,3,4):
            self.write(f':CHANnel{channel}:DISPlay {int(channel in self.channels)}')
        for channel in self.channels:
            for command in ('IMPedance ONEMeg','COUPling DC','BWLimit OFF','INVert OFF',
                            'PROBe:SKEW 0','SCALe 1','OFFSet 1.65'):
                self.write(f':CHANnel{channel}:'+command)
        for command in (':ACQuire:MODE RTIMe', ':ACQuire:TYPE NORMal', ':ACQuire:COMPlete 100',
                        ':TIMebase:MODE MAIN', ':TIMebase:REFerence CENTer',
                        f':TIMebase:SCALe {scale}', ':TIMebase:POSition 0',
                        ':TRIGger:MODE EDGE', ':TRIGger:SWEep NORMal',
                        f':TRIGger:EDGE:SOURce CHANnel{self.reference}',
                        ':TRIGger:EDGE:SLOPe POSitive', ':TRIGger:EDGE:LEVel 1.65'):
            self.write(command)
        self.errors()
        self.scale = float(self.query(':TIMebase:SCALe?'))

    def settings(self):
        queries = ['*IDN?',':ACQuire:MODE?',':ACQuire:TYPE?',':ACQuire:POINts?',':ACQuire:SRATe?',
                   ':TIMebase:MODE?',':TIMebase:SCALe?',':TIMebase:POSition?',
                   ':TRIGger:SWEep?',':TRIGger:EDGE:SOURce?',':TRIGger:EDGE:LEVel?']
        queries += [f':CHANnel{ch}:{key}?' for ch in self.channels
                    for key in ('PROBe','IMPedance','COUPling','SCALe','OFFSet','BWLimit','INVert','PROBe:SKEW')]
        return {query:self.query(query) for query in queries}

    def single(self):
        self.completed = False
        started = utc()
        self.write(':DIGitize '+','.join(f'CHANnel{ch}' for ch in self.channels))
        try:
            if self.query('*OPC?') != '1':
                raise RuntimeError('DIGitize did not complete')
        except Exception as error:
            self.record('acquisition_arming_error',str(error))
            self.device.clear()
            self.write(':STOP')
            raise
        self.completed = True
        return started

    def pair(self, stem, *, started=None, expected_period=None):
        if not self.completed:
            raise ValueError('A completed fresh DIGitize is required before waveform transfer')
        condition_before=int(self.query(':OPERegister:CONDition?'))
        if condition_before&8:
            raise ValueError('Scope is still running before paired waveform transfer')
        native_points = int(float(self.query(':ACQuire:POINts?')))
        native_rate = float(self.query(':ACQuire:SRATe?'))
        if self.query(':ACQuire:TYPE?') != 'NORM':
            raise ValueError('Averaging/high-resolution acquisition cannot qualify raw jitter')
        metadata = dict(utc=utc(), acquisition_started_utc=started, trigger_state='STOP',
                        completion='DIGitize then *OPC?=1', reference_channel=self.reference,
                        observed_channel=self.observed, scope_identity=self.identity,
                        allow_per_channel_x_origin=True,
                        native_points=native_points, native_sample_rate=native_rate, channels={})
        metadata['operation_condition_before']=condition_before
        arrays, traces = {}, {}
        for channel in self.channels:
            self.write(f':WAVeform:SOURce CHANnel{channel}')
            self.write(':WAVeform:FORMat BYTE')
            self.write(':WAVeform:UNSigned ON')
            self.write(':WAVeform:POINts:MODE RAW')
            # Reset the point request as well as the mode: an earlier fine-view
            # count otherwise survives and decimates a later wide acquisition.
            self.write(':WAVeform:POINts MAXimum')
            maximum = int(float(self.query(':WAVeform:POINts?')))
            text = self.query(':WAVeform:PREamble?')
            preamble = decode_preamble(text)
            if preamble['format'] != 0 or preamble['type'] != 0 or preamble['count'] != 1:
                raise ValueError('Expected unsigned BYTE/NORM single-acquisition data')
            unsigned = self.query(':WAVeform:UNSigned?')
            points_mode = self.query(':WAVeform:POINts:MODE?')
            # This firmware switches RAW to MAX after an explicit POINts value.
            # MAX on a stopped NORM acquisition exposes the acquisition record;
            # Native sample interval and complete visible window reject decimation.
            if unsigned != '1' or points_mode not in ('RAW','MAX'):
                raise ValueError('Full-memory unsigned transfer was not applied')
            payload = self.binary(':WAVeform:DATA?')
            if len(payload) != preamble['points'] or preamble['points'] != maximum:
                raise ValueError('Incomplete waveform transfer')
            if not 1 <= maximum <= native_points or not np.isclose(preamble['x_increment']*native_rate,1,rtol=1e-5):
                raise ValueError('RAW record length/sample rate differs from acquisition')
            # InfiniiVision exports the visible raw window, which can be smaller
            # than ACQuire:POINts (pre/post-display acquisition guard samples).
            if abs(maximum*preamble['x_increment']-10*self.scale) > max(2*preamble['x_increment'],.001*10*self.scale):
                raise ValueError('Transfer does not cover the complete visible raw time window')
            arrays[f'ch{channel}'] = np.frombuffer(payload,dtype=np.uint8)
            metadata['channels'][str(channel)] = dict(preamble=text,points=len(payload),
                voltage_encoding='keysight_byte',physical_channel=channel,
                points_mode=points_mode,full_available_raw_window_verified=True,
                native_sample_interval_verified=True,full_native_memory_transferred=maximum==native_points)
            traces[channel] = decode_waveform(payload,preamble,voltage_encoding='keysight_byte')
        np.savez_compressed(self.directory/f'{stem}.npz',**arrays)
        metadata['operation_condition_after']=int(self.query(':OPERegister:CONDition?'))
        path = self.directory/f'{stem}.json'
        path.write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
        try:
            if metadata['operation_condition_after']&8:
                raise ValueError('Scope restarted during paired waveform transfer')
            first, second = [decode_preamble(metadata['channels'][str(ch)]['preamble']) for ch in self.channels]
            if any(first[key] != second[key] for key in ('points','x_increment','x_reference')):
                raise ValueError('The two channels do not share one time grid')
            if abs(first['x_origin']-second['x_origin']) > 2*first['x_increment']:
                raise ValueError('Per-channel time origins differ by more than two sample intervals')
            metadata['channel_time_origin_delta_s'] = second['x_origin']-first['x_origin']
            validation = paired_delays(*traces[self.reference],*traces[self.observed],
                                       max_delta=1e-6,expected_period_s=expected_period,threshold_v=1.65)
            metadata['validation'] = dict(status='passed',paired_edges=validation['count'],
                                           mean_delay_s=validation['mean_s'],period_verified=validation['expected_period_verified'])
            self.errors()
        except Exception as error:
            metadata['validation'] = dict(status='failed',error=str(error))
            raise
        finally:
            path.write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
        self.completed = False
        return metadata

    def screenshot(self, name):
        payload = self.binary(':DISPlay:DATA? PNG,COLor')
        if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Invalid scope PNG')
        (self.directory/name).write_bytes(payload)

    def close(self):
        self.device.close()
        self.rm.close()
        self.log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--resource',default=RESOURCE)
    parser.add_argument('--reference-channel',type=int,default=1)
    parser.add_argument('--observed-channel',type=int,default=3)
    parser.add_argument('--count',type=int,default=200)
    parser.add_argument('--window',type=float,default=20)
    parser.add_argument('--scale',type=float,default=2e-7)
    parser.add_argument('--case-id')
    parser.add_argument('--label')
    parser.add_argument('--board',choices=('A','B','C'))
    parser.add_argument('--node',type=int)
    parser.add_argument('--kind',choices=('module','instrument_calibration'),default='module')
    args = parser.parse_args()
    if args.count < 1 or args.window < 0 or args.scale <= 0:
        parser.error('Positive acquisition count/scale and nonnegative window required')
    scope = Scope(args.directory,resource=args.resource,reference=args.reference_channel,observed=args.observed_channel)
    summary = dict(started_utc=utc(),resource=args.resource,scope_identity=scope.identity,
                   reference_channel=args.reference_channel,observed_channel=args.observed_channel,
                   fresh_single_acquisitions=0,status='running',programming_guide=GUIDE)
    if args.case_id:
        marker = dict(id=args.case_id,label=args.label or args.case_id,board=args.board,
                      observer_node=args.node,kind=args.kind,expected_period_s=1e-4,
                      reference_channel=args.reference_channel,observed_channel=args.observed_channel)
        (scope.directory/'case.json').write_text(json.dumps(marker,indent=2)+'\n',encoding='utf-8')
    try:
        scope.configure(5e-5)
        stamp = scope.single()
        scope.pair('wide_before',started=stamp,expected_period=1e-4)
        scope.configure(args.scale)
        scope.write(':DISPlay:CLEar')
        scope.write(':RUN')
        start = time.monotonic()
        time.sleep(args.window)
        scope.write(':STOP')
        summary['settling_window_wall_s'] = time.monotonic()-start
        scope.screenshot('screen_before_fresh_acquisitions.png')
        summary['settings'] = scope.settings()
        rng = random.Random(20261030)
        for index in range(args.count):
            time.sleep(rng.uniform(.001,.004))
            stamp = scope.single()
            scope.pair(f'single_{index:04d}',started=stamp)
            summary['fresh_single_acquisitions'] = index+1
            if index%20==0:
                print(json.dumps(dict(utc=utc(),fresh_acquisitions=index+1,requested=args.count)),flush=True)
        summary['status'] = 'acquired'
        scope.write(':RUN')
    except Exception as error:
        summary.update(status='error',error=str(error))
        try:
            scope.device.clear()
            scope.write(':STOP')
        except Exception:
            pass
        raise
    finally:
        summary['finished_utc'] = utc()
        (scope.directory/'acquisition.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        scope.close()


if __name__ == '__main__':
    main()
