"""Assign reproducible, fixed, independent uniform logical drifts to PTP modules.

The physical FPGA clocks are unchanged. Values are integer ppb, drawn once per
global node (including M1), and consumed by the existing Q48.32 accumulators.
"""
from pathlib import Path
import argparse
import json
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from ptp_config import normalize, config_id


def clock_config(base, *, seed, run_id, limit_ppb=4000, simulation=False):
    """Preserve the normalized base except seed, run_id and per-node drift.

    Use an iid discrete uniform law on [-limit_ppb, +limit_ppb], inclusive.
    Equal draws are possible; no sorting, centering or rejection changes the
    law. A fixed seed makes the assignment repeatable across acquisitions.
    """
    if type(limit_ppb) is not int or not 1 <= limit_ppb <= 1_000_000:
        raise ValueError('limit_ppb must be an integer in 1..1000000')
    cfg = normalize(dict(base, seed=seed, run_id=run_id), simulation=simulation)
    rng = random.Random(cfg['seed'])
    cfg['drift_ppb'] = [rng.randint(-limit_ppb, limit_ppb) for _ in range(cfg['nodes'])]
    return cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/ptp_emulation_9.example.json')
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--limit-ppb', type=int, default=4000)
    parser.add_argument('--simulation', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        base = json.loads(args.config.read_text(encoding='utf-8'))
        cfg = clock_config(base, seed=args.seed, run_id=args.run_id,
                           limit_ppb=args.limit_ppb, simulation=args.simulation)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as output:
            output.write(json.dumps(cfg, indent=2) + '\n')
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f'{args.output}: {cfg["nodes"]} fixed logical drifts, uniform +/-{args.limit_ppb} ppb; '
          f'config_id={config_id(cfg):016x}; no hardware action')


if __name__ == '__main__':
    main()
