"""Conditional M9 diagnostic, excluded from unconditioned mean/jitter samples."""
import json
import sys
from pathlib import Path

import numpy as np

REPORT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPORT.parent.parent / "scripts"))
from ptp_scope_analysis import decode_preamble, decode_waveform, paired_delays, rising_edges
from ptp_scope_capture import Scope, utc


def decode_pair(directory, stem):
    metadata = json.loads((directory / f"{stem}.json").read_text())
    with np.load(directory / f"{stem}.npz") as data:
        traces = []
        for channel in (1, 2):
            traces.extend(decode_waveform(data[f"ch{channel}"].tobytes(),
                          decode_preamble(metadata["channels"][str(channel)]["preamble"])))
    return traces


reference = decode_pair(REPORT / "12b_C_M7_wide_validation", "persistence_last_pair")
t, v = reference[:2]
edges = rising_edges(t, v)
rising = np.asarray(edges["edges_s"])
level = edges["threshold_v"]
index = np.flatnonzero((v[:-1] >= level) & (v[1:] < level))
falling = t[index] + (level - v[index]) / (v[index + 1] - v[index]) * (t[index + 1] - t[index])
widths = []
for edge in rising:
    after = falling[(falling > edge) & (falling < edge + 2e-6)]
    if len(after):
        widths.append(float(after[0] - edge))
period, width = float(np.median(np.diff(rising))), float(np.median(widths))
assert 99e-6 < period < 101e-6 and .9e-6 < width < 1.2e-6
center = period - width
lower, upper = center - 40e-9, center + 20e-9
directory = REPORT / "15_C_M9_outlier_trigger"
scope = Scope(directory)
result = dict(schema="ptp_scope_conditional_outlier_v1", started_utc=utc(),
              source="CH1 falling followed by CH2 rising", reference_period_s=period,
              reference_width_s=width, lower_delay_s=lower, upper_delay_s=upper,
              intended_rr_range_s=[-40e-9, 20e-9], captures=[],
              contributes_to_unconditioned_statistics=False)
try:
    scope.stop()
    scope.reset_transfer_window()
    for command in (":TRIGger:MODE DELay", ":TRIGger:DELay:SA CHANnel1",
                    ":TRIGger:DELay:ASLop NEGative", ":TRIGger:DELay:SB CHANnel2",
                    ":TRIGger:DELay:BSLop POSitive", ":TRIGger:DELay:ALEVel 1.65",
                    ":TRIGger:DELay:BLEVel 1.65", ":TRIGger:DELay:TYPE GOUT",
                    f":TRIGger:DELay:TUPPer {upper:.14g}",
                    f":TRIGger:DELay:TLOWer {lower:.14g}", ":TRIGger:SWEep NORMal",
                    ":MEASure:STATistic:RESet", ":DISPlay:CLEar"):
        scope.write(command)
    result["settings"] = {command: scope.query(command) for command in (
        ":TRIGger:MODE?", ":TRIGger:DELay:SA?", ":TRIGger:DELay:ASLop?",
        ":TRIGger:DELay:SB?", ":TRIGger:DELay:BSLop?", ":TRIGger:DELay:TYPE?",
        ":TRIGger:DELay:TLOWer?", ":TRIGger:DELay:TUPPer?")}
    scope.errors()
    for number in range(3):
        try:
            scope.single()
        except TimeoutError:
            result["timeout_without_qualified_trigger"] = True
            scope.stop()
            break
        stem = f"outlier_{number:04d}"
        scope.screenshot(stem + ".png")
        scope.pair(stem)
        analysis = paired_delays(*decode_pair(directory, stem))
        qualifies = all(value < -40e-9 or value > 20e-9 for value in analysis["delays_s"])
        result["captures"].append(dict(stem=stem, qualifies=qualifies, analysis=analysis))
        print(json.dumps(dict(capture=number, delay_ns=[x * 1e9 for x in analysis["delays_s"]],
                              qualifies=qualifies)), flush=True)
        if not qualifies:
            result["qualification_mismatch"] = True
            break
    result["status"] = "captured" if result["captures"] else "no_qualified_capture"
except Exception as error:
    result.update(status="error", error=str(error))
    raise
finally:
    # Leave the scope on the user's requested REF rising trigger/persistence.
    scope.stop()
    for command in (":TRIGger:MODE EDGE", ":TRIGger:EDGE:SOURce CHANnel1",
                    ":TRIGger:EDGE:SLOPe POSitive", ":TRIGger:EDGE:LEVel 1.65",
                    ":TRIGger:SWEep NORMal", ":DISPlay:GRADing:TIME INFinite",
                    ":MEASure:STATistic:RESet", ":DISPlay:CLEar", ":RUN"):
        scope.write(command)
    result["restored_mode"] = scope.query(":TRIGger:MODE?")
    result["restored_trigger_source"] = scope.query(":TRIGger:EDGE:SOURce?")
    scope.errors()
    result["finished_utc"] = utc()
    (directory / "outlier_trigger.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    scope.close()
