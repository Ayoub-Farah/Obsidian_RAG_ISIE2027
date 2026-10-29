"""Export independent RTL samples or explicitly epoch-paired oscilloscope data.

Scope CSV: node_id (zero based), epoch_index, reference_ns, observed_ns.
The epoch index must come from a checked pairing procedure; nearest-edge
matching without missing-cycle detection is deliberately not performed.
"""
from pathlib import Path
import argparse
import csv
import json
import math
import re
import statistics


def signed64(v):
    return v-(1 << 64) if v & (1 << 63) else v


def metrics(values):
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError('A nonempty finite series is required')
    return dict(samples=len(values), mean_ns=statistics.fmean(values), sigma_ns=statistics.pstdev(values),
                rms_ns=math.sqrt(statistics.fmean(v*v for v in values)), min_ns=min(values), max_ns=max(values),
                peak_to_peak_ns=max(values)-min(values), maximum_absolute_sample_ns=max(map(abs, values)),
                fraction_above_20ns=sum(abs(v)>20 for v in values)/len(values))


def simulation_rows(text):
    rows = []
    for match in re.finditer(r'PTP_CSV,(\d+),(\d+),([0-9A-Fa-f]+),([0-9A-Fa-f]+),([0-9A-Fa-f]+),([0-9A-Fa-f]+),([0-9A-Fa-f]+)', text):
        tick, node, logical, error, correction, theta, delay = match.groups()
        rows.append(dict(source='rtl_simulation', node_id=int(node), sample_tick=int(tick),
                         time_ns=int(tick)*16, logical_q48_16=int(logical,16),
                         error_ns=signed64(int(error,16))*16/65536,
                         cumulative_correction_ns=signed64(int(correction,16))*16/65536,
                         estimated_offset_ns=signed64(int(theta,16))*16/65536,
                         estimated_delay_ns=signed64(int(delay,16))*16/65536))
    if not rows:
        raise ValueError('No independent RTL samples found')
    return rows


def scope_rows(rows, instrument_delay_ns):
    result, seen = [], set()
    for row in rows:
        node, epoch = int(row['node_id']), int(row['epoch_index'])
        key = node, epoch
        if key in seen or node < 1 or epoch < 0:
            raise ValueError('Duplicate/invalid node or epoch; pairing must be checked')
        seen.add(key)
        ref, obs = float(row['reference_ns']), float(row['observed_ns'])
        if not all(math.isfinite(v) for v in (ref, obs, instrument_delay_ns)):
            raise ValueError('Non-finite scope sample')
        delta = obs-ref
        result.append(dict(source='oscilloscope_paired_epochs', node_id=node, epoch_index=epoch,
                           time_ns=ref, raw_delta_ns=delta, calibrated_delta_ns=delta-instrument_delay_ns))
    if not result:
        raise ValueError('No scope samples')
    return result


def summarize(rows, field):
    result = {}
    for node in sorted({r['node_id'] for r in rows}):
        series = sorted((r for r in rows if r['node_id']==node), key=lambda r:r['time_ns'])
        result[str(node)] = metrics([r[field] for r in series])
        result[str(node)].update(duration_ns=series[-1]['time_ns']-series[0]['time_ns'],
                                 first_time_above_20ns=next((r['time_ns'] for r in series if abs(r[field])>20), None))
        if field == 'calibrated_delta_ns':
            indices = [r['epoch_index'] for r in series]
            if any(b<=a for a,b in zip(indices, indices[1:])):
                raise ValueError('Epoch indices do not increase with reference time')
            result[str(node)]['missing_epochs_between_samples'] = indices[-1]-indices[0]+1-len(indices)
            result[str(node)]['raw'] = metrics([r['raw_delta_ns'] for r in series])
    return result


def decode_page(page):
    if page.get('schema') != 'ptp_emulation_page_v1' or not page.get('double_read_verified'):
        raise ValueError('A verified PTP page is required')
    w = [int(v,16) for v in page['snapshot_words']]
    if len(w)<8 or w[0] != 0x5054504500010001:
        raise ValueError('Snapshot signature mismatch')
    nodes, first = (w[4]>>16)&65535, w[4]&65535
    count = w[6]&0xffffffff
    if count<1 or len(w)!=8+16*count or first+count>nodes:
        raise ValueError('Snapshot population mismatch')
    rows = []
    for i in range(count):
        v = w[8+16*i:24+16*i]
        rows.append(dict(source='hardware_local_snapshot', run_id=w[2], config_id=f'{w[1]:016x}',
                         node_id=first+i, parent_id=first+i-1 if first+i else None,
                         raw_tick=w[3], logical_q48_16=v[0], cumulative_correction_q48_16=signed64(v[1]),
                         estimated_offset_q48_16=signed64(v[2]), estimated_delay_q48_16=signed64(v[3]),
                         accepted_age_ticks=v[4], accepted=v[5]>>32, rejected=v[5]&0xffffffff,
                         deferred_ticks=v[6]>>32, skipped_epochs=v[6]&0xffffffff, epoch_index=v[7],
                         running=bool(v[8]&(1<<32)), locked=bool(v[8]&(1<<33)),
                         holdover=bool(v[8]&(1<<34)), error=bool(v[8]&(1<<35)), backsteps=v[8]&0xffffffff,
                         injected_frame_drops=v[9],
                         global_clock_error_ns=None))
    events = []
    ev = [int(v,16) for v in page['event_words']]
    if len(ev)%4:
        raise ValueError('Truncated event page')
    for i in range(0,len(ev),4):
        a = sum(ev[i+j]<<(64*j) for j in range(4))
        if not (a&(1<<255)) or not (a&(1<<204)) or not first <= ((a>>188)&65535) < first+count:
            raise ValueError('Invalid event format or node ownership')
        node=(a>>188)&65535
        events.append(dict(source='hardware_jtag', run_id=w[2], config_id=f'{w[1]:016x}',
                           node_id=node, parent_id=node-1 if node else None, neighbor_id=(a>>172)&65535,
                           right_port=bool(a&(1<<171)),
                           seq_id=(a>>128)&0xffffffff, kind=(a>>160)&255, tx=bool(a&(1<<170)),
                           raw_tick=a&((1<<64)-1), logical_q48_16=(a>>64)&((1<<64)-1)))
    return rows, events


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind', choices=('simulation','scope','page'))
    p.add_argument('input', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--instrument-delay-ns', type=float, default=0)
    p.add_argument('--plot', action='store_true')
    a = p.parse_args();events = []
    if a.kind == 'simulation':
        rows = simulation_rows(a.input.read_text(errors='replace'));field='error_ns'
    elif a.kind == 'scope':
        with a.input.open(newline='') as f:
            rows = scope_rows(csv.DictReader(f), a.instrument_delay_ns)
        field='calibrated_delta_ns'
    else:
        page=json.loads(a.input.read_text())
        rows, events = decode_page(page);field=None
    a.output.mkdir(parents=True, exist_ok=True)
    with (a.output/'samples.csv').open('w', newline='', encoding='utf-8') as f:
        writer=csv.DictWriter(f, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary = dict(schema='ptp_analysis_v1', kind=a.kind, metric=field,
                   acquisition_included=False if a.kind=='simulation' else None,
                   global_hardware_clock_error_ns=None,
                   statistics=summarize(rows,field) if field else None,
                   instrument_delay_ns=a.instrument_delay_ns if a.kind=='scope' else None)
    if a.kind=='page':
        status=int(page['status'],16)
        header=[int(v,16) for v in page['snapshot_words'][:8]]
        summary['coverage']=dict(page_id=header[4]>>32, snapshot_raw_tick=header[3],
                                 missed_snapshots_at_freeze=header[5]&0xffffffff,
                                 lost_events_at_freeze=header[5]>>32,
                                 missed_snapshots_at_collection=(status>>96)&0xffffffff,
                                 lost_events_at_collection=(status>>128)&0xffffffff,
                                 retained_events=len(events), sample_period_ticks=header[7]>>32)
    (a.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    if events:
        (a.output/'events.json').write_text(json.dumps(events, indent=2)+'\n')
    if a.plot and field:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.colors import Normalize
        from matplotlib.cm import ScalarMappable
        nodes=sorted({r['node_id'] for r in rows})
        norm=Normalize(vmin=nodes[0]+1,vmax=max(nodes[-1]+1,nodes[0]+2))
        fig,ax=plt.subplots()
        for node in nodes:
            series=sorted((r for r in rows if r['node_id']==node),key=lambda r:r['time_ns'])
            ax.plot([r['time_ns']/1e6 for r in series],[r[field] for r in series],label=f'M{node+1}',color=plt.cm.viridis(norm(node+1)))
        ax.set_xlabel('Time (ms)');ax.set_ylabel(field+' (ns)')
        if len(nodes)<=12:ax.legend(ncol=3, fontsize=6)
        else:fig.colorbar(ScalarMappable(norm=norm,cmap='viridis'),ax=ax,label='Module M')
        ax.axhline(20,color='gray',linestyle=':');ax.axhline(-20,color='gray',linestyle=':')
        fig.tight_layout();fig.savefig(a.output/'series.png',dpi=160);plt.close(fig)
        stats=summary['statistics'];fig,ax=plt.subplots()
        ax.errorbar([n+1 for n in nodes],[stats[str(n)]['mean_ns'] for n in nodes],
                    yerr=[stats[str(n)]['sigma_ns'] for n in nodes],fmt='.-',label='Mean +/- sigma')
        ax.plot([n+1 for n in nodes],[stats[str(n)]['maximum_absolute_sample_ns'] for n in nodes],label='Sampled maximum |error|')
        ax.set_xlabel('Module M');ax.set_ylabel('ns');ax.legend();fig.tight_layout()
        fig.savefig(a.output/'depth.png',dpi=160);plt.close(fig)


if __name__=='__main__':
    main()
