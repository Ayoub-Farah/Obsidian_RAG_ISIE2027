"""Central-component surrogate for the fixed N=9, three-board PTP experiment.

For h directed hops, p physical clock-domain crossings and v=h-p virtual hops:
    variance_ns2 = measurement_sigma_ns**2 + v*virtual_sigma_ns**2
                   + p*physical_sigma_ns**2
The signed phase mean is the baseline plus the ordered boundary-bias prefix.

Independent uniform per-edge increments are a simulation ASSUMPTION fitted to
central moments, not an identified time process. No autocorrelation, tails,
outlier probability, or effect of changing N is inferred by this module.
"""
from dataclasses import dataclass, fields
import json
import math
from numbers import Integral, Real
from pathlib import Path
from typing import Sequence

import numpy as np

PARAMETER_SCHEMA = 'ptp_distance_model_v1'


def _count(value, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f'{name} must be a nonnegative integer')
    return int(value)


def _finite(value, name, *, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite number')
    result = float(value)
    if not math.isfinite(result) or nonnegative and result < 0:
        raise ValueError(f'{name} must be finite' + (' and nonnegative' if nonnegative else ''))
    return result


def _biases(values, name):
    if isinstance(values, (str, bytes)):
        raise ValueError(f'{name} must be a sequence of finite signed biases in ns')
    try:
        return tuple(_finite(value, name) for value in values)
    except TypeError as error:
        raise ValueError(f'{name} must be a sequence of finite signed biases in ns') from error


def _boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f'{name} must be a boolean')
    return value


@dataclass(frozen=True)
class ModelParameters:
    measurement_sigma_ns: float = .0358848
    virtual_sigma_ns: float = 0.
    physical_sigma_ns: float = 4.3801
    baseline_phase_ns: float = .002319
    boundary_bias_ns: tuple[float, ...] = (-23.150096, 13.478333)
    observed_max_hops: int = 8

    def __post_init__(self):
        for name in ('measurement_sigma_ns', 'virtual_sigma_ns', 'physical_sigma_ns'):
            object.__setattr__(self, name, _finite(getattr(self, name), name, nonnegative=True))
        object.__setattr__(self, 'baseline_phase_ns', _finite(self.baseline_phase_ns, 'baseline_phase_ns'))
        object.__setattr__(self, 'boundary_bias_ns', _biases(self.boundary_bias_ns, 'boundary_bias_ns'))
        object.__setattr__(self, 'observed_max_hops', _count(self.observed_max_hops, 'observed_max_hops'))


def load_parameters(path: str | Path) -> ModelParameters:
    """Read {schema, central_component_only:true, outlier_probability:null, parameters:{...}}.

    Additional top-level fit/provenance metadata is allowed. Unknown parameter
    names are rejected; omitted parameter fields use the explicit defaults.
    """
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema') != PARAMETER_SCHEMA:
        raise ValueError(f'Expected schema {PARAMETER_SCHEMA}')
    if data.get('central_component_only') is not True or data.get('outlier_probability') is not None:
        raise ValueError('Only a central-component model with no fitted outlier probability is supported')
    parameters = data.get('parameters')
    if not isinstance(parameters, dict):
        raise ValueError('parameters must be a JSON object')
    unknown = set(parameters) - {field.name for field in fields(ModelParameters)}
    if unknown:
        raise ValueError('Unknown model parameters: ' + ', '.join(sorted(unknown)))
    return ModelParameters(**parameters)


def predict(hops, physical_crossings, parameters: ModelParameters,
            include_measurement=True, explicit_boundary_bias_ns=None):
    """Return JSON-safe central moments in ns; positive mean means later OBS.

    explicit_boundary_bias_ns, when supplied, is a complete ordered bias vector
    starting at the first crossing. Beyond two physical boundaries, prediction
    requires this explicit vector for a mean; otherwise mean_phase_ns is null.
    Central variance can still be extrapolated, with the flag set.
    """
    if not isinstance(parameters, ModelParameters):
        raise TypeError('parameters must be ModelParameters')
    h = _count(hops, 'hops')
    p = _count(physical_crossings, 'physical_crossings')
    if p > h:
        raise ValueError('physical_crossings cannot exceed hops')
    _boolean(include_measurement, 'include_measurement')
    biases = parameters.boundary_bias_ns if explicit_boundary_bias_ns is None else \
        _biases(explicit_boundary_bias_ns, 'explicit_boundary_bias_ns')
    mean = None
    if len(biases) >= p and (p <= 2 or explicit_boundary_bias_ns is not None):
        mean = math.fsum((parameters.baseline_phase_ns, *biases[:p]))
    sigma = math.hypot(parameters.measurement_sigma_ns if include_measurement else 0.,
                       math.sqrt(h-p)*parameters.virtual_sigma_ns,
                       math.sqrt(p)*parameters.physical_sigma_ns)
    if not math.isfinite(sigma) or mean is not None and not math.isfinite(mean):
        raise ValueError('Predicted moments overflowed; use finite practical parameters')
    return dict(hops=h, physical_crossings=p, virtual_hops=h-p,
                mean_phase_ns=mean, sigma_ns=sigma, central_component_only=True,
                extrapolation=bool(h > parameters.observed_max_hops or p > 2),
                calibrated_mapping=bool(h <= parameters.observed_max_hops and p == h//3))


def sample_chain(domains: Sequence[int], sample_count, parameters: ModelParameters,
                 seed=0, include_measurement=False, boundary_bias_ns=None,
                 zero_mean_boundaries=False) -> np.ndarray:
    """Generate central phase samples [sample, node], in ns.

    Domain IDs start at zero and can remain equal or increase by one. Each edge
    contributes an independent uniform increment of half-width sqrt(3)*sigma;
    prefixes therefore share upstream errors. With zero virtual sigma, nodes
    in one domain share exactly the same phase before independent optional
    Gaussian measurement noise.

    boundary_bias_ns overrides the complete boundary vector. Insufficient
    known biases raise; zero_mean_boundaries=True instead requests an explicit
    counterfactual with every boundary bias zero, retaining the baseline.
    Rows are independent simulation samples, not an identified temporal model.
    """
    if not isinstance(parameters, ModelParameters):
        raise TypeError('parameters must be ModelParameters')
    count = _count(sample_count, 'sample_count')
    if count == 0:
        raise ValueError('sample_count must be positive')
    _boolean(include_measurement, 'include_measurement')
    _boolean(zero_mean_boundaries, 'zero_mean_boundaries')
    if seed is not None:
        seed = _count(seed, 'seed')
    if isinstance(domains, (str, bytes)):
        raise ValueError('domains must be a nonempty integer sequence')
    try:
        labels = tuple(_count(value, 'domain label') for value in domains)
    except TypeError as error:
        raise ValueError('domains must be a nonempty integer sequence') from error
    if not labels or labels[0] != 0 or any(b-a not in (0, 1) for a, b in zip(labels, labels[1:])):
        raise ValueError('Domain labels must start at zero and remain equal or increase by one')
    if zero_mean_boundaries and boundary_bias_ns is not None:
        raise ValueError('Choose explicit boundary biases or zero_mean_boundaries, not both')
    physical_edges = sum(a != b for a, b in zip(labels, labels[1:]))
    biases = parameters.boundary_bias_ns if boundary_bias_ns is None else \
        _biases(boundary_bias_ns, 'boundary_bias_ns')
    if zero_mean_boundaries:
        biases = (0.,)*physical_edges
    elif len(biases) < physical_edges:
        raise ValueError('Unknown boundary bias: provide a complete vector or explicitly set zero_mean_boundaries=True')
    rng = np.random.default_rng(seed)
    samples = np.empty((count, len(labels)), dtype=np.float64)
    samples[:, 0] = parameters.baseline_phase_ns
    boundary = 0
    for node in range(1, len(labels)):
        physical = labels[node] != labels[node-1]
        sigma = parameters.physical_sigma_ns if physical else parameters.virtual_sigma_ns
        bias = biases[boundary] if physical else 0.
        if physical:
            boundary += 1
        samples[:, node] = samples[:, node-1] + bias
        if sigma:
            half_width = math.sqrt(3.)*sigma
            if not math.isfinite(half_width):
                raise ValueError('Uniform increment width overflowed')
            samples[:, node] += rng.uniform(-half_width, half_width, size=count)
    if include_measurement and parameters.measurement_sigma_ns:
        samples += rng.normal(0., parameters.measurement_sigma_ns, size=samples.shape)
    if not np.isfinite(samples).all():
        raise ValueError('Sample phases overflowed; use finite practical parameters')
    return samples
