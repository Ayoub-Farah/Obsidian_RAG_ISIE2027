"""PTP configuration and register contract. Only standard-library dependencies.

The checked-in JSON Schema is the source of scalar bounds/defaults. Cross-field
rules (population, array lengths, runtime capacity) are checked below.
"""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'config/ptp_emulation.schema.json').read_text())
MASK64 = (1 << 64) - 1


def _validate(value, schema, path):
    kind = schema['type']
    correct = {'object': isinstance(value, dict), 'array': isinstance(value, list),
               'integer': type(value) is int}[kind]
    if not correct:
        raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: expected one of {schema["enum"]}')
    if kind == 'integer':
        if value < schema.get('minimum', value) or value > schema.get('maximum', value):
            raise ValueError(f'{path}: outside declared bounds')
    elif kind == 'array':
        if len(value) > schema['maxItems']:
            raise ValueError(f'{path}: too many entries')
        for i, item in enumerate(value):
            _validate(item, schema['items'], f'{path}[{i}]')
    else:
        unknown = value.keys() - schema['properties'].keys()
        if unknown:
            raise ValueError(f'{path}: unknown fields {sorted(unknown)}')
        for key in schema.get('required', []):
            if key not in value:
                raise ValueError(f'{path}: missing {key}')
        for key, item in value.items():
            _validate(item, schema['properties'][key], f'{path}.{key}')


def logical_step(ppb):
    """Signed truncation towards zero, matching numeric_std division."""
    magnitude = abs(ppb) * (1 << 32) // 1_000_000_000
    return (1 << 32) + (magnitude if ppb >= 0 else -magnitude)


def normalize(data, *, simulation=False):
    _validate(data, SCHEMA, 'config')
    cfg = {k: data.get(k, spec['default']) for k, spec in SCHEMA['properties'].items()}
    n = cfg['nodes']
    if n > 3 * cfg['capacity'] or (not simulation and (n > 60 or cfg['capacity'] > 20)):
        raise ValueError('nodes exceeds synthesized capacity or the hardware limit of 60')
    for key in ('drift_ppb', 'offset_ticks'):
        if cfg[key] and len(cfg[key]) != n:
            raise ValueError(f'{key}: supply exactly nodes entries, or an empty array')
        cfg[key] = cfg[key] or [0] * n
    if cfg['links'] and len(cfg['links']) != n - 1:
        raise ValueError('links: supply nodes-1 entries, or an empty array')
    cfg['links'] = cfg['links'] or [dict(forward_ticks=1, reverse_ticks=1) for _ in range(n-1)]
    return cfg


def partition(nodes):
    counts = [nodes // 3 + int(b < nodes % 3) for b in range(3)]
    return [(sum(counts[:b]), counts[b]) for b in range(3)]


def locate(cfg, user_node):
    if type(user_node) is not int or not 1 <= user_node <= cfg['nodes']:
        raise ValueError('Observed module must be in M1..MN')
    for board, (first, count) in enumerate(partition(cfg['nodes'])):
        if first <= user_node - 1 < first + count:
            return dict(board='ABC'[board], board_index=board, node_id=user_node-1,
                        local_index=user_node-1-first, module=f'M{user_node}')


def config_id(cfg):
    return int(hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16], 16)


def registers(cfg, board):
    """Shadow bank shared with ptp_emulation_system. IDs here are zero-based."""
    first, count = partition(cfg['nodes'])[board]
    words = [0] * (16 + 4 * cfg['capacity'])
    words[0] = cfg['nodes']
    words[1] = cfg['period_ticks'] | cfg['maintenance_ratio'] << 32
    words[2] = cfg['epoch_ticks'] << 16
    words[3] = cfg['pulse_width_ticks'] | cfg['jitter_mask'] << 16 | cfg['drop_every'] << 32
    words[4] = config_id(cfg)
    words[5] = cfg['run_id']
    words[6] = (cfg['seed'] + board) | cfg['sample_period_ticks'] << 32
    words[7] = cfg['duration_ticks']
    for local in range(cfg['capacity']):
        node = first + local
        step, offset, forward, reverse = 1 << 32, 0, 1, 1
        if local < count:
            step = logical_step(cfg['drift_ppb'][node])
            offset = cfg['offset_ticks'][node] << 16
            if node > 0:
                forward = cfg['links'][node-1]['forward_ticks']
            if node < cfg['nodes']-1:
                reverse = cfg['links'][node]['reverse_ticks']
        words[16+4*local:20+4*local] = [step, offset & MASK64, forward | reverse << 16, 0]
    return words
