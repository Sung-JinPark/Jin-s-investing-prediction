"""V5 scoring, dependent bootstrap and unchanged research Gate."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def stationary_bootstrap_ci(values: np.ndarray, *, block_length: int = 13, confidence: float = 0.90, iterations: int = 2000, seed: int = 52026) -> list[float]:
    data = np.asarray(values, dtype=float); rng = np.random.default_rng(seed); means = np.empty(iterations); restart = 1.0 / block_length
    for iteration in range(iterations):
        indexes = np.empty(len(data), dtype=int); indexes[0] = rng.integers(0, len(data))
        for position in range(1, len(data)):
            indexes[position] = rng.integers(0, len(data)) if rng.random() < restart else (indexes[position - 1] + 1) % len(data)
        means[iteration] = np.mean(data[indexes])
    alpha = (1 - confidence) / 2; return [float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    model = float(np.mean([row["model_crps"] for row in rows])); baseline = float(np.mean([row["baseline_crps"] for row in rows])); coverage = float(np.mean([row["p10"] <= row["actual"] <= row["p90"] for row in rows])); core_coverage = float(np.mean([row["p25"] <= row["actual"] <= row["p75"] for row in rows])); baseline_coverage = float(np.mean([row["baseline_p10"] <= row["actual"] <= row["baseline_p90"] for row in rows])); misses = [row for row in rows if row["actual"] < row["p10"] or row["actual"] > row["p90"]]; lower_share = float(np.mean([row["actual"] < row["p10"] for row in misses])) if misses else 0.5
    return {"count": len(rows), "model_crps": model, "baseline_crps": baseline, "improvement": (baseline - model) / baseline if baseline else 0.0, "p10_p90_coverage": coverage, "p25_p75_coverage": core_coverage, "lower_miss_share": lower_share, "baseline_p10_p90_coverage": baseline_coverage, "mean_width": float(np.mean([row["p90"] - row["p10"] for row in rows]))}


def evaluate(rows: list[dict[str, Any]], contract: dict[str, Any], *, pit_leakage_count: int = 0, lineage_linkage: float = 1.0) -> dict[str, Any]:
    by_horizon = {str(h): _summary([row for row in rows if row["horizon"] == h]) for h in (1, 5, 21, 63)}
    long_mean = float(np.mean([by_horizon["21"]["improvement"], by_horizon["63"]["improvement"]]))
    by_origin: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["horizon"] in {21, 63}: by_origin[row["origin"]].append(row["model_crps"] - row["baseline_crps"])
    paired = np.asarray([np.mean(by_origin[key]) for key in sorted(by_origin)], dtype=float); ci = stationary_bootstrap_ci(paired, iterations=int(contract["evaluation"]["bootstrap"]["iterations"]), block_length=int(contract["evaluation"]["bootstrap"]["block_length_origins"]))
    conditional: dict[str, Any] = {}
    sign_underperformance = 0.0; q4_ok = True; stress_ok = True
    for horizon in (21, 63):
        selected = [row for row in rows if row["horizon"] == horizon]; absolute = np.asarray([abs(row["actual"]) for row in selected]); q4_cut = float(np.quantile(absolute, 0.75)); q4 = [row for row in selected if abs(row["actual"]) >= q4_cut]
        signs = {name: _summary([row for row in selected if (row["actual"] >= 0) is positive]) for name, positive in (("up", True), ("down", False))}
        sign_underperformance = max(sign_underperformance, max(0.0, -min(value["improvement"] for value in signs.values())))
        q4_summary = _summary(q4); q4_ok = q4_ok and q4_summary["p10_p90_coverage"] >= 0.65 and q4_summary["p10_p90_coverage"] >= q4_summary["baseline_p10_p90_coverage"]
        stress = {name: _summary([row for row in selected if row["stress_regime"] == name]) for name in sorted({row["stress_regime"] for row in selected})}
        required_stress = [value for key, value in stress.items() if key != "normal" and value["count"] >= 3]
        stress_ok = stress_ok and bool(required_stress) and all(value["p10_p90_coverage"] >= 0.70 for value in required_stress)
        conditional[str(horizon)] = {"actual_sign": signs, "extreme_move_q4": q4_summary, "stress_regime": stress}
    thresholds = contract["research_gate"]; reasons = []
    if pit_leakage_count > int(thresholds["pit_leakage_count_max"]): reasons.append("PIT leakage detected")
    if lineage_linkage < float(thresholds["lineage_linkage_min"]): reasons.append("lineage linkage below 100%")
    if long_mean < float(thresholds["long_horizon_mean_crps_improvement_min"]): reasons.append("21/63 mean CRPS improvement below 2%")
    if min(by_horizon["21"]["improvement"], by_horizon["63"]["improvement"]) <= 0: reasons.append("a long horizon failed positive improvement")
    if ci[1] > float(thresholds["paired_bootstrap_ci_upper_max"]): reasons.append("paired bootstrap CI upper bound is above zero")
    if sign_underperformance > float(thresholds["sign_side_max_underperformance"]): reasons.append("one return-sign side underperforms by more than 5%")
    if not q4_ok: reasons.append("extreme-move Q4 coverage gate failed")
    if not stress_ok: reasons.append("stress-regime coverage gate failed")
    coverage80 = thresholds["p10_p90_coverage_range"]; coverage50 = thresholds["p25_p75_coverage_range"]; miss_range = thresholds["lower_miss_share_range"]
    if any(not coverage80[0] <= by_horizon[str(h)]["p10_p90_coverage"] <= coverage80[1] for h in (1, 5, 21, 63)): reasons.append("p10-p90 coverage range gate failed")
    if any(not coverage50[0] <= by_horizon[str(h)]["p25_p75_coverage"] <= coverage50[1] for h in (1, 5, 21, 63)): reasons.append("p25-p75 coverage range gate failed")
    if any(not miss_range[0] <= by_horizon[str(h)]["lower_miss_share"] <= miss_range[1] for h in (1, 5, 21, 63)): reasons.append("lower/upper miss balance gate failed")
    monotone = all(row["p10"] <= row["p25"] <= row["p50"] <= row["p75"] <= row["p90"] for row in rows)
    finite_width = all(np.isfinite(row["p90"] - row["p10"]) and row["p90"] > row["p10"] for row in rows)
    if not monotone: reasons.append("quantile monotonicity gate failed")
    if not finite_width: reasons.append("finite positive width gate failed")
    return {"pass": not reasons, "reasons": reasons, "by_horizon": by_horizon, "long_horizon_mean_improvement": long_mean, "paired_loss_difference_90_ci": ci, "sign_side_max_underperformance": sign_underperformance, "conditional": conditional, "pit_leakage_count": pit_leakage_count, "lineage_linkage": lineage_linkage}
