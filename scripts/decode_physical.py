"""Decode frozen physical_v3 pages; inter-board times require calibrated maps."""
from __future__ import annotations
from pathlib import Path
import argparse,csv,json,sys,hashlib,math
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from physical_codec import Config
UNAVAILABLE=(1<<64)-1
FIELDS=['source','board','page','generation','run','trial','mode','payload_bytes','local_bytes','hops','repetitions','period_ticks',
        'local_bad','global_bad','fault','valid','retired_origin','retired_hops','launch_raw','first_tx_raw','last_tx_raw','first_retired_rx_raw','last_retired_rx_raw',
        'ct_rtt_ticks','ct_rtt_us','local_packet_duration_us','tx_span_us','launch_wait_us','tx_stall_ticks','own_tx_stall_ticks','relay_tx_stall_ticks','relay_residence_sum_ticks',
        'relay_frames','rx_frames','tx_words','rx_words','crc_errors','pattern_errors','fifo_highwater','skipped_deadlines_cumulative',
        'holdover_during_trial','sync_locked_at_drain','holdover_at_drain','trace_lost_at_summary','calibration_lost_at_summary',
        'first_tx_common_ticks','last_rx_common_ticks','launch_skew_ns','packet_duration_us','calibration_id','time_uncertainty_ns','page_trace_lost','page_calibration_lost']

def bits(value,start,width):return value>>start&((1<<width)-1)
def timestamp(value):return None if value==UNAVAILABLE else value
def read_page(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema')!='physical_v3':raise ValueError(f'{path}: wrong schema')
    words=data['words']
    if len(words)!=8192:raise ValueError(f'{path}: expected 8192 words')
    words=[int(w,16) if isinstance(w,str) else w for w in words]
    if any(not 0<=w<1<<64 for w in words):raise ValueError('Invalid journal word')
    if words[7168]!=0x5048595300030001:raise ValueError('Invalid firmware journal signature')
    ns=bits(words[7169],32,16);ne=bits(words[7170],0,32);nc=bits(words[7170],32,32)
    role=bits(words[7169],48,2)
    if ns>128 or ne>1024 or nc>256 or role>2:raise ValueError('Corrupt journal counts/role')
    board='ABC'[role]
    if data.get('board')!=board:raise ValueError('Cable/role mismatch')
    data.update(board=board,words=words,summary_count=ns,event_count=ne,calibration_count=nc,page=bits(words[7169],0,32),
                lost_events=bits(words[7171],0,32),lost_calibration=bits(words[7171],32,32))
    return data

def decode_page(page):
    words=page['words'];rows=[];events=[];cal=[]
    for i in range(page['summary_count']):
        s=sum(words[32*i+j]<<(64*j) for j in range(32));c=Config.from_register(bits(s,0,160))
        row=dict(source=page.get('source','unknown'),board=page['board'],page=page['page'],**{k:v for k,v in c.__dict__.items() if k!='mode'},
            run=bits(s,160,32),trial=bits(s,192,32),mode='CT' if c.mode==1 else 'RAG',
            local_bad=bits(s,226,1),fault=bits(s,227,1),global_bad=bits(s,228,1),retired_origin=bits(s,240,2),retired_hops=bits(s,256,16),
            launch_raw=timestamp(bits(s,272,64)),first_tx_raw=timestamp(bits(s,336,64)),last_tx_raw=timestamp(bits(s,400,64)),
            first_retired_rx_raw=timestamp(bits(s,464,64)),last_retired_rx_raw=timestamp(bits(s,528,64)),
            tx_stall_ticks=bits(s,592,64),relay_frames=bits(s,720,64),rx_frames=bits(s,784,64),tx_words=bits(s,848,64),rx_words=bits(s,912,64),
            crc_errors=bits(s,976,64),pattern_errors=bits(s,1040,64),fifo_highwater=bits(s,1104,16),skipped_deadlines_cumulative=bits(s,1184,64),
            holdover_during_trial=bits(s,1248,1),sync_locked_at_drain=bits(s,1249,1),holdover_at_drain=bits(s,1250,1),
            trace_lost_at_summary=bits(s,1536,32),calibration_lost_at_summary=bits(s,1568,32),ct_rtt_ticks=timestamp(bits(s,1664,64)),
            own_tx_stall_ticks=bits(s,1728,64),relay_tx_stall_ticks=bits(s,1792,64),launch_wait_us=bits(s,1856,64)*.016,
            relay_residence_sum_ticks=bits(s,1920,64))
        row['valid']=not(row['local_bad'] or row['global_bad'] or row['fault'])
        row['page_trace_lost']=page.get('lost_events',0);row['page_calibration_lost']=page.get('lost_calibration',0)
        row['ct_rtt_us']=None if row['ct_rtt_ticks'] is None else row['ct_rtt_ticks']*.016
        row['local_packet_duration_us']=None
        if row['mode']=='RAG' and row['retired_origin']=='ABC'.index(row['board']) and row['first_tx_raw'] is not None and row['last_retired_rx_raw'] is not None:
            row['local_packet_duration_us']=(row['last_retired_rx_raw']-row['first_tx_raw'])*.016
        row['tx_span_us']=None if row['first_tx_raw'] is None or row['last_tx_raw'] is None else (row['last_tx_raw']-row['first_tx_raw'])*.016
        if row['first_tx_raw'] is None:row['launch_wait_us']=None
        if row['mode']=='CT' and row['board']=='A' and row['first_tx_raw'] is not None and row['last_retired_rx_raw'] is not None:
            if row['ct_rtt_ticks']!=row['last_retired_rx_raw']-row['first_tx_raw']:raise ValueError('Firmware RTT disagrees with raw Aurora events')
        rows.append(row)
    for i in range(page['event_count']):
        e=words[4096+2*i]|words[4097+2*i]<<64
        events.append(dict(board=page['board'],page=page['page'],generation=Config.from_register(sum((words[7172+j]&0xffffffff)<<(32*j) for j in range(5))).generation,
            run=rows[0]['run'] if rows else None,raw=bits(e,0,64),trial=bits(e,64,32),hop=bits(e,96,16),origin=bits(e,112,2),kind=bits(e,114,4),bad=bits(e,118,1)))
    for i in range(page['calibration_count']):
        a=sum(words[6144+4*i+j]<<(64*j) for j in range(4))
        cal.append(dict(board=page['board'],raw=bits(a,0,64),logical_q16=bits(a,64,64),sequence=bits(a,128,32),kind=bits(a,160,8),peer=bits(a,168,2),
                        tx=bits(a,170,1),port=bits(a,171,1),collision=bits(a,254,1)))
    return rows,events,cal

def map_stamp(calibration,board,raw):
    if raw is None or not calibration or calibration.get('status')!='calibrated':return None
    for m in calibration.get('mappings',[]):
        if m['board']==board and m['valid_from_raw']<=raw<=m['valid_to_raw']:
            if m.get('uncertainty_ns') is None or not math.isfinite(m['uncertainty_ns']) or m['uncertainty_ns']<0:continue
            t=m['master_ref_ticks']+(raw-m['raw_ref'])*m['slope']
            return t,m['uncertainty_ns'],calibration['calibration_id']
    return None

def calibrated_metrics(rows,calibration):
    grouped={}
    for r in rows:
        key=(r['generation'],r['run'],r['trial']);grouped.setdefault(key,[]).append(r)
        a=map_stamp(calibration,r['board'],r['first_tx_raw']);z=map_stamp(calibration,r['board'],r['last_retired_rx_raw'])
        if a:r.update(first_tx_common_ticks=a[0],calibration_id=a[2],time_uncertainty_ns=a[1])
        if z:r['last_rx_common_ticks']=z[0]
    for group in grouped.values():
        byboard={r['board']:r for r in group}
        if len(byboard)!=3:continue
        if group[0]['mode']=='RAG':
            starts=[r.get('first_tx_common_ticks') for r in group]
            if all(t is not None for t in starts):
                skew=(max(starts)-min(starts))*16
                for r in group:r['launch_skew_ns']=skew
            for sink in group:
                origin=byboard['ABC'[sink['retired_origin']]]
                t0=map_stamp(calibration,origin['board'],origin['first_tx_raw']);t1=map_stamp(calibration,sink['board'],sink['last_retired_rx_raw'])
                if t0 and t1:
                    sink['packet_duration_us']=(t1[0]-t0[0])*.016
                    sink['time_uncertainty_ns']=t0[1]+t1[1]
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('pages',nargs='+',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--calibration',type=Path)
    a=p.parse_args();rows=[];events=[];cal=[];seen=set();pages=[]
    for path in a.pages:
        page=read_page(path);key=(page['board'],page['page'])
        if key in seen:raise ValueError('Duplicate board/page: '+str(key))
        seen.add(key);r,e,c=decode_page(page);rows+=r;events+=e;cal+=c
        pages.append({k:page[k] for k in ('board','page','summary_count','event_count','calibration_count','lost_events','lost_calibration')})
    calibration=json.loads(a.calibration.read_text()) if a.calibration else None
    calibrated_metrics(rows,calibration);a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    a.output.with_suffix('.events.json').write_text(json.dumps(events,indent=2)+'\n')
    a.output.with_suffix('.sync.json').write_text(json.dumps(cal,indent=2)+'\n')
    summary=dict(source='decoded_capture',rows=len(rows),invalid=sum(not r['valid'] for r in rows),pages=pages,
                 calibration='absent' if not calibration else calibration.get('status'),raw_interboard_subtraction=False,
                 input_sha256={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in a.pages})
    a.output.with_suffix('.summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
