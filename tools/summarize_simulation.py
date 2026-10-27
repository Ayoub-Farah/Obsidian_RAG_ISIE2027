#!/usr/bin/env python3
"""Summarize the three-segment CSV from run_tests.py in its common timebase.

This intentionally refuses ordinary hardware counters: timestamps from separate
boards are not comparable without a calibrated time mapping.
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

MODES = {0: "RAG_C", 1: "AGG_C", 2: "RAG_D", 3: "AGG_D2", 4: "AGG_D2_PIPE"}


def summarize(source, destination):
    rows = list(csv.DictReader(source.open()))
    groups = defaultdict(list)
    for row in rows:
        if "common-clock simulation" not in row["t0_method"]:
            raise ValueError("Global subtraction requires the declared common-clock simulation timebase")
        groups[(row["case"], int(row["cycle_id"]))].append(row)
    cases = defaultdict(list)
    for (case, cycle), group in groups.items():
        if {row["board_id"] for row in group} != {"0", "1", "2"} or len(group) != 3:
            raise ValueError(f"Expected exactly three segments for {case}, cycle {cycle}")
        anchor = next(row for row in group if row["board_id"] == "0")
        t0 = int(anchor["local_t0_raw_cycles"])
        useful = max(int(row["local_t0_raw_cycles"]) - t0 + int(row["T_useful_cycles"]) for row in group)
        drained = max(int(row["local_t0_raw_cycles"]) - t0 + int(row["T_drained_cycles"]) for row in group)
        tx = [int(row["local_t0_raw_cycles"]) - t0 + int(row["first_tx_cycles"]) for row in group]
        ns_per_cycle = 1e9 / int(anchor["user_clock_hz"])
        cases[case].append((useful * ns_per_cycle, drained * ns_per_cycle,
                            (max(tx) - min(tx)) * ns_per_cycle, anchor))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case", "mode", "N", "periods", "max_observed_global_T_useful_ns",
                         "max_observed_global_T_drained_ns", "max_first_TX_spread_between_segments_ns",
                         "evidence", "scope"])
        for case, values in sorted(cases.items()):
            first = values[0][3]
            mode = int(first["mode_code"])
            writer.writerow([case, MODES[mode], first["N"], len(values),
                max(row[0] for row in values), max(row[1] for row in values),
                max(row[2] for row in values) if mode in (0, 2) else "",
                "RTL_INTERFACE_SIMULATION", "common-clock digital transport; not hardware; observed maximum, not a worst-case proof"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.source.with_name(args.source.stem + "_summary.csv")
    summarize(args.source, output)
    print(output)
