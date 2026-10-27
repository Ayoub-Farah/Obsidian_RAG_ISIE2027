from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from validate_profile import MODES, validate


class ProfileTests(unittest.TestCase):
    def test_reference_population_lengths(self):
        for mode in MODES:
            for n in (2, 3, 10, 20, 30, 60, 180):
                result = validate(mode, n, 6, 2, 4096)
                self.assertTrue(result["valid"], result["errors"])
                self.assertIn("not established", result["hardware_admission"])

    def test_segmentation_needed_is_rejected(self):
        result = validate("AGG_C", 180, 128, 8, 4096)
        self.assertFalse(result["valid"])
        self.assertTrue(any("G_MAX_FRAME_BYTES" in x for x in result["errors"]))
        result = validate("AGG_C", 1000, 128, 8, 200000)
        self.assertFalse(result["valid"])
        self.assertTrue(any("uint16" in x for x in result["errors"]))

    def test_invalid_ranges_period_and_causal_header_delay(self):
        for kwargs in ({"node_base": 3}, {"local_nodes": 4},
                       {"header_delay_cycles": 9}, {"period_cycles": 625},
                       {"user_clock_hz": 125000000}):
            self.assertFalse(validate("RAG_D", 3, 6, 2, 4096, **kwargs)["valid"])

    def test_aggregate_ping_pong_slot_capacity(self):
        result = validate("AGG_C", 180, 6, 8, 4096)
        self.assertFalse(result["valid"])
        self.assertTrue(any("ping-pong slot" in x for x in result["errors"]))
        self.assertTrue(validate("AGG_C", 180, 6, 8, 4096, fifo_words=4096)["valid"])


if __name__ == "__main__": unittest.main()
