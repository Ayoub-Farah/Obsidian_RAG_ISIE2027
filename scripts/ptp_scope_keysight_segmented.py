"""Fast triggered RAW segments from DSO-X 3014T; no per-point rearming.

Firmware 7.20 has no all-segments waveform query. One hardware burst is frozen
once, then each segment's two raw channels, preambles and time tag are exported.
Segments in one burst can be correlated; no iid or absolute epoch claim is made.
"""
import argparse
import json
from pathlib import Path
import time
import uuid

import numpy as np
import pyvisa

from ptp_scope_keysight import Scope,RESOURCE,GUIDE,utc
from ptp_scope_analysis import decode_preamble


def acquire(args):
    if args.count<2 or args.segments_per_burst<2:
        raise ValueError('At least two triggered segments are required')
    scope=Scope(args.directory,resource=args.resource,reference=args.reference_channel,observed=args.observed_channel)
    began=time.monotonic()
    summary=dict(started_utc=utc(),scope_identity=scope.identity,resource=args.resource,
                 acquisition_kind='segmented_triggered_bursts',fresh_single_acquisitions=0,
                 reference_channel=args.reference_channel,observed_channel=args.observed_channel,
                 bursts=[],status='running',programming_guide=GUIDE,
                 note='Each single_* file is one hardware-triggered segment; one software SINGLE arms a burst. Consecutive segments can be correlated.')
    if args.case_id:
        marker=dict(id=args.case_id,label=args.label or args.case_id,board=args.board,observer_node=args.node,
                    kind=args.kind,expected_period_s=1e-4,reference_channel=args.reference_channel,
                    observed_channel=args.observed_channel,acquisition_kind='segmented_triggered_bursts')
        (scope.directory/'case.json').write_text(json.dumps(marker,indent=2)+'\n',encoding='utf-8')
    try:
        # One wide diagnostic verifies period and channel identity before bursts.
        scope.configure(5e-5);stamp=scope.single()
        scope.pair('wide_before',started=stamp,expected_period=1e-4)
        scope.configure(args.scale)
        scope.write(':ACQuire:MODE SEGMented')
        for ch in scope.channels:
            scope.write(f':WAVeform:SOURce CHANnel{ch}')
            scope.write(':WAVeform:FORMat BYTE;:WAVeform:UNSigned ON;:WAVeform:POINts:MODE RAW;:WAVeform:POINts MAXimum')
        scope.errors()
        exported=0
        while exported<args.count:
            count=min(args.segments_per_burst,args.count-exported)
            if args.count-exported-count==1:count-=1
            if count<2:raise ValueError('Burst partition leaves a one-segment remainder')
            scope.write(f':ACQuire:SEGMented:COUNt {count}')
            if int(scope.query(':ACQuire:SEGMented:COUNt?'))!=count:
                raise ValueError('Requested segment count exceeds available scope memory')
            burst_id=uuid.uuid4().hex
            start=utc();started=time.monotonic()
            scope.write(':SINGle')
            while True:
                actual=int(scope.query(':WAVeform:SEGMented:COUNt?'))
                condition=int(scope.query(':OPERegister:CONDition?'))
                if actual==count and not condition&8:break
                if time.monotonic()-started>10:raise TimeoutError('Segment burst did not complete within 10 s')
                time.sleep(.01)
            acquisition_wall=time.monotonic()-started
            # Firmware 7.20 can reject the first query after the completion
            # transition. Retry this read of the same frozen buffer, never rearm.
            handoff=[];saved_timeout=scope.device.timeout;scope.device.timeout=250
            deadline=time.monotonic()+5
            try:
                while True:
                    try:
                        first_tag=float(scope.query(':ACQuire:SEGMented:INDex 1;:WAVeform:SEGMented:TTAG?'))
                        break
                    except pyvisa.errors.VisaIOError as error:
                        if error.error_code!=pyvisa.constants.StatusCode.error_timeout:raise
                        scope.record('segment_buffer_read_retry',str(error));scope.device.clear();scope.write(':STOP')
                        diagnostic=[]
                        for _ in range(8):
                            item=scope.query(':SYSTem:ERRor?');diagnostic.append(item)
                            code=int(item.split(',',1)[0])
                            if code==0:break
                            if code not in (-221,-420):raise RuntimeError('Unexpected segment handoff error: '+item)
                        handoff.append(diagnostic)
                        if time.monotonic()>deadline:raise TimeoutError('Frozen segment buffer is unavailable')
            finally:scope.device.timeout=saved_timeout
            if actual!=count or condition&8:raise ValueError('Incomplete or still-running segmented acquisition')
            rate=float(scope.query(':ACQuire:SRATe?'))
            tags=[];first_index=exported
            for index in range(1,count+1):
                tag=float(scope.query(f':ACQuire:SEGMented:INDex {index};:WAVeform:SEGMented:TTAG?'))
                if tags and tag<=tags[-1]:raise ValueError('Segment time tags do not increase')
                tags.append(tag)
                meta=dict(utc=utc(),utc_is_export_time=True,trigger_state='STOP',
                          completion='segmented SINGLE, exact segment count, RUN bit clear',
                          acquisition_kind='segmented',burst_id=burst_id,burst_started_utc=start,
                          segment_index=index,segment_time_tag_s=tag,scope_identity=scope.identity,
                          reference_channel=scope.reference,observed_channel=scope.observed,
                          allow_per_channel_x_origin=True,native_sample_rate=rate,channels={})
                arrays={}
                for ch in scope.channels:
                    pre=scope.query(f':WAVeform:SOURce CHANnel{ch};:WAVeform:PREamble?')
                    decoded=decode_preamble(pre);payload=scope.binary(':WAVeform:DATA?')
                    if decoded['format']!=0 or decoded['type']!=0 or decoded['count']!=1 or len(payload)!=decoded['points']:
                        raise ValueError('Segment transfer is incomplete or averaged')
                    if not np.isclose(decoded['x_increment']*rate,1,rtol=1e-5):
                        raise ValueError('Segment waveform was decimated')
                    if abs(len(payload)*decoded['x_increment']-10*args.scale)>max(2*decoded['x_increment'],.001*10*args.scale):
                        raise ValueError('Segment does not contain the complete visible raw window')
                    arrays[f'ch{ch}']=np.frombuffer(payload,dtype=np.uint8)
                    meta['channels'][str(ch)]=dict(preamble=pre,points=len(payload),physical_channel=ch,
                                                   voltage_encoding='keysight_byte',native_sample_interval_verified=True)
                stem=f'single_{exported:04d}'
                np.savez_compressed(scope.directory/f'{stem}.npz',**arrays)
                (scope.directory/f'{stem}.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
                exported+=1
            if int(scope.query(':OPERegister:CONDition?'))&8:raise ValueError('Scope restarted during segment export')
            scope.errors()
            summary['bursts'].append(dict(id=burst_id,segments=count,first_export_index=first_index,
                                         first_tag_s=tags[0],last_tag_s=tags[-1],
                                         time_tags_s=tags,acquisition_wall_s=acquisition_wall,
                                         host_started_utc=start,native_sample_rate=rate,handoff_read_retries=handoff))
            summary['fresh_single_acquisitions']=exported
            print(json.dumps(dict(utc=utc(),exported_triggered_segments=exported,requested=args.count,
                                  burst_acquisition_wall_s=round(acquisition_wall,4),
                                  elapsed_wall_s=round(time.monotonic()-began,2))),flush=True)
        scope.write(':ACQuire:MODE RTIMe')
        summary['native_sample_rates']=[burst['native_sample_rate'] for burst in summary['bursts']]
        summary['status']='acquired'
        scope.write(':RUN')
    except Exception as error:
        summary.update(status='error',error=str(error))
        try:scope.device.clear();scope.write(':STOP')
        except Exception:pass
        raise
    finally:
        summary.update(finished_utc=utc(),elapsed_wall_s=time.monotonic()-began)
        (scope.directory/'acquisition.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        scope.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--resource',default=RESOURCE)
    p.add_argument('--reference-channel',type=int,default=1)
    p.add_argument('--observed-channel',type=int,default=3)
    p.add_argument('--count',type=int,default=1000)
    p.add_argument('--segments-per-burst',type=int,default=200)
    p.add_argument('--window',type=float,default=0,help='Compatibility argument; no fixed waiting window is used')
    p.add_argument('--scale',type=float,default=2e-7)
    p.add_argument('--case-id');p.add_argument('--label');p.add_argument('--board',choices=('A','B','C'))
    p.add_argument('--node',type=int)
    p.add_argument('--kind',choices=('module','instrument_calibration'),default='module')
    acquire(p.parse_args())


if __name__=='__main__':main()
