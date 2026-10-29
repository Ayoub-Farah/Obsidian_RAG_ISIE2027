"""Plot idealized CT/RAG total transmission time from the three-board bench.

No FPGA, JTAG or network access. Curves are predictions, not hardware data.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import argparse,csv,hashlib,json,math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]


def parameters():
    source=ROOT/'reports/hardware_validation'
    files=[source/n for n in ('model.json','events.json','results.csv','ila/verification.json')]
    model=json.loads(files[0].read_text(encoding='utf-8'))
    events=json.loads(files[1].read_text(encoding='utf-8'))
    with files[2].open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    ila=json.loads(files[3].read_text(encoding='utf-8'))
    if model['data_sources']!=['hardware_jtag'] or not ila['passed']:
        raise ValueError('Accepted bench/ILA evidence required')
    tau=round(model['serialization_fit']['ns_per_word'],9)
    a={f['channel']:f for f in ila['frames'] if f['board']=='A'}
    first_wave=(a['left_rx']['first_raw']-a['right_tx']['first_raw'])*tau
    relay_by_board=model['relay_minimum_ns']
    if len(set(relay_by_board.values()))!=1:
        raise ValueError('This homogeneous extrapolation requires equal observed relay minima')
    relay=float(relay_by_board['A'])
    # Only the sum of the three effective links is inferred. Equal links are
    # a modeling assumption, not three independently calibrated measurements.
    link=(first_wave-relay_by_board['B']-relay_by_board['C'])/3
    if link<=0:raise ValueError('Nonpositive inferred equivalent-link delay')
    rag={(int(r['generation']),int(r['run'])) for r in rows if r['mode']=='RAG'}
    groups=defaultdict(list)
    for e in events:
        if (e['generation'],e['run']) in rag and e['kind'] in (1,2,3,4):
            groups[(e['generation'],e['run'],e['trial'],e['board'])].append(e)
    gaps=[]
    for es in groups.values():
        last=None
        for e in sorted(es,key=lambda x:x['raw']):
            if e['kind'] in (2,4):last=e['raw']
            elif last is not None:
                if e['raw']>last:gaps.append(e['raw']-last)
                last=None
    if not gaps:raise ValueError('No same-transmitter frame-turnaround observations')
    return dict(tick_ns=tau,ct_first_wave_loop_ns=first_wave,relay_minimum_ns=relay,
                equivalent_link_ns=link,tx_last_to_next_first_ticks=min(gaps),
                input_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def calculate(n,local_bytes,p):
    tau=p['tick_ns'];link=p['equivalent_link_ns'];relay=p['relay_minimum_ns']
    ct_payload=n*local_bytes;rag_payload=local_bytes
    wc=math.ceil((ct_payload+36)/2);wr=math.ceil((rag_payload+36)/2)
    sc=(wc-1)*tau;sr=(wr-1)*tau
    # The transmitter is locked through its last accepted word. The measured
    # last-to-next-first interval includes the natural cycle plus idle bubbles.
    service=sr+p['tx_last_to_next_first_ticks']*tau
    wave=link+relay;step=max(service,wave)
    redistribution=(sc+(n-1)*link+(n-2)*relay)/1000
    reinjection=p.get('ct_redistribution_delay_ns',0)/1000
    collection=(sc+n*link+(n-1)*relay)/1000
    rag_total=(sr+link+(n-1)*step)/1000
    return dict(source='theoretical_model',modules=n,physical_bench_modules=3,full_rtt_hops=n,
                ct_collection_hops=n,ct_redistribution_hops=n-1,ct_total_hops=2*n-1,
                local_bytes=local_bytes,ct_payload_bytes=ct_payload,rag_payload_bytes=rag_payload,
                simultaneous_rag_packets=n,ct_words=wc,rag_words=wr,
                ct_serialization_us=sc/1000,rag_serialization_us=sr/1000,
                rag_transmitter_service_us=service/1000,rag_wave_step_us=wave/1000,
                rag_service_penalty_per_relay_us=max(0,service-wave)/1000,
                ct_rtt_us=collection,ct_collection_us=collection,
                ct_redistribution_us=redistribution,ct_redistribution_delay_us=reinjection,
                ct_total_time_us=collection+reinjection+redistribution,
                rag_rtt_us=rag_total,rag_total_time_us=rag_total)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-bytes',type=int,default=10)
    parser.add_argument('--min-modules',type=int,default=2)
    parser.add_argument('--max-modules',type=int,default=30)
    parser.add_argument('--ct-redistribution-delay-ns',type=float,default=0,
                        help='Unmeasured module-1 reinjection delay; nominal default assumes immediate retransmission')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'reports/theoretical_rtt_10bytes')
    a=parser.parse_args()
    if not 2<=a.min_modules<=a.max_modules or a.local_bytes<1 or a.max_modules*a.local_bytes>4096:
        parser.error('Require 2 <= min <= max, positive local bytes, and CT payload <= 4096 bytes')
    if not math.isfinite(a.ct_redistribution_delay_ns) or a.ct_redistribution_delay_ns<0:
        parser.error('CT redistribution delay must be finite and nonnegative')
    p=parameters();p['ct_redistribution_delay_ns']=a.ct_redistribution_delay_ns
    rows=[calculate(n,a.local_bytes,p) for n in range(a.min_modules,a.max_modules+1)]
    # N=3 must reconstruct the observed CT first-wave decomposition exactly.
    anchor=calculate(3,a.local_bytes,p)
    assert math.isclose((anchor['ct_rtt_us']-anchor['ct_serialization_us'])*1000,p['ct_first_wave_loop_ns'],abs_tol=1e-9)
    assert all(r['full_rtt_hops']==r['modules'] and r['ct_payload_bytes']==r['modules']*a.local_bytes for r in rows)
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    with (out/'rtt_vs_modules.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    metadata=dict(schema='theoretical_ring_total_time_v2',source='theoretical_model',local_bytes=a.local_bytes,
                  module_range=[a.min_modules,a.max_modules],parameters=p,
                  equations=dict(words='ceil((payload_bytes + 36) / 2)',serialization='(words - 1) * tick_ns',
                                 CT_collection='S_CT(N) + N*link + (N-1)*relay',
                                 CT_redistribution='S_CT(N) + (N-1)*link + (N-2)*relay',
                                 CT_total='CT_collection + reinjection_delay + CT_redistribution',
                                 RAG='S_RAG + link + (N-1)*max(link+relay, S_RAG+turnaround)'),
                  assumptions=['CT gathers through N hops back to module 1, then sends the complete table through N-1 hops to module N.',
                               'CT redistribution starts only after the entire first frame has returned; serialization is counted once per phase.',
                               'Redistribution relays are cut-through and reuse the observed relay-latency floor as an assumption.',
                               'The new CT dissemination phase is not hardware-timed in the source captures.',
                               'Module-1 reinjection delay is unmeasured; zero by default is an immediate-retransmission assumption.',
                               'RAG remains a full return to origin: H=N.',
                               'CT payload = N*local_bytes; every RAG payload = local_bytes.',
                               'N identical modules, N synchronous RAG injections, equal effective links.',
                               'Equivalent link delay is inferred from a three-link loop, not calibrated per link.',
                               'Fixed frame ownership and deterministic service-time contention are included.',
                               'No additional clock-compensation pauses, random jitter or unrelated traffic.',
                               'Serialization overlaps across cut-through hops; it is not counted N times for CT.',
                               'No hardware measurements at the plotted module counts are asserted.'])
    (out/'model_assumptions.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    plt.rcParams.update({'font.size':11,'axes.titlesize':17,'axes.labelsize':12})
    fig,ax=plt.subplots(figsize=(10.8,6.5))
    fig.subplots_adjust(left=.11,right=.97,top=.97,bottom=.13)
    ns=[r['modules'] for r in rows]
    ax.plot(ns,[r['ct_total_time_us'] for r in rows],color='#245eaa',marker='o',markersize=4,linewidth=2.2,label='CT')
    ax.plot(ns,[r['rag_total_time_us'] for r in rows],color='#ce4f26',marker='s',markersize=4,linewidth=2.2,linestyle='--',label='RAG')
    ax.set(xlabel='Number of modules, N',ylabel='Total transmission time (µs)',xlim=(a.min_modules-.4,a.max_modules+.4),ylim=(0,None))
    ticks=sorted({a.min_modules,a.max_modules,*range(a.min_modules,a.max_modules+1,2)})
    ax.set_xticks(ticks);ax.grid(alpha=.23);ax.legend(loc='upper left',fontsize=13,framealpha=.95)
    for ext in ('png','pdf','svg'):fig.savefig(out/f'rtt_vs_modules.{ext}',dpi=220)
    plt.close(fig)
    print(json.dumps(dict(output=str(out),parameters={k:v for k,v in p.items() if k!='input_sha256'},
                          endpoints=[rows[0],rows[-1]]),indent=2))


if __name__=='__main__':main()
