"""Fit fixed-N9 PTP distance data and export conditional timing scenarios.

Offline only: reads the sealed scope report's official acquisition CSVs.  No
VISA/JTAG access, waveform recapture, source-report rewrite or tail-rate fit.
All computations use ns; sample SDs use ddof=1.  Run from any working directory.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import itertools
import json
import sys
from pathlib import Path, PureWindowsPath

import numpy as np


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / 'tools'))
from report_paths import resolve_report_path
DEFAULT_SOURCE = REPOSITORY / "reports/ptp_scope_20261029T160956Z"
DEFAULT_OUTPUT = REPOSITORY / "build/report_outputs/ptp_distance_model"
BOARD_COLORS = {"A": "#147D92", "B": "#C26428", "C": "#7656A3"}
ASSUMPTIONS = [
    "Chaîne mesurée fixe : N=9, trois FPGA, trois modules par FPGA ; aucun balayage de N.",
    "Distance dirigée depuis M1 : h=i-1, p=floor(h/3), v=h-p ; retour M9 vers M1 hors chemin de phase.",
    "Moyennes corrigées par soustraction de la moyenne de calibration A_same_sync ; SD observées conservées.",
    "Le choix parcimonieux sigma_v=0 ne démontre pas un bruit virtuel intrinsèquement nul.",
    "La loi de variance en p suppose des incréments indépendants et homogènes ; leurs covariances ne sont pas identifiées.",
    "Les modules d'un FPGA partagent une horloge physique ; les captures successives n'identifient pas leurs covariances.",
    "Seules les distributions marginales de la campagne observée sont ajustées ; les biais au-delà des deux frontières sont inconnus.",
    "Les trois excursions sélectionnées par déclenchement restent séparées ; leur fréquence et leur probabilité ne sont pas calibrées.",
    "Les projections décrivent la composante centrale, sans queues rares, dérives virtuelles indépendantes ni garantie de borne.",
    "Le scénario à trois FPGA au-delà de N=9 suppose une image de plus grande capacité ; faisabilité matérielle non validée.",
    "Un pas ADC de 0,5 ns avec interpolation ne confère pas une précision absolue de quelques dizaines de ps.",
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def portable_directory_name(value):
    return PureWindowsPath(value).name if "\\" in value else Path(value).name


def load_official_csvs(source):
    """Whitelist cases through the sealed report; use CSV values for all fits."""
    analysis_path = source / "analysis.json"
    report = json.loads(analysis_path.read_text(encoding="utf-8"))
    if not report.get("complete") or report.get("status") != "passed":
        raise ValueError("Source report is not complete/passed")
    cases = {case["case"]["id"]: case for case in report["cases"]}
    expected = ["A_same_sync"] + [f"{'ABC'[i//3]}_M{i+1}" for i in range(9)]
    if set(cases) != set(expected):
        raise ValueError("Expected exactly the calibration plus nine official module cases")
    records, manifests, arrays = [], [], {}
    for identifier in expected:
        case = cases[identifier]
        if not case.get("complete") or case.get("status") != "passed":
            raise ValueError(f"Case {identifier} is not complete/passed")
        directory = source / portable_directory_name(case["directory"])
        path = directory / "acquisition_delays.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != 100 or len({r["acquisition"] for r in rows}) != 100:
            raise ValueError(f"Case {identifier} requires 100 distinct CSV acquisitions")
        audit = {item["acquisition"]: item for item in case["acquisitions"]}
        for row in rows:
            if row["status"] != "passed" or row["errors"] or int(row["paired_edges"]) != 1:
                raise ValueError(f"Invalid official acquisition in {path}: {row['acquisition']}")
            item = audit[row["acquisition"]]
            if item["status"] != "passed" or not np.isclose(
                    float(row["mean_ns"]), item["signed_mean_s"] * 1e9, rtol=0, atol=1e-12):
                raise ValueError(f"CSV/report disagreement for {identifier}/{row['acquisition']}")
        values = np.asarray([float(row["mean_ns"]) for row in rows])
        if not np.all(np.isfinite(values)):
            raise ValueError(f"Nonfinite measurements in {path}")
        arrays[identifier] = values
        manifests.append(dict(case_id=identifier, path=path.relative_to(source).as_posix(),
                              sha256=sha256(path), acquisition_count=len(rows)))
        if identifier == "A_same_sync":
            continue
        i = int(case["case"]["observer_node"])
        if case["case"]["board"] != "ABC"[i//3] or identifier != f"{'ABC'[i//3]}_M{i+1}":
            raise ValueError(f"Unexpected topology for {identifier}")
        records.append(dict(case_id=identifier, board=case["case"]["board"],
                            module=i+1, observer_node=i, n=len(values), h=i, p=i//3,
                            v=i-i//3, csv_path=manifests[-1]["path"]))
    calibration = arrays["A_same_sync"]
    for row in records:
        values = arrays[row["case_id"]]
        row.update(mean_raw_ns=float(values.mean()),
                   mean_corrected_ns=float(values.mean()-calibration.mean()),
                   sample_sd_ns=float(values.std(ddof=1)),
                   variance_ns2=float(values.var(ddof=1)),
                   min_raw_ns=float(values.min()), max_raw_ns=float(values.max()),
                   min_corrected_ns=float(values.min()-calibration.mean()),
                   max_corrected_ns=float(values.max()-calibration.mean()),
                   mean_se_iid_ns=float(values.std(ddof=1)/np.sqrt(values.size)))
    provenance = dict(directory=str(source), analysis_json_sha256=sha256(analysis_path),
                      official_module_acquisitions=900, calibration_acquisitions=100,
                      case_csv_files=manifests, values_source="acquisition_delays.csv",
                      analysis_json_role="official case whitelist and exact numeric cross-check",
                      note="Initial unverified cases, persistence and conditional triggers are excluded")
    return records, np.asarray([arrays[row["case_id"]] for row in records]), calibration, provenance


def nnls(design, target):
    """Exact active-set enumeration for the one/two-column models used here."""
    best = np.zeros(design.shape[1])
    best_error = float(np.dot(target, target))
    for flags in itertools.product((False, True), repeat=design.shape[1]):
        active = np.asarray(flags)
        if not np.any(active):
            continue
        beta = np.linalg.lstsq(design[:, active], target, rcond=None)[0]
        if np.any(beta < -1e-12):
            continue
        result = np.zeros(design.shape[1])
        result[active] = np.maximum(beta, 0)
        error = float(np.sum((target-design @ result)**2))
        if error < best_error:
            best, best_error = result, error
    return best


def r_squared(values, predictions):
    return float(1-np.sum((values-predictions)**2)/np.sum((values-values.mean())**2))


def mean_fit(values, design, names, formula, weights=None):
    def solve(mask):
        x, y = design[mask], values[mask]
        if weights is not None:
            w = np.sqrt(weights[mask])
            x, y = x*w[:, None], y*w
        return np.linalg.lstsq(x, y, rcond=None)[0]
    keep = np.ones(len(values), dtype=bool)
    beta = solve(keep)
    prediction = design @ beta
    loo = np.zeros_like(values)
    for i in range(len(values)):
        mask = keep.copy()
        mask[i] = False
        loo[i] = design[i] @ solve(mask)
    return dict(formula=formula, coefficient_names=names, coefficients=beta.tolist(),
                parameters=dict(zip(names, beta.tolist())), predictions_ns=prediction.tolist(),
                rmse_ns=float(np.sqrt(np.mean((values-prediction)**2))),
                r2=r_squared(values, prediction),
                loo_rmse_ns=float(np.sqrt(np.mean((values-loo)**2))),
                loo_predictions_ns=loo.tolist(),
                loo_scope="Retrait d'un module, interpolation entre cartes déjà observées ; aucune validation de nouvelle carte")


def variance_metrics(observed, predicted):
    return dict(predicted_variance_ns2=predicted.tolist(),
                predicted_sd_ns=np.sqrt(predicted).tolist(),
                rmse_variance_ns2=float(np.sqrt(np.mean((observed-predicted)**2))),
                rmse_sd_ns=float(np.sqrt(np.mean((np.sqrt(observed)-np.sqrt(predicted))**2))),
                r2_variance=r_squared(observed, predicted))


def variance_fit(observed, design, floor, names, formula):
    beta = nnls(design, observed-floor)
    prediction = floor+design @ beta
    loo = np.zeros_like(observed)
    for i in range(len(observed)):
        keep = np.arange(len(observed)) != i
        loo[i] = floor+design[i] @ nnls(design[keep], observed[keep]-floor)
    result = dict(formula=formula, **dict(zip(names, beta.tolist())),
                  measurement_sigma_ns=float(np.sqrt(floor)),
                  loo_rmse_variance_ns2=float(np.sqrt(np.mean((observed-loo)**2))),
                  **variance_metrics(observed, prediction))
    return result


def bootstrap_iid(data, calibration, h, p, v, replicates, seed):
    rng = np.random.default_rng(seed)
    design = np.column_stack((np.ones(9), v, p >= 1, p >= 2))
    columns = ["baseline_phase_ns", "boundary_1_ns", "boundary_2_ns",
               "q_physical_ns2", "physical_sigma_ns", "board_plus_v_baseline_phase_ns",
               "virtual_mean_slope_ns_per_hop", "board_plus_v_boundary_1_ns",
               "board_plus_v_boundary_2_ns", "q_virtual_free_ns2", "q_physical_free_ns2",
               "virtual_sigma_free_ns", "physical_sigma_free_ns"]
    samples = np.zeros((replicates, len(columns)))
    for iteration in range(replicates):
        resampled = np.take_along_axis(data, rng.integers(0, 100, (9, 100)), axis=1)
        reference = calibration[rng.integers(0, 100, 100)]
        means = resampled.mean(axis=1)-reference.mean()
        variances = resampled.var(axis=1, ddof=1)
        floor = reference.var(ddof=1)
        groups = means.reshape(3, 3).mean(axis=1)
        q = max(0, float(np.dot(p, variances-floor)/np.dot(p, p)))
        mb = np.linalg.lstsq(design, means, rcond=None)[0]
        qv, qp = nnls(np.column_stack((v, p)), variances-floor)
        samples[iteration] = [groups[0], groups[1]-groups[0], groups[2]-groups[1],
                              q, np.sqrt(q), *mb, qv, qp, np.sqrt(qv), np.sqrt(qp)]
    intervals = {}
    for index, name in enumerate(columns):
        lo, median, hi = np.percentile(samples[:, index], [2.5, 50, 97.5])
        intervals[name] = dict(lower=float(lo), median=float(median), upper=float(hi))
    return dict(method="Ordinary within-case iid percentile bootstrap, calibration also resampled",
                replicates=replicates, seed=seed, confidence_level=0.95, intervals=intervals,
                free_virtual_coefficient_zero_fraction=float(np.mean(samples[:, 9] == 0)),
                limitations=["Captures supposées iid ; corrélations temporelles non corrigées.",
                             "Ne couvre ni changement de carte/démarrage, ni précision absolue, ni queues rares.",
                             "Seulement neuf positions et trois horloges physiques ; pas 900 chemins indépendants.",
                             "La calibration commune crée une covariance entre moyennes corrigées."])


def load_conditional_outliers(source):
    path = source / "17_C_M7_outlier_trigger_quantized/outlier_trigger.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    captures = data["captures"]
    if len(captures) != 3 or not all(row.get("qualifies") for row in captures):
        raise ValueError("Expected the three independently confirmed conditional M7 captures")
    return dict(case_id="C_M7", source=path.relative_to(source).as_posix(), sha256=sha256(path),
                count=3, signed_raw_delays_ns=[float(row["analysis"]["mean_s"]*1e9) for row in captures],
                contributes_to_unconditioned_statistics=False, outlier_probability=None,
                selection="Déclenchement conditionnel hors fenêtre de ±50 ns",
                caveat="Aucun dénominateur d'exposition exploitable ; ne pas interpréter 3/903 comme une fréquence")


def make_scenarios(measurement_variance, physical_variance, terminal_sd, max_modules):
    counts = np.arange(3, max_modules+1)
    physical_counts = [counts-1, (counts-1)//3, np.full_like(counts, 2)]
    identifiers = ["one_fpga_per_module", "growing_fpga_count_k3", "three_fixed_fpgas"]
    formulas = ["sqrt(sigma_m^2 + (N-1)*sigma_p^2)",
                "sqrt(sigma_m^2 + floor((N-1)/3)*sigma_p^2)",
                "sqrt(sigma_m^2 + 2*sigma_p^2)"]
    curves = {}
    for key, p_count, formula in zip(identifiers, physical_counts, formulas):
        curves[key] = dict(formula=formula, physical_crossings=p_count.tolist(),
                           terminal_sd_ns=np.sqrt(measurement_variance+physical_variance*p_count).tolist())
    return dict(scenarios_only=True, N=counts.tolist(), curves=curves,
                empirical_terminal_point=dict(N=9, case_id="C_M9", sample_sd_ns=terminal_sd,
                                               physical_fpga_count=3, modules_per_fpga=3),
                assumptions=ASSUMPTIONS,
                mean_extrapolation=None,
                note="N désigne le nombre total de modules du scénario ; seul N=9 a été mesuré")


def make_figures(result, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.titlesize": 11, "axes.labelsize": 11,
                         "legend.fontsize": 9.5, "xtick.labelsize": 10,
                         "ytick.labelsize": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "savefig.dpi": 300})
    width = 17/2.54
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    rows = result["measurements"]
    h = np.asarray([r["h"] for r in rows])
    mean = np.asarray([r["mean_corrected_ns"] for r in rows])
    sd = np.asarray([r["sample_sd_ns"] for r in rows])
    board_mean = np.asarray(result["mean_models"]["board_step"]["predictions_ns"])
    french_number = FuncFormatter(lambda x, _: f"{x:g}".replace(".", ","))

    def decorate(axis):
        axis.set_xlim(-0.35, 8.35)
        axis.set_xticks(h)
        axis.yaxis.set_major_formatter(french_number)
        axis.grid(axis="y", color="#DFE4E8", linewidth=0.65)
        axis.set_axisbelow(True)
        for boundary in (2.5, 5.5):
            axis.axvline(boundary, color="#8C969E", linestyle=":", linewidth=1)

    def observed(axis, values, with_error=False, board_labels=False):
        for board in "ABC":
            keep = np.asarray([r["board"] == board for r in rows])
            label = f"Carte {board}" if board_labels else None
            if with_error:
                axis.errorbar(h[keep], values[keep], yerr=sd[keep], fmt="o", markersize=5.5,
                              capsize=3, color=BOARD_COLORS[board], label=label, zorder=4)
            else:
                axis.scatter(h[keep], values[keep], color=BOARD_COLORS[board], s=35,
                             label=label, zorder=4)

    fig, axes = plt.subplots(2, 1, figsize=(width, 8.0))
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.22, top=0.91, hspace=0.40)
    fig.suptitle("Distance à M1, chaîne fixe de neuf modules", fontsize=12, y=0.97)
    observed(axes[0], mean, with_error=True, board_labels=True)
    axes[0].step(h, board_mean, where="mid", color="#283745", linestyle="--",
                 label="Moyennes par carte", linewidth=1.5)
    axes[0].set_ylabel("Moyenne corrigée (ns)")
    axes[0].set_title("Retard signé Δ = OBS − REF ; positif = en retard")
    axes[0].legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=4,
                   borderaxespad=0, columnspacing=0.9, handlelength=1.5)
    observed(axes[1], sd)
    axes[1].step(h, result["variance_models"]["qp_parsimonious"]["predicted_sd_ns"],
                 where="mid", color="#283745", linewidth=1.7,
                 label="Modèle calibré en frontières p")
    axes[1].step(h, result["variance_models"]["quant16_theory"]["predicted_sd_ns"],
                 where="mid", color="#B14C79", linewidth=1.4, linestyle="--",
                 label="Hypothèse uniforme 16 ns/√12")
    axes[1].set_ylabel("Écart-type observé σ (ns)")
    axes[1].set_xlabel("Sauts dirigés depuis M1, h = i − 1")
    axes[1].set_ylim(-0.15, 7.5)
    axes[1].legend(loc="upper left")
    for axis in axes:
        decorate(axis)
    fig.text(0.15, 0.04, "100 captures par module. Barres : ±1 écart-type observé, pas un IC.\n"
             "Source : campagne N=9. Ajustements sur ces données, sans validation indépendante.\n"
             "Les événements rares restent hors du modèle central.", fontsize=9, va="bottom")
    fig.savefig(figures / "Distance_offset_jitter.png")
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(width, 7.7))
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.22, top=0.91, hspace=0.40)
    fig.suptitle("Comparaison des modèles de distance", fontsize=12, y=0.97)
    observed(axes[0], mean)
    axes[0].plot(h, result["mean_models"]["naive_linear"]["predictions_ns"],
                 color="#B56126", linestyle="--", label="Moyenne linéaire en h")
    axes[0].step(h, board_mean, where="mid", color="#147D92", label="Biais distincts des frontières")
    axes[0].set_ylabel("Moyenne corrigée (ns)")
    axes[0].legend(loc="upper right")
    observed(axes[1], sd**2)
    axes[1].plot(h, result["variance_models"]["qh"]["predicted_variance_ns2"],
                 color="#B56126", linestyle="--", label="Variance linéaire en h")
    axes[1].step(h, result["variance_models"]["qp_parsimonious"]["predicted_variance_ns2"],
                 where="mid", color="#147D92", label="Variance en frontières p")
    axes[1].set_ylabel("Variance observée σ² (ns²)")
    axes[1].set_xlabel("Sauts dirigés depuis M1, h = i − 1")
    axes[1].legend(loc="upper left")
    for axis in axes:
        decorate(axis)
    fig.text(0.15, 0.04, "Source : 900 captures, neuf positions, trois horloges physiques.\n"
             "Pour la variance, le plancher de calibration est fixé dans les deux modèles.\n"
             "Comparaison descriptive sur les données d'ajustement.", fontsize=9, va="bottom")
    fig.savefig(figures / "model_comparison.png")
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(width, 5.7))
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.28, top=0.88)
    fig.suptitle("Scénarios conditionnels de dispersion terminale", fontsize=12, y=0.96)
    scenarios = result["scenarios"]
    names = ["Un FPGA par module", "Groupes de 3, FPGA supplémentaires", "Trois FPGA fixes, groupes virtuels croissants"]
    for (key, curve), name, color, style in zip(scenarios["curves"].items(), names,
                                               ["#B56126", "#147D92", "#7656A3"], ["-", "--", "-."]):
        if key == "growing_fpga_count_k3":
            axis.step(scenarios["N"], curve["terminal_sd_ns"], where="post", color=color,
                      linestyle=style, linewidth=1.8, label=name)
        else:
            axis.plot(scenarios["N"], curve["terminal_sd_ns"], color=color, linestyle=style,
                      linewidth=1.8, label=name)
    axis.scatter([9], [sd[-1]], marker="D", color="#17232D", s=40, zorder=5,
                 label="Seule mesure terminale : M9, N=9, 3 FPGA")
    axis.set_xlabel("Nombre total de modules N du scénario")
    axis.set_ylabel("Écart-type terminal σ (ns)")
    axis.set_xlim(3, max(scenarios["N"]))
    axis.set_ylim(0, None)
    if max(scenarios["N"]) == 60:
        axis.set_xticks([3, 9, 15, 30, 45, 60])
    axis.yaxis.set_major_formatter(french_number)
    axis.grid(color="#DFE4E8", linewidth=0.65)
    axis.set_axisbelow(True)
    axis.legend(loc="upper left", fontsize=9)
    fig.text(0.15, 0.065, "Seul N=9 a été mesuré. Courbes : hypothèses, pas un balayage expérimental.\n"
             "Modèle central : bruit virtuel nul choisi, sans dérives indépendantes ni queues rares.\n"
             "Trois FPGA au-delà de N=9 : capacité d'image supplémentaire non démontrée.\n"
             "Biais moyens au-delà des deux frontières mesurées non identifiés.", fontsize=9, va="bottom")
    fig.savefig(figures / "extrapolation_scenarios.png")
    plt.close(fig)


def fit(source, output, replicates=5000, seed=20261029, max_modules=60):
    source, output = resolve_report_path(Path(source).resolve()), Path(output).resolve()
    if output == source or source in output.parents:
        raise ValueError("Output must not be inside the sealed source report")
    if replicates < 100 or max_modules < 9:
        raise ValueError("Require at least 100 bootstrap repeats and max_modules >= 9")
    rows, data, calibration, provenance = load_official_csvs(source)
    h = np.asarray([row["h"] for row in rows])
    p = h//3
    v = h-p
    means = data.mean(axis=1)-calibration.mean()
    variances = data.var(axis=1, ddof=1)
    floor = calibration.var(ddof=1)
    mean_models = {
        "naive_linear": mean_fit(means, np.column_stack((np.ones(9), h)),
                                 ["intercept_ns", "slope_ns_per_hop"], "mu=a+b*h"),
        "board_step": mean_fit(means, np.column_stack((np.ones(9), p >= 1, p >= 2)),
                               ["baseline_phase_ns", "boundary_1_ns", "boundary_2_ns"],
                               "mu=a0+a1*I(p>=1)+a2*I(p>=2)"),
        "board_plus_v": mean_fit(means, np.column_stack((np.ones(9), v, p >= 1, p >= 2)),
                                 ["baseline_phase_ns", "virtual_slope_ns_per_hop", "boundary_1_ns", "boundary_2_ns"],
                                 "mu=a0+bv*v+a1*I(p>=1)+a2*I(p>=2)"),
    }
    mean_models["board_plus_v_iid_wls_sensitivity"] = mean_fit(
        means, np.column_stack((np.ones(9), v, p >= 1, p >= 2)),
        ["baseline_phase_ns", "virtual_slope_ns_per_hop", "boundary_1_ns", "boundary_2_ns"],
        "mu=a0+bv*v+a1*I(p>=1)+a2*I(p>=2); weights=100/sample_variance", weights=100/variances)
    vm = {
        "qh": variance_fit(variances, h[:, None], floor, ["q_h_ns2"], "sigma2=sm2+qh*h"),
        "qp_parsimonious": variance_fit(variances, p[:, None], floor, ["q_physical_ns2"], "sigma2=sm2+qp*p; qv=0"),
        "qv_qp_free": variance_fit(variances, np.column_stack((v, p)), floor,
                                   ["q_virtual_ns2", "q_physical_ns2"], "sigma2=sm2+qv*v+qp*p; qv,qp>=0"),
        "quant16_theory": dict(formula="sigma2=sm2+(16^2/12)*p", q_physical_ns2=256/12,
                               physical_sigma_ns=float(16/np.sqrt(12)), measurement_sigma_ns=float(np.sqrt(floor)),
                               assumptions="Four independent uniform effective timestamp errors of width16ns; not guaranteed by RTL",
                               **variance_metrics(variances, floor+(256/12)*p)),
    }
    for key in ("qp_parsimonious", "qv_qp_free"):
        vm[key]["physical_sigma_ns"] = float(np.sqrt(vm[key]["q_physical_ns2"]))
        vm[key]["virtual_sigma_ns"] = float(np.sqrt(vm[key].get("q_virtual_ns2", 0)))
    physical_q = vm["qp_parsimonious"]["q_physical_ns2"]
    groups = []
    for index, board in enumerate("ABC"):
        groups.append(dict(board=board, module_count=3,
                           mean_corrected_ns=float(means[p == index].mean()),
                           mean_within_module_variance_ns2=float(variances[p == index].mean()),
                           pooled_within_module_sd_ns=float(np.sqrt(variances[p == index].mean()))))
    result = dict(schema="ptp_distance_fit_results_v1", generated_at_utc=datetime.now(timezone.utc).isoformat(),
                  source=provenance, script_sha256=sha256(__file__), units=dict(time="ns", variance="ns^2"),
                  calibration=dict(case_id="A_same_sync", n=100, mean_raw_ns=float(calibration.mean()),
                                   sample_sd_ns=float(calibration.std(ddof=1)), mean_se_iid_ns=float(calibration.std(ddof=1)/10)),
                  measurements=rows, group_statistics=groups, mean_models=mean_models, variance_models=vm,
                  bootstrap_iid=bootstrap_iid(data, calibration, h, p, v, replicates, seed),
                  conditional_outliers=load_conditional_outliers(source),
                  scenarios=make_scenarios(floor, physical_q, rows[-1]["sample_sd_ns"], max_modules),
                  assumptions=ASSUMPTIONS)
    coefficients = mean_models["board_step"]["parameters"]
    parameters = dict(schema="ptp_distance_model_v1", central_component_only=True, outlier_probability=None,
                      parameters=dict(measurement_sigma_ns=float(np.sqrt(floor)), virtual_sigma_ns=0,
                                      physical_sigma_ns=float(np.sqrt(physical_q)),
                                      baseline_phase_ns=coefficients["baseline_phase_ns"],
                                      boundary_bias_ns=[coefficients["boundary_1_ns"], coefficients["boundary_2_ns"]],
                                      observed_max_hops=8),
                      formula_mean="mu=a0+a1*I(p>=1)+a2*I(p>=2), only for the observed two boundaries",
                      formula_variance="sigma2=measurement_sigma_ns^2+physical_sigma_ns^2*p; virtual_sigma_ns=0 is a parsimonious choice",
                      conditional_outliers=result["conditional_outliers"], assumptions=ASSUMPTIONS,
                      source_fit_results="fit_results.json")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "fit_results.json", result)
    write_json(output / "model_parameters.json", parameters)
    with (output / "measurements.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    make_figures(result, output)
    # Read-only guarantee also checked after all output writes and rendering.
    if sha256(source / "analysis.json") != provenance["analysis_json_sha256"]:
        raise RuntimeError("Source analysis changed during execution")
    for manifest in provenance["case_csv_files"]:
        if sha256(source / manifest["path"]) != manifest["sha256"]:
            raise RuntimeError("Source CSV changed during execution")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-replicates", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--max-modules", type=int, default=60)
    args = parser.parse_args(argv)
    result = fit(args.source, args.output, args.bootstrap_replicates, args.seed, args.max_modules)
    print(json.dumps(dict(output=str(args.output), module_captures=900,
                          physical_sigma_ns=result["variance_models"]["qp_parsimonious"]["physical_sigma_ns"],
                          figures=3), ensure_ascii=False))


if __name__ == "__main__":
    main()
