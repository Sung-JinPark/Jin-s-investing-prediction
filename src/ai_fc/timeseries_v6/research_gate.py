"""Unchanged V6 integrity, research, and operational Gate calculation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def stationary_bootstrap_ci(values: np.ndarray, *, iterations: int = 5000, block_length: int = 13, seed: int = 62026) -> list[float]:
    data = np.asarray(values, dtype=float); rng = np.random.default_rng(seed); means = np.empty(iterations)
    for iteration in range(iterations):
        indexes = np.empty(len(data), dtype=int); indexes[0] = rng.integers(len(data))
        for position in range(1, len(data)):
            indexes[position] = rng.integers(len(data)) if rng.random() < 1 / block_length else (indexes[position - 1] + 1) % len(data)
        means[iteration] = np.mean(data[indexes])
    return [float(np.quantile(means, 0.05)), float(np.quantile(means, 0.95))]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    model = float(np.mean([row["model_crps"] for row in rows])); baseline = float(np.mean([row["baseline_crps"] for row in rows]))
    return {
        "count": len(rows), "model_crps": model, "baseline_crps": baseline,
        "improvement": (baseline - model) / baseline,
        "p10_p90_coverage": float(np.mean([row["p10"] <= row["actual"] <= row["p90"] for row in rows])),
        "p25_p75_coverage": float(np.mean([row["p25"] <= row["actual"] <= row["p75"] for row in rows])),
        "baseline_coverage": float(np.mean([row["baseline_p10"] <= row["actual"] <= row["baseline_p90"] for row in rows])),
    }


def evaluate_research_gate(
    rows: list[dict[str, Any]],
    *,
    provenance_rate: float | None = None,
    pit_leakage_count: int | None = None,
    contract_runtime_mismatch_count: int | None = None,
    receipt_observation_link_rate: float | None = None,
    operational_pass: bool | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if verification is not None:
        provenance_rate = float(verification["pit"]["active_feature_provenance_rate"])
        pit_leakage_count = int(verification["pit"]["pit_leakage_count"])
        contract_runtime_mismatch_count = int(verification["runtime"]["contract_runtime_mismatch_count"])
        receipt_observation_link_rate = float(verification["archive"]["receipt_observation_link_rate"])
        operational_pass = bool(verification["operational"]["pass"])
    if None in {provenance_rate, pit_leakage_count, contract_runtime_mismatch_count, receipt_observation_link_rate, operational_pass}:
        raise ValueError("all integrity and operational coordinates must be independently supplied")
    integrity_reasons = []
    if pit_leakage_count != 0: integrity_reasons.append("pit_leakage_count_nonzero")
    if provenance_rate < 1.0: integrity_reasons.append("active_feature_provenance_below_one")
    if receipt_observation_link_rate < 1.0: integrity_reasons.append("receipt_observation_link_rate_below_one")
    if contract_runtime_mismatch_count != 0: integrity_reasons.append("contract_runtime_mismatch")
    by_horizon = {str(h): _summary([row for row in rows if row["horizon"] == h]) for h in (1, 5, 21, 63)}
    long_mean = float(np.mean([by_horizon["21"]["improvement"], by_horizon["63"]["improvement"]]))
    paired: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["horizon"] in {21, 63}: paired[row["origin"]].append(row["model_crps"] - row["baseline_crps"])
    ci = stationary_bootstrap_ci(np.asarray([np.mean(paired[key]) for key in sorted(paired)]))
    research_reasons = []
    if long_mean < 0.02: research_reasons.append("long_horizon_mean_crps_improvement_below_2pct")
    if any(by_horizon[str(h)]["improvement"] <= 0 for h in (21, 63)): research_reasons.append("long_horizon_not_individually_positive")
    if ci[1] > 0: research_reasons.append("paired_stationary_bootstrap_ci_upper_above_zero")
    sign_under = 0.0
    for horizon in (21, 63):
        horizon_rows = [row for row in rows if row["horizon"] == horizon]
        for positive in (False, True):
            subset = [row for row in horizon_rows if (row["actual"] >= 0) == positive]
            if subset: sign_under = max(sign_under, max(0.0, -_summary(subset)["improvement"]))
        absolute = np.asarray([abs(row["actual"]) for row in horizon_rows]); threshold = np.quantile(absolute, 0.75)
        q4 = _summary([row for row in horizon_rows if abs(row["actual"]) >= threshold])
        if q4["p10_p90_coverage"] < 0.65 or q4["p10_p90_coverage"] < q4["baseline_coverage"]:
            research_reasons.append(f"h{horizon}_extreme_q4_coverage")
        for regime in ("gfc", "pandemic", "tightening", "rebound"):
            subset = [row for row in horizon_rows if row["stress_regime"] == regime]
            if len(subset) < 20 or _summary(subset)["p10_p90_coverage"] < 0.70:
                research_reasons.append(f"h{horizon}_{regime}_coverage_or_sample")
    if sign_under > 0.05: research_reasons.append("return_sign_side_underperformance_above_5pct")
    for horizon in (1, 5, 21, 63):
        summary = by_horizon[str(horizon)]
        if not 0.76 <= summary["p10_p90_coverage"] <= 0.84: research_reasons.append(f"h{horizon}_p10_p90_coverage")
        if not 0.45 <= summary["p25_p75_coverage"] <= 0.55: research_reasons.append(f"h{horizon}_p25_p75_coverage")
    integrity_pass = not integrity_reasons; research_pass = not research_reasons
    return {
        "schema_version": 1,
        "integrity_gate": {"pass": integrity_pass, "reasons": integrity_reasons, "pit_leakage_count": pit_leakage_count, "receipt_observation_link_rate": receipt_observation_link_rate, "active_feature_provenance_rate": provenance_rate, "contract_runtime_mismatch_count": contract_runtime_mismatch_count},
        "research_gate": {"pass": research_pass, "reasons": sorted(set(research_reasons)), "by_horizon": by_horizon, "long_horizon_mean_crps_improvement": long_mean, "paired_stationary_bootstrap_90_ci": ci, "sign_side_max_underperformance": sign_under},
        "operational_gate": {"pass": operational_pass, "reasons": [] if operational_pass else ["source_freshness_or_snapshot_compatibility"]},
        "numbers_visible": bool(integrity_pass and research_pass and operational_pass),
        "status": "research_gate_pass" if integrity_pass and research_pass and operational_pass else "shadow_gate_hold",
    }
