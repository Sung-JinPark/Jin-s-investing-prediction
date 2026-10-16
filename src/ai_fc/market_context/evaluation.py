"""Empirical forecast scores and grouped forward-only research evaluation.

Scores use actual simulated distributions, including parameter mixtures.  All
price-distribution scores have index-level units; probabilities are fractions.
No function here appends a ledger, changes a model, or authorizes promotion.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from .contracts import SEED, MarketContextError, aware, canonical_hash
from .model import _finite

MODELS = ("combined", "market_only", "event_only", "fhs")


def score_distribution(values1d: Any, actual: float) -> dict[str, Any]:
    """Exact equal-weight empirical CRPS and WIS for50/80/90% intervals.

    ``median_error`` is signed forecast median minus outcome.  Intervals are
    pointwise.  Missing/invalid values are rejected, never silently dropped.
    """
    values = np.asarray(values1d, dtype=float)
    outcome = _finite(actual, "actual")
    if values.ndim != 1 or len(values) == 0 or not np.all(np.isfinite(values)):
        raise MarketContextError("distribution must be a non-empty finite one-dimensional array")
    ordered = np.sort(values)
    count = len(ordered)
    # Centering removes catastrophic cancellation when index levels are large.
    pairwise_half = np.dot(2 * np.arange(1, count + 1) - count - 1, ordered - ordered[0]) / count ** 2
    crps = float(np.mean(np.abs(values - outcome)) - pairwise_half)
    if crps < 0:
        raise MarketContextError("negative CRPS from unstable distribution arithmetic")
    quantile_values = np.percentile(values, [5, 10, 25, 50, 75, 90, 95])
    quantiles = dict(zip(("p05", "p10", "p25", "p50", "p75", "p90", "p95"), map(float, quantile_values)))
    median_error = quantiles["p50"] - outcome
    weighted = .5 * abs(median_error)
    coverage = {}
    for alpha, low, high, name in ((.5, "p25", "p75", "coverage50"),
                                   (.2, "p10", "p90", "coverage80"),
                                   (.1, "p05", "p95", "coverage90")):
        lower, upper = quantiles[low], quantiles[high]
        interval_score = (upper - lower + 2 / alpha * max(lower - outcome, 0)
                          + 2 / alpha * max(outcome - upper, 0))
        weighted += alpha / 2 * interval_score
        coverage[name] = bool(lower <= outcome <= upper)
    return {"crps": crps, "wis": float(weighted / 3.5), "median_error": float(median_error),
            "absolute_median_error": abs(float(median_error)), **coverage, "quantiles": quantiles,
            "sample_count": count, "score_method": "empirical_equal_weight_v1",
            "intervals_are_simultaneous": False}


def score_path_functionals(
    paths: Any, actual_path: Any, *, anchor: float, barrier: float | None = None,
) -> dict[str, Any]:
    """Score MDD magnitude and daily-discrete fixed lower-barrier first touch."""
    values = np.asarray(paths, dtype=float)
    realized = np.asarray(actual_path, dtype=float)
    start = _finite(anchor, "anchor")
    threshold = _finite(barrier, "barrier") if barrier is not None else .9 * start
    if (start <= 0 or threshold <= 0 or threshold >= start or values.ndim != 2 or len(values) == 0
            or realized.ndim != 1 or values.shape[1] != len(realized) or len(realized) == 0
            or not np.all(np.isfinite(values)) or not np.all(np.isfinite(realized))
            or np.any(values <= 0) or np.any(realized <= 0)):
        raise MarketContextError("path scores require aligned finite positive daily paths and a lower barrier")
    forecast = np.column_stack((np.full(len(values), start), values))
    actual = np.concatenate(([start], realized))
    mdd = np.max(1 - forecast / np.maximum.accumulate(forecast, axis=1), axis=1)
    actual_mdd = float(np.max(1 - actual / np.maximum.accumulate(actual)))
    touch = np.any(values <= threshold, axis=1)
    observed = bool(np.any(realized <= threshold))
    probability = float(touch.mean())
    return {"max_drawdown": score_distribution(mdd, actual_mdd),
            "actual_max_drawdown_magnitude": actual_mdd, "drawdown_unit": "fraction_nonnegative",
            "touch_barrier": threshold, "touch_probability": probability, "touch_outcome": observed,
            "touch_brier": (probability - int(observed)) ** 2,
            "monitoring": "daily_discrete", "probability_unit": "fraction"}


def _nonoverlap(rows: list[dict[str, Any]]) -> int:
    previous_end = None
    count = 0
    for row in sorted(rows, key=lambda item: (item["anchor_date"], item["target_date"])):
        if previous_end is None or row["anchor_date"] >= previous_end:
            count += 1
            previous_end = row["target_date"]
    return count


def _score_values(score: dict[str, Any], model: str) -> dict[str, float]:
    result = {key: _finite(score.get(key), f"{model}.{key}")
              for key in ("crps", "wis", "median_error")}
    if result["crps"] < 0 or result["wis"] < 0:
        raise MarketContextError("proper distribution scores must be nonnegative")
    for key in ("coverage50", "coverage80"):
        value = score.get(key)
        if isinstance(value, bool):
            result[key] = float(value)
        else:
            result[key] = _finite(value, f"{model}.{key}")
            if result[key] not in (0, 1):
                raise MarketContextError("per-resolution coverage must be an observed0/1 indicator")
    return result


def evaluate_resolutions(
    rows: list[dict[str, Any]], *, bootstrap_count: int = 1000,
    use_63_for_promotion: bool = False,
) -> dict[str, Any]:
    """Group all horizons by earliest issued origin and report paired criteria.

    A passed numerical criterion remains research evidence, never automatic
    promotion.  Missing FHS or ablation scores are explicit comparison gaps.
    """
    if isinstance(bootstrap_count, bool) or not isinstance(bootstrap_count, int) or bootstrap_count < 1:
        raise MarketContextError("bootstrap_count must be a positive integer")
    earliest: dict[str, tuple[Any, str]] = {}
    dedup: dict[tuple[str, int], dict[str, Any]] = {}
    forecast_origins: dict[str, tuple[str, Any]] = {}
    exclusions: dict[str, int] = {}
    for row in rows:
        if row.get("data_grade") != "captured_forward":
            exclusions["not_captured_forward"] = exclusions.get("not_captured_forward", 0) + 1
            continue
        try:
            anchor = date.fromisoformat(str(row["anchor_date"])).isoformat()
            target = date.fromisoformat(str(row["target_date"])).isoformat()
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketContextError("resolution anchor/target must be ISO dates") from exc
        if target <= anchor:
            raise MarketContextError("resolution target must follow anchor")
        if not row.get("as_of") or not row.get("available_at"):
            raise MarketContextError("resolution timestamps are required")
        issued, available = aware(row["as_of"]), aware(row["available_at"])
        if available <= issued:
            raise MarketContextError("resolution cannot be known before forecast issuance")
        if available.date() < date.fromisoformat(target):
            raise MarketContextError("resolution availability precedes target date")
        horizon = row.get("horizon")
        if isinstance(horizon, bool) or horizon not in (5, 21, 63):
            exclusions["non_preregistered_horizon"] = exclusions.get("non_preregistered_horizon", 0) + 1
            continue
        identity = str(row.get("forecast_id", ""))
        if not identity:
            raise MarketContextError("forecast_id is required")
        if identity in forecast_origins and forecast_origins[identity] != (anchor, issued):
            raise MarketContextError("forecast_id has inconsistent origin metadata across horizons")
        forecast_origins[identity] = (anchor, issued)
        key = (identity, horizon)
        if key in dedup and canonical_hash(dedup[key]) != canonical_hash(row):
            raise MarketContextError("conflicting duplicate forecast/horizon resolution")
        dedup[key] = row
        candidate = (issued, identity)
        if anchor not in earliest or candidate < earliest[anchor]:
            earliest[anchor] = candidate
    selected = [row for row in dedup.values()
                if (aware(row["as_of"]), str(row["forecast_id"])) == earliest[str(row["anchor_date"])]]
    selected.sort(key=lambda row: (row["anchor_date"], row["horizon"]))
    discarded = len(dedup) - len(selected)
    if discarded:
        exclusions["later_issuance_same_anchor"] = discarded
    comparisons: dict[str, Any] = {}
    for model in MODELS:
        by_horizon: dict[str, Any] = {}
        for horizon in (5, 21, 63):
            pairs = []
            for row in selected:
                scores = row.get("scores", {})
                if row["horizon"] != horizon or scores.get("baseline") is None or scores.get(model) is None:
                    continue
                pairs.append((row, _score_values(scores["baseline"], "baseline"),
                              _score_values(scores[model], model)))
            if not pairs:
                by_horizon[str(horizon)] = {"status": "missing_comparison", "origin_count": 0}
                continue
            base = np.asarray([pair[1]["crps"] for pair in pairs])
            candidate_scores = np.asarray([pair[2]["crps"] for pair in pairs])
            differences = candidate_scores - base
            block = 63 if use_63_for_promotion or any(row["horizon"] == 63 for row in selected) else 21
            # Each sampled row is one complete forecast origin.  Horizons are
            # never stacked or sampled as additional independent observations.
            rng = np.random.default_rng(SEED + 67867967 + horizon)
            means = []
            for _ in range(bootstrap_count):
                starts = rng.integers(0, len(pairs), size=int(np.ceil(len(pairs) / block)))
                indexes = np.concatenate([(start + np.arange(block)) % len(pairs) for start in starts])[:len(pairs)]
                means.append(float(differences[indexes].mean()))
            base_mean, candidate_mean = float(base.mean()), float(candidate_scores.mean())
            baseline_coverage = {level: float(np.mean([pair[1][f"coverage{level}"] for pair in pairs]))
                                 for level in (50, 80)}
            candidate_coverage = {level: float(np.mean([pair[2][f"coverage{level}"] for pair in pairs]))
                                  for level in (50, 80)}
            # A nominal deviation outside a95% binomial-normal reference band
            # is reported; overlapping outcomes mean it is diagnostic, not a
            # claim of an independent binomial hypothesis test.
            coverage_failures = []
            effective_count = max(1, _nonoverlap([pair[0] for pair in pairs]))
            for level in (50, 80):
                nominal = level / 100
                tolerance = 1.96 * np.sqrt(nominal * (1 - nominal) / effective_count)
                if abs(candidate_coverage[level] - nominal) > tolerance:
                    coverage_failures.append(f"coverage{level}_outside_dependence_adjusted_reference")
                if candidate_coverage[level] < baseline_coverage[level] - .02:
                    coverage_failures.append(f"coverage{level}_more_than2pp_below_baseline")
            by_horizon[str(horizon)] = {
                "status": "scored", "origin_count": len(pairs),
                "nonoverlapping_blocks": effective_count,
                "baseline_crps": base_mean, "candidate_crps": candidate_mean,
                "relative_crps_improvement": 1 - candidate_mean / base_mean if base_mean > 0 else None,
                "mean_paired_delta_crps": float(differences.mean()),
                "one_sided95_delta_crps_upper": float(np.percentile(means, 95)),
                "baseline_wis": float(np.mean([pair[1]["wis"] for pair in pairs])),
                "candidate_wis": float(np.mean([pair[2]["wis"] for pair in pairs])),
                "candidate_median_mae": float(np.mean([abs(pair[2]["median_error"]) for pair in pairs])),
                "baseline_coverage": {str(key): value for key, value in baseline_coverage.items()},
                "candidate_coverage": {str(key): value for key, value in candidate_coverage.items()},
                "coverage_failures": coverage_failures, "bootstrap_block_sessions": block,
            }
        comparisons[model] = by_horizon
    primary = comparisons["combined"]["21"]
    reasons = []
    if primary.get("origin_count", 0) < 252:
        reasons.append("fewer_than252_unique_matured_primary_origins")
    if primary.get("nonoverlapping_blocks", 0) < 12:
        reasons.append("fewer_than12_nonoverlapping21_session_blocks")
    if primary.get("relative_crps_improvement") is None or primary["relative_crps_improvement"] < .02:
        reasons.append("primary_crps_improvement_below2percent_or_unavailable")
    if primary.get("one_sided95_delta_crps_upper", float("inf")) >= 0:
        reasons.append("primary_one_sided95_evidence_not_established")
    for horizon in (5, 63):
        secondary = comparisons["combined"][str(horizon)]
        improvement = secondary.get("relative_crps_improvement")
        if improvement is None or improvement < -.02:
            reasons.append(f"secondary{horizon}_missing_or_more_than2percent_worse")
        if secondary.get("coverage_failures"):
            reasons.append(f"secondary{horizon}_coverage_diagnostic_failure")
    if primary.get("coverage_failures"):
        reasons.append("primary_coverage_diagnostic_failure")
    if use_63_for_promotion and comparisons["combined"]["63"].get("nonoverlapping_blocks", 0) < 8:
        reasons.append("fewer_than8_nonoverlapping63_session_blocks")
    missing = {model: [h for h, info in result.items() if info["status"] == "missing_comparison"]
               for model, result in comparisons.items()}
    insufficient = any(reason.startswith("fewer_than") for reason in reasons)
    return {"status": "insufficient_data" if insufficient else "research_criteria_met" if not reasons else "research_criteria_not_met",
            "comparisons": comparisons, "comparison_gaps": missing,
            "complete_comparison_set": not any(missing.values()), "reasons": reasons,
            "unique_origin_count": len(earliest), "excluded": exclusions,
            "primary_horizon": 21, "use_63_for_promotion": use_63_for_promotion,
            "bootstrap_unit": "whole_origin_contiguous_blocks", "automatic_promotion": False,
            "predictive_validation": "not_established"}
