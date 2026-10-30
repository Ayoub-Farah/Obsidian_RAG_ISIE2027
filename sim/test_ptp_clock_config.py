"""Independent module clock assignments and the existing runtime register path."""
import json
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tools')]
from generate_ptp_clock_config import clock_config
from ptp_config import config_id, logical_step, normalize, partition, registers
from run_ptp_campaign import render


class LogicalClockConfig(unittest.TestCase):
    def setUp(self):
        self.base = json.loads((ROOT / 'config/ptp_emulation_9.example.json').read_text())

    def test_fixed_iid_assignment_including_anchor_and_preserved_base(self):
        original = json.dumps(self.base, sort_keys=True)
        cfg = clock_config(self.base, seed=20261030, run_id=10)
        rng = random.Random(20261030)
        self.assertEqual(cfg['drift_ppb'], [rng.randint(-4000, 4000) for _ in range(9)])
        self.assertEqual(cfg, clock_config(self.base, seed=20261030, run_id=10))
        self.assertNotEqual(cfg['drift_ppb'][0], 0)
        self.assertEqual(len(set(cfg['drift_ppb'])), 9)  # This seed, not an iid guarantee.
        for key, value in normalize(self.base).items():
            if key not in ('seed', 'run_id', 'drift_ppb'):
                self.assertEqual(cfg[key], value)
        self.assertEqual(json.dumps(self.base, sort_keys=True), original)
        self.assertNotEqual(config_id(cfg), config_id(normalize(self.base)))
        self.assertNotEqual(cfg['drift_ppb'], clock_config(self.base, seed=20261031, run_id=10)['drift_ppb'])

    def test_every_global_node_reaches_its_own_local_step_register(self):
        for nodes in (9, 10):
            cfg = clock_config(dict(self.base, capacity=4, nodes=nodes), seed=20261030, run_id=10)
            for board, (first, count) in enumerate(partition(nodes)):
                words = registers(cfg, board)
                for slot in range(count):
                    ppb = cfg['drift_ppb'][first + slot]
                    step = words[16 + 4 * slot]
                    self.assertEqual(step, logical_step(ppb))
                    self.assertLess(abs(((step - (1 << 32)) * 1e9 / (1 << 32)) - ppb), 1e9 / (1 << 32))
                for slot in range(count, cfg['capacity']):
                    self.assertEqual(words[16 + 4 * slot], 1 << 32)
            before = cfg['drift_ppb'][:]
            render('run', cfg, ['A1', 'B2', 'C3'], Path('image'), Path('out'), node=9)
            self.assertEqual(cfg['drift_ppb'], before)

    def test_four_ppm_endpoints_and_rejected_invalid_inputs(self):
        self.assertEqual(logical_step(4000), (1 << 32) + 17179)
        self.assertEqual(logical_step(-4000), (1 << 32) - 17179)
        for limit in (True, 0, -4000, 4000.0, 1_000_001):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                clock_config(self.base, seed=1, run_id=10, limit_ppb=limit)
        for seed in (0, True, 4294967294):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                clock_config(self.base, seed=seed, run_id=10)

    def test_checked_in_campaign_is_reproducible(self):
        actual = json.loads((ROOT / 'config/ptp_emulation_9_uniform_4ppm.json').read_text())
        self.assertEqual(actual, clock_config(self.base, seed=20261030, run_id=10))


if __name__ == '__main__':
    unittest.main()
