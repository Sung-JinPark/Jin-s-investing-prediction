"""Coherent daily path generation, with independent research comparisons.

All plotted quantities come from one multivariate simulation.  In particular,
the change in marginal medians is never used as the daily rise probability.
The historical FHS benchmark is a separate joint distribution, not a hidden
replacement for the selected multivariate model.
"""

from __future__ import annotations

import calendar
import hashlib
import importlib.metadata
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from ai_fc.timeseries.model import deterministic_seed
from ai_fc.timeseries_v2.model import (
    select_distribution_parameters_v2,
    select_ridge_varx_v2,
    simulate_correlated_paths_v2,
)
from ai_fc.timeseries_v2.contracts import runtime_manifest
from ai_fc.timeseries_v8.model import _ewma_variance_series, simulate_calibrated_paths_v8

from .contracts import (
    Daily6mContractError, ENDOGENOUS_NAMES, EXOGENOUS_NAMES, MINIMUM_TRAINING_SESSIONS,
    MODEL_ID, MODEL_VERSION, PATH_COUNT, QUANTILE_LEVELS, QUANTILE_NAMES, canonical_hash,
)


def add_calendar_months(day: date, months: int = 6) -> date:
    """Preserve a calendar month-end; otherwise keep the day with clamping."""
    month_index = day.year * 12 + day.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    destination_end = calendar.monthrange(year, month)[1]
    origin_is_month_end = day.day == calendar.monthrange(day.year, day.month)[1]
    return date(year, month, destination_end if origin_is_month_end else min(day.day, destination_end))


def future_session_dates(origin_session: str) -> tuple[list[str], str, str]:
    """All XNAS sessions through six calendar months, with explicit bounds.

    Explicit calendar bounds avoid exchange-calendars' rolling default end
    date truncating a future forecast.  Missing optional dependencies fail;
    this function never installs packages or manufactures weekdays.
    """
    try:
        import exchange_calendars as xcals
        import pandas as pd
    except ImportError as exc:
        raise Daily6mContractError("XNAS calendar dependencies are unavailable") from exc
    origin = date.fromisoformat(origin_session)
    end = add_calendar_months(origin)
    exchange = xcals.get_calendar("XNAS", start=origin - timedelta(days=7), end=end + timedelta(days=7))
    if not exchange.is_session(pd.Timestamp(origin)):
        raise Daily6mContractError("forecast origin is not an XNAS session")
    sessions = exchange.sessions_in_range(pd.Timestamp(origin + timedelta(days=1)), pd.Timestamp(end))
    dates = [stamp.date().isoformat() for stamp in sessions]
    if not dates:
        raise Daily6mContractError("XNAS supplied no six-month forecast sessions")
    calendar_hash = canonical_hash({"exchange": "XNAS", "origin": origin_session,
                                    "calendar_end_date": end.isoformat(), "future_dates": dates})
    return dates, end.isoformat(), calendar_hash


def _get(bundle: Any, key: str, default: Any = None) -> Any:
    return bundle.get(key, default) if isinstance(bundle, dict) else getattr(bundle, key, default)


def _timestamp(raw: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError) as exc:
        raise Daily6mContractError("as_of and availability require ISO timestamps") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise Daily6mContractError("as_of and availability require timezone-aware timestamps")
    return result


def _path_hash(paths: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(paths, dtype=np.float64).tobytes()).hexdigest()


def _validate_lineage_availability(lineage: dict[str, Any], issued: datetime) -> None:
    for key in ("max_available_at", "maximum_available_at", "max_input_available_at", "available_at_max"):
        if lineage.get(key) is not None and _timestamp(lineage[key]) > issued:
            raise Daily6mContractError("input availability is after forecast issuance")
    for group in ("market_rows", "factor_rows", "issuance_factor_lineage"):
        for row in lineage.get(group, ()):
            for key in ("available_at", "vintage_start", "cutoff", "retrieved_at", "built_at", "cache_materialized_at"):
                if row.get(key) is not None and _timestamp(row[key]) > issued:
                    raise Daily6mContractError(f"{group} {key} is after forecast issuance")


def _validate_registered_captured_tail(lineage: dict[str, Any], origin: str) -> None:
    from .live_tail import validate_tail_lineage_rows
    try:
        validate_tail_lineage_rows(lineage.get("market_rows", ()), origin)
    except Daily6mContractError as exc:
        raise Daily6mContractError("captured VIX tail or registered source tail invalid: " + str(exc)) from exc


def summarize_joint_paths(
    index_paths: np.ndarray, *, anchor: float, future_dates: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive daily events and representative members from the SAME matrix."""
    paths = np.asarray(index_paths, dtype=float)
    if (paths.ndim != 2 or not paths.shape[0] or paths.shape[1] != len(future_dates)
            or not future_dates or not np.isfinite(paths).all() or np.any(paths <= 0)
            or not np.isfinite(anchor) or anchor <= 0):
        raise Daily6mContractError("joint paths require finite positive prices and one column per session")
    if future_dates != sorted(set(future_dates)):
        raise Daily6mContractError("future session dates must be strictly increasing")
    previous = np.column_stack((np.full(paths.shape[0], float(anchor)), paths[:, :-1]))
    daily_returns = paths / previous - 1.0
    index_quantiles = np.quantile(paths, QUANTILE_LEVELS, axis=0)
    daily_quantiles = np.quantile(daily_returns, QUANTILE_LEVELS, axis=0)
    probability_daily = np.mean(paths > previous, axis=0)
    probability_origin = np.mean(paths > anchor, axis=0)
    records = []
    for step, day in enumerate(future_dates):
        bands = {name: float(index_quantiles[level, step])
                 for level, name in enumerate(QUANTILE_NAMES)}
        records.append({
            "date": day,
            "median_index": bands["p50"],
            "band_index": bands,
            "probability_up_from_previous": float(probability_daily[step]),
            "probability_up_from_origin": float(probability_origin[step]),
            "median_return_from_origin": bands["p50"] / float(anchor) - 1.0,
            "median_return_from_previous": float(daily_quantiles[2, step]),
            "return_quantiles": {name: value / float(anchor) - 1.0 for name, value in bands.items()},
            "daily_return_quantiles": {name: float(daily_quantiles[level, step])
                                       for level, name in enumerate(QUANTILE_NAMES)},
        })
    # These are actual ensemble members, not interpolated or cosmetically
    # perturbed quantiles.  Stable sorting preserves deterministic tie breaks.
    order = np.argsort(paths[:, -1], kind="stable")
    samples = []
    for percentile in QUANTILE_LEVELS:
        rank = int(np.floor(percentile * (len(order) - 1) + 0.5))
        member = int(order[rank])
        samples.append({"path_id": f"simulation-{member}", "endpoint_percentile": percentile,
                        "values": paths[member].tolist()})
    return records, samples


def historical_fhs_paths(
    training_returns: np.ndarray, *, anchor: float, horizon: int, decay: float = 0.97, burn_in: int = 60,
) -> np.ndarray:
    """A coherent FHS comparator using shared completed historical windows.

    r*[i,t] = mu + (r[i+t]-mu) * sigma_now / sigma_i.  Common window support
    preserves daily dependence and is intentionally different from V8's
    independently supported and recalibrated endpoint distributions.
    """
    returns = np.asarray(training_returns, dtype=float)
    if (returns.ndim != 1 or not np.isfinite(returns).all() or horizon <= 0
            or burn_in < 0 or len(returns) < max(MINIMUM_TRAINING_SESSIONS, horizon + burn_in + 30)
            or not 0 < decay < 1 or not np.isfinite(anchor) or anchor <= 0):
        raise Daily6mContractError("FHS needs finite history and completed full-horizon windows")
    variance = _ewma_variance_series(returns, decay)
    windows = np.lib.stride_tricks.sliding_window_view(returns, horizon)[burn_in:]
    variance_start = variance[burn_in:burn_in + len(windows)]
    mu = float(np.mean(returns))
    scales = np.sqrt(np.maximum(variance[-1], 1e-16) / np.maximum(variance_start, 1e-16))
    log_paths = mu + (windows - mu) * scales[:, None]
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        paths = float(anchor) * np.exp(np.cumsum(log_paths, axis=1))
    if not np.isfinite(paths).all() or np.any(paths <= 0):
        raise Daily6mContractError("FHS produced non-finite or non-positive paths; no clipping applied")
    return paths


def _fhs_comparison(main: np.ndarray, baseline: np.ndarray, anchor: float) -> dict[str, Any]:
    horizon = main.shape[1]
    horizons = sorted({min(step, horizon) for step in (1, 5, 21, 63, horizon)})
    records = []
    for step in horizons:
        candidate = main[:, step - 1]
        reference = baseline[:, step - 1]
        left = np.quantile(candidate, QUANTILE_LEVELS)
        right = np.quantile(reference, QUANTILE_LEVELS)
        records.append({
            "horizon_sessions": step,
            "main_index_quantiles": dict(zip(QUANTILE_NAMES, left.tolist(), strict=True)),
            "fhs_index_quantiles": dict(zip(QUANTILE_NAMES, right.tolist(), strict=True)),
            "index_quantile_differences": dict(zip(QUANTILE_NAMES, (left - right).tolist(), strict=True)),
            "main_probability_up_from_origin": float(np.mean(candidate > anchor)),
            "fhs_probability_up_from_origin": float(np.mean(reference > anchor)),
            "median_return_difference": float((left[2] - right[2]) / anchor),
        })
    main_previous = np.column_stack((np.full(len(main), anchor), main[:, :-1]))
    fhs_previous = np.column_stack((np.full(len(baseline), anchor), baseline[:, :-1]))
    probability_difference = np.mean(main > main_previous, axis=0) - np.mean(baseline > fhs_previous, axis=0)
    return {"model_id": "research.nasdaq_daily6m_fhs_benchmark_v1", "role": "independent_benchmark_only",
            "window_count": len(baseline), "path_hash": _path_hash(baseline), "ewma_lambda": 0.97,
            "burn_in_sessions": 60, "horizons": records,
            "max_abs_daily_probability_difference": float(np.max(np.abs(probability_difference))),
            "performance_validation": "not_established"}


def generate_forecast_with_paths(
    bundle: Any, *, anchor: float, as_of: str, future_dates: list[str],
    history: dict[str, Any] | None = None, lineage: dict[str, Any] | None = None,
    path_count: int = PATH_COUNT,
) -> tuple[dict[str, Any], np.ndarray]:
    """Fit and generate without collecting data or writing any files.

    The caller must enforce full issuance lineage and freshness before
    appending a research revision.  Small path counts support disposable
    numerical tests; production publication independently requires 20,000.
    """
    issued = _timestamp(as_of)
    dates = list(_get(bundle, "dates", ()))
    y = np.asarray(_get(bundle, "endogenous"), dtype=float)
    x = np.asarray(_get(bundle, "exogenous"), dtype=float)
    if (not isinstance(path_count, int) or isinstance(path_count, bool) or path_count < 5
            or len(dates) < MINIMUM_TRAINING_SESSIONS
            or dates != sorted(set(dates))
            or y.shape != (len(dates), len(ENDOGENOUS_NAMES))
            or x.shape != (len(dates), len(EXOGENOUS_NAMES))
            or tuple(_get(bundle, "endogenous_names", ())) != ENDOGENOUS_NAMES
            or tuple(_get(bundle, "exogenous_names", ())) != EXOGENOUS_NAMES
            or not np.isfinite(y).all() or not np.isfinite(x).all()
            or not np.isfinite(anchor) or anchor <= 0):
        raise Daily6mContractError("daily6m needs 800 complete named multivariate sessions and valid dimensions")
    if _get(bundle, "issues", ()):
        raise Daily6mContractError("input bundle has unresolved issues")
    origin = str(dates[-1])
    if date.fromisoformat(origin) > issued.date():
        raise Daily6mContractError("forecast origin is after issuance")
    expected_dates, calendar_end, calendar_hash = future_session_dates(origin)
    if list(future_dates) != expected_dates:
        raise Daily6mContractError("future dates must be the complete exact six-calendar-month XNAS range")
    import exchange_calendars as xcals
    import pandas as pd
    exchange = xcals.get_calendar("XNAS", start=origin, end=calendar_end)
    if issued.timestamp() < exchange.session_close(pd.Timestamp(origin)).timestamp() + 900:
        raise Daily6mContractError("forecast origin session must be completed before issuance")
    if issued.timestamp() >= exchange.session_close(pd.Timestamp(future_dates[0])).timestamp():
        raise Daily6mContractError("first forecast target session has already closed at issuance")
    lineage = lineage if lineage is not None else _get(bundle, "lineage", {})
    _validate_lineage_availability(lineage, issued)
    _validate_registered_captured_tail(lineage, origin)
    issuance_exog = _get(bundle, "issuance_exogenous")
    projection_exog = x[-1] if issuance_exog is None else np.asarray(issuance_exog, dtype=float)
    if projection_exog.shape != (len(EXOGENOUS_NAMES),) or not np.isfinite(projection_exog).all():
        raise Daily6mContractError("issuance exogenous state must contain three finite known values")
    _validate_lineage_availability(
        {"issuance_factor_lineage": _get(bundle, "issuance_factor_lineage", ())}, issued,
    )
    expanding = select_ridge_varx_v2(y, x, endog_names=ENDOGENOUS_NAMES, exog_names=EXOGENOUS_NAMES)
    rolling = select_ridge_varx_v2(y, x, endog_names=ENDOGENOUS_NAMES, exog_names=EXOGENOUS_NAMES,
                                   train_start=max(0, len(dates) - 2520))
    seed = deterministic_seed(MODEL_ID, MODEL_VERSION, origin)
    residuals = np.vstack((expanding.residuals, rolling.residuals))
    block, decay, selection = select_distribution_parameters_v2(residuals, seed=seed)
    kwargs = dict(weights=(0.5, 0.5), endog_history=y, exog_last=projection_exog, anchor=float(anchor),
                  path_count=path_count, horizon=len(future_dates), block_length=block, ewma_lambda=decay,
                  seed=seed)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        simulated = simulate_correlated_paths_v2((expanding, rolling), **kwargs)
        reference = simulate_calibrated_paths_v8((expanding, rolling), step_scale=None, **kwargs)
    paths = np.asarray(simulated["index_paths"], dtype=float)
    if not np.isfinite(simulated["log_returns"]).all():
        raise Daily6mContractError("multivariate simulation produced non-finite returns")
    records, samples = summarize_joint_paths(paths, anchor=anchor, future_dates=future_dates)
    raw_difference = float(np.max(np.abs(paths - np.asarray(reference["index_paths"], dtype=float))))
    raw_return_difference = float(np.max(np.abs(np.asarray(simulated["log_returns"])
                                               - np.asarray(reference["log_returns"]))))
    identity_pass = raw_difference <= 1e-12 and raw_return_difference <= 1e-12
    if not identity_pass:
        raise Daily6mContractError("immutable V2/V8 raw joint-kernel shadow identity failed")
    fhs = historical_fhs_paths(y[:, 0], anchor=anchor, horizon=len(future_dates))
    payload = {
        "schema_version": 1, "model_id": MODEL_ID, "model_version": MODEL_VERSION,
        "as_of": issued.isoformat(), "origin_session": origin, "anchor_index": float(anchor),
        "calendar_end_date": calendar_end, "forecast_end_date": future_dates[-1],
        "calendar_hash": calendar_hash, "horizon_sessions": len(future_dates), "path_count": path_count,
        "path_hash": _path_hash(paths), "probability_unit": "fraction",
        "probability_space": "research_timeseries_daily6m_conditional",
        "predictive_validation": "not_established",
        "exogenous_assumption": "latest_known_values_held_constant",
        "records": records, "sample_paths": samples,
        "history": history if history is not None else _get(bundle, "history", {}),
        "lineage": lineage,
        "model_config": {
            "seed": seed, "ensemble_weights": {"expanding": 0.5, "rolling_10y": 0.5},
            "runtime": {**runtime_manifest(), "exchange_calendars": importlib.metadata.version("exchange-calendars")},
            "issuance_exogenous": {name: float(value) for name, value in zip(EXOGENOUS_NAMES, projection_exog, strict=True)},
            "block_length": block, "ewma_lambda": decay,
            "expanding_fit": expanding.manifest(), "rolling_fit": rolling.manifest(),
            "distribution_selection": {key: (float(value) if np.isfinite(value) else None)
                                       for key, value in selection.items()},
            "per_horizon_calibration": "none",
        },
        "comparison": {
            "v8_raw_identity": {
                "pass": identity_pass, "reference": "immutable_v8_raw_joint_kernel",
                "same_inputs_horizon_seed": True, "max_abs_index_difference": raw_difference,
                "max_abs_log_return_difference": raw_return_difference, "tolerance": 1e-12,
                "calibrated_endpoint_evidence_inherited": False,
            },
            "fhs": _fhs_comparison(paths, fhs, float(anchor)),
            "v8_calibrated_endpoints": {
                "status": "unavailable",
                "reason": "comparable_frozen_v8_input_vintage_and_calibration_state_not_supplied; "
                          "native_T10Y2Y_and_ALFRED_source_mapping_differs_from_v8_reconstructed_inputs",
                "evidence_inherited": False,
                "horizons": [
                    {"horizon_sessions": step, "daily6m_index_quantiles": records[step - 1]["band_index"],
                     "daily6m_probability_up_from_origin": records[step - 1]["probability_up_from_origin"],
                     "v8_index_quantiles": None, "index_quantile_differences": None}
                    for step in (1, 5, 21, 63) if step <= len(records)
                ],
            },
        },
        "validation_checks": {
            "finite_positive_paths": True, "shared_daily_joint_paths": True,
            "probability_bounds": True, "ordered_quantiles": True,
            "exact_six_calendar_months": True, "raw_kernel_identity": identity_pass,
            "predictive_performance_pass_claimed": False,
        },
    }
    # Reject any accidental non-JSON or non-finite metadata at the API boundary.
    payload["content_hash"] = canonical_hash(payload)
    return payload, paths


def generate_forecast(
    bundle: Any, *, anchor: float, as_of: str, future_dates: list[str],
    history: dict[str, Any] | None = None, lineage: dict[str, Any] | None = None,
    path_count: int = PATH_COUNT,
) -> dict[str, Any]:
    return generate_forecast_with_paths(bundle, anchor=anchor, as_of=as_of, future_dates=future_dates,
                                        history=history, lineage=lineage, path_count=path_count)[0]
