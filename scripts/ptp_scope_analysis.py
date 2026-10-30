"""Offline BYTE-waveform decoding and conservative paired rising-edge timing.

No VISA/JTAG access. Times and delays are seconds, voltages are volts. Pairing
never wraps a delay by a pulse period or assigns an absolute PTP epoch number.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np


PREAMBLE_FIELDS = (
    'format', 'type', 'points', 'count', 'x_increment', 'x_origin',
    'x_reference', 'y_increment', 'y_origin', 'y_reference',
)


def parse_ieee_block(raw: bytes) -> bytes:
    """Read one definite-length IEEE #N block, preserving all payload bytes.

    Only an absent terminator, LF, or CRLF may follow the declared payload.
    Indefinite #0 blocks are rejected because binary LF is not a delimiter.
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('IEEE block must be bytes-like')
    raw = bytes(raw)
    if len(raw) < 2 or raw[0:1] != b'#' or not 49 <= raw[1] <= 57:
        raise ValueError('Expected a definite-length #N binary block (N=1..9)')
    digits = raw[1] - 48
    start = 2 + digits
    if len(raw) < start:
        raise ValueError('Truncated IEEE block length header')
    length_text = raw[2:start]
    if any(byte < 48 or byte > 57 for byte in length_text):
        raise ValueError('IEEE payload length is not decimal')
    end = start + int(length_text)
    if len(raw) < end:
        raise ValueError('Truncated IEEE binary payload')
    if raw[end:] not in (b'', b'\n', b'\r\n'):
        raise ValueError('Unexpected bytes after the IEEE binary payload')
    return raw[start:end]


def decode_preamble(text: str) -> dict:
    """Decode FORMAT,TYPE,POINTS,COUNT,XINC,XORIG,XREF,YINC,YORIG,YREF."""
    if not isinstance(text, str):
        raise TypeError('Waveform preamble must be text')
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    fields = text.split(',')
    if len(fields) != 10:
        raise ValueError('Waveform preamble must contain exactly ten fields')
    try:
        values = [float(value.strip()) for value in fields]
    except ValueError as error:
        raise ValueError('Non-numeric waveform preamble field') from error
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Waveform preamble contains a non-finite value')
    if any(value != int(value) for value in values[:4]):
        raise ValueError('FORMAT, TYPE, POINTS and COUNT must be integers')
    result = dict(zip(PREAMBLE_FIELDS, [int(v) for v in values[:4]] + values[4:]))
    if min(result[name] for name in PREAMBLE_FIELDS[:4]) < 0 or result['points'] == 0:
        raise ValueError('Preamble needs non-negative codes/count and positive points')
    if result['x_increment'] <= 0 or result['y_increment'] == 0:
        raise ValueError('Preamble needs positive X increment and nonzero Y increment')
    return result


def decode_waveform(payload: bytes, preamble: Mapping, *, voltage_encoding='rigol_byte') -> tuple[np.ndarray, np.ndarray]:
    """Return time_s, voltage_v for one complete unsigned BYTE waveform.

    RIGOL: V = (byte - Yorigin - Yreference) * Yincrement
    Keysight: V = (byte - Yreference) * Yincrement + Yorigin (volts)
    t = (sample_index - Xreference) * Xincrement + Xorigin

    Concatenate raw-memory chunks before calling: POINTS must match byte count.
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError('BYTE waveform must be bytes-like')
    try:
        if preamble['format'] != 0:
            raise ValueError('Only unsigned BYTE format (FORMAT=0) is supported')
        if len(payload) != preamble['points'] or not len(payload):
            raise ValueError('BYTE payload length differs from preamble POINTS')
        xinc, xorigin, xref = (float(preamble[key]) for key in PREAMBLE_FIELDS[4:7])
        yinc, yorigin, yref = (float(preamble[key]) for key in PREAMBLE_FIELDS[7:10])
    except KeyError as error:
        raise ValueError(f'Missing preamble field: {error.args[0]}') from error
    if not all(math.isfinite(v) for v in (xinc, xorigin, xref, yinc, yorigin, yref)) or xinc <= 0 or yinc == 0:
        raise ValueError('Invalid waveform scaling')
    codes = np.frombuffer(payload, dtype=np.uint8).astype(np.float64)
    if voltage_encoding == 'rigol_byte':
        voltage = (codes - yorigin - yref) * yinc
    elif voltage_encoding == 'keysight_byte':
        voltage = (codes - yref) * yinc + yorigin
    else:
        raise ValueError('Unknown BYTE voltage encoding: ' + str(voltage_encoding))
    time = (np.arange(len(codes), dtype=np.float64) - xref) * xinc + xorigin
    return time, voltage


def waveform_quality(payload: bytes) -> dict:
    """Report raw ADC rail hits; these suggest clipping but do not prove it.

    Flat high/low digital plateaus alone are not classified as clipping.
    """
    codes = np.frombuffer(payload, dtype=np.uint8)
    if not len(codes):
        raise ValueError('Empty waveform')
    low, high = int(np.count_nonzero(codes == 0)), int(np.count_nonzero(codes == 255))
    return dict(samples=len(codes), adc_min=int(codes.min()), adc_max=int(codes.max()),
                low_rail_samples=low, high_rail_samples=high,
                rail_fraction=(low + high) / len(codes), possible_clipping=bool(low or high),
                note='Rail hits require checking vertical range; flat digital plateaus alone are not clipping evidence.')


def _trace(time, voltage) -> tuple[np.ndarray, np.ndarray]:
    t, v = np.asarray(time, dtype=np.float64), np.asarray(voltage, dtype=np.float64)
    if t.ndim != 1 or v.ndim != 1 or len(t) != len(v) or len(t) < 3:
        raise ValueError('Time/voltage must be equal one-dimensional arrays of at least three samples')
    if not np.isfinite(t).all() or not np.isfinite(v).all() or not np.all(np.diff(t) > 0):
        raise ValueError('Trace must be finite with strictly increasing time')
    return t, v


def rising_edges(time, voltage, *, min_amplitude_v: float = 0.5,
                 threshold_v: float | None = None) -> dict:
    """Find complete rising crossings, using seeded median levels and hysteresis.

    P99.8 retains the high plateau of the 1 us / 100 us PTP pulse; P90 would
    mistake it for baseline. It also works for a fine view with 50% high level.
    Their midpoint seeds a low/high partition; medians of each plateau then
    remove percentile-tail noise bias from the actual crossing threshold.
    A crossing is accepted only after low->mid->high (30/50/70% amplitude), and
    its midpoint time is linearly interpolated between surrounding samples.
    """
    t, v = _trace(time, voltage)
    if not math.isfinite(min_amplitude_v) or min_amplitude_v <= 0:
        raise ValueError('Minimum amplitude must be positive and finite')
    seed_low, seed_high = (float(x) for x in np.percentile(v, (10, 99.8)))
    seed = (seed_low + seed_high) / 2
    if seed_high - seed_low < min_amplitude_v:
        raise ValueError(f'Signal amplitude {seed_high-seed_low:g} V is below {min_amplitude_v:g} V')
    low, high = float(np.median(v[v <= seed])), float(np.median(v[v > seed]))
    amplitude = high - low
    if amplitude < min_amplitude_v:
        raise ValueError(f'Plateau amplitude {amplitude:g} V is below {min_amplitude_v:g} V')
    threshold = (low + high) / 2 if threshold_v is None else float(threshold_v)
    lower, upper = threshold - 0.2 * amplitude, threshold + 0.2 * amplitude
    if not math.isfinite(threshold) or not low < lower < threshold < upper < high:
        raise ValueError('Threshold/hysteresis must lie inside measured low/high levels')
    armed = bool(v[0] <= lower)
    candidate = None
    edges = []
    for index in range(1, len(t)):
        if v[index] <= lower:
            armed, candidate = True, None
        elif armed:
            if candidate is None and v[index - 1] < threshold <= v[index]:
                fraction = (threshold - v[index - 1]) / (v[index] - v[index - 1])
                candidate = float(t[index - 1] + fraction * (t[index] - t[index - 1]))
            if candidate is not None and v[index] >= upper:
                edges.append(candidate)
                armed, candidate = False, None
    if not edges:
        raise ValueError('No complete rising edge found')
    return dict(edges_s=edges, edge_count=len(edges), samples=len(t), low_v=low, high_v=high,
                amplitude_v=amplitude, threshold_v=threshold,
                hysteresis_low_v=lower, hysteresis_high_v=upper,
                level_seed_v=seed, level_method='P10/P99.8 seed followed by low/high plateau medians')


def _period(edges: np.ndarray, sample_interval: float, tolerance: float, label: str):
    if len(edges) < 2:
        return None
    intervals = np.diff(edges)
    period = float(np.median(intervals))
    if period <= 0 or np.max(np.abs(intervals - period)) > max(period * tolerance, 2 * sample_interval):
        raise ValueError(f'{label} has irregular periods or missing/extra rising edges')
    return period


def paired_delays(t1, v1, t2, v2, max_delta: float = 1e-6, *,
                  expected_period_s: float | None = None, period_tolerance: float = 0.005,
                  min_amplitude_v: float = 0.5, threshold_v: float | None = None) -> dict:
    """Pair nearest unique edges within max_delta; signed delay is t2 - t1.

    No modulo operation is performed. Inconsistent periods, ambiguous epochs,
    and unmatched interior edges are errors. Unmatched window-boundary edges
    are reported. A fine single-edge capture can pair but cannot verify period;
    request expected_period_s only for records containing at least two edges.
    """
    a_t, a_v = _trace(t1, v1)
    b_t, b_v = _trace(t2, v2)
    if not math.isfinite(max_delta) or max_delta <= 0:
        raise ValueError('max_delta must be positive and finite')
    if not math.isfinite(period_tolerance) or not 0 < period_tolerance < 0.5:
        raise ValueError('Period tolerance must be between zero and 0.5')
    if expected_period_s is not None and (not math.isfinite(expected_period_s) or expected_period_s <= 0):
        raise ValueError('Expected period must be positive and finite')
    first = rising_edges(a_t, a_v, min_amplitude_v=min_amplitude_v, threshold_v=threshold_v)
    second = rising_edges(b_t, b_v, min_amplitude_v=min_amplitude_v, threshold_v=threshold_v)
    e1, e2 = np.asarray(first['edges_s']), np.asarray(second['edges_s'])
    interval = float(max(np.max(np.diff(a_t)), np.max(np.diff(b_t))))
    p1, p2 = _period(e1, interval, period_tolerance, 'Reference'), _period(e2, interval, period_tolerance, 'Observed')
    periods = [p for p in (p1, p2) if p is not None]
    if len(periods) == 2 and abs(p1 - p2) > max(max(periods) * period_tolerance, 2 * interval):
        raise ValueError('Reference and observed periods differ')
    if expected_period_s is not None:
        if len(periods) != 2:
            raise ValueError('At least two edges per channel are needed to verify the expected period')
        if any(abs(p - expected_period_s) > max(expected_period_s * period_tolerance, 2 * interval) for p in periods):
            raise ValueError('Observed period differs from the expected period')
    if periods and max_delta >= min(periods) / 2:
        raise ValueError('Pairing window permits ambiguous adjacent epochs')
    epsilon = max(1e-15, max(abs(a_t[0]), abs(a_t[-1]), abs(b_t[0]), abs(b_t[-1])) * 16 * np.finfo(float).eps)
    matched = []
    used = set()
    for i, edge in enumerate(e1):
        position = int(np.searchsorted(e2, edge))
        candidates = [(abs(float(e2[j] - edge)), j) for j in (position - 1, position)
                      if 0 <= j < len(e2) and abs(e2[j] - edge) <= max_delta + epsilon]
        if not candidates:
            continue
        candidates.sort()
        if len(candidates) == 2 and abs(candidates[0][0] - candidates[1][0]) <= epsilon:
            raise ValueError('Equidistant rising edges make pairing ambiguous')
        j = candidates[0][1]
        if j in used:
            raise ValueError('Multiple reference edges claim one observed edge')
        used.add(j)
        matched.append((i, j))
    if not matched:
        raise ValueError('No rising-edge pairs within max_delta; no modulo correction is applied')
    matched_first = {i for i, _ in matched}
    unmatched_first = [i for i in range(len(e1)) if i not in matched_first]
    unmatched_second = [j for j in range(len(e2)) if j not in used]
    start, end = max(a_t[0], b_t[0]) + max_delta, min(a_t[-1], b_t[-1]) - max_delta
    if any(start < e1[i] < end for i in unmatched_first) or any(start < e2[j] < end for j in unmatched_second):
        raise ValueError('Unmatched interior rising edge: possible dropout or wrong epoch')
    pairs = [dict(reference_s=float(e1[i]), observed_s=float(e2[j]), delay_s=float(e2[j] - e1[i])) for i, j in matched]
    delays = [p['delay_s'] for p in pairs]
    return dict(count=len(delays), delays_s=delays, pairs=pairs,
                mean_s=float(np.mean(delays)), std_s=float(np.std(delays)),
                min_s=min(delays), max_s=max(delays), max_delta_s=max_delta,
                reference=first, observed=second, reference_period_s=p1, observed_period_s=p2,
                period_verified=len(periods) == 2, expected_period_verified=expected_period_s is not None,
                unmatched_reference_indices=unmatched_first, unmatched_observed_indices=unmatched_second,
                absolute_epoch_verified=False, matching='nearest unique rising edges; signed observed-reference; no modulo')
