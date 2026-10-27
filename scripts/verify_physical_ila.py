"""Verify CT bytes, CRC and cut-through in actual Aurora-boundary ILA captures."""
from pathlib import Path
import argparse,csv,hashlib,json,sys,zlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from physical_codec import Config,encode,relay
from decode_physical import read_page,decode_page


def frames(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        raw_key=next(k for k in reader.fieldnames if 'raw_1' in k)
        streams_key=next(k for k in reader.fieldnames if 'streams' in k)
        state={};result=[]
        for sample in reader:
            try:raw=int(sample[raw_key],16);bus=int(sample[streams_key],16)
            except (ValueError,TypeError):continue  # Vivado radix descriptor row.
            for name,offset,tx in [('left_tx',0,True),('right_tx',24,True),('left_rx',48,False),('right_rx',72,False)]:
                block=(bus>>offset)&0xffffff
                if not(block&(1<<5)) or (tx and not(block&(1<<3))):continue
                word=block>>8;keep=(block>>6)&3;last=bool(block&(1<<4))
                if name not in state:
                    if word not in (0xc35a,0xd3a7):continue  # Initial partial frame.
                    state[name]=dict(channel=name,first_raw=raw,data=bytearray())
                frame=state[name]
                if keep&2:frame['data'].append(word>>8)
                if keep&1:frame['data'].append(word&255)
                if last:
                    frame['last_raw']=raw;frame['data']=bytes(frame['data']);result.append(frame);del state[name]
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('ila',type=Path);p.add_argument('--campaign',type=Path,required=True);p.add_argument('--generation',type=int);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();meta=json.loads((a.campaign/'campaign.json').read_text())
    if meta.get('source')!='hardware_jtag' or not meta.get('completed'):raise ValueError('Completed hardware campaign required')
    configs=[c for c in meta['configurations'] if a.generation is None or c['generation']==a.generation]
    if len(configs)!=1:raise ValueError('Select exactly one CT configuration with --generation')
    config=Config.from_dict(configs[0])
    if config.mode!=1:raise ValueError('CT configuration required')
    rows=[]
    for page in a.campaign.rglob('*_page_*.json'):rows+=decode_page(read_page(page))[0]
    observed={};checks=[];errors=[];hashes={};captured={};sync_seen=0
    for board in 'ABC':
        path=a.ila/f'{board}_ila.csv';hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        captured[board]=frames(path)
        data=[f for f in captured[board] if f['data'][:3]==b'\xc3\x5a\x02']
        for channel in ('right_tx','left_rx'):
            candidates=[f for f in data if f['channel']==channel]
            if len(candidates)!=1:raise ValueError(f'{board} {channel}: expected one complete DATA frame, got {len(candidates)}')
            frame=candidates[0];packet=frame['data'];run=int.from_bytes(packet[8:12],'big');trial=int.from_bytes(packet[12:16],'big')
            expected=encode(config,run,trial,0)
            if board=='A' and channel=='left_rx' or board=='C' and channel=='right_tx':
                expected=relay(relay(expected,config,1)[0],config,2)[0]
            elif board=='B' and channel=='right_tx' or board=='C' and channel=='left_rx':
                expected=relay(expected,config,1)[0]
            crc=zlib.crc32(packet[:-4])==int.from_bytes(packet[-4:],'little')
            exact=packet==expected
            if not crc or not exact:errors.append(f'{board} {channel}: CRC or exact contribution bytes mismatch')
            checks.append(dict(board=board,channel=channel,bytes=len(packet),run=run,trial=trial,crc_valid=crc,exact_expected_bytes=exact,first_raw=frame['first_raw'],last_raw=frame['last_raw']))
            observed[(board,channel)]=frame
    if len({(f['run'],f['trial']) for f in checks})!=1:
        errors.append('ILA boards did not capture the same CT packet identity')
    for board in 'BC':
        tx=observed[(board,'right_tx')];rx=observed[(board,'left_rx')]
        if tx['first_raw']>=rx['last_raw']:errors.append(board+': relay did not start before last RX')
    for board in 'ABC':
        start=observed[(board,'right_tx' if board=='A' else 'left_rx')]['first_raw']
        end=observed[(board,'left_rx' if board=='A' else 'right_tx')]['last_raw']
        for frame in captured[board]:
            if frame['data'][:3]!=b'\xc3\x5a\x01':continue
            sync_seen+=1
            if frame['first_raw']<=end and frame['last_raw']>=start:
                errors.append(board+': synchronization overlaps the observed DATA transfer')
    first=observed[('A','right_tx')];last=observed[('A','left_rx')]
    packet=first['data'];run=int.from_bytes(packet[8:12],'big');trial=int.from_bytes(packet[12:16],'big')
    r=next(r for r in rows if r['generation']==config.generation and r['board']=='A' and r['run']==run and r['trial']==trial)
    rtt=last['last_raw']-first['first_raw']
    if rtt!=r['ct_rtt_ticks'] or first['first_raw']!=r['first_tx_raw'] or last['last_raw']!=r['last_retired_rx_raw']:
        errors.append('ILA accepted-boundary timestamps disagree with journal RTT')
    result=dict(schema='physical_ila_verification_v1',source='hardware_jtag',passed=not errors,errors=errors,frames=checks,ct_rtt_ticks=rtt,ct_rtt_us=rtt*.016,input_sha256=hashes,
                cross_board_raw_subtraction=False,sync_frames_seen=sync_seen,
                synchronization_overlap_check='No SYNC frame overlaps each board DATA interval within this acquisition')
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
