"""Offline waveform fixtures; no scope, USB, VISA or JTAG access."""
import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np


spec = importlib.util.spec_from_file_location('scope_analysis', Path(__file__).resolve().parents[1]/'scripts/ptp_scope_analysis.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def pulse_train(time, *, shift=0.0, period=100e-6, width=1e-6, rise=20e-9, omit=()):
    """Known analog trapezoids, with fractional-sample timing and 3.3 V swing."""
    result = np.zeros_like(time)
    for cycle in range(-1, 8):
        if cycle in omit:
            continue
        start = cycle*period + 10e-6 + shift
        result += 3.3*np.minimum(np.clip((time-start)/rise, 0, 1), np.clip((start+width-time)/rise, 0, 1))
    return result


class ScopeBlockAndScaling(unittest.TestCase):
    def test_embedded_lf_crlf_and_nul_are_payload_not_delimiters(self):
        payload = b'\x00\n\r\n#123\xff\x0a'
        header = b'#2' + str(len(payload)).zfill(2).encode()
        for ending in (b'', b'\n', b'\r\n'):
            self.assertEqual(analysis.parse_ieee_block(header+payload+ending), payload)

    def test_binary_length_and_trailer_errors_are_not_silently_trimmed(self):
        for raw in (b'', b'#0hello\n', b'#', b'#31', b'#2xxabc', b'#15abc', b'#13abcjunk', b'#13abc\n\n', b'#13abc\r'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                analysis.parse_ieee_block(raw)
        self.assertEqual(analysis.parse_ieee_block(b'#10'), b'')

    def test_preamble_origin_reference_and_unsigned_voltage_formula(self):
        preamble = analysis.decode_preamble('0,0,4,1,2e-9,-5e-9,1.5,0.02,100,20')
        time, voltage = analysis.decode_waveform(bytes((0, 100, 120, 255)), preamble)
        np.testing.assert_allclose(time, np.array((-8, -6, -4, -2))*1e-9, atol=1e-23)
        np.testing.assert_allclose(voltage, (-2.4, -0.4, 0, 2.7), atol=1e-14)

    def test_invalid_preambles_and_partial_or_word_payload(self):
        for value in ('0,0,4', '0,0,4,1,nan,0,0,1,0,0', '0,0,0,1,1,0,0,1,0,0',
                      '0,0,4,1,0,0,0,1,0,0', '0,0,4,1,1,0,0,0,0,0', '0,0,4.5,1,1,0,0,1,0,0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analysis.decode_preamble(value)
        preamble = analysis.decode_preamble('0,0,4,1,1e-9,0,0,1,0,0')
        with self.assertRaises(ValueError):analysis.decode_waveform(b'abc', preamble)
        with self.assertRaises(ValueError):analysis.decode_waveform(b'abcd', dict(preamble, format=1))

    def test_rail_diagnostic_does_not_mistake_flat_digital_plateaus_for_clipping(self):
        self.assertFalse(analysis.waveform_quality(bytes([40]*100+[200]*20))['possible_clipping'])
        quality = analysis.waveform_quality(bytes((0, 0, 40, 200, 255)))
        self.assertEqual((quality['low_rail_samples'], quality['high_rail_samples']), (2, 1))
        self.assertTrue(quality['possible_clipping'])
        json.dumps(quality)


class ScopeEdgeTiming(unittest.TestCase):
    def test_low_duty_train_fractional_delays_in_both_directions(self):
        time = np.arange(0, 410e-6, 2e-9)
        first = pulse_train(time)
        for delay in (7.3e-9, -4.7e-9):
            result = analysis.paired_delays(time, first, time, pulse_train(time, shift=delay), expected_period_s=100e-6)
            self.assertEqual(result['count'], 4)
            np.testing.assert_allclose(result['delays_s'], delay, atol=2e-16)
            self.assertTrue(result['period_verified'])
            self.assertTrue(result['expected_period_verified'])
            self.assertFalse(result['absolute_epoch_verified'])
            self.assertAlmostEqual(result['reference']['threshold_v'], 1.65)
            json.dumps(result)

    def test_fine_single_edge_fifty_percent_view_keeps_signed_fractional_shift(self):
        time = np.arange(-100e-9, 100e-9, 1e-9)
        def edge(delay):return 3.3*np.clip((time-delay)/20e-9+0.5, 0, 1)
        result = analysis.paired_delays(time, edge(0), time, edge(-2.4e-9))
        self.assertEqual(result['count'], 1)
        self.assertAlmostEqual(result['mean_s'], -2.4e-9, delta=1e-18)
        self.assertFalse(result['period_verified'])
        with self.assertRaises(ValueError):
            analysis.paired_delays(time, edge(0), time, edge(0), expected_period_s=100e-6)

    def test_flat_small_signal_falling_only_and_invalid_time_are_rejected(self):
        time = np.linspace(0, 1e-6, 1000)
        for voltage in (np.zeros_like(time), 0.01*np.sin(time*1e8), np.linspace(3.3, 0, len(time))):
            with self.subTest(kind=float(np.ptp(voltage))), self.assertRaises(ValueError):
                analysis.rising_edges(time, voltage)
        with self.assertRaises(ValueError):analysis.rising_edges(time[::-1], np.linspace(0, 3.3, len(time)))

    def test_hysteresis_rejects_midlevel_chatter_without_counting_extra_edges(self):
        time = np.arange(100)*1e-9
        voltage = np.r_[np.zeros(30), (1.4, 1.8, 1.5, 1.7, 1.55, 1.75, 2.5), np.full(63, 3.3)]
        result = analysis.rising_edges(time, voltage)
        self.assertEqual(result['edge_count'], 1)

    def test_plateau_medians_remove_asymmetric_percentile_noise_bias(self):
        voltage = np.r_[np.tile((-0.08, 0.0, 0.08), 1000), np.tile((3.28, 3.3, 3.32), 1000)]
        time = np.arange(len(voltage))*1e-9
        result = analysis.rising_edges(time, voltage)
        self.assertAlmostEqual(result['level_seed_v'], 1.62)
        self.assertAlmostEqual(result['low_v'], 0)
        self.assertAlmostEqual(result['high_v'], 3.3)
        self.assertAlmostEqual(result['threshold_v'], 1.65)
        self.assertEqual(result['edge_count'], 1)

    def test_wrong_period_missing_pulse_and_large_epoch_window_are_rejected(self):
        time = np.arange(0, 610e-6, 10e-9)
        first = pulse_train(time)
        for second, maximum in ((pulse_train(time, period=200e-6), 1e-6),
                                (pulse_train(time, omit=(2,)), 1e-6),
                                (pulse_train(time), 60e-6)):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                analysis.paired_delays(time, first, time, second, max_delta=maximum)

    def test_out_of_window_delay_is_not_reduced_modulo_period(self):
        time = np.arange(0, 410e-6, 10e-9)
        with self.assertRaises(ValueError):
            analysis.paired_delays(time, pulse_train(time), time, pulse_train(time, shift=3e-6), max_delta=1e-6)


if __name__ == '__main__':
    unittest.main()
