"""Calibrate, plot and identify a cut-through timing model from actual captures."""
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,json,math,sys
import numpy as np
from decode_physical import map_stamp

def calibrate(events,bias=None,min_samples=8):
    """Midpoint regression of accepted four-timestamp exchanges, in A ticks.

    Offset/asymmetry are not identifiable separately: no certified mapping is
    returned without the external directional calibration and its uncertainty.
    """
    bykey={};accepted=set()
    for e in events:
        if e.get('collision'):continue
        if e['kind']==0x15:accepted.add((e['board'],e['sequence']))
        key=(e['board'],e['peer'],e['sequence'],e['kind'],bool(e['tx']))
        if key in bykey and bykey[key]['raw']!=e['raw']:raise ValueError('Reset or ambiguous PTP sequence; split captures by boot')
        bykey[key]=e
    ar=[e['raw'] for e in events if e['board']=='A']
    if not ar:raise ValueError('No A synchronization events')
    anchor=min(ar);mappings=[dict(board='A',raw_ref=anchor,master_ref_ticks=0.,slope=1.,valid_from_raw=min(ar),valid_to_raw=max(ar),uncertainty_ns=0.)]
    quality=[];certified=bool(bias and bias.get('status')=='measured' and bias.get('provenance'))
    for parent,child in [('A','B'),('B','C')]:
        pi='ABC'.index(parent);ci='ABC'.index(child);pm=mappings[-1];points=[]
        for board,seq in sorted(accepted):
            if board!=child:continue
            keys=[(parent,ci,seq,0x10,True),(child,pi,seq,0x10,False),(child,pi,seq,0x12,True),(parent,ci,seq,0x12,False)]
            if not all(k in bykey for k in keys):continue
            t1,t2,t3,t4=[bykey[k]['raw'] for k in keys]
            if not pm['valid_from_raw']<=t1<=t4<=pm['valid_to_raw']:continue
            y=((t1+t4)/2-pm['raw_ref'])*pm['slope']+pm['master_ref_ticks']
            points.append(((t2+t3)/2,y,t1,t2,t3,t4))
        if len(points)<min_samples:raise ValueError(f'{parent}->{child}: only {len(points)} complete accepted exchanges, need {min_samples}')
        external=(bias or {}).get('links',{}).get(parent+child,{})
        asym=external.get('forward_minus_reverse_ns');unc=external.get('uncertainty_ns')
        if asym is None or unc is None or not math.isfinite(asym) or not math.isfinite(unc) or unc<0:
            certified=False;asym=0.;unc=None
        xref=int(min(p[0] for p in points));x=np.array([p[0]-xref for p in points]);y=np.array([p[1]+asym/32 for p in points])
        if np.ptp(x)==0:raise ValueError('No time baseline for frequency calibration')
        design=np.column_stack([x,np.ones_like(x)]);slope,intercept=np.linalg.lstsq(design,y,rcond=None)[0]
        if slope<=0 or not np.isfinite(slope):raise ValueError('Invalid calibrated clock slope')
        residual=y-(slope*x+intercept);residual_ns=float(np.max(np.abs(residual))*16)
        uncertainty=None if unc is None or pm['uncertainty_ns'] is None else pm['uncertainty_ns']+unc/2+residual_ns+16
        m=dict(board=child,raw_ref=xref,master_ref_ticks=float(intercept),slope=float(slope),
               valid_from_raw=math.ceil(min(p[0] for p in points)),valid_to_raw=math.floor(max(p[0] for p in points)),uncertainty_ns=uncertainty)
        mappings.append(m);quality.append(dict(link=parent+child,samples=len(points),max_residual_ns=residual_ns,
            directional_asymmetry_ns=asym if unc is not None else None,external_uncertainty_ns=unc))
    result=dict(schema='physical_time_map_v1',status='calibrated' if certified else 'uncalibrated_symmetry_assumption',
                reference='A raw ticks; nominal tick = 16 ns',mappings=mappings,quality=quality,
                extrapolation=False,quantization_budget_ns=16,
                identifiability='External forward/reverse asymmetry is required; PTP alone cannot determine it.')
    result['calibration_id']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()[:16]
    return result

def plot(rows,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    panels=[('ct_rtt_us','CT round trip (µs)'),('tx_span_us','Local injection TX span (µs)'),('launch_wait_us','Injection wait (µs)')]
    if any(r.get('packet_duration_us') not in ('',None) for r in rows):panels.append(('packet_duration_us','Calibrated RAG packet duration (µs)'))
    fig,axes=plt.subplots(1,len(panels),figsize=(4.3*len(panels),4),layout='constrained')
    sources=sorted({r.get('source','unknown') for r in rows})
    fig.suptitle('RTL simulation — no hardware measurements' if sources==['rtl_simulation'] else 'Sources: '+', '.join(sources),fontsize=11)
    for mode in ('CT','RAG'):
        for b in 'ABC':
            rs=[r for r in rows if r['mode']==mode and r['board']==b and str(r['valid']).lower() in ('true','1')]
            for ax,(field,label) in zip(axes,panels):
                pts=[(int(r['payload_bytes']),float(r[field])) for r in rs if r.get(field) not in ('',None)]
                if pts:ax.scatter(*zip(*pts),label=f'{mode} {b}',s=20)
                ax.set(xlabel='Payload bytes',ylabel=label);ax.grid(alpha=.3)
    for ax in axes:
        handles,_=ax.get_legend_handles_labels()
        if handles:ax.legend(fontsize=8)
        else:ax.text(.5,.5,'No valid observations',ha='center',transform=ax.transAxes)
    fig.savefig(output,dpi=180);plt.close(fig)

def identify(rows,events,calibration):
    serialization=[];relay=[];links=[];byevent={}
    configurations={(int(r['generation']),int(r['run']),int(r['trial'])):r for r in rows if str(r['valid']).lower() in ('true','1')}
    for r in rows:
        if str(r['valid']).lower() not in ('true','1') or r.get('tx_span_us') in ('',None):continue
        words=math.ceil((int(r['payload_bytes'])+36)/2)
        pause=int(r['own_tx_stall_ticks']);span=float(r['tx_span_us'])*1000
        serialization.append(dict(board=r['board'],words=words,span_ns=span,ready_pause_ns=pause*16,
                                  unpaused_span_ns=span-pause*16,expected_unpaused_span_ns=(words-1)*16))
    for e in events:
        if e.get('run') is None:continue
        if (int(e['generation']),int(e['run']),int(e['trial'])) not in configurations:continue
        k=(e['generation'],e['run'],e['trial'],e['origin'],e['hop'],e['board'],e['kind'])
        if k in byevent:raise ValueError('Duplicate trace event; split input runs/boots')
        byevent[k]=e
    for key,e in byevent.items():
        generation,run,trial,origin,hop,board,kind=key
        if e['bad']:continue
        if kind==3:
            first=byevent.get((generation,run,trial,origin,hop,board,5))
            if first and not first['bad']:relay.append(dict(board=board,hop=hop,rx_to_tx_ns=(e['raw']-first['raw'])*16))
        if kind in (1,3):
            nextboard='ABC'[('ABC'.index(board)+1)%3]
            first=byevent.get((generation,run,trial,origin,hop+1,nextboard,5))
            if first and not first['bad']:
                a=map_stamp(calibration,board,e['raw']);b=map_stamp(calibration,nextboard,first['raw'])
                if a and b:links.append(dict(link=board+nextboard,delay_ns=(b[0]-a[0])*16,uncertainty_ns=a[1]+b[1]))
    result=dict(schema='physical_cut_through_model_v1',source='observations_only',data_sources=sorted({r.get('source','unknown') for r in rows}),
        serialization_observations=serialization,relay_observations=relay,link_observations=links,
        serialization_fit=None,relay_minimum_ns={},effective_link_delay_ns={},
        composition='CT first-wave link delays + local RX-first to TX-first relay delays + final RX-first to RX-last span; never sum all per-hop frame serializations.',
        propagation_identifiability='Effective link includes fiber, Aurora and PHY. Fiber-only propagation requires independent PHY calibration or varying known fiber lengths.',
        simulation_targets=['centralized CT','decentralized simultaneous injection with physical-hop budget'])
    if len({v['words'] for v in serialization})>=2:
        x=np.array([v['words']-1 for v in serialization]);y=np.array([v['unpaused_span_ns'] for v in serialization])
        fit=np.polyfit(x,y,1);residual=y-np.polyval(fit,x)
        result['serialization_fit']=dict(ns_per_word=float(fit[0]),intercept_ns=float(fit[1]),max_residual_ns=float(np.max(np.abs(residual))))
    for b in 'ABC':
        values=[v['rx_to_tx_ns'] for v in relay if v['board']==b]
        if values:result['relay_minimum_ns'][b]=min(values)
    for link in ('AB','BC','CA'):
        values=[v['delay_ns'] for v in links if v['link']==link]
        if values:result['effective_link_delay_ns'][link]=dict(median=float(np.median(values)),samples=len(values),spread=float(np.ptp(values)))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('calibrate');c.add_argument('sync',nargs='+',type=Path);c.add_argument('--bias-calibration',type=Path);c.add_argument('--min-samples',type=int,default=8);c.add_argument('--output',type=Path,required=True)
    for name in ('plot','fit-model'):
        q=sub.add_parser(name);q.add_argument('csv',type=Path);q.add_argument('--output',type=Path,required=True)
        if name=='fit-model':q.add_argument('--events',type=Path);q.add_argument('--calibration',type=Path)
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.action=='calibrate':
        events=[]
        for path in a.sync:events+=json.loads(path.read_text())
        bias=json.loads(a.bias_calibration.read_text()) if a.bias_calibration else None
        result=calibrate(events,bias,a.min_samples);a.output.write_text(json.dumps(result,indent=2)+'\n')
    else:
        with a.csv.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
        if a.action=='plot':plot(rows,a.output)
        else:
            events=json.loads(a.events.read_text()) if a.events else []
            calibration=json.loads(a.calibration.read_text()) if a.calibration else None
            a.output.write_text(json.dumps(identify(rows,events,calibration),indent=2)+'\n')
if __name__=='__main__':main()
