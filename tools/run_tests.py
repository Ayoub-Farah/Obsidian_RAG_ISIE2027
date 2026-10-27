#!/usr/bin/env python3
"""Run actual Python and portable GHDL tests; retain skipped evidence as skipped.

This does not simulate the proprietary Aurora IP, run Vivado, calibrate links
or turn model values into hardware measurements.
"""
from __future__ import annotations
import argparse
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sources_in_order(paths):
    sources = list(dict.fromkeys(p.resolve() for p in paths))
    texts = {p: p.read_text(encoding="utf-8") for p in sources}
    entities, packages = {}, {}
    for path, content in texts.items():
        for entity in re.findall(r"\bentity\s+(\w+)\s+is", content, re.I):
            entities[entity.lower()] = path
        for package in re.findall(r"\bpackage\s+(?!body\b)(\w+)\s+is", content, re.I):
            packages[package.lower()] = path
    pending = {}
    for path, content in texts.items():
        deps = set()
        for name in re.findall(r"\bentity\s+work\.(\w+)", content, re.I):
            if name.lower() in entities: deps.add(entities[name.lower()])
        for name in re.findall(r"\buse\s+work\.(\w+)\.", content, re.I):
            if name.lower() in packages: deps.add(packages[name.lower()])
        pending[path] = deps - {path}
    done, ordered = set(), []
    while pending:
        ready = sorted((p for p, deps in pending.items() if deps <= done), key=str)
        if not ready: raise RuntimeError("cyclic source dependencies: " + str(pending))
        for p in ready:
            ordered.append(p); done.add(p); del pending[p]
    return ordered


def run_command(command, cwd, timeout=180):
    try:
        result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout)
        return {"command": command, "returncode": result.returncode,
                "status": "passed" if result.returncode == 0 else "failed", "output": result.stdout}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "status": "failed", "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("all", "RAG", "CT"), default="RAG")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/test_results.json")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/ghdl")
    parser.add_argument("--require-rtl", action="store_true")
    parser.add_argument("--stop-time", default="2ms")
    parser.add_argument("--matrix", action="store_true", help="N=2/3, odd/even payloads, stalls and available fault cases")
    parser.add_argument("--only", help="run testbench entities matching this regular expression")
    parser.add_argument("--long", choices=("400", "10000"), help="requested integration journal records; not executed automatically")
    parser.add_argument("--integration-records", type=int, default=12)
    parser.add_argument("--integration-modes", help="comma-separated mode codes for an integration matrix, e.g. 0 or 0,2")
    parser.add_argument("--integration-local-nodes", default="1,2", help="local segment populations for an integration matrix")
    parser.add_argument("--sync-scenarios", help="comma-separated synchronization matrix scenario names")
    args = parser.parse_args()
    report = {"generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "scope": "portable logic only", "family": args.family, "tests": [],
              "vivado_synthesis": "not_executed", "vivado_implementation": "not_executed",
              "static_timing": "not_executed", "hardware_validation": "not_executed"}
    report["tests"].append({"name": "python_wire_format", **run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "sim"), "-p", "test_*.py", "-v"], ROOT)})
    ghdl = shutil.which("ghdl")
    if not ghdl:
        report["tests"].append({"name": "ghdl", "status": "failed" if args.require_rtl else "skipped",
                                "reason": "ghdl executable unavailable"})
    else:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        report["ghdl_version"] = run_command([ghdl, "--version"], ROOT)["output"].splitlines()[0]
        # Portable board support is intentionally excluded: it instantiates AMD
        # primitives. The hardware build compiles it through Vivado instead.
        rtl = [p for directory in ("protocol", "links", "sync", "system")
               for p in (ROOT / "rtl" / directory).glob("*.vhd")]
        testbenches = list((ROOT / "sim").glob("tb_*.vhd"))
        ordered = sources_in_order(rtl + testbenches)
        report["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in ordered}
        compiled = True
        for path in ordered:
            result = {"name": "analyze:" + str(path.relative_to(ROOT)), **run_command(
                [ghdl, "-a", "--std=08", "--workdir=" + str(args.work_dir.resolve()), str(path)], ROOT)}
            report["tests"].append(result)
            if result["status"] != "passed": compiled = False; break
        entities = []
        selected_testbench_paths = set()
        for path in testbenches:
            for entity in re.findall(r"\bentity\s+(tb_\w+)\s+is", path.read_text(), re.I):
                if args.family == "RAG" and "aggregate" in entity.lower(): continue
                if args.family == "CT" and "rag" in entity.lower(): continue
                if args.only and not re.fullmatch(args.only, entity): continue
                entities.append(entity)
                selected_testbench_paths.add(str(path.relative_to(ROOT)))
        report["executed_source_sha256"] = {name: digest for name, digest in report["source_sha256"].items()
            if name.startswith("rtl/") or name in selected_testbench_paths}
        if compiled:
            for entity in sorted(set(entities)):
                elaborate = {"name": "elaborate:" + entity, **run_command(
                    [ghdl, "-e", "--std=08", "--workdir=" + str(args.work_dir.resolve()), entity], ROOT)}
                report["tests"].append(elaborate)
                if elaborate["status"] == "passed":
                    cases = [("default", [])]
                    if args.matrix and entity == "tb_rag_ring":
                        cases = [(f"mode{m}_N{n}_D{d}_stalls{s}",
                                  [f"-gG_MODE={m}", f"-gG_NODES={n}", f"-gG_D={d}",
                                   "-gG_STALLS=" + str(s).lower()])
                                 for m in (0, 2) for n in (2, 3) for d in (5, 6)
                                 for s in (False, True)]
                    if args.matrix and entity == "tb_rag_integrity":
                        cases = [("fault" + str(f), [f"-gG_FAULT={f}"]) for f in range(5)]
                    if args.matrix and entity == "tb_aggregate_integrity":
                        cases = [("fault" + str(f), [f"-gG_FAULT={f}"]) for f in range(8)]
                    if args.matrix and entity == "tb_sync_system":
                        cases = [("default", []), ("TX_stalls", ["-gG_STALL=true"]),
                                 ("occupied_window", ["-gG_TEST_MISS=true"]),
                                 ("graceful_stop", ["-gG_TEST_STOP=true"]),
                                 ("deadline", ["-gG_TEST_DEADLINE=true"]),
                                 ("bounded_campaign", ["-gG_TEST_BOUNDED=true"]),
                                 ("restart_campaign", ["-gG_TEST_RESTART=true"]),
                                 ("held_start", ["-gG_TEST_HELD_START=true"]),
                                 ("2ppm_real_period", ["-gG_REAL_PERIOD=true", "-gG_DRIFT_PPB=2000"]),
                                 ("50ppm_real_period", ["-gG_REAL_PERIOD=true", "-gG_DRIFT_PPB=50000"])]
                        if args.sync_scenarios:
                            requested = set(args.sync_scenarios.split(","))
                            if requested - {name for name, _ in cases}: raise ValueError("unknown sync scenario")
                            cases = [case for case in cases if case[0] in requested]
                    if args.matrix and entity == "tb_benchmark_fault":
                        cases = [("fault" + str(f), [f"-gG_KIND={f}"]) for f in (0, 1)]
                    if args.matrix and entity == "tb_aggregate_ring":
                        cases = [(f"mode{m}_N{n}_D{d}",
                                  [f"-gG_TEST_MODE={m}", f"-gG_TEST_NODES={n}", f"-gG_TEST_DATA={d}"])
                                 for m in (1, 3, 4) for n in (2, 3) for d in (5, 6)]
                        cases += [(f"mode{m}_corrupt", [f"-gG_TEST_MODE={m}", "-gG_CORRUPT=true"])
                                  for m in (1, 3, 4)]
                    if entity == "tb_benchmark_system":
                        records = int(args.long) if args.long else args.integration_records
                        if records < 1: raise ValueError("integration records must be positive")
                        modes = (0, 2) if args.family == "RAG" else (1, 3, 4) if args.family == "CT" else (0, 1, 2, 3, 4)
                        if args.integration_modes:
                            modes = tuple(int(value) for value in args.integration_modes.split(","))
                            if not modes or any(value not in (0, 1, 2, 3, 4) for value in modes):
                                raise ValueError("integration mode codes must be 0..4")
                        local_populations = tuple(int(value) for value in args.integration_local_nodes.split(","))
                        if not local_populations or any(value < 1 for value in local_populations):
                            raise ValueError("local populations must be positive")
                        cases = [(f"mode{m}_N{3*local}_records{records}",
                                  [f"-gG_MODE={m}", f"-gG_LOCAL_NODES={local}", f"-gG_RECORDS={records}", "-gG_ARM_DELAY=10000"])
                                 for m in modes for local in local_populations] if args.matrix else [("default", [f"-gG_RECORDS={records}",
                                  "-gG_MODE=" + ("3" if args.family == "CT" else "2")])]
                    for case, generics in cases:
                        stop_time = args.stop_time
                        if entity == "tb_benchmark_system":
                            stop_time = str(10 + (records + 9)//10) + "ms"
                        if entity == "tb_benchmark_fault": stop_time = "12ms"
                        result = {"name": "simulate:" + entity + ":" + case, **run_command(
                            [ghdl, "-r", "--std=08", "--workdir=" + str(args.work_dir.resolve()), entity,
                             *generics, "--assert-level=error", "--stop-time=" + stop_time], ROOT,
                            timeout=3600 if args.long else 300)}
                        if result["status"] == "passed" and not re.search(r"\bPASS\b", result.get("output", "")):
                            result["status"] = "failed"
                            result["reason"] = "simulation exited without an explicit PASS marker; stop-time alone is not evidence"
                        report["tests"].append(result)
    required = [] if args.only else [("crc", r"tb_crc")]
    if not args.only and args.family in ("all", "RAG"): required.append(("RAG", r"tb_rag.*"))
    if not args.only and args.family in ("all", "CT"): required.append(("CT", r"tb_(?:aggregate|agg).*"))
    simulated = {x["name"].split(":", 2)[1] for x in report["tests"]
                 if x["name"].startswith("simulate:") and x["status"] == "passed"}
    for family, pattern in required:
        if not any(re.fullmatch(pattern, name) for name in simulated):
            report["tests"].append({"name": "required:" + family,
                                    "status": "failed" if args.require_rtl else "skipped",
                                    "reason": "required top-level testbench not executed successfully"})
    report["status"] = "failed" if any(x["status"] == "failed" for x in report["tests"]) else "passed"
    if "source_sha256" in report:
        report["source_changed_during_run"] = [name for name, digest in report["source_sha256"].items()
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
        report["executed_source_changed_during_run"] = [name for name in report["source_changed_during_run"]
            if name in report["executed_source_sha256"]]
        if report["executed_source_changed_during_run"]:
            report["status"] = "failed"
            report["tests"].append({"name": "stable_source_snapshot", "status": "failed",
                                    "reason": "sources changed during validation; rerun after edits finish"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case", "evidence", "mode_code", "N", "board_id", "cycle_id",
                         "local_t0_raw_cycles", "T_useful_cycles", "T_drained_cycles", "first_tx_cycles",
                         "user_clock_hz", "t0_method"])
        for case in report["tests"]:
            for row in re.findall(r"BENCH_CSV,([0-9,]+)", case.get("output", "")):
                writer.writerow([case["name"], "RTL_DIGITAL_INTERFACE_SIMULATION", *row.split(","),
                                 62500000, "local raw counter; common-clock simulation only"])
    report["integration_csv"] = str(csv_path)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for result in report["tests"]:
        print(result["status"].upper(), result["name"])
        if result["status"] == "failed": print(result.get("output", result.get("error", result.get("reason", ""))))
    print("Report:", args.output)
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
