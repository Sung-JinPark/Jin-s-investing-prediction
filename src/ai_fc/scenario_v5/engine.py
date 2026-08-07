"""Deterministic prior, soft entropy pooling, conditional fans, and diagnostics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp


QUANTILES = (5, 10, 25, 50, 75, 90, 95)


def reproduce_legacy_prior(snapshot: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
    model = snapshot["model"]
    params = model["gbm_parameters"]
    n_paths = int(model["n_paths"])
    horizon = int(model["horizon_business_days"])
    seed = int(model["seed"])
    anchor = float(snapshot["anchor"])
    mu = float(params["mu_daily_log_return"])
    sigma = float(params["sigma_daily_log_return"])
    dates = list(snapshot["quantile_table"]["trading_days"])
    if len(dates) != horizon:
        raise ValueError("snapshot trading-day count does not match model horizon")
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal((n_paths, horizon))
    ratios = np.exp(np.cumsum(mu - sigma ** 2 / 2.0 + sigma * shocks, axis=1))
    paths = anchor * ratios
    if not np.isfinite(paths).all() or float(paths.min()) <= 0:
        raise ValueError("prior contains non-finite or non-positive paths")
    return paths, dates


def condition_matrix(paths: np.ndarray, dates: list[str], snapshot: dict[str, Any],
                     evidence_views: list[dict[str, Any]]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    classification = snapshot["model"]["classification_date"]
    class_indexes = [index for index, day in enumerate(dates) if day <= classification]
    if not class_indexes:
        raise ValueError("classification date is outside prior horizon")
    class_end = class_indexes[-1]
    corr_indexes = [index for index, day in enumerate(dates)
                    if "2026-08-01" <= day <= "2026-10-31"]
    indicators: list[np.ndarray] = []
    used: list[dict[str, Any]] = []
    for row in evidence_views:
        if not row.get("used_numerically"):
            continue
        condition = row["condition"]
        if condition.startswith("max_close"):
            values = (paths[:, :class_end + 1] > float(snapshot["ath"])).any(axis=1)
        elif condition.startswith("min_close"):
            values = (paths[:, corr_indexes] <= float(snapshot["corr10"])).any(axis=1)
        elif condition.startswith("classification_close"):
            values = paths[:, class_end] > float(snapshot["reference_price"])
        else:
            raise ValueError(f"unsupported numerical EvidenceView condition: {condition}")
        indicators.append(values.astype(float))
        used.append(row)
    matrix = np.column_stack(indicators) if indicators else np.empty((paths.shape[0], 0))
    return matrix, used


def entropy_pool(matrix: np.ndarray, views: list[dict[str, Any]],
                 config: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    n_paths, n_views = matrix.shape
    prior = np.full(n_paths, 1.0 / n_paths, dtype=float)
    if n_views == 0:
        return prior, {"status": "no_numerical_views", "converged": True, "iterations": 0}
    targets = np.asarray([float(row["target"]) for row in views], dtype=float)
    strengths = np.asarray([float(row["quality"]["effective_strength"]) for row in views])
    tolerances = np.asarray([float(row["tolerance"]) for row in views])
    kappa = strengths / np.square(tolerances)
    log_prior = np.log(prior)

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        logits = log_prior + matrix @ theta
        value = logsumexp(logits) - float(targets @ theta) + 0.5 * float(np.sum(theta ** 2 / kappa))
        weights = np.exp(logits - logsumexp(logits))
        gradient = matrix.T @ weights - targets + theta / kappa
        return value, gradient

    result = minimize(
        lambda theta: objective(theta), np.zeros(n_views), jac=True, method="L-BFGS-B",
        options={
            "maxiter": int(config["maximum_iterations"]),
            "gtol": float(config["gradient_tolerance"]),
            "ftol": 1e-15,
            "maxls": 50,
        },
    )
    logits = log_prior + matrix @ result.x
    weights = np.exp(logits - logsumexp(logits))
    fitted = matrix.T @ weights
    max_weight = float(weights.max())
    top_n = max(1, math.ceil(n_paths * 0.01))
    top_share = float(np.partition(weights, -top_n)[-top_n:].sum())
    ess = float(1.0 / np.square(weights).sum())
    fits = []
    for index, row in enumerate(views):
        fits.append({
            "view_id": row["view_id"],
            "prior_probability": float(matrix[:, index].mean()),
            "target_probability": float(targets[index]),
            "posterior_probability": float(fitted[index]),
            "residual": float(fitted[index] - targets[index]),
            "tolerance": float(tolerances[index]),
            "effective_strength": float(strengths[index]),
            "dual_parameter": float(result.x[index]),
        })
    diagnostics = {
        "status": "ok" if result.success else "solver_warning",
        "converged": bool(result.success),
        "solver_message": str(result.message),
        "iterations": int(result.nit),
        "objective": float(result.fun),
        "weight_sum": float(weights.sum()),
        "effective_sample_size": ess,
        "maximum_path_weight": max_weight,
        "top_one_percent_weight_share": top_share,
        "view_fit": fits,
        "gates": {
            "ess": ess >= float(config["overall_ess_minimum"]),
            "maximum_path_weight": max_weight <= float(config["maximum_single_path_weight"]),
            "top_one_percent_share": top_share <= float(config["maximum_top_one_percent_weight_share"]),
        },
    }
    diagnostics["gates_pass"] = all(diagnostics["gates"].values())
    if not np.isclose(weights.sum(), 1.0, atol=float(config["numerical_tolerance"])):
        raise ValueError("posterior weights do not sum to one")
    if (weights < 0).any() or not np.isfinite(weights).all():
        raise ValueError("posterior weights are invalid")
    return weights, diagnostics


def weighted_quantile(values: np.ndarray, weights: np.ndarray,
                      quantiles: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights) - 0.5 * sorted_weights
    cumulative /= sorted_weights.sum()
    return np.interp(quantiles, cumulative, sorted_values)


def _bands(paths: np.ndarray, weights: np.ndarray, anchor: float) -> dict[str, list[float]]:
    extended = np.column_stack((np.full(paths.shape[0], anchor), paths))
    result = {f"p{quantile}": [] for quantile in QUANTILES}
    levels = np.asarray(QUANTILES, dtype=float) / 100.0
    for column in range(extended.shape[1]):
        values = weighted_quantile(extended[:, column], weights, levels)
        for index, quantile in enumerate(QUANTILES):
            result[f"p{quantile}"].append(round(float(values[index]), 2))
    return result


def _path_metrics(paths: np.ndarray) -> dict[str, np.ndarray]:
    log_returns = np.diff(np.log(paths), axis=1)
    running_max = np.maximum.accumulate(paths, axis=1)
    drawdowns = paths / running_max - 1.0
    weekly_levels = paths[:, 4::5]
    weekly = np.diff(np.log(weekly_levels), axis=1)
    signs = np.sign(weekly)
    direction_changes = (signs[:, 1:] * signs[:, :-1] < 0).sum(axis=1)
    return {
        "terminal": paths[:, -1],
        "daily_volatility": log_returns.std(axis=1, ddof=1) * math.sqrt(252.0),
        "weekly_volatility": weekly.std(axis=1, ddof=1) * math.sqrt(52.0),
        "maximum_drawdown": drawdowns.min(axis=1),
        "underwater": (drawdowns < -0.02).mean(axis=1),
        "direction_changes": direction_changes.astype(float),
        "continuation": (log_returns[:, 1:] * log_returns[:, :-1] > 0).mean(axis=1),
    }


def _weighted_l1_centrality(values: np.ndarray, weights: np.ndarray,
                            scale: np.ndarray | float) -> np.ndarray:
    """Exact weighted-medoid objective under coordinate-wise L1 distance."""
    matrix = values[:, None] if values.ndim == 1 else values
    scales = np.broadcast_to(np.asarray(scale, dtype=float), (matrix.shape[1],))
    result = np.zeros(matrix.shape[0], dtype=float)
    for column in range(matrix.shape[1]):
        column_values = matrix[:, column]
        order = np.argsort(column_values, kind="stable")
        sorted_values = column_values[order]
        sorted_weights = weights[order]
        cumulative_weight = np.cumsum(sorted_weights)
        cumulative_value = np.cumsum(sorted_weights * sorted_values)
        total_value = cumulative_value[-1]
        left_weight = cumulative_weight - sorted_weights
        left_value = cumulative_value - sorted_weights * sorted_values
        right_weight = 1.0 - cumulative_weight
        right_value = total_value - cumulative_value
        deviations = (sorted_values * left_weight - left_value
                      + right_value - sorted_values * right_weight)
        unsorted = np.empty_like(deviations)
        unsorted[order] = deviations
        result += unsorted / max(float(scales[column]), 1e-12)
    return result / matrix.shape[1]


def _representative(paths: np.ndarray, weights: np.ndarray, indexes: np.ndarray,
                    bands: dict[str, list[float]], config: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    scenario_paths = paths[indexes]
    scenario_weights = weights[indexes]
    normalized = scenario_weights / scenario_weights.sum()
    metrics = _path_metrics(scenario_paths)
    eligible = normalized >= normalized.max() * float(config["minimum_relative_path_weight"])
    terminal_lo, terminal_hi = config["terminal_percentile"]
    t_lo, t_hi = weighted_quantile(metrics["terminal"], normalized,
                                   np.asarray([terminal_lo, terminal_hi]) / 100.0)
    eligible &= (metrics["terminal"] >= t_lo) & (metrics["terminal"] <= t_hi)
    gate_ranges = {
        "daily_volatility": config["ordinary_metric_percentile"],
        "weekly_volatility": config["ordinary_metric_percentile"],
        "underwater": config["ordinary_metric_percentile"],
        "maximum_drawdown": config["wide_metric_percentile"],
        "direction_changes": config["wide_metric_percentile"],
        "continuation": config["continuation_metric_percentile"],
    }
    for key, percentiles in gate_ranges.items():
        lo, hi = weighted_quantile(
            metrics[key], normalized, np.asarray(percentiles, dtype=float) / 100.0)
        eligible &= (metrics[key] >= lo) & (metrics[key] <= hi)
    local = np.flatnonzero(eligible)
    relaxed = False
    if local.size == 0:
        local = np.arange(len(indexes))
        relaxed = True
    target = np.asarray(bands["p50"][1:], dtype=float)
    trajectory = _weighted_l1_centrality(
        scenario_paths, normalized, np.maximum(target, 1.0))
    terminal_scale = max(float(weighted_quantile(
        metrics["terminal"], normalized, np.asarray([0.75]))[0]
        - weighted_quantile(metrics["terminal"], normalized, np.asarray([0.25]))[0]), 1.0)
    score_all = (float(config["score_weights"]["trajectory"]) * trajectory
                 + float(config["score_weights"]["terminal"])
                 * _weighted_l1_centrality(metrics["terminal"], normalized, terminal_scale))
    for key in ("daily_volatility", "weekly_volatility", "maximum_drawdown",
                "underwater", "direction_changes", "continuation"):
        lo, hi = weighted_quantile(metrics[key], normalized, np.asarray([0.25, 0.75]))
        metric_scale = max(float(hi - lo), 1e-6)
        score_all += (float(config["score_weights"][key])
                      * _weighted_l1_centrality(metrics[key], normalized, metric_scale))
    score = score_all[local]
    score += float(config["score_weights"]["posterior_weight_penalty"]) * (
        1.0 - normalized[local] / normalized.max())
    best_score = float(score.min())
    ties = local[np.isclose(score, best_score, rtol=0, atol=1e-14)]
    chosen_local = int(ties[np.argmin(indexes[ties])])
    chosen_global = int(indexes[chosen_local])
    return chosen_global, {
        "rule": "actual_weighted_medoid_v2",
        "member_path": True,
        "eligible_count": int(local.size),
        "gate_relaxed": relaxed,
        "score": best_score,
        "objective": "exact_weighted_l1_medoid_with_registered_metric_penalties",
    }


def _turning_points(values: np.ndarray) -> set[int]:
    changes = np.diff(np.log(values))
    signs = np.sign(changes)
    return set((np.flatnonzero(signs[1:] * signs[:-1] < 0) + 1).tolist())


def _same_shape(representatives: dict[str, np.ndarray], config: dict[str, Any]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    keys = sorted(representatives)
    for left_index, left in enumerate(keys):
        for right in keys[left_index + 1:]:
            a = representatives[left]
            b = representatives[right]
            a_ret = np.diff(np.log(a[::5]))
            b_ret = np.diff(np.log(b[::5]))
            correlation = float(np.corrcoef(a_ret, b_ret)[0, 1])
            a_norm = a / a[0]
            b_norm = b / b[0]
            distance = float(np.sqrt(np.mean(np.square(np.log(a_norm) - np.log(b_norm)))))
            a_turn = _turning_points(a[::5])
            b_turn = _turning_points(b[::5])
            union = a_turn | b_turn
            overlap = float(len(a_turn & b_turn) / len(union)) if union else 1.0
            flagged = (
                correlation >= float(config["weekly_return_correlation_high"])
                and overlap >= float(config["turning_point_overlap_high"])
                and distance <= float(config["normalized_trajectory_distance_low"])
            )
            pairs.append({
                "pair": f"{left}/{right}",
                "weekly_return_correlation": correlation,
                "turning_point_overlap": overlap,
                "normalized_trajectory_distance": distance,
                "same_shape_flag": flagged,
            })
    return {"pairs": pairs, "gate_pass": not any(row["same_shape_flag"] for row in pairs)}


def build_conditional_outputs(paths: np.ndarray, dates: list[str], weights: np.ndarray,
                              snapshot: dict[str, Any], model_contract: dict[str, Any]) -> dict[str, Any]:
    classification = snapshot["model"]["classification_date"]
    class_end = max(index for index, day in enumerate(dates) if day <= classification)
    hit_ath = (paths[:, :class_end + 1] > float(snapshot["ath"])).any(axis=1)
    above_reference = paths[:, class_end] > float(snapshot["reference_price"])
    masks = {"S1": hit_ath, "S2": ~hit_ath & above_reference, "S3": ~hit_ath & ~above_reference}
    if not np.array_equal(masks["S1"] | masks["S2"] | masks["S3"], np.ones(paths.shape[0], dtype=bool)):
        raise ValueError("scenario partition is not exhaustive")
    if any((masks[a] & masks[b]).any() for a, b in (("S1", "S2"), ("S1", "S3"), ("S2", "S3"))):
        raise ValueError("scenario partition overlaps")
    labels = {
        "S1": "ATH breakout by classification date",
        "S2": "No ATH breakout; classification close above fixed reference",
        "S3": "No ATH breakout; classification close at/below fixed reference",
    }
    colors = {"S1": "#ff4f17", "S2": "#ff9d19", "S3": "#c9002d"}
    scenario_rows: dict[str, Any] = {}
    representatives: dict[str, np.ndarray] = {}
    for key, mask in masks.items():
        indexes = np.flatnonzero(mask)
        scenario_mass = float(weights[indexes].sum())
        conditional_weights = weights[indexes] / scenario_mass
        ess = float(1.0 / np.square(conditional_weights).sum())
        bands = _bands(paths[indexes], conditional_weights, float(snapshot["anchor"]))
        path_id, selection = _representative(
            paths, weights, indexes, bands, model_contract["representative"])
        values = np.concatenate(([float(snapshot["anchor"])], paths[path_id]))
        representatives[key] = values
        scenario_rows[key] = {
            "label": labels[key],
            "color": colors[key],
            "probability": scenario_mass,
            "probability_space": "scenario_conditional",
            "path_count": int(indexes.size),
            "weighted_effective_sample_size": ess,
            "representative_path_id": path_id,
            "representative_path_values": [round(float(value), 2) for value in values],
            "representative_selection": selection,
            "bands": bands,
            "band_visibility": {
                "p25_p75": ess >= 500,
                "p10_p90": ess >= 1000,
                "p05_p95": ess >= 2000,
            },
        }
    same_shape = _same_shape(representatives, model_contract["same_shape_gate"])
    above_anchor = (paths > float(snapshot["anchor"])).T @ weights
    above_ath = (paths > float(snapshot["ath"])).T @ weights
    corr10_touch = np.maximum.accumulate(
        paths <= float(snapshot["corr10"]), axis=1).T @ weights
    return {
        "dates": [snapshot["asof"], *dates],
        "unconditional_bands": _bands(paths, weights, float(snapshot["anchor"])),
        "unconditional_prob_above_anchor": [0.0, *[float(value) for value in above_anchor]],
        "unconditional_prob_above_ath": [0.0, *[float(value) for value in above_ath]],
        "unconditional_prob_touch_corr10": [0.0, *[float(value) for value in corr10_touch]],
        "scenarios": scenario_rows,
        "same_shape_diagnostics": same_shape,
        "representative_lines_visible": same_shape["gate_pass"],
    }
