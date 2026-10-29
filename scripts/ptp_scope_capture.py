"""Acquire paired, stopped MHO900 waveforms and finite-window delay statistics.

This script only controls oscilloscope acquisition inputs. It never controls a
waveform generator or changes FPGA configuration/observation selection.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyvisa

from ptp_scope_analysis import parse_ieee_block

RESOURCE = "USB0::0x1AB1::0x0452::MHO9B280300263::INSTR"


def utc():
    return datetime.now(timezone.utc).isoformat()


class Scope:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.log = (self.directory / "scpi.jsonl").open("w", encoding="utf-8")
        self.rm = pyvisa.ResourceManager()
        self.device = self.rm.open_resource(RESOURCE)
        self.device.timeout = 15000
        self.device.read_termination = None
        self.device.write_termination = "\n"
        self.device.chunk_size = 1048576
        self.native_points = None
        self.native_rate = None
        self.record("idn", self.query("*IDN?"))

    def record(self, command, reply=None):
        self.log.write(json.dumps({"utc": utc(), "command": command, "reply": reply}) + "\n")
        self.log.flush()

    def write(self, command):
        self.device.write(command)
        self.record(command)

    def query(self, command):
        reply = self.device.query(command).strip()
        self.record(command, reply)
        return reply

    def binary(self, command):
        self.device.write(command)
        block = self.device.read_raw()
        payload = parse_ieee_block(block)
        self.record(command, {"payload_bytes": len(payload)})
        return payload

    def errors(self):
        errors = []
        for _ in range(32):
            error = self.query(":SYSTem:ERRor?")
            if error.startswith("0,"):
                break
            errors.append(error)
        if errors:
            raise RuntimeError("SCPI errors: " + repr(errors))

    def stop(self):
        self.write(":STOP")
        self.wait_stop()

    def wait_stop(self, timeout=10):
        deadline = time.monotonic() + timeout
        while self.query(":TRIGger:STATus?").upper() != "STOP":
            if time.monotonic() > deadline:
                raise TimeoutError("Scope did not complete a triggered acquisition")
            time.sleep(.02)

    def single(self):
        self.write(":SINGle")
        self.wait_stop()

    def reset_transfer_window(self):
        # MHO firmware can reject either bound if a previous chunk lies beyond
        # the newly reduced memory depth. Shrink the window BEFORE the depth.
        for channel in (1, 2):
            self.write(f":WAVeform:SOURce CHANnel{channel}")
            self.write(":WAVeform:MODE RAW")
            self.write(":WAVeform:STARt 1")
            self.write(":WAVeform:STOP 1000")
            if self.query(":WAVeform:STARt?") != "1" or self.query(":WAVeform:STOP?") != "1000":
                raise ValueError("Could not reset waveform transfer window before memory change")
        self.errors()

    def screenshot(self, filename):
        payload = self.binary(":DISPlay:DATA? PNG")
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid PNG signature")
        (self.directory / filename).write_bytes(payload)

    def pair(self, stem):
        # The device remains STOP throughout both channel transfers.
        self.wait_stop()
        record = {"utc": utc(), "channels": {}, "trigger_state": "STOP"}
        verify_bounds = self.native_points is None
        if verify_bounds:
            self.native_points = int(float(self.query(":ACQuire:MDEPth?")))
            self.native_rate = float(self.query(":ACQuire:SRATe?"))
        native_points, native_rate = self.native_points, self.native_rate
        arrays = {}
        for channel in (1, 2):
            self.write(f":WAVeform:SOURce CHANnel{channel}")
            self.write(":WAVeform:MODE RAW")
            self.write(":WAVeform:FORMat BYTE")
            # The transfer window survives source changes. Reset BOTH bounds
            # before PREamble?, whose point count follows that selected window.
            self.write(":WAVeform:STARt 1")
            self.write(f":WAVeform:STOP {native_points}")
            preamble = self.query(":WAVeform:PREamble?")
            fields = [float(v) for v in preamble.split(",")]
            if len(fields) != 10:
                raise ValueError("Expected ten preamble fields")
            points = int(fields[2])
            if not 2 <= points <= 10000000:
                raise ValueError("Unexpected native record length")
            if points != native_points or not np.isclose(fields[4] * native_rate, 1, rtol=1e-5):
                raise ValueError("RAW point count or sample increment disagrees with acquisition")
            if verify_bounds and (int(float(self.query(":WAVeform:STARt?"))) != 1 or int(float(self.query(":WAVeform:STOP?"))) != points):
                raise ValueError("Full RAW waveform bounds were not applied")
            chunks = []
            for first in range(1, points + 1, 100000):
                last = min(points, first + 99999)
                self.write(f":WAVeform:STARt {first}")
                self.write(f":WAVeform:STOP {last}")
                chunk = self.binary(":WAVeform:DATA?")
                if len(chunk) != last - first + 1:
                    raise ValueError(f"Wrong waveform size: {len(chunk)} != {last-first+1}")
                chunks.append(chunk)
            payload = b"".join(chunks)
            arrays[f"ch{channel}"] = np.frombuffer(payload, dtype=np.uint8)
            record["channels"][str(channel)] = {"preamble": preamble, "points": points}
        self.wait_stop()
        np.savez_compressed(self.directory / f"{stem}.npz", **arrays)
        (self.directory / f"{stem}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        self.errors()
        return record

    def close(self):
        self.device.close()
        self.rm.close()
        self.log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--window", type=float, default=20)
    parser.add_argument("--scale", type=float, default=1e-7)
    parser.add_argument("--depth", type=int, choices=(10000, 100000), default=10000)
    parser.add_argument("--wide", action="store_true")
    parser.add_argument("--case-id")
    parser.add_argument("--label")
    parser.add_argument("--board", choices=("A", "B", "C"))
    parser.add_argument("--node", type=int)
    parser.add_argument("--kind", choices=("module", "instrument_calibration"), default="module")
    args = parser.parse_args()
    scope = Scope(args.directory)
    if args.case_id:
        case = {"id": args.case_id, "label": args.label or args.case_id,
                "board": args.board, "observer_node": args.node, "kind": args.kind,
                "ch1": "A_TEST_SYNC_TP23_or_TP15",
                "ch2": "A_same_SYNC_net" if args.kind == "instrument_calibration" else f"{args.board}_MOSI_TP24_or_TP16",
                "expected_period_s": .0001}
        (scope.directory / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    summary = {"started_utc": utc(), "resource": RESOURCE, "requested": vars(args) | {"directory": str(args.directory)}}
    try:
        scope.stop()
        scope.reset_transfer_window()
        for channel in (1, 2):
            scope.write(f":CHANnel{channel}:BWLimit OFF")
            scope.write(f":CHANnel{channel}:INVert OFF")
        scope.write(":TIMebase:MAIN:SCALe " + str(5e-5 if args.wide else args.scale))
        scope.write(":TIMebase:MAIN:OFFSet 0")
        scope.write(":ACQuire:MDEPth " + ("1000000" if args.wide else str(args.depth)))
        scope.write(":ACQuire:TYPE NORMal")
        scope.write(":MEASure:STATistic:RESet")
        scope.write(":DISPlay:CLEar")
        scope.write(":RUN")
        summary["statistics_started_utc"] = utc()
        start = time.monotonic()
        time.sleep(args.window)
        scope.stop()
        summary["statistics_window_wall_s"] = time.monotonic() - start
        summary["statistics_stopped_utc"] = utc()
        summary["settings"] = {q: scope.query(q) for q in (
            ":ACQuire:MDEPth?", ":ACQuire:SRATe?", ":TIMebase:MAIN:SCALe?",
            ":TIMebase:MAIN:OFFSet?", ":DISPlay:GRADing:TIME?",
            ":CHANnel1:PROBe?", ":CHANnel2:PROBe?", ":CHANnel1:SCALe?", ":CHANnel2:SCALe?",
            ":ACQuire:TYPE?", ":CHANnel1:BWLimit?", ":CHANnel2:BWLimit?",
            ":CHANnel1:INVert?", ":CHANnel2:INVert?",
            ":CHANnel1:TCALibrate?", ":CHANnel2:TCALibrate?")}
        summary["instrument_delay_s"] = {}
        for kind in ("CURRent", "AVERages", "DEViation", "MINimum", "MAXimum", "CNT"):
            value = float(scope.query(f":MEASure:STATistic:ITEM? {kind},RRDelay,CHANnel1,CHANnel2"))
            summary["instrument_delay_s"][kind] = value
        scope.screenshot("persistence.png")
        scope.pair("persistence_last_pair")
        for index in range(args.count):
            scope.single()
            scope.pair(f"single_{index:04d}")
            if index % 10 == 0:
                print(json.dumps({"utc": utc(), "fresh_acquisitions": index + 1, "requested": args.count}), flush=True)
        summary["fresh_single_acquisitions"] = args.count
        summary["status"] = "acquired"
        summary["finished_utc"] = utc()
        scope.errors()
        scope.write(":MEASure:STATistic:RESet")
        scope.write(":DISPlay:CLEar")
        scope.write(":RUN")
        print(json.dumps(summary), flush=True)
    except Exception as error:
        summary["status"] = "error"
        summary["error"] = str(error)
        raise
    finally:
        (scope.directory / "acquisition.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        scope.close()


if __name__ == "__main__":
    main()
