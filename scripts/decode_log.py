#!/usr/bin/env python3
"""Decode actual benchmark VIO journal dumps into CSV without cross-board subtraction."""
from pathlib import Path
import argparse,csv,json,re,sys
MODES={0:'RAG_C',1:'AGG_C',2:'RAG_D',3:'AGG_D2',4:'AGG_D2_PIPE'}
MISSING=(1<<64)-1
FIELDS=['run_id','git_commit','bitstream_id','tool_version','board_id','mode','N','D','R','line_rate',
        'mapping','virtual_model_id','cycle_id','log_sequence','t0_method','t0_raw_ticks','T_useful_us',
        'T_drained_us','T_return_us','first_tx_delay_ns','Delta_launch_ns','sync_interval','fifo_highwater',
        'crc_errors_cumulative','capture_overflow','protocol_overflow','deadline_miss','sync_error',
        'sync_locked','link_lost','flags_hex','period_ticks','status','measurement_uncertainty_ns','source']

def bits(value,lo,size):return (value>>lo)&((1<<size)-1)
def time_value(value,scale):return '' if value==MISSING else f'{value*scale:.9g}'

def decode_dump(dump, metadata=None, tick_ns=16.0):
    metadata=metadata or {}
    records=dump.get('raw_records_hex')
    if not isinstance(records,list):raise ValueError('Missing raw_records_hex list')
    rows=[];skipped=0
    for record in records:
        h=str(record).removeprefix('0x')
        if len(h)!=128 or not re.fullmatch('[0-9a-fA-F]{128}',h):skipped+=1;continue
        value=int(h,16);sequence=bits(value,448,32)
        if sequence==0:skipped+=1;continue
        mode=bits(value,416,32);flags=bits(value,320,32)
        if mode not in MODES:raise ValueError(f'Invalid mode {mode} in sequence {sequence}')
        useful=bits(value,96,64);drained=bits(value,160,64);tx=bits(value,224,64)
        row={key:metadata.get(key,'') for key in FIELDS}
        row.update(board_id=dump.get('board_id',metadata.get('board_id','')),mode=MODES[mode],N=bits(value,400,16),
                   tool_version=dump.get('vivado',metadata.get('tool_version','')),
                   mapping=f"base={bits(value,368,16)},local={bits(value,384,16)}",
                   cycle_id=bits(value,0,32),log_sequence=sequence,t0_method='local_raw_counter',
                   t0_raw_ticks=bits(value,32,64),T_useful_us=time_value(useful,tick_ns/1000),
                   T_drained_us=time_value(drained,tick_ns/1000),
                   T_return_us=time_value(tx,tick_ns/1000) if flags&256 else '',
                   first_tx_delay_ns='' if flags&256 else time_value(tx,tick_ns),
                   # A per-board journal cannot establish global launch skew.
                   Delta_launch_ns='',fifo_highwater=bits(value,352,16),crc_errors_cumulative=bits(value,288,32),
                   capture_overflow=int(bool(flags&2)),deadline_miss=int(bool(flags&4)),
                   sync_error=int(bool(flags&8)),sync_locked=int(bool(flags&16)),
                   link_lost=int(bool(flags&64)),protocol_overflow=int(bool(flags&128)),
                   flags_hex=f'{flags:08x}',period_ticks=bits(value,480,32),
                   status='failed' if flags&0xef or useful==MISSING or drained==MISSING else 'ok',
                   source=dump.get('source','unspecified'))
        rows.append(row)
    rows.sort(key=lambda r:r['log_sequence'])
    return rows,skipped

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('dumps',nargs='+',type=Path);p.add_argument('--metadata',type=Path)
    p.add_argument('--output','-o',type=Path,required=True)
    p.add_argument('--tick-ns',type=float,default=16.0)
    a=p.parse_args()
    if a.tick_ns<=0:p.error('--tick-ns must be positive')
    metadata=json.loads(a.metadata.read_text()) if a.metadata else {}
    rows=[]
    for path in a.dumps:
        decoded,skipped=decode_dump(json.loads(path.read_text()),metadata,a.tick_ns)
        rows.extend(decoded);print(f'{path.name}: {len(decoded)} records, {skipped} unused/nonhex entries',file=sys.stderr)
    if not rows:p.error('No valid journal records; CSV not written')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    print(a.output)
if __name__=='__main__':main()
