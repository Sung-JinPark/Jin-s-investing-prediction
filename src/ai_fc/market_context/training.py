"""Purged, strongly regularized PIT training/evaluation; no durable writes.

Targets are realized cumulative LOG returns, not pre-computed residuals.
The unchanged GBM median is h*(mean_log_return-sigma_log_return**2/2).
All public artifacts contain raw-feature-equivalent coefficients.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
from scipy.special import ndtr

from .contracts import (
    MIN_EVENTS, MIN_TRAIN_SESSIONS, SEED, TRAIN_HORIZONS, TRAIN_WEIGHTS,
    MarketContextError, aware, canonical_hash,
)
from .model import FEATURE_COUNT, _finite, _vector, horizon_basis

RIDGE_CANDIDATES = (0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0)
BLOCK_SESSIONS = 63
EMBARGO_SESSIONS = 5


def _prepare(samples: list[dict[str, Any]], cutoff: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not cutoff:
        raise MarketContextError("training/evaluation cutoff must be explicit")
    end = aware(cutoff)
    rows = []
    excluded: Counter[str] = Counter()
    seen: set[str] = set()
    for original in samples:
        origin = str(original.get("origin_date", ""))
        if not origin or not original.get("as_of"):
            raise MarketContextError("training samples require origin_date and as_of")
        stamp = aware(original["as_of"])
        try:
            from datetime import date
            day = date.fromisoformat(origin)
        except ValueError as exc:
            raise MarketContextError("origin_date must be an ISO date") from exc
        if day > stamp.date():
            raise MarketContextError("origin_date is after sample as_of")
        if origin in seen:
            raise MarketContextError("duplicate training origin_date")
        seen.add(origin)
        if stamp > end:
            excluded["origin_after_train_cutoff"] += 1
            continue
        row = dict(original)
        row["stamp"] = stamp
        row["state"] = _vector(row.get("state"), "sample.state")
        row["baseline_mu"] = _finite(row.get("baseline_mu"), "baseline_mu")
        row["baseline_sigma"] = _finite(row.get("baseline_sigma"), "baseline_sigma")
        if row["baseline_sigma"] < 0:
            raise MarketContextError("baseline_sigma must be nonnegative")
        if row.get("state_available_at") and aware(row["state_available_at"]) > stamp:
            raise MarketContextError("future state at training origin")
        components = row.get("state_by_family", {})
        if not isinstance(components, dict):
            raise MarketContextError("state_by_family must be a mapping")
        row["state_by_family"] = {str(key): _vector(value, "state_by_family")
                                  for key, value in components.items()}
        event_ids = row.get("event_ids_by_family", {})
        if not isinstance(event_ids, dict):
            raise MarketContextError("event_ids_by_family must be a mapping")
        for family, values in event_ids.items():
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                raise MarketContextError(f"invalid unique event ids for {family}")
        targets = row.get("targets", {})
        available = row.get("target_available_at", {})
        if any(str(h) not in targets or str(h) not in available for h in TRAIN_HORIZONS):
            excluded["incomplete_horizon_labels"] += 1
            continue
        if any(not available[str(h)] for h in TRAIN_HORIZONS):
            raise MarketContextError("target availability timestamps must be explicit")
        target_stamps = [aware(available[str(h)]) for h in TRAIN_HORIZONS]
        if any(value <= stamp for value in target_stamps):
            raise MarketContextError("target availability must follow origin as_of")
        if any(value > end for value in target_stamps):
            excluded["unmatured_target"] += 1
            continue
        row["target_stamps"] = target_stamps
        row["target_array"] = np.asarray([_finite(targets[str(h)], "target log return")
                                           for h in TRAIN_HORIZONS])
        baseline = (row["baseline_mu"] - row["baseline_sigma"] ** 2 / 2) * np.asarray(TRAIN_HORIZONS)
        row["residual_array"] = row["target_array"] - baseline
        rows.append(row)
    rows.sort(key=lambda row: (row["origin_date"], row["stamp"]))
    if any(b["stamp"] <= a["stamp"] for a, b in zip(rows, rows[1:])):
        raise MarketContextError("training as_of timestamps must increase with origin dates")
    return rows, dict(excluded)


def _family_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    ids: dict[str, set[str]] = {}
    supplied: dict[str, int] = {}
    for row in rows:
        for family, values in row.get("event_ids_by_family", {}).items():
            ids.setdefault(str(family), set()).update(values)
        for family, value in row.get("event_family_counts", {}).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MarketContextError("event_family_counts require nonnegative unique-event counts")
            supplied[str(family)] = max(supplied.get(str(family), 0), value)
    # Exact IDs take precedence.  Cumulative audited counts are never summed.
    return {key: len(ids[key]) if key in ids else supplied[key] for key in sorted(ids.keys() | supplied.keys())}


def _states(rows: list[dict[str, Any]], active: set[str]) -> np.ndarray:
    result = []
    for row in rows:
        parts = row["state_by_family"]
        if parts:
            vector = sum((value for key, value in parts.items() if key in active), np.zeros(FEATURE_COUNT))
        else:
            families = set(row.get("event_ids_by_family", {})) | set(row.get("event_family_counts", {}))
            if np.any(row["state"] != 0) and not families.issubset(active):
                raise MarketContextError("mixed unsupported aggregate state requires state_by_family")
            vector = row["state"] if active and families else np.zeros(FEATURE_COUNT)
        result.append(vector)
    return np.asarray(result, dtype=float)


def _fit(rows: list[dict[str, Any]], penalty: float) -> dict[str, Any]:
    counts = _family_counts(rows)
    active = {key for key, value in counts.items() if value >= MIN_EVENTS}
    states = _states(rows, active)
    basis = horizon_basis(TRAIN_HORIZONS)
    design = states[:, None, :] * basis[None, :, :]
    residuals = np.asarray([row["residual_array"] for row in rows])
    scale = np.sqrt(np.mean(np.square(design), axis=(0, 1)))
    scale[scale == 0] = 1.0  # A structurally absent regressor retains coefficient0.
    target_scale = np.std(residuals, axis=0, ddof=1) if len(rows) > 1 else np.ones(3)
    target_scale[target_scale == 0] = 1.0
    weights = np.sqrt(np.asarray(TRAIN_WEIGHTS) / len(rows))
    x = (design / scale[None, None, :] / target_scale[None, :, None]
         * weights[None, :, None]).reshape(-1, FEATURE_COUNT)
    y = (residuals / target_scale[None, :] * weights[None, :]).reshape(-1)
    gram = x.T @ x
    try:
        scaled = np.linalg.solve(gram + penalty * np.eye(FEATURE_COUNT), x.T @ y)
    except np.linalg.LinAlgError as exc:
        raise MarketContextError("ridge solve failed") from exc
    coef = scaled / scale
    if not np.all(np.isfinite(coef)):
        raise MarketContextError("non-finite fitted coefficients")
    return {"coef": coef, "scale": scale, "target_scale": target_scale,
            "active_families": sorted(active), "event_family_counts": counts,
            "effective_degrees_of_freedom": float(np.trace(np.linalg.solve(
                gram + penalty * np.eye(FEATURE_COUNT), gram)))}


def _loss(rows: list[dict[str, Any]], fitted: dict[str, Any]) -> float:
    if not rows:
        return math.inf
    states = _states(rows, set(fitted["active_families"]))
    predictions = (states * fitted["coef"]) @ horizon_basis(TRAIN_HORIZONS).T
    actual = np.asarray([row["residual_array"] for row in rows])
    return float(np.mean(np.sum(np.square((actual - predictions) / fitted["target_scale"])
                                * np.asarray(TRAIN_WEIGHTS)[None, :], axis=1)))


def _selection_loss(rows: list[dict[str, Any]], fitted: dict[str, Any]) -> float:
    """Lambda selection uses primary21 proper predictive score, never a path."""
    states = _states(rows, set(fitted["active_families"]))
    primary = TRAIN_HORIZONS.index(21)
    correction = (states * fitted["coef"]) @ horizon_basis([21])[0]
    actual = np.asarray([row["target_array"][primary] for row in rows])
    mean = np.asarray([(row["baseline_mu"] - row["baseline_sigma"] ** 2 / 2) * 21 for row in rows])
    sigma = np.asarray([row["baseline_sigma"] * math.sqrt(21) for row in rows])
    return float(_normal_crps(actual, mean + correction, sigma).mean())


def _split(rows: list[dict[str, Any]], split: int, stop: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validation = rows[split:stop]
    if not validation:
        return [], []
    # The five dated-origin embargo precedes the validation origin.  Then all
    # targets crossing that earlier fit cutoff are purged, independently of h.
    fit_index = max(0, split - EMBARGO_SESSIONS)
    cutoff = rows[fit_index]["stamp"]
    training = [row for row in rows[:fit_index] if max(row["target_stamps"]) < cutoff]
    return training, validation


def _select_penalty(rows: list[dict[str, Any]]) -> tuple[float, list[dict[str, Any]]]:
    scores = {value: [] for value in RIDGE_CANDIDATES}
    audit = []
    for start_fraction, stop_fraction in ((.60, .80), (.80, 1.0)):
        train, validation = _split(rows, int(len(rows) * start_fraction), int(len(rows) * stop_fraction))
        if len(train) < 63 or not validation:
            continue
        audit.append({"train_count": len(train), "validation_count": len(validation),
                      "last_train_target_at": max(max(row["target_stamps"]) for row in train).isoformat(),
                      "first_validation_as_of": validation[0]["as_of"]})
        for value in RIDGE_CANDIDATES:
            scores[value].append(_selection_loss(validation, _fit(train, value)))
    valid = [(float(np.mean(losses)), -value, value) for value, losses in scores.items() if losses]
    # An unidentifiable/tied CV selects strongest shrinkage, never weakest.
    chosen = min(valid)[2] if valid else max(RIDGE_CANDIDATES)
    return chosen, audit


def _blocked(cutoff: str, reason: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
    artifact = {"status": "blocked", "reason": reason, "coef": [0.0] * FEATURE_COUNT,
                "scale": [1.0] * FEATURE_COUNT, "bootstrap_coefficients": [],
                "coefficient_units": "raw_feature", "train_cutoff": aware(cutoff).isoformat(),
                "active_families": [], "diagnostics": diagnostics,
                "predictive_validation": "not_established"}
    artifact["artifact_sha256"] = canonical_hash(artifact)
    return artifact


def fit_model(
    samples: list[dict[str, Any]], *, train_cutoff: str,
    minimum_sessions: int = MIN_TRAIN_SESSIONS, bootstrap_count: int = 200,
) -> dict[str, Any]:
    """Fit the fixed model after nested, purged chronological lambda selection.

    ``event_ids_by_family`` are stable incident IDs, not revision/article IDs.
    ``state_by_family`` lets each CV fold enforce its own30-event floor before
    aggregation; an aggregate mixed-family state cannot be safely demixed.
    """
    if minimum_sessions < 2 or bootstrap_count < 0:
        raise MarketContextError("invalid minimum_sessions or bootstrap_count")
    rows, excluded = _prepare(samples, train_cutoff)
    diagnostics: dict[str, Any] = {"matured_sessions": len(rows), "excluded": excluded,
                                   "minimum_sessions": minimum_sessions,
                                   "event_family_counts": _family_counts(rows),
                                   "purge_horizon_sessions": BLOCK_SESSIONS,
                                   "embargo_origin_sessions": EMBARGO_SESSIONS}
    if len(rows) < minimum_sessions:
        return _blocked(train_cutoff, "insufficient_matured_pit_sessions", diagnostics)
    if not any(value >= MIN_EVENTS for value in diagnostics["event_family_counts"].values()):
        return _blocked(train_cutoff, "insufficient_unique_events_per_family", diagnostics)
    outer = []
    for start_fraction, stop_fraction in ((.70, .85), (.85, 1.0)):
        training, validation = _split(rows, int(len(rows) * start_fraction), int(len(rows) * stop_fraction))
        if len(training) < 126 or not validation:
            continue
        penalty, inner_audit = _select_penalty(training)
        fitted = _fit(training, penalty)
        outer.append({"selected_ridge": penalty, "train_count": len(training),
                      "validation_count": len(validation), "weighted_scaled_mse": _loss(validation, fitted),
                      "primary21_log_return_crps": _selection_loss(validation, fitted),
                      "inner_splits": inner_audit,
                      "last_train_target_at": max(max(row["target_stamps"]) for row in training).isoformat(),
                      "first_validation_as_of": validation[0]["as_of"]})
    penalty, inner_audit = _select_penalty(rows)
    fitted = _fit(rows, penalty)
    if not np.any(fitted["coef"] != 0):
        return _blocked(train_cutoff, "no_estimable_numerical_signal", diagnostics)
    rng = np.random.default_rng(SEED + 32452843)
    bootstrap = []
    for _ in range(bootstrap_count):
        # Sample whole63-origin blocks, preserving all horizons/families within
        # each origin.  No second simulated daily-price innovation is added.
        starts = rng.integers(0, len(rows), size=math.ceil(len(rows) / BLOCK_SESSIONS))
        indexes = np.concatenate([(start + np.arange(BLOCK_SESSIONS)) % len(rows) for start in starts])[:len(rows)]
        resampled = [rows[int(index)] for index in indexes]
        bootstrap.append(_fit(resampled, penalty)["coef"].tolist())
    diagnostics.update({"outer_splits": outer, "final_inner_splits": inner_audit,
                        "selected_ridge": penalty, "fit_intercept": False, "center_features": False,
                        "coefficient_units": "raw_feature", "horizon_loss_weights": list(TRAIN_WEIGHTS),
                        "lambda_selection_score": "primary21_log_return_crps",
                        "effective_degrees_of_freedom": fitted["effective_degrees_of_freedom"],
                        "target_scales": fitted["target_scale"].tolist(),
                        "bootstrap_block_sessions": BLOCK_SESSIONS,
                        "bootstrap_count": bootstrap_count})
    artifact = {"status": "ready", "coef": fitted["coef"].tolist(), "scale": fitted["scale"].tolist(),
                "bootstrap_coefficients": bootstrap, "coefficient_units": "raw_feature",
                "train_cutoff": aware(train_cutoff).isoformat(), "active_families": fitted["active_families"],
                "event_family_counts": fitted["event_family_counts"], "diagnostics": diagnostics,
                "predictive_validation": "not_established"}
    artifact["artifact_sha256"] = canonical_hash(artifact)
    return artifact


def _normal_crps(actual: np.ndarray, mean: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    result = np.abs(actual - mean)
    valid = sigma > 0
    z = np.zeros_like(actual)
    z[valid] = (actual[valid] - mean[valid]) / sigma[valid]
    result[valid] = sigma[valid] * (z[valid] * (2 * ndtr(z[valid]) - 1)
                                  + 2 * np.exp(-z[valid] ** 2 / 2) / math.sqrt(2 * math.pi)
                                  - 1 / math.sqrt(math.pi))
    return result


def evaluate_model(
    samples: list[dict[str, Any]], coefficients: dict[str, Any], *, as_of: str,
    bootstrap_count: int = 1000,
) -> dict[str, Any]:
    """Held-out paired Gaussian-log-return CRPS; no claim of empirical promotion.

    Evaluation uses the location-only predictive model.  Parameter-mixture
    scores must be measured from the stored forecast distribution separately.
    """
    if bootstrap_count < 1:
        raise MarketContextError("evaluation bootstrap_count must be positive")
    if coefficients.get("status") != "ready":
        raise MarketContextError("held-out evaluation requires a ready model")
    if not coefficients.get("train_cutoff"):
        raise MarketContextError("held-out model train_cutoff must be explicit")
    rows, excluded = _prepare(samples, as_of)
    fit_cutoff = aware(coefficients.get("train_cutoff"))
    if any(row["stamp"] <= fit_cutoff for row in rows):
        raise MarketContextError("evaluation origins overlap model training cutoff")
    if not rows:
        return {"status": "insufficient_data", "matured_origins": 0, "excluded": excluded,
                "predictive_validation": "not_established"}
    coef = _vector(coefficients.get("coef"), "coef")
    states = _states(rows, set(coefficients.get("active_families", [])))
    correction = (states * coef) @ horizon_basis(TRAIN_HORIZONS).T
    actual = np.asarray([row["target_array"] for row in rows])
    mean = np.asarray([(row["baseline_mu"] - row["baseline_sigma"] ** 2 / 2)
                       * np.asarray(TRAIN_HORIZONS) for row in rows])
    sigma = np.asarray([row["baseline_sigma"] * np.sqrt(TRAIN_HORIZONS) for row in rows])
    baseline = _normal_crps(actual, mean, sigma)
    candidate = _normal_crps(actual, mean + correction, sigma)
    difference = candidate - baseline
    rng = np.random.default_rng(SEED + 49979687)
    primary = TRAIN_HORIZONS.index(21)
    block = max(TRAIN_HORIZONS)
    boot_means = []
    for _ in range(bootstrap_count):
        starts = rng.integers(0, len(rows), size=math.ceil(len(rows) / block))
        indexes = np.concatenate([(start + np.arange(block)) % len(rows) for start in starts])[:len(rows)]
        boot_means.append(float(difference[indexes, primary].mean()))
    upper = float(np.percentile(boot_means, 95))
    by_horizon = {}
    for index, horizon in enumerate(TRAIN_HORIZONS):
        baseline_mean, candidate_mean = float(baseline[:, index].mean()), float(candidate[:, index].mean())
        by_horizon[str(horizon)] = {"baseline_crps": baseline_mean, "candidate_crps": candidate_mean,
                                    "relative_improvement": (1 - candidate_mean / baseline_mean)
                                    if baseline_mean > 0 else None}
    enough = len(rows) >= 252 and len(rows) // 21 >= 12 and len(rows) // 63 >= 8
    primary_improvement = by_horizon["21"]["relative_improvement"]
    secondary_ok = all(by_horizon[str(h)]["relative_improvement"] is not None
                       and by_horizon[str(h)]["relative_improvement"] >= -.02 for h in (5, 63))
    passes = enough and primary_improvement is not None and primary_improvement >= .02 and upper < 0 and secondary_ok
    return {"status": "research_criteria_met" if passes else "research_criteria_not_met",
            "matured_origins": len(rows), "nonoverlapping_21_session_blocks": len(rows) // 21,
            "nonoverlapping_63_session_blocks": len(rows) // 63,
            "by_horizon": by_horizon, "primary_delta_crps_one_sided95_upper": upper,
            "bootstrap_block_sessions": block, "score_space": "cumulative_log_return",
            "parameter_mixture_scored": False, "automatic_promotion": False,
            "predictive_validation": "not_established", "excluded": excluded}
