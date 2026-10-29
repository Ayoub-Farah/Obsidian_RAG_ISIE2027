"""Offline reports from marked PTP scope cases; never opens VISA or JTAG.

Only single_*.npz acquisitions contribute to official statistics. Persistence
waveforms and instrument-native measurements are kept as separate diagnostics.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import zipfile

import numpy as np

try:
    from .ptp_scope_analysis import (decode_preamble, decode_waveform, paired_delays,
                                     rising_edges, waveform_quality)
except ImportError:
    from ptp_scope_analysis import (decode_preamble, decode_waveform, paired_delays,
                                    rising_edges, waveform_quality)


def _safe(value):
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _write_json(path, value):
    path.write_text(json.dumps(_safe(value), indent=2, allow_nan=False)+'\n', encoding='utf-8')


def _stats(values):
    if not values:
        return None
    return dict(count=len(values), mean_s=statistics.fmean(values),
                sample_sd_s=statistics.stdev(values) if len(values)>1 else None,
                min_s=min(values), max_s=max(values),
                rms_s=math.sqrt(statistics.fmean(value*value for value in values)))


def validate_native(data):
    """Validate native delay statistics independently of waveform validity."""
    if not isinstance(data, dict):
        return dict(status='missing', statistics_valid=False, current_valid=False,
                    errors=['No instrument_delay_s dictionary'], raw=data)
    values, valid, errors = {}, {}, []
    for key in ('CURRent', 'AVERages', 'DEViation', 'MINimum', 'MAXimum', 'CNT'):
        try:
            value = float(data[key])
            good = math.isfinite(value)
            if key == 'CNT':
                good = good and value>=2 and value==int(value)
            else:
                good = good and abs(value)<1e-6
                if key == 'DEViation':good = good and value>=0
        except (ValueError, TypeError, KeyError, OverflowError):
            value, good = None, False
        values[key], valid[key] = value, bool(good)
        if not good:errors.append(f'Invalid native {key}')
    consistent = all(valid[key] for key in ('AVERages', 'MINimum', 'MAXimum'))
    if consistent:
        consistent = values['MINimum'] <= values['AVERages'] <= values['MAXimum']
        if not consistent:errors.append('Native minimum/mean/maximum are inconsistent')
    statistics_valid = bool(consistent and valid['DEViation'] and valid['CNT'])
    return dict(status='passed' if statistics_valid and valid['CURRent'] else 'partial' if statistics_valid else 'invalid',
                statistics_valid=statistics_valid, current_valid=valid['CURRent'],
                fields_valid=valid, errors=errors, values=values, raw=data,
                note='Native statistics may cover a different acquisition window; 0.5 ns display quantization and sentinels are not waveform precision evidence.')


def _analyze_acquisition(path, expected_period, max_delta, threshold):
    result = dict(acquisition=path.name, status='failed', errors=[])
    try:
        metadata_path = path.with_suffix('.json')
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        if not isinstance(metadata,dict):raise ValueError('Acquisition metadata must be an object')
        result.update(utc=metadata.get('utc'), npz_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest())
        if metadata.get('trigger_state', 'STOP') != 'STOP':
            raise ValueError('Paired waveforms were not recorded in a common stopped acquisition')
        channels, traces, quality, edges = {}, {}, {}, {}
        result.update(channels=channels,quality=quality)
        with np.load(path, allow_pickle=False) as archive:
            for channel in ('1', '2'):
                samples = archive['ch'+channel]
                if samples.dtype != np.uint8 or samples.ndim != 1:
                    raise ValueError(f'Channel {channel} is not a one-dimensional BYTE waveform')
                entry = metadata['channels'][channel]
                preamble = decode_preamble(entry['preamble'])
                if entry.get('points', len(samples)) != len(samples):
                    raise ValueError(f'Channel {channel} metadata POINTS differs from payload')
                payload = samples.tobytes()
                quality[channel] = waveform_quality(payload)
                if quality[channel]['possible_clipping']:
                    raise ValueError(f'Channel {channel} contains ADC rail codes (0 or 255)')
                traces[channel] = decode_waveform(payload, preamble)
                edges[channel] = rising_edges(*traces[channel], threshold_v=threshold)
                if edges[channel]['amplitude_v']<=0.5:
                    raise ValueError(f'Channel {channel} amplitude must exceed 0.5 V')
                channels[channel] = dict(preamble=preamble, points=len(samples))
        result.update(channels=channels, quality=quality)
        for field in ('points', 'x_increment', 'x_origin', 'x_reference'):
            if channels['1']['preamble'][field] != channels['2']['preamble'][field]:
                raise ValueError(f'Channel timing field {field} differs between paired waveforms')
        period = expected_period if all(edges[ch]['edge_count']>=2 for ch in ('1','2')) else None
        pair = paired_delays(*traces['1'], *traces['2'], max_delta=max_delta,
                             expected_period_s=period, threshold_v=threshold)
        result.update(status='passed', pairing=pair, paired_edge_stats=_stats(pair['delays_s']),
                      signed_mean_s=pair['mean_s'], period_expected_s=expected_period,
                      period_verified=pair['expected_period_verified'])
    except (ValueError, TypeError, KeyError, OSError, OverflowError, EOFError, zipfile.BadZipFile) as error:
        result['errors'].append(str(error))
    return result


def analyze_case(marker, *, expected_period_s=1e-4, max_delta_s=1e-6, threshold_v=None):
    directory = marker.parent
    report = dict(schema='ptp_scope_case_v1', directory=str(directory.resolve()),
                  status='failed', complete=False, errors=[], acquisitions=[], paired_samples=[])
    try:
        metadata = json.loads(marker.read_text(encoding='utf-8'))
        for key in ('id', 'label', 'board', 'observer_node', 'kind'):
            if key not in metadata:raise ValueError(f'Missing case field {key}')
        if not isinstance(metadata['id'], str) or not metadata['id'] or not isinstance(metadata['label'], str) or not metadata['label']:
            raise ValueError('Case id and label must be nonempty strings')
        if metadata['board'] not in ('A','B','C') or metadata['kind'] not in ('module','instrument_calibration'):
            raise ValueError('Invalid case board or kind')
        if 'path_identity_verified' in metadata and type(metadata['path_identity_verified']) is not bool:
            raise ValueError('path_identity_verified must be an explicit JSON boolean')
        node = metadata['observer_node']
        if not (type(node) is int and node>=0 or metadata['kind']=='instrument_calibration' and node is None):
            raise ValueError('observer_node must be a zero-based RTL integer (or null for common-net calibration)')
        report['case'] = metadata
        expected_period = metadata.get('expected_period_s', expected_period_s)
        if expected_period is not None and (type(expected_period) not in (int,float) or not math.isfinite(expected_period) or expected_period<=0):
            raise ValueError('Invalid case expected_period_s')
        paths = sorted(directory.glob('single_*.npz'))
        if not paths:raise ValueError('No official single_*.npz acquisitions found')
        timestamps = set()
        for path in paths:
            record = _analyze_acquisition(path, expected_period, max_delta_s, threshold_v)
            stamp = record.get('utc')
            if stamp and stamp in timestamps:
                record.update(status='failed')
                record['errors'].append('Duplicate acquisition UTC; independent acquisition identity is ambiguous')
            if stamp:timestamps.add(stamp)
            report['acquisitions'].append(record)
            if record['status']=='passed':
                for index, pair in enumerate(record['pairing']['pairs']):
                    report['paired_samples'].append(dict(acquisition=path.name, edge_index=index, **pair))
            else:report['errors'].append(f'{path.name}: '+ '; '.join(record['errors']))
        valid = [record for record in report['acquisitions'] if record['status']=='passed']
        report.update(acquisition_count=len(paths), valid_acquisition_count=len(valid),
                      invalid_acquisition_count=len(paths)-len(valid), paired_edge_count=len(report['paired_samples']),
                      raw=dict(acquisition_mean_stats=_stats([record['signed_mean_s'] for record in valid]),
                               paired_edge_stats=_stats([row['delay_s'] for row in report['paired_samples']])),
                      complete=len(valid)==len(paths))
        report['status'] = 'passed' if report['complete'] else 'partial' if valid else 'failed'
    except (ValueError, TypeError, KeyError, OSError) as error:
        report['errors'].append(str(error))
    acquisition_file = directory/'acquisition.json'
    try:
        acquisition = json.loads(acquisition_file.read_text(encoding='utf-8'))
        if not isinstance(acquisition,dict):raise ValueError('Collector acquisition metadata must be an object')
        report['instrument_native'] = validate_native(acquisition.get('instrument_delay_s'))
        report['capture_settings'] = acquisition.get('settings', {})
        report['collector_fresh_single_acquisitions'] = acquisition.get('fresh_single_acquisitions')
        declared=acquisition.get('fresh_single_acquisitions')
        provenance_error=None
        if declared is not None and declared!=report.get('acquisition_count'):
            provenance_error=f'Collector declared {declared} fresh acquisitions; found {report.get("acquisition_count",0)} records'
        if acquisition.get('status','acquired')!='acquired':
            provenance_error='Collector did not mark acquisition complete'
        if provenance_error:
            report.update(status='partial' if report.get('valid_acquisition_count',0) else 'failed',complete=False)
            report['errors'].append(provenance_error)
    except (ValueError, TypeError, OSError) as error:
        report['instrument_native'] = dict(status='missing', statistics_valid=False, current_valid=False, errors=[str(error)])
    persistence = directory/'persistence_last_pair.npz'
    if persistence.is_file():
        report['persistence_diagnostic'] = _analyze_acquisition(persistence, expected_period_s, max_delta_s, threshold_v)
        report['persistence_diagnostic']['official_statistics'] = False
    report['notes'] = [
        'Only single_*.npz records contribute to official statistics; persistence is diagnostic.',
        'One saved fresh-single record is one acquisition; multiple edge pairs within it are not extra independent acquisitions.',
        'Freshness provenance comes from the collector and saved metadata, not from deduplicating similar quantized waveforms.',
        'Fine single-edge records cannot verify pulse period or absolute PTP epoch identity.',
        'Sub-sample linear interpolation is not evidence of picosecond timing accuracy.',
    ]
    return report


def _apply_corrections(cases):
    baselines = {}
    for baseline in ('A_M1', 'A_same_sync'):
        found = [case for case in cases if case.get('case',{}).get('id')==baseline]
        good = len(found)==1 and found[0]['status']=='passed' and found[0].get('raw',{}).get('acquisition_mean_stats') is not None
        if good:
            item = found[0]
            expected_kind = 'module' if baseline=='A_M1' else 'instrument_calibration'
            good = item['case']['board']=='A' and item['case']['kind']==expected_kind
            if baseline=='A_M1':good = good and item['case']['observer_node']==0
        baselines[baseline] = found[0] if good else None
    for case in cases:
        case['corrections'] = {}
        if case.get('case',{}).get('kind')!='module' or not case.get('raw',{}).get('acquisition_mean_stats'):
            continue
        raw = case['raw']['acquisition_mean_stats']
        for key, baseline in (('relative_to_A_M1','A_M1'),('instrument_corrected','A_same_sync')):
            source = baselines[baseline]
            if source is None:
                case['corrections'][key] = dict(available=False, baseline_id=baseline,
                    reason='Missing, incomplete, duplicated or incorrectly labelled baseline')
                continue
            offset = source['raw']['acquisition_mean_stats']['mean_s']
            verified=source['case'].get('path_identity_verified') is True if baseline=='A_M1' else True
            case['corrections'][key] = dict(available=True, baseline_id=baseline,
                baseline_mean_s=offset, mean_s=raw['mean_s']-offset, sample_sd_s=raw['sample_sd_s'],
                baseline_acquisition_count=source['valid_acquisition_count'],
                provisional=not verified,
                qualification=('A_M1 path identity not physically verified' if not verified else
                               'Operator-declared baseline; this subtraction alone does not establish true PTP clock error'),
                meaning=('Relative to the A M1 REF/OBS output-path baseline; B/C results include transfer of GPIO/PCB paths.'
                         if baseline=='A_M1' else 'Common-SYNC instrument/probe bias removed; GPIO/PCB differences remain.'),
                note='Constant mean subtraction only. No variance-floor subtraction or implied intrinsic jitter/precision.')
    return {name:dict(available=case is not None,
                     path_identity_verified=case['case'].get('path_identity_verified') is True if case and name=='A_M1' else None,
                     mean_s=case['raw']['acquisition_mean_stats']['mean_s'] if case else None)
            for name,case in baselines.items()}


def _csvs(directory, cases):
    columns = ('id label board observer_node kind status complete acquisition_count valid_acquisition_count '
               'invalid_acquisition_count paired_edge_count mean_delay_ns sample_sd_acquisition_means_ns '
               'paired_edge_mean_ns sample_sd_edges_ns relative_A_M1_mean_ns instrument_corrected_mean_ns '
               'relative_A_M1_provisional native_statistics_valid native_current_valid errors').split()
    with (directory/'summary.csv').open('w', newline='', encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for case in cases:
            row={key:case.get('case',{}).get(key) for key in columns[:5]}
            row.update({key:case.get(key) for key in columns[5:11]})
            for source,prefix in (('acquisition_mean_stats',''),('paired_edge_stats','paired_edge_')):
                stats=case.get('raw',{}).get(source)
                row['mean_delay_ns' if not prefix else 'paired_edge_mean_ns']=stats['mean_s']*1e9 if stats else None
                row['sample_sd_acquisition_means_ns' if not prefix else 'sample_sd_edges_ns']=stats['sample_sd_s']*1e9 if stats and stats['sample_sd_s'] is not None else None
            for key,column in (('relative_to_A_M1','relative_A_M1_mean_ns'),('instrument_corrected','instrument_corrected_mean_ns')):
                item=case.get('corrections',{}).get(key,{})
                row[column]=item['mean_s']*1e9 if item.get('available') else None
            row['relative_A_M1_provisional']=case.get('corrections',{}).get('relative_to_A_M1',{}).get('provisional')
            native=case['instrument_native'];row.update(native_statistics_valid=native['statistics_valid'],native_current_valid=native['current_valid'],errors='; '.join(case['errors']))
            writer.writerow(row)
    for case in cases:
        with (Path(case['directory'])/'acquisition_delays.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=['acquisition','utc','status','paired_edges','mean_ns','sample_sd_edges_ns','period_verified','errors']);writer.writeheader()
            for item in case['acquisitions']:
                stats=item.get('paired_edge_stats');writer.writerow(dict(acquisition=item['acquisition'],utc=item.get('utc'),status=item['status'],
                    paired_edges=stats['count'] if stats else 0,mean_ns=stats['mean_s']*1e9 if stats else None,
                    sample_sd_edges_ns=stats['sample_sd_s']*1e9 if stats and stats['sample_sd_s'] is not None else None,
                    period_verified=item.get('period_verified',False),errors='; '.join(item['errors'])))


def _plot(directory, cases):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    valid=[case for case in cases if case.get('raw',{}).get('acquisition_mean_stats')]
    fig,axes=plt.subplots(1,3,figsize=(15,4.8))
    for index,case in enumerate(valid):
        color=plt.get_cmap('tab10')(index%10);label=case['case']['label'];stats=case['raw']['acquisition_mean_stats']
        if stats['sample_sd_s'] is not None:
            axes[0].errorbar(index,stats['mean_s']*1e9,yerr=stats['sample_sd_s']*1e9,fmt='o',capsize=4,color=color)
        else:axes[0].plot(index,stats['mean_s']*1e9,'o',color=color)
        records=[item for item in case['acquisitions'] if item['status']=='passed']
        axes[1].plot(range(1,len(records)+1),[r['signed_mean_s']*1e9 for r in records],'.-',lw=.8,color=color,label=label)
        values=[row['delay_s']*1e9 for row in case['paired_samples']]
        axes[2].hist(values,bins=min(30,max(3,int(math.sqrt(len(values))))),histtype='step',lw=1.3,color=color,
                     label=f'{label} (Nacq={len(records)}, Nedge={len(values)})')
    axes[0].set_xticks(range(len(valid)),[case['case']['label'] for case in valid],rotation=40,ha='right')
    axes[0].set(title='Mean ± sample SD of acquisition means',ylabel='Raw OBS − REF delay (ns)')
    axes[1].set(title='Fresh-single acquisition means',xlabel='Acquisition within condition',ylabel='Raw OBS − REF delay (ns)')
    axes[2].set(title='Paired edges, not independent acquisition count',xlabel='Raw OBS − REF delay (ns)',ylabel='Paired rising edges')
    if valid:axes[2].legend(fontsize=7)
    else:
        for axis in axes:axis.text(.5,.5,'No valid official acquisitions',ha='center',transform=axis.transAxes)
    for axis in axes:axis.grid(alpha=.2)
    fig.suptitle('Offline raw paired-edge timing — no modulo or variance-floor correction',fontsize=12)
    fig.tight_layout();fig.savefig(directory/'delaytrace_histogram.png',dpi=170);plt.close(fig)


def build_report(directory, output=None, *, expected_period_s=1e-4, max_delta_s=1e-6,
                 threshold_v=None, make_plots=True):
    directory=Path(directory).resolve();output=Path(output).resolve() if output else directory
    output.mkdir(parents=True,exist_ok=True)
    markers=sorted(directory.rglob('case.json'))
    cases=[analyze_case(marker,expected_period_s=expected_period_s,max_delta_s=max_delta_s,threshold_v=threshold_v) for marker in markers]
    ids=[case.get('case',{}).get('id') for case in cases]
    for case in cases:
        identifier=case.get('case',{}).get('id')
        if identifier and ids.count(identifier)>1:
            case.update(status='failed',complete=False);case['errors'].append('Duplicate case id')
    calibrations=_apply_corrections(cases)
    for case in cases:_write_json(Path(case['directory'])/'analysis.json',case)
    errors=[] if cases else ['No case.json files discovered; no official dataset was analyzed']
    passed=sum(case['status']=='passed' for case in cases)
    report=dict(schema='ptp_scope_report_v1',generated_at_utc=datetime.now(timezone.utc).isoformat(),directory=str(directory),
                status='passed' if cases and passed==len(cases) else 'partial' if passed else 'failed',
                complete=bool(cases and passed==len(cases)),errors=errors,cases=cases,calibrations=calibrations,
                expected_period_s=expected_period_s,max_delta_s=max_delta_s,threshold_v=threshold_v,
                notes=['Raw statistics use only fresh single_*.npz records; persistence/native statistics are separate.',
                       'Acquisition count differs from paired-edge count; standard deviations are sample SD, not standard error.',
                       'No variance-floor subtraction, PTP epoch proof, or picosecond-accuracy inference is performed.'])
    _csvs(output,cases)
    if make_plots:
        try:_plot(output,cases)
        except (ImportError,ValueError,OSError) as error:
            report.update(status='partial' if passed else 'failed',complete=False);report['errors'].append('Plot generation failed: '+str(error))
    _write_json(output/'analysis.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--expected-period-s',type=float,default=1e-4)
    parser.add_argument('--max-delta-s',type=float,default=1e-6)
    parser.add_argument('--threshold-v',type=float)
    args=parser.parse_args()
    result=build_report(args.directory,args.output,expected_period_s=args.expected_period_s,max_delta_s=args.max_delta_s,threshold_v=args.threshold_v)
    print(json.dumps(dict(status=result['status'],complete=result['complete'],cases=len(result['cases']),errors=result['errors'])))
    return 0 if result['complete'] else 1


if __name__=='__main__':
    raise SystemExit(main())
