"""Export simultaneous RTL truth samples for later physical/model comparisons."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


FIELDS = ('version sample_index sim_time_ps capacity nodes board local_slot node_id '
          'parent_board parent_local_slot hops physical_hops internal_hops '
          'logical_q48_16 anchor_logical_q48_16 truth_error_q48_16 '
          'adjacent_truth_error_q48_16 correction_q48_16 estimated_theta_q48_16 '
          'estimated_delay_q48_16 accepted_age_ticks accepted_count rejected_count '
          'dropped_count running locked holdover error drift_ppb logical_step_q32_32 '
          'jitter_mask seed asymmetry phase_ps').split()
HEX_FIELDS = set(FIELDS[13:24]) | {'logical_step_q32_32'}
SIGNED_FIELDS = {'truth_error_q48_16', 'adjacent_truth_error_q48_16',
                 'correction_q48_16', 'estimated_theta_q48_16', 'estimated_delay_q48_16'}


def signed64(value):
    return value - (1 << 64) if value & (1 << 63) else value


def parse_samples(text):
    rows = []
    for line in text.splitlines():
        if 'PTP_CAP_HEADER,' in line:
            header = line.split('PTP_CAP_HEADER,', 1)[1].strip().split(',')
            if header != FIELDS:
                raise ValueError('Unsupported capacity sample header')
        if 'PTP_CAP_CSV,' not in line:
            continue
        fields = line.split('PTP_CAP_CSV,', 1)[1].strip().split(',')
        if len(fields) != len(FIELDS):
            raise ValueError('Incomplete capacity sample')
        row = {name: int(value, 16 if name in HEX_FIELDS else 10)
               for name, value in zip(FIELDS, fields)}
        if any(not 0 <= row[name] < 1 << 64 for name in HEX_FIELDS):
            raise ValueError('Hexadecimal payload exceeds its unsigned 64-bit representation')
        if any(row[name] not in (0, 1) for name in ('running', 'locked', 'holdover', 'error', 'asymmetry')):
            raise ValueError('Invalid state flag')
        if row['version'] != 1 or not 3 <= row['nodes'] <= 3 * row['capacity']:
            raise ValueError('Invalid capacity or sample version')
        if not 0 <= row['node_id'] < row['nodes'] or not 0 <= row['board'] < 3:
            raise ValueError('Invalid node ownership')
        if row['hops'] != row['node_id'] or row['physical_hops'] + row['internal_hops'] != row['hops']:
            raise ValueError('Inconsistent hop decomposition')
        if row['physical_hops'] != row['board']:
            raise ValueError('Physical hops differ from the instantiated A/B/C chain')
        counts = [row['nodes'] // 3 + (b < row['nodes'] % 3) for b in range(3)]
        first = sum(counts[:row['board']])
        if not 0 <= row['local_slot'] < counts[row['board']] or first + row['local_slot'] != row['node_id']:
            raise ValueError('Ownership differs from the physical board partition')
        expected = (row['logical_q48_16'] - row['anchor_logical_q48_16']) & ((1 << 64) - 1)
        if expected != row['truth_error_q48_16']:
            raise ValueError('Truth error does not match simultaneous logical times')
        for name in SIGNED_FIELDS:
            row[name] = signed64(row[name])
            row[name.replace('_q48_16', '_ns')] = row[name] * 16 / 65536
        row['time_ns'] = row['sim_time_ps'] / 1000
        row['valid_for_steady_state'] = int(row['running'] == row['locked'] == 1
                                          and row['holdover'] == row['error'] == 0)
        rows.append(row)
    if not rows:
        raise ValueError('No PTP_CAP_CSV truth samples found')
    configurations = {(r['capacity'], r['nodes'], r['jitter_mask'],
                       r['seed']-r['board'], r['asymmetry']) for r in rows}
    if len(configurations) != 1:
        raise ValueError('Use one simulation case per dataset')
    for node in {row['node_id'] for row in rows}:
        settings = {(r['drift_ppb'], r['logical_step_q32_32'], r['phase_ps'], r['seed'])
                    for r in rows if r['node_id'] == node}
        if len(settings) != 1:
            raise ValueError('Node configuration changes within the sampled run')
    samples = {}
    for row in rows:
        sample = samples.setdefault(row['sample_index'], {})
        if row['node_id'] in sample:
            raise ValueError('Duplicate node/sample')
        sample[row['node_id']] = row
    previous = -1
    for _, sample in sorted(samples.items()):
        if set(sample) != set(range(rows[0]['nodes'])):
            raise ValueError('A simultaneous sample is missing nodes')
        times = {r['sim_time_ps'] for r in sample.values()}
        if len(times) != 1 or next(iter(times)) <= previous:
            raise ValueError('Samples must be simultaneous and increase in time')
        previous = next(iter(times))
        for node, row in sample.items():
            parent = sample[node - 1] if node else row
            if node and (row['parent_board'], row['parent_local_slot']) != (parent['board'], parent['local_slot']):
                raise ValueError('Incorrect parent ownership')
            adjacent = signed64((row['logical_q48_16'] - parent['logical_q48_16']) & ((1 << 64) - 1))
            if adjacent != row['adjacent_truth_error_q48_16']:
                raise ValueError('Incorrect adjacent truth error')
    return rows


def metrics(values):
    if not values:
        return None
    return dict(samples=len(values), mean_ns=statistics.fmean(values),
                sampled_sigma_ns=statistics.pstdev(values),
                sampled_rms_ns=math.sqrt(statistics.fmean(x*x for x in values)),
                sampled_max_abs_ns=max(map(abs, values)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = parse_samples(args.log.read_text(errors='replace'))
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output/'samples.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    by_node = {}
    for node in sorted({r['node_id'] for r in rows}):
        series = [r for r in rows if r['node_id'] == node]
        by_node[str(node)] = dict(board=series[0]['board'], local_slot=series[0]['local_slot'],
                                 hops=series[0]['hops'], physical_hops=series[0]['physical_hops'],
                                 internal_hops=series[0]['internal_hops'],
                                 drift_ppb=series[0]['drift_ppb'], seed=series[0]['seed'],
                                 phase_ps=series[0]['phase_ps'],
                                 all_samples=metrics([r['truth_error_ns'] for r in series]),
                                 locked_samples=metrics([r['truth_error_ns'] for r in series if r['valid_for_steady_state']]),
                                 excluded_samples=sum(not r['valid_for_steady_state'] for r in series))
    report = dict(schema='ptp_capacity_truth_v1', source='rtl_simulation',
                  source_log_sha256=hashlib.sha256(args.log.read_bytes()).hexdigest(),
                  capacity=rows[0]['capacity'], nodes=rows[0]['nodes'], by_node=by_node,
                  physical_clock_domains=3, hardware_validation=False, extrapolation_performed=False,
                  note='Finite RTL samples; shared oscillator within each board. No physical stability or extrapolation claim.')
    (args.output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(capacity=report['capacity'], nodes=report['nodes'], samples=len(rows))))


if __name__ == '__main__':
    main()
