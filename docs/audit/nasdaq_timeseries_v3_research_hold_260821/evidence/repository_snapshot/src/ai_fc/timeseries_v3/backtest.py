"""Fixed-comparator pseudo-OOS evaluation and conditional research gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


def empirical_crps(samples: np.ndarray, actual: float) -> float:
    values = np.sort(np.asarray(samples, dtype=float).reshape(-1))
    if values.size == 0:
        raise ValueError("CRPS requires samples")
    first = float(np.mean(np.abs(values - actual)))
    indexes = np.arange(1, values.size + 1, dtype=float)
    pairwise = float(2.0 * np.sum((2 * indexes - values.size - 1) * values) / (values.size * values.size))
    return first - 0.5 * pairwise


def pinball_loss(quantile: float, prediction: float, actual: float) -> float:
    error = actual - prediction
    return float(max(quantile * error, (quantile - 1.0) * error))


def tail_weighted_crps(samples: np.ndarray, actual: float) -> float:
    """Finite-grid weighted CRPS with extra mass in both distribution tails."""
    levels = np.array([0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])
    predictions = np.quantile(np.asarray(samples, dtype=float), levels)
    weights = 1.0 + 4.0 * np.abs(levels - 0.50)
    losses = np.array([
        pinball_loss(float(level), float(prediction), actual)
        for level, prediction in zip(levels, predictions, strict=True)
    ])
    return float(2.0 * np.average(losses, weights=weights))


def energy_score(samples: np.ndarray, actual: np.ndarray, rng: np.random.Generator) -> float:
    values = np.asarray(samples, dtype=float)
    actual = np.asarray(actual, dtype=float)
    first = float(np.mean(np.linalg.norm(values - actual, axis=1)))
    paired = values[rng.permutation(len(values))]
    return first - 0.5 * float(np.mean(np.linalg.norm(values - paired, axis=1)))


def stationary_bootstrap_mean_ci(
    losses: np.ndarray, *, block_length: int, confidence: float, iterations: int,
    seed: int,
) -> tuple[float, float]:
    values = np.asarray(losses, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(iterations)
    restart = 1.0 / block_length
    for iteration in range(iterations):
        indexes = np.empty(values.size, dtype=int)
        indexes[0] = rng.integers(0, values.size)
        for position in range(1, values.size):
            indexes[position] = (
                rng.integers(0, values.size) if rng.random() < restart else (indexes[position - 1] + 1) % values.size
            )
        means[iteration] = np.mean(values[indexes])
    alpha = (1.0 - confidence) / 2.0
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))


def quartile_labels(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    boundaries = np.quantile(array[np.isfinite(array)], [0.25, 0.50, 0.75])
    return np.array([f"Q{1 + int(np.searchsorted(boundaries, value, side='right'))}" for value in array])


@dataclass(frozen=True)
class OriginScore:
    origin: str
    horizon: int
    actual: float
    model_crps: float
    baseline_crps: float
    p10: float
    p90: float
    baseline_p10: float
    baseline_p90: float
    trend_regime: str
    stress_regime: str
    event_status: str
    origin_volatility: float = float("nan")
    component_staleness: str = "unknown"
    pit_value: float = float("nan")
    up_probability: float = float("nan")
    mean_pinball: float = float("nan")
    tail_weighted_crps: float = float("nan")
    quantiles: dict[str, float] = field(default_factory=dict)

    @property
    def loss_difference(self) -> float:
        return self.model_crps - self.baseline_crps


def _group_summary(rows: list[OriginScore], labels: list[str]) -> dict[str, dict[str, float | int]]:
    output: dict[str, dict[str, float | int]] = {}
    for label in sorted(set(labels)):
        selected = [row for row, value in zip(rows, labels, strict=True) if value == label]
        hits = sum(row.p10 <= row.actual <= row.p90 for row in selected)
        baseline_hits = sum(row.baseline_p10 <= row.actual <= row.baseline_p90 for row in selected)
        model = float(np.mean([row.model_crps for row in selected]))
        baseline = float(np.mean([row.baseline_crps for row in selected]))
        output[label] = {
            "count": len(selected), "model_crps": model, "baseline_crps": baseline,
            "crps_improvement": (baseline - model) / baseline if baseline else 0.0,
            "p10_p90_coverage": hits / len(selected),
            "baseline_p10_p90_coverage": baseline_hits / len(selected),
        }
    return output


def conditional_tables(rows: list[OriginScore]) -> dict[str, Any]:
    move_labels = list(quartile_labels(np.abs([row.actual for row in rows])))
    volatility = np.array([row.origin_volatility for row in rows], dtype=float)
    if np.isfinite(volatility).any():
        finite_labels = quartile_labels(volatility[np.isfinite(volatility)])
        iterator = iter(finite_labels)
        volatility_labels = [str(next(iterator)) if np.isfinite(value) else "unknown" for value in volatility]
    else:
        volatility_labels = ["unknown"] * len(rows)
    return {
        "actual_sign": _group_summary(rows, ["up" if row.actual >= 0 else "down" for row in rows]),
        "absolute_move_quartile": _group_summary(rows, move_labels),
        "trend_regime": _group_summary(rows, [row.trend_regime for row in rows]),
        "stress_regime": _group_summary(rows, [row.stress_regime for row in rows]),
        "event_status": _group_summary(rows, [row.event_status for row in rows]),
        "volatility_quartile": _group_summary(rows, volatility_labels),
        "component_staleness": _group_summary(rows, [row.component_staleness for row in rows]),
    }


def pit_histogram(rows: list[OriginScore], bins: int = 10) -> dict[str, Any]:
    values = np.array([row.pit_value for row in rows], dtype=float)
    values = values[np.isfinite(values)]
    edges = np.linspace(0.0, 1.0, bins + 1)
    counts, _ = np.histogram(np.clip(values, 0.0, 1.0), bins=edges)
    return {"edges": edges.tolist(), "counts": counts.tolist(), "sample_n": int(values.size)}


def direction_reliability(rows: list[OriginScore], bins: int = 10) -> list[dict[str, float | int]]:
    probabilities = np.array([row.up_probability for row in rows], dtype=float)
    actual = np.array([row.actual >= 0.0 for row in rows], dtype=float)
    output: list[dict[str, float | int]] = []
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        mask = np.isfinite(probabilities) & (probabilities >= lower) & (
            probabilities <= upper if index == bins - 1 else probabilities < upper
        )
        if not mask.any():
            continue
        output.append({
            "bin_low": lower, "bin_high": upper, "count": int(mask.sum()),
            "mean_forecast": float(np.mean(probabilities[mask])),
            "realized_frequency": float(np.mean(actual[mask])),
        })
    return output


def evaluate_research_gate(
    rows: list[OriginScore], *, leakage_count: int, lineage_linkage: float,
    block_length: int = 13, bootstrap_iterations: int = 2000, seed: int = 3,
) -> dict[str, Any]:
    long_rows = [row for row in rows if row.horizon in {21, 63}]
    by_horizon: dict[int, dict[str, float]] = {}
    for horizon in (21, 63):
        selected = [row for row in long_rows if row.horizon == horizon]
        model = float(np.mean([row.model_crps for row in selected]))
        baseline = float(np.mean([row.baseline_crps for row in selected]))
        by_horizon[horizon] = {"model_crps": model, "baseline_crps": baseline, "improvement": (baseline - model) / baseline}
    paired_by_origin: dict[str, list[float]] = {}
    for row in long_rows:
        paired_by_origin.setdefault(row.origin, []).append(row.loss_difference)
    paired = np.array([np.mean(values) for values in paired_by_origin.values()])
    ci = stationary_bootstrap_mean_ci(
        paired, block_length=block_length, confidence=0.90,
        iterations=bootstrap_iterations, seed=seed,
    )
    tables = {horizon: conditional_tables([row for row in rows if row.horizon == horizon]) for horizon in (21, 63)}
    pit = {str(horizon): pit_histogram([row for row in rows if row.horizon == horizon]) for horizon in (1, 5, 21, 63)}
    reliability = {
        str(horizon): direction_reliability([row for row in rows if row.horizon == horizon])
        for horizon in (1, 5, 21, 63)
    }
    score_tables: dict[str, dict[str, Any]] = {}
    for horizon in (1, 5, 21, 63):
        selected = [row for row in rows if row.horizon == horizon]
        if not selected:
            score_tables[str(horizon)] = {
                "origins": 0, "model_crps": None, "baseline_crps": None,
                "improvement": None, "mean_pinball": None, "tail_weighted_crps": None,
            }
            continue
        model = float(np.mean([row.model_crps for row in selected]))
        baseline = float(np.mean([row.baseline_crps for row in selected]))
        score_tables[str(horizon)] = {
            "origins": len(selected), "model_crps": model, "baseline_crps": baseline,
            "improvement": (baseline - model) / baseline,
            "mean_pinball": float(np.nanmean([row.mean_pinball for row in selected])),
            "tail_weighted_crps": float(np.nanmean([row.tail_weighted_crps for row in selected])),
        }
    sign_improvements = [
        float(table["crps_improvement"])
        for horizon in tables.values() for table in horizon["actual_sign"].values()
    ]
    q4 = [tables[horizon]["absolute_move_quartile"].get("Q4", {}) for horizon in tables]
    stress = [
        table for horizon in tables.values() for name, table in horizon["stress_regime"].items()
        if name in {"great_financial_crisis_2008", "pandemic_2020", "tightening_2022", "rebound"}
    ]
    mean_improvement = float(np.mean([by_horizon[h]["improvement"] for h in (21, 63)]))
    reasons: list[str] = []
    if leakage_count:
        reasons.append("PIT leakage is nonzero")
    if abs(lineage_linkage - 1.0) > 1e-12:
        reasons.append("lineage linkage is below 100%")
    if mean_improvement < 0.02:
        reasons.append("21/63 fixed-baseline mean CRPS improvement is below 2%")
    if any(by_horizon[h]["improvement"] <= 0 for h in (21, 63)):
        reasons.append("a long horizon does not improve on the fixed baseline")
    if ci[1] > 0:
        reasons.append("paired overlap-aware 90% CI upper bound is above zero")
    if sign_improvements and min(sign_improvements) < -0.05:
        reasons.append("up/down conditional CRPS degrades by more than 5%")
    if any(table and (float(table["p10_p90_coverage"]) < 0.65 or float(table["p10_p90_coverage"]) + 1e-12 < float(table["baseline_p10_p90_coverage"])) for table in q4):
        reasons.append("extreme-move Q4 coverage gate failed")
    if any(float(table["p10_p90_coverage"]) < 0.70 for table in stress):
        reasons.append("a required stress regime coverage is below 70%")
    return {
        "pass": not reasons, "reasons": reasons, "by_horizon": by_horizon,
        "long_horizon_mean_improvement": mean_improvement,
        "paired_loss_difference_90_ci": list(ci), "conditional_tables": tables,
        "score_tables": score_tables, "pit_histograms": pit,
        "direction_reliability": reliability,
        "fixed_comparator": "fixed_anchor_ensemble_v3", "row_wise_oracle_used": False,
    }
