"""Analytic moments and independent Monte Carlo checks of the central surrogate."""
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.ptp_distance_model import (ModelParameters, PARAMETER_SCHEMA,
                                     load_parameters, predict, sample_chain)

DOMAINS = (0, 0, 0, 1, 1, 1, 2, 2, 2)


class DistanceModelTests(unittest.TestCase):
    def test_default_distance_law_units_signed_mean_and_mapping(self):
        parameters = ModelParameters()
        for hops in range(9):
            physical = hops//3
            result = predict(hops, physical, parameters)
            self.assertAlmostEqual(result['sigma_ns']**2,
                                   .0358848**2 + physical*4.3801**2, places=11)
            expected = .002319 + sum((-23.150096, 13.478333)[:physical])
            self.assertAlmostEqual(result['mean_phase_ns'], expected, places=12)
            self.assertTrue(result['central_component_only'])
            self.assertTrue(result['calibrated_mapping'])
            self.assertFalse(result['extrapolation'])
            json.dumps(result, allow_nan=False)
        self.assertFalse(predict(2, 1, parameters)['calibrated_mapping'])
        self.assertEqual(predict(2, 0, parameters, include_measurement=False)['sigma_ns'], 0.)

    def test_prefix_variance_covariance_and_mean_100000_samples(self):
        parameters = ModelParameters(measurement_sigma_ns=.2, virtual_sigma_ns=.7)
        samples = sample_chain(DOMAINS, 100000, parameters, seed=20261029,
                               include_measurement=True)
        self.assertEqual(samples.shape, (100000, 9))
        expected_covariance = np.empty((9, 9))
        for left in range(9):
            for right in range(9):
                common = min(left, right)
                physical = common//3
                expected_covariance[left, right] = \
                    (common-physical)*.7**2 + physical*4.3801**2 + (.2**2 if left == right else 0)
        covariance = np.cov(samples, rowvar=False, ddof=0)
        np.testing.assert_allclose(np.diag(covariance), np.diag(expected_covariance),
                                   rtol=.02, atol=.0003)
        np.testing.assert_allclose(covariance, expected_covariance, rtol=.02, atol=.03)
        expected_means = [predict(h, h//3, parameters)['mean_phase_ns'] for h in range(9)]
        np.testing.assert_allclose(samples.mean(axis=0), expected_means, rtol=0, atol=.08)

    def test_zero_virtual_noise_shares_exact_phase_inside_each_domain(self):
        parameters = ModelParameters()
        samples = sample_chain(DOMAINS, 2000, parameters, seed=127)
        for first in (0, 3, 6):
            np.testing.assert_array_equal(samples[:, first], samples[:, first+1])
            np.testing.assert_array_equal(samples[:, first], samples[:, first+2])
        np.testing.assert_array_equal(samples[:, 0], np.full(2000, parameters.baseline_phase_ns))
        self.assertGreater(np.var(samples[:, 3]), 1.)
        # Each uniform increment stays within its assumed bounded support.
        increment = samples[:, 3]-samples[:, 2]-parameters.boundary_bias_ns[0]
        self.assertLessEqual(float(np.max(np.abs(increment))), math.sqrt(3)*parameters.physical_sigma_ns+1e-12)

    def test_deterministic_signed_bias_without_noise_and_repeatable_seed(self):
        parameters = ModelParameters(measurement_sigma_ns=0., physical_sigma_ns=0.,
                                     baseline_phase_ns=2., boundary_bias_ns=(-10., 3.))
        expected = [2., 2., 2., -8., -8., -8., -5., -5., -5.]
        np.testing.assert_array_equal(sample_chain(DOMAINS, 5, parameters),
                                      np.tile(expected, (5, 1)))
        stochastic = ModelParameters(virtual_sigma_ns=.5)
        first = sample_chain(DOMAINS, 100, stochastic, seed=512, include_measurement=True)
        np.testing.assert_array_equal(first, sample_chain(DOMAINS, 100, stochastic,
                                                         seed=512, include_measurement=True))
        self.assertFalse(np.array_equal(first, sample_chain(DOMAINS, 100, stochastic,
                                                            seed=513, include_measurement=True)))

    def test_unknown_third_boundary_requires_explicit_bias_or_counterfactual(self):
        parameters = ModelParameters()
        prediction = predict(9, 3, parameters)
        self.assertIsNone(prediction['mean_phase_ns'])
        self.assertTrue(prediction['extrapolation'])
        self.assertFalse(prediction['calibrated_mapping'])
        self.assertIsNone(predict(9, 3, parameters, explicit_boundary_bias_ns=(1., 2.))['mean_phase_ns'])
        explicit = predict(9, 3, parameters, explicit_boundary_bias_ns=(-10., 3., 5.))
        self.assertAlmostEqual(explicit['mean_phase_ns'], parameters.baseline_phase_ns-2.)
        with self.assertRaisesRegex(ValueError, 'Unknown boundary bias'):
            sample_chain((0, 1, 2, 3), 10, parameters)
        counterfactual = sample_chain((0, 1, 2, 3), 100, parameters, seed=8,
                                     zero_mean_boundaries=True)
        explicit_zero = sample_chain((0, 1, 2, 3), 100, parameters, seed=8,
                                     boundary_bias_ns=(0., 0., 0.))
        np.testing.assert_array_equal(counterfactual, explicit_zero)
        with self.assertRaises(ValueError):
            sample_chain((0, 1), 10, parameters, boundary_bias_ns=(0.,),
                         zero_mean_boundaries=True)

    def test_invalid_parameters_counts_and_domain_maps(self):
        for values in (dict(measurement_sigma_ns=-1), dict(virtual_sigma_ns=float('nan')),
                       dict(physical_sigma_ns=float('inf')), dict(baseline_phase_ns=float('nan')),
                       dict(boundary_bias_ns=(0., float('inf'))), dict(observed_max_hops=-1),
                       dict(observed_max_hops=8.), dict(physical_sigma_ns=True)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ModelParameters(**values)
        parameters = ModelParameters()
        for hops, physical in ((-1, 0), (1, -1), (1, 2), (1.5, 0), (1, True)):
            with self.subTest(hops=hops, physical=physical), self.assertRaises(ValueError):
                predict(hops, physical, parameters)
        for count in (0, -1, 1.5, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                sample_chain(DOMAINS, count, parameters)
        for domains in ((), (1,), (0, 2), (0, 1, 0), (0, -1), (0, 1.5), (False,)):
            with self.subTest(domains=domains), self.assertRaises(ValueError):
                sample_chain(domains, 10, parameters)
        with self.assertRaises(ValueError):
            predict(1, 1, parameters, explicit_boundary_bias_ns=(float('nan'),))

    def test_json_loader_preserves_defaults_and_rejects_noncentral_or_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'model.json'
            data = dict(schema=PARAMETER_SCHEMA, central_component_only=True,
                        outlier_probability=None, parameters=asdict(ModelParameters()))
            path.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(load_parameters(path), ModelParameters())
            for patch in (dict(central_component_only=False), dict(outlier_probability=.01),
                          dict(schema='another_model'), dict(parameters={'physical_sigam_ns': 4.})):
                with self.subTest(patch=patch), self.assertRaises(ValueError):
                    path.write_text(json.dumps(data | patch), encoding='utf-8')
                    load_parameters(path)


if __name__ == '__main__':
    unittest.main()
