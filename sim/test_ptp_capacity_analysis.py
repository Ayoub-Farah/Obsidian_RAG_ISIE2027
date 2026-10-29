"""Check that the future model input preserves independent, simultaneous truth."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('capacity_analysis', Path(__file__).resolve().parents[1]/'tools/analyze_ptp_capacity.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def rows_text(samples=2):
    rows = []
    for sample in range(samples):
        for node in range(6):
            row = dict.fromkeys(analysis.FIELDS, 0)
            board, slot = divmod(node, 2)
            parent_board, parent_slot = divmod(max(node - 1, 0), 2)
            row.update(version=1, sample_index=sample, sim_time_ps=sample*16000+1,
                       capacity=2, nodes=6, board=board, local_slot=slot, node_id=node,
                       parent_board=parent_board, parent_local_slot=parent_slot,
                       hops=node, physical_hops=board, internal_hops=node-board,
                       logical_q48_16=100000-node*4096,
                       anchor_logical_q48_16=100000,
                       truth_error_q48_16=(-node*4096) % (1 << 64),
                       adjacent_truth_error_q48_16=(-4096 if node else 0) % (1 << 64),
                       running=1, locked=1, drift_ppb=2000 if node%2 else -2000,
                       logical_step_q32_32=(1 << 32)+(-8590 if node%2 else 8590), seed=1+board)
            rows.append(row)
    return rows


def encode(rows):
    header = 'PTP_CAP_HEADER,'+','.join(analysis.FIELDS)
    return header+'\n'+'\n'.join('PTP_CAP_CSV,'+','.join(
        format(row[name], 'x') if name in analysis.HEX_FIELDS else str(row[name])
        for name in analysis.FIELDS) for row in rows)


class CapacityTruth(unittest.TestCase):
    def test_signed_subtick_errors_and_per_node_drift(self):
        rows = analysis.parse_samples(encode(rows_text()))
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[3]['truth_error_ns'], -3)
        self.assertEqual(rows[3]['adjacent_truth_error_ns'], -1)
        self.assertEqual((rows[3]['physical_hops'], rows[3]['internal_hops']), (1, 2))

    def test_missing_or_duplicate_nodes_are_not_simultaneous_evidence(self):
        rows = rows_text()
        for candidate in (rows[:-1], rows+[rows[0]]):
            with self.subTest(candidate=len(candidate)), self.assertRaises(ValueError):
                analysis.parse_samples(encode(candidate))

    def test_truth_and_topology_must_match_actual_nodes(self):
        for name, value in (('truth_error_q48_16', 0), ('physical_hops', 0),
                            ('parent_board', 2), ('local_slot', 0), ('sim_time_ps', 500)):
            rows = rows_text()
            rows[3][name] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                analysis.parse_samples(encode(rows))

    def test_holdover_is_preserved_and_excluded_from_nominal_statistics(self):
        rows = rows_text()
        rows[3]['holdover'] = 1
        parsed = analysis.parse_samples(encode(rows))
        self.assertEqual(parsed[3]['valid_for_steady_state'], 0)
        self.assertEqual(parsed[3]['truth_error_ns'], -3)


if __name__ == '__main__':
    unittest.main()
