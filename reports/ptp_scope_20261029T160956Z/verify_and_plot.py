"""Offline verification of the final dataset, recorded health and outliers."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPORT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPORT.parent.parent / "scripts"))
from ptp_scope_analysis import decode_preamble, decode_waveform, paired_delays

analysis = json.loads((REPORT / "analysis.json").read_text())
expected = {f"{board}_M{node}" for board, nodes in (("A", range(1, 4)),
            ("B", range(4, 7)), ("C", range(7, 10))) for node in nodes}
assert analysis["complete"] and analysis["status"] == "passed"
assert {case["case"]["id"] for case in analysis["cases"]} == expected | {"A_same_sync"}
assert all(case["valid_acquisition_count"] == 100 and case["invalid_acquisition_count"] == 0
           for case in analysis["cases"])

roles = {"OBS001A": 0, "OBS003A": 1, "OBS002A": 2}
records = {serial: [] for serial in roles}
rpc_errors = []
for path in (REPORT / "hardware_rpc").glob("*.json"):
    receipt = json.loads(path.read_text())
    if receipt.get("status") == "error":
        rpc_errors.append({"file": path.name, "error": receipt.get("error")})
    for card in receipt.get("cards", []):
        if "status_hex" not in card:
            continue  # An absent USB interface is explicitly unknown.
        serial = card["serial"]
        status = int(card["status_hex"], 16)
        assert card["nominal"] is True
        assert status >> 232 == 0x505401 and status & 0x19 == 0x19
        assert not status & 0x1062  # config error, holdover, fault, halt
        assert (status >> 16) & 65535 == 3 and (status >> 32) & 65535 == 9
        assert (status >> 8) & 3 == roles[serial]
        assert (status >> 48) & 65535 == 3 * roles[serial]
        assert int(card["config_id_hex"], 16) == 0xb548f1927173517b
        assert int(card["links_hex"], 16) == 3 and int(card["phy_errors_hex"], 16) == 0
        records[serial].append(dict(host_started_ms=card["host_started_ms"],
            host_utc=card["host_started_utc"], raw_tick=(status >> 176) & ((1 << 56) - 1),
            missed_pages=(status >> 96) & 0xffffffff,
            journal_event_lost=(status >> 128) & 0xffffffff, receipt=path.name))

health = dict(schema="ptp_scope_health_summary_v1", all_recorded_samples_nominal=True,
              continuous_health_proven=False, board_health={}, rpc_setup_errors=rpc_errors)
for serial, samples in records.items():
    samples.sort(key=lambda sample: sample["host_started_ms"])
    assert samples and all(b["raw_tick"] >= a["raw_tick"] for a, b in zip(samples, samples[1:]))
    health["board_health"][serial] = dict(sample_count=len(samples), raw_ticks_monotonic=True,
        first=samples[0], last=samples[-1], config_id="b548f1927173517b",
        all_samples_run_locked=True, all_samples_links_up=True, all_samples_current_phy_errors_zero=True)
(REPORT / "health_summary.json").write_text(json.dumps(health, indent=2) + "\n", encoding="utf-8")

directory = REPORT / "17_C_M7_outlier_trigger_quantized"
outliers = json.loads((directory / "outlier_trigger.json").read_text())
assert outliers["status"] == "captured" and len(outliers["captures"]) == 3
assert outliers["restored_mode"] == "EDGE" and outliers["restored_trigger_source"] == "CHAN1"
fig, axes = plt.subplots(1, 3, figsize=(12, 3.7), sharey=True, constrained_layout=True)
for number, (axis, capture) in enumerate(zip(axes, outliers["captures"])):
    assert capture["qualifies"]
    stem = capture["stem"]
    metadata = json.loads((directory / f"{stem}.json").read_text())
    traces = []
    with np.load(directory / f"{stem}.npz") as data:
        for channel in (1, 2):
            traces.extend(decode_waveform(data[f"ch{channel}"].tobytes(),
                          decode_preamble(metadata["channels"][str(channel)]["preamble"])))
    paired = paired_delays(*traces)
    assert paired["count"] == 1 and abs(paired["mean_s"]) > 50e-9
    assert abs(paired["mean_s"] - capture["analysis"]["mean_s"]) < 1e-15
    origin = paired["pairs"][0]["reference_s"]
    for channel, color, label in ((1, "#c18700", "CH1 : REF A"), (2, "#007f9d", "CH2 : OBS M7/C")):
        t, voltage = traces[2 * (channel - 1):2 * channel]
        time_ns = (t - origin) * 1e9
        mask = (time_ns > -120) & (time_ns < 110)
        axis.plot(time_ns[mask], voltage[mask], color=color, label=label, linewidth=1.2)
    axis.axvline(0, color="gray", linestyle=":", linewidth=.7)
    axis.axvline(paired["mean_s"] * 1e9, color="#007f9d", linestyle=":", linewidth=.7)
    axis.set(title=f"Capture {number+1} : Δ = {paired['mean_s']*1e9:+.2f} ns",
             xlabel="Temps relatif au front REF (ns)", xlim=(-120, 110), ylim=(-.2, 3.7))
    axis.grid(alpha=.2)
axes[0].set_ylabel("Tension (V)")
axes[1].legend(loc="lower right", fontsize=8)
fig.savefig(REPORT / "outliers_confirmes.png", dpi=180)
plt.close(fig)

final = json.loads((REPORT / "18_final_live/final_settings.json").read_text())["settings"]
assert final[":ACQuire:TYPE?"] == "NORM" and final[":TRIGger:MODE?"] == "EDGE"
assert final[":DISPlay:GRADing:TIME?"] == "INF" and final[":TRIGger:EDGE:SOURce?"] == "CHAN1"
assert final[":TRIGger:STATus?"] != "STOP"
print(json.dumps({"status": "passed", "module_cases": 9, "calibration_cases": 1,
                  "validated_fresh_acquisitions": 1000, "conditional_outliers_confirmed": 3}))
