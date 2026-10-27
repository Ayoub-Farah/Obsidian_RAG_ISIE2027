"""Check actual three-board captures against physical-ring invariants."""
from pathlib import Path
from collections import defaultdict
import argparse, csv, hashlib, json, math
from decode_physical import read_page, decode_page


def verify(folder):
    metadata=json.loads((folder/'campaign.json').read_text())
    if metadata.get('source')!='hardware_jtag' or not metadata.get('completed'):
        raise ValueError('A completed hardware_jtag capture is required')
    rows=[];events=[];pages=[];hashes={}
    for path in sorted(folder.rglob('*_page_*.json')):
        page=read_page(path)
        if page.get('source')!='hardware_jtag' or not page.get('double_read_verified'):
            raise ValueError('Expected double-read hardware pages')
        r,e,_=decode_page(page);rows+=r;events+=e
        pages.append(dict(board=page['board'],page=page['page'],generation=(page['words'][7172]&0xffffffff),
                          sealed_raw=page['words'][7178],lost_events=page['lost_events'],lost_calibration=page['lost_calibration']))
        hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    errors=[];groups=defaultdict(list)
    for r in rows:
        groups[(r['generation'],r['mode'],r['payload_bytes'],r['local_bytes'],r['hops'])].append(r)
        b='ABC'.index(r['board']);h=r['hops'];words=math.ceil((r['payload_bytes']+36)/2)
        expected_rx=h if r['mode']=='RAG' else 1
        expected_relay=h-1 if r['mode']=='RAG' else int(b!=0)
        label=f"generation={r['generation']} board={r['board']} trial={r['trial']}"
        expected=dict(rx_frames=expected_rx,relay_frames=expected_relay,tx_words=(expected_relay+int(r['mode']=='RAG' or b==0))*words,rx_words=expected_rx*words)
        if not r['valid'] or r['crc_errors'] or r['pattern_errors']:errors.append(label+': integrity failure')
        should_inject=r['mode']=='RAG' or b==0
        if (r['first_tx_raw'] is not None)!=should_inject:errors.append(label+': missing/unexpected local injection')
        for field,value in expected.items():
            if r[field]!=value:errors.append(f'{label}: {field}={r[field]}, expected {value}')
        if r['mode']=='RAG' and (r['retired_hops']!=h or r['retired_origin']!=(b-h)%3):
            errors.append(label+': incorrect physical retirement')
        if r['fifo_highwater']>8192:errors.append(label+': FIFO exceeded capacity')
    statistics=[]
    for key,rs in sorted(groups.items()):
        generation,mode,p,s,h=key
        for b in 'ABC':
            br=[r for r in rs if r['board']==b];expected=(br[0]['repetitions'] or len(br)) if br else None
            if not br or len(br)!=expected or sorted(r['trial'] for r in br)!=list(range(expected)):
                errors.append(f'generation={generation} board={b}: missing/duplicate trial summaries')
        bytrial=defaultdict(list)
        for r in rs:bytrial[(r['run'],r['trial'])].append(r)
        for trial,tr in bytrial.items():
            if len({r['skipped_deadlines_cumulative'] for r in tr})!=1:
                errors.append(f'generation={generation} trial={trial}: boards disagree on skipped deadlines')
        rr=[r['ct_rtt_us'] for r in rs if r['ct_rtt_us'] is not None]
        local=[r['local_packet_duration_us'] for r in rs if r['local_packet_duration_us'] is not None]
        statistics.append(dict(generation=generation,mode=mode,payload_bytes=p,local_bytes=s,hops=h,summary_rows=len(rs),
                               invalid_rows=sum(not r['valid'] for r in rs),ct_rtt_us_min=min(rr) if rr else None,
                               ct_rtt_us_max=max(rr) if rr else None,ct_rtt_us_mean=sum(rr)/len(rr) if rr else None,
                               local_rag_duration_us_min=min(local) if local else None,local_rag_duration_us_max=max(local) if local else None,
                               tx_stall_ticks=sum(r['tx_stall_ticks'] for r in rs),
                               skipped_deadlines_max=max(r['skipped_deadlines_cumulative'] for r in rs),
                               rx_frames_per_board={b:sorted({r['rx_frames'] for r in rs if r['board']==b}) for b in 'ABC'}))
    for c in metadata.get('configurations') or []:
        if not any(key[0]==c['generation'] for key in groups):errors.append(f"Missing configuration generation={c['generation']}")
    # Only compare raw timestamps from the SAME board, including cut-through.
    indexed={(e['generation'],e['run'],e['trial'],e['board'],e['origin'],e['hop'],e['kind']):e for e in events}
    pairs=[]
    for k,e in indexed.items():
        if e['kind']!=3:continue
        last=indexed.get((*k[:-1],6))
        if last:pairs.append(dict(generation=e['generation'],board=e['board'],trial=e['trial'],origin=e['origin'],hop=e['hop'],
                                  tx_first_raw=e['raw'],rx_last_raw=last['raw'],cut_through=e['raw']<last['raw']))
    for key,rs in groups.items():
        generation,mode,p,_,_=key
        if mode=='CT':
            for r in rs:
                if r['board']=='A':continue
                matches=[q for q in pairs if q['generation']==generation and q['board']==r['board'] and q['trial']==r['trial']]
                initial_stalls=r['tx_stall_ticks']-r['own_tx_stall_ticks']-r['relay_tx_stall_ticks']
                for q in matches:q['first_beat_stall_ticks']=initial_stalls
                if not matches or (not all(q['cut_through'] for q in matches) and initial_stalls==0):
                    errors.append(f"CT cut-through not proved with available output: generation={generation} board={r['board']} trial={r['trial']}")
    pauses=[]
    for b in 'ABC':
        stamps=[p['sealed_raw'] for p in sorted(pages,key=lambda p:p['page']) if p['board']==b]
        if any(y<=x for x,y in zip(stamps,stamps[1:])):errors.append(f'Nonmonotonic raw page timestamps on {b}')
        board_pages=sorted([p for p in pages if p['board']==b],key=lambda p:p['page'])
        for previous,current in zip(board_pages,board_pages[1:]):
            before=[r for r in rows if r['board']==b and r['page']==previous['page']]
            after=[r for r in rows if r['board']==b and r['page']==current['page']]
            if not before or not after:continue
            last=max(before,key=lambda r:r['trial']);first=min(after,key=lambda r:r['trial'])
            if (last['generation'],last['run'])!=(first['generation'],first['run']) or first['trial']!=last['trial']+1:continue
            resume=first['launch_raw'];sealed=previous['sealed_raw']
            if resume is None or resume<=sealed:errors.append(f'Invalid continuation timestamps on {b}');continue
            pauses.append(dict(board=b,generation=first['generation'],run=first['run'],from_page=previous['page'],to_page=current['page'],
                               page_seal_raw=sealed,next_launch_raw=resume,ticks=resume-sealed,duration_us=(resume-sealed)*.016,
                               scope='page seal to next launch; includes collection, ACK, synchronization and rearming'))
    return dict(schema='physical_hardware_verification_v1',source='hardware_jtag',passed=not errors,errors=errors,
                bitstream_sha256=metadata['bitstream_sha256'],summary_rows=len(rows),configurations=statistics,
                cut_through_pairs=pairs,pages=pages,collection_pauses=pauses,input_sha256=hashes,
                interboard_timing='Unavailable without external directional calibration; no cross-board raw subtraction used')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=verify(a.capture);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    pause_csv=a.output.with_name(a.output.stem+'_collection_pauses.csv')
    with pause_csv.open('w',newline='',encoding='utf-8') as f:
        fields=['board','generation','run','from_page','to_page','page_seal_raw','next_launch_raw','ticks','duration_us','scope']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(report['collection_pauses'])
    print(json.dumps({k:v for k,v in report.items() if k not in ('input_sha256','cut_through_pairs','pages')},indent=2))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
