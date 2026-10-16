"""Pure, daily market-context kernels for the isolated GRAPH02 preview.

The original GBM convention is deliberately reproduced.  Coefficients are
stored in RAW feature units; ``scale`` is an audit value, never applied twice.
Nothing in this module reads/writes a ledger or an official snapshot.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import rankdata

from ai_fc.quant.mc import gbm_paths
from .contracts import (
    AXES, HALF_LIVES, HORIZON, PATH_COUNT, SEED, TRAIN_HORIZONS,
    MarketContextError, aware,
)

FEATURE_COUNT = len(AXES) * len(HALF_LIVES)
QUANTILES = (5, 10, 25, 50, 75, 90, 95)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, (bool, str)):
        raise MarketContextError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketContextError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise MarketContextError(f"{label} must be a finite number")
    return result


def _vector(value: Any, label: str) -> np.ndarray:
    if not isinstance(value, (list, tuple, np.ndarray)):
        raise MarketContextError(f"{label} must have {FEATURE_COUNT} finite values")
    if np.asarray(value).shape != (FEATURE_COUNT,):
        raise MarketContextError(f"{label} must have {FEATURE_COUNT} finite values")
    return np.asarray([_finite(item, label) for item in value], dtype=float)


def _dates(values: list[str], label: str) -> list[date]:
    try:
        result = [date.fromisoformat(str(value)) for value in values]
    except (TypeError, ValueError) as exc:
        raise MarketContextError(f"{label} must contain ISO dates") from exc
    if not result or any(b <= a for a, b in zip(result, result[1:])):
        raise MarketContextError(f"{label} must be non-empty and strictly increasing")
    return result


def horizon_basis(horizons: Any) -> np.ndarray:
    """(horizon, feature) basis; extra drift is exactly zero after session63."""
    steps = np.asarray(horizons, dtype=int)
    if steps.ndim != 1 or np.any(steps < 0):
        raise MarketContextError("horizons must be nonnegative integers")
    rho = np.power(2.0, -1.0 / np.asarray(HALF_LIVES, dtype=float))
    capped = np.minimum(steps, max(TRAIN_HORIZONS))[:, None]
    kernels = rho[None, :] * (1.0 - np.power(rho[None, :], capped)) / (1.0 - rho[None, :])
    return np.tile(kernels, (1, len(AXES)))


def score_state(
    events: list[dict[str, Any]], *, as_of: str, session_dates: list[str],
    eligible_families: set[str] | None = None,
) -> dict[str, Any]:
    """Decay PIT-selected revisions on an exchange-session clock.

    Upstream should provide ``effective_session`` from its exchange calendar.
    Without one we conservatively wait for the NEXT dated session, because a
    date alone cannot establish whether publication preceded an early close.
    Missing surprise is an explicit reference row, never fabricated as news0.
    """
    if not as_of:
        raise MarketContextError("score_state requires an explicit as_of")
    cutoff = aware(as_of)
    from .ledger import annotate_incident_groups
    # Group only after temporal selection: later re-reporting must never erase
    # an earlier knowable fact, and every source row remains available to audit.
    for event in events:
        for field in ("available_at", "retrieved_at"):
            if event.get(field) is not None and aware(event[field]) > cutoff:
                raise MarketContextError(f"future event {field}")
    events = annotate_incident_groups(events)
    sessions = _dates(session_dates, "session_dates")
    if sessions[-1] > cutoff.astimezone(ZoneInfo("America/New_York")).date():
        raise MarketContextError("session_dates contains a future completed session")
    eligible = set(eligible_families or ())
    reference = np.zeros(FEATURE_COUNT)
    numerical = np.zeros(FEATURE_COUNT)
    by_family: dict[str, np.ndarray] = {}
    event_ids: dict[str, set[str]] = {}
    receipt: list[dict[str, Any]] = []
    seen: set[str] = set()
    observed = 0
    for event in events:
        revision = str(event.get("revision_id", ""))
        if not revision or revision in seen:
            raise MarketContextError("events require unique revision_id values")
        seen.add(revision)
        if not event.get("available_at"):
            raise MarketContextError("event available_at is required")
        available = aware(event["available_at"])
        if available > cutoff:
            raise MarketContextError(f"future event: {revision}")
        axis = str(event.get("axis", ""))
        if axis not in AXES:
            raise MarketContextError(f"unregistered event axis: {axis}")
        family = str(event.get("family", ""))
        if not family:
            raise MarketContextError("event family is required")
        row = {**event, "revision_id": revision, "family": family, "axis": axis,
               "available_at": available.isoformat(), "used_numerically": False}
        surprise = event.get("surprise_z")
        if surprise is None:
            row["exclusion_reason"] = ("duplicate_incident_no_additional_shock"
                                       if event.get("incident_group_status") == "duplicate"
                                       else "missing_validated_surprise")
            row["reason"] = row["exclusion_reason"]
            receipt.append(row)
            continue
        raw = _finite(surprise, "surprise_z")
        observed += 1
        effective = event.get("effective_session")
        published_day = available.astimezone(ZoneInfo("America/New_York")).date()
        if effective:
            try:
                effective_day = date.fromisoformat(str(effective))
            except ValueError as exc:
                raise MarketContextError("effective_session must be an ISO date") from exc
            if effective_day < published_day:
                raise MarketContextError("effective_session precedes availability")
            assignment = "registered_exchange_session"
        else:
            effective_day = next((day for day in sessions if day > published_day), None)
            assignment = "conservative_next_session_without_close_timestamp"
        row["assignment_basis"] = assignment
        if effective_day is not None and effective_day <= sessions[-1] and effective_day not in sessions:
            raise MarketContextError("effective_session missing from completed exchange sessions")
        # Known weekend/after-close news already belongs in the next forecast.
        # It has not yet aged by a completed exchange session, so age is0.
        age = sum(day > effective_day for day in sessions) if effective_day is not None else 0
        offset = AXES.index(axis) * len(HALF_LIVES)
        component = raw * np.power(2.0, -age / np.asarray(HALF_LIVES, dtype=float))
        reference[offset:offset + len(HALF_LIVES)] += component
        allow = event.get("numerical_eligible") is True and family in eligible
        row.update({"surprise_z": raw, "age_sessions": age,
                    "effective_session": effective_day.isoformat() if effective_day is not None else None,
                    "used_numerically": allow})
        if event.get("numerical_eligible") is True:
            # Keep provenance-approved family components for later floor-gated
            # training, even before that family has30 captured unique events.
            by_family.setdefault(family, np.zeros(FEATURE_COUNT))[offset:offset + len(HALF_LIVES)] += component
            event_ids.setdefault(family, set()).add(str(event.get("event_id") or revision))
        if allow:
            numerical[offset:offset + len(HALF_LIVES)] += component
            row.pop("exclusion_reason", None)
            row.pop("reason", None)
        else:
            row["exclusion_reason"] = "family_or_asset_mapping_not_approved"
        if row.get("exclusion_reason"):
            row["reason"] = row["exclusion_reason"]
        receipt.append(row)
    if not np.all(np.isfinite(reference)) or not np.all(np.isfinite(numerical)):
        raise MarketContextError("event aggregation overflow")
    return {
        "reference_vector": reference.tolist(), "numerical_vector": numerical.tolist(),
        "state_by_family": {family: values.tolist() for family, values in sorted(by_family.items())},
        "event_ids_by_family": {family: sorted(values) for family, values in sorted(event_ids.items())},
        "events": receipt,
        "axis_scores": {axis: {"reference": reference[i * 3:(i + 1) * 3].tolist(),
                               "numerical": numerical[i * 3:(i + 1) * 3].tolist()}
                        for i, axis in enumerate(AXES)},
        "coverage": {"event_count": len(events), "observed_surprise_count": observed,
                     "numerical_event_count": sum(row["used_numerically"] for row in receipt),
                     "missing_surprise_count": len(events) - observed},
        "feature_order": [f"{axis}:half_life_{half}" for axis in AXES for half in HALF_LIVES],
    }


def project_paths(
    closes: list[float], *, state: list[float], coefficients: dict[str, Any] | None,
    future_dates: list[str], n_paths: int = PATH_COUNT, seed: int = SEED,
) -> dict[str, Any]:
    dates = _dates(future_dates, "future_dates")
    if len(dates) != HORIZON:
        raise MarketContextError(f"future_dates must cover {HORIZON} exchange sessions")
    prices = np.asarray([_finite(value, "close") for value in closes])
    if len(prices) < 253 or np.any(prices <= 0):
        raise MarketContextError("at least253 finite positive aligned closes are required")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths <= 0:
        raise MarketContextError("n_paths must be a positive integer")
    vector = _vector(state, "state")
    baseline = gbm_paths(prices.tolist(), lookback=252, horizon=HORIZON, n=n_paths, seed=seed)
    if not np.all(np.isfinite(baseline)) or np.any(baseline <= 0):
        raise MarketContextError("baseline generated non-finite or non-positive paths")
    basis = horizon_basis(np.arange(1, HORIZON + 1))
    coef = np.zeros(FEATURE_COUNT)
    bootstrap = None
    if coefficients and coefficients.get("status", "ready") == "ready":
        coef = _vector(coefficients.get("coef"), "coef")
        # scale is an audit value: fitting has already converted to raw units.
        scale = _vector(coefficients.get("scale", np.ones(FEATURE_COUNT)), "scale")
        if np.any(scale <= 0):
            raise MarketContextError("coefficient scale must be strictly positive")
        if coefficients.get("coefficient_units", "raw_feature") != "raw_feature":
            raise MarketContextError("unsupported coefficient_units")
        if coefficients.get("bootstrap_coefficients") is not None:
            bootstrap = np.asarray(coefficients["bootstrap_coefficients"], dtype=float)
            if bootstrap.ndim != 2 or bootstrap.shape[1] != FEATURE_COUNT or not np.all(np.isfinite(bootstrap)):
                raise MarketContextError("bootstrap_coefficients must be finite (draws,21)")
            if len(bootstrap) == 0:
                bootstrap = None
    delta = basis @ (vector * coef)
    has_effect = bool(np.any(delta != 0.0))
    if bootstrap is not None and np.any(vector != 0.0):
        # A separate stream preserves every baseline daily innovation.
        assignments = np.random.default_rng(seed + 104729).integers(0, len(bootstrap), size=n_paths)
        parameter_delta = (bootstrap[assignments] * vector[None, :]) @ basis.T
        # Center draws on the fitted correction, not on bootstrap Monte Carlo bias.
        parameter_delta -= ((bootstrap.mean(axis=0) - coef) * vector) @ basis.T
        has_effect = has_effect or bool(np.any(parameter_delta != 0.0))
    else:
        parameter_delta = delta[None, :]
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        candidate = baseline * np.exp(parameter_delta) if has_effect else baseline.copy()
    if not np.all(np.isfinite(candidate)) or np.any(candidate <= 0):
        raise MarketContextError("context adjustment produced invalid prices; clipping is prohibited")
    attribution = {
        axis: {str(h): float(np.dot((vector * coef)[i * 3:(i + 1) * 3],
                                    horizon_basis([h])[0, i * 3:(i + 1) * 3]))
               for h in TRAIN_HORIZONS}
        for i, axis in enumerate(AXES)
    }
    return {"baseline_paths": baseline, "candidate_paths": candidate,
            "delta_log": delta.tolist(), "attribution": attribution,
            "attribution_basis": {axis: (vector * coef)[i * 3:(i + 1) * 3].tolist()
                                  for i, axis in enumerate(AXES)},
            "numerical_context_applied": has_effect,
            "parameter_uncertainty_applied": bootstrap is not None and has_effect,
            "coefficient_units": "raw_feature", "incremental_drift_last_session": max(TRAIN_HORIZONS)}


def _path_hash(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values, dtype="<f8").tobytes()).hexdigest()


def _representative(paths: np.ndarray, anchor: float) -> dict[str, Any]:
    count, horizon = paths.shape
    daily = np.column_stack((np.full(count, anchor), paths))
    log_returns = np.diff(np.log(daily), axis=1)
    drawdowns = np.max(1.0 - daily / np.maximum.accumulate(daily, axis=1), axis=1)
    sign_change = (np.mean(np.sign(log_returns[:, 1:]) != np.sign(log_returns[:, :-1]), axis=1)
                   if horizon > 1 else np.zeros(count))
    metrics = np.column_stack((np.log(paths[:, -1] / anchor), drawdowns,
                               np.std(log_returns, axis=1, ddof=1) if horizon > 1 else np.zeros(count),
                               np.mean(log_returns < 0, axis=1), sign_change))
    ranks = np.column_stack([(rankdata(metrics[:, index], method="average") - .5) / count
                             for index in range(metrics.shape[1])])
    lower = np.array([.40, .25, .25, .10, .10])
    upper = np.array([.60, .75, .75, .90, .90])
    eligible = np.flatnonzero(np.all((ranks >= lower) & (ranks <= upper), axis=1))
    if len(eligible) == 0:
        return {"status": "unavailable", "reason": "no_jointly_typical_paths",
                "eligible_count": int(len(eligible)), "selection_relaxed": False,
                "metric_names": ["terminal_log_return", "max_drawdown", "daily_log_volatility",
                                 "negative_session_share", "sign_change_share"]}
    # Equal metric weights are preregistered.  No distance-to-median-path term:
    # such a term rewards abnormally smooth realizations of a rough process.
    score = np.mean(np.square(2 * ranks[eligible] - 1), axis=1)
    selected = int(eligible[np.lexsort((eligible, score))[0]])
    return {"status": "ok", "path_id": selected, "path_hash": _path_hash(daily[selected]),
            "values": daily[selected].tolist(), "eligible_count": int(len(eligible)),
            "selection": "jointly_typical_real_path_v1", "selection_relaxed": False,
            "score": float(score[np.flatnonzero(eligible == selected)[0]]),
            "metric_percentile_ranks": ranks[selected].tolist(),
            "is_pointwise_median": False, "daily_sampling": True}


def summarize_paths(
    paths: np.ndarray, *, anchor: float, future_dates: list[str],
    baseline_paths: np.ndarray | None = None,
) -> dict[str, Any]:
    dates = _dates(future_dates, "future_dates")
    values = np.asarray(paths, dtype=float)
    start = _finite(anchor, "anchor")
    if (start <= 0 or values.ndim != 2 or len(values) == 0 or values.shape[1] != len(dates)
            or not np.all(np.isfinite(values)) or np.any(values <= 0)):
        raise MarketContextError("paths must be a non-empty finite positive daily matrix aligned to dates")
    previous = np.column_stack((np.full(len(values), start), values[:, :-1]))
    returns = values / previous - 1.0
    peaks = np.maximum.accumulate(np.column_stack((np.full(len(values), start), values)), axis=1)[:, 1:]
    drawdowns = 1.0 - values / peaks
    cumulative_drawdown = np.maximum.accumulate(drawdowns, axis=1)
    quantiles = np.percentile(values, QUANTILES, axis=0)
    return_quantiles = np.percentile(returns, QUANTILES, axis=0)
    # Instantaneous drawdown can recover to0 at a new high.  It is not MDD.
    drawdown_quantiles = np.percentile(values / peaks - 1.0, QUANTILES, axis=0)
    max_drawdown_quantiles = np.percentile(cumulative_drawdown, QUANTILES, axis=0)
    records = []
    for index, day in enumerate(dates):
        record = {"date": day.isoformat(), "horizon": index + 1,
                  **{f"q{q:02d}": float(quantiles[j, index]) for j, q in enumerate(QUANTILES)},
                  "index_quantiles": {f"p{q:02d}": float(quantiles[j, index])
                                      for j, q in enumerate(QUANTILES)},
                  "p_up_previous": float(np.mean(values[:, index] > previous[:, index])),
                  "p_up_origin": float(np.mean(values[:, index] > start)),
                  "probability_up_from_previous": float(np.mean(values[:, index] > previous[:, index])),
                  "probability_down_from_previous": float(np.mean(values[:, index] < previous[:, index])),
                  "probability_up_from_origin": float(np.mean(values[:, index] > start)),
                  "daily_return_quantiles": {f"p{q:02d}": float(return_quantiles[j, index])
                                             for j, q in enumerate(QUANTILES)},
                  "drawdown_quantiles": {f"p{q:02d}": float(drawdown_quantiles[j, index])
                                         for j, q in enumerate(QUANTILES)},
                  "max_drawdown_magnitude_quantiles": {f"p{q:02d}": float(max_drawdown_quantiles[j, index])
                                                        for j, q in enumerate(QUANTILES)}}
        records.append(record)
    diagnostics = {"path_count": len(values), "horizon": len(dates),
                   "path_hash": _path_hash(values), "probability_unit": "fraction",
                   "daily_return_unit": "fraction", "drawdown_unit": "signed_fraction_nonpositive",
                   "max_drawdown_magnitude_unit": "fraction_nonnegative",
                   "fan_basis": "whole_ensemble_pointwise_quantiles",
                   "max_drawdown_median": float(np.median(cumulative_drawdown[:, -1]))}
    if baseline_paths is not None:
        baseline = np.asarray(baseline_paths, dtype=float)
        if baseline.shape != values.shape or not np.all(np.isfinite(baseline)) or np.any(baseline <= 0):
            raise MarketContextError("baseline_paths must match candidate finite positive paths")
        diagnostics["baseline_path_hash"] = _path_hash(baseline)
        diagnostics["exact_baseline_identity"] = bool(np.array_equal(values, baseline))
        diagnostics["median_log_shift"] = (
            np.median(np.log(values), axis=0) - np.median(np.log(baseline), axis=0)).tolist()
    return {"daily": records, "records": records, "representative": _representative(values, start),
            "diagnostics": diagnostics, "quantile_unit": "index_level",
            "probability_space": "model_conditional_research_only"}
