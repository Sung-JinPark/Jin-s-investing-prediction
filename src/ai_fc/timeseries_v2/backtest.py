"""V2 walk-forward evaluator using the numerically equivalent batched selector."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from ai_fc.timeseries.backtest import (
    OriginScore,
    _stationary_bootstrap_mean_ci,
    sample_crps,
    summarize_backtest,
)
from ai_fc.timeseries.model import (
    deterministic_seed,
    ensemble_weights,
)

from .model import (
    _stationary_bootstrap_batch,
    select_distribution_parameters_v2,
    select_ridge_varx_v2,
    simulate_correlated_paths_v2,
)


def _baseline_samples_v2(
    returns: np.ndarray, *, horizon: int, count: int, rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Generate the frozen benchmark family without path-by-path Python loops.

    This preserves the V1 benchmark definitions but batches the AR(1) and
    stationary-block innovations.  The seed remains the preregistered origin
    seed; only redundant interpreter work is removed.
    """
    values = np.asarray(returns, dtype=float)
    if len(values) < horizon + 30:
        raise ValueError("insufficient baseline return history")
    mu = float(np.mean(values))
    sigma = float(np.std(values, ddof=1))
    centered = values - mu
    denominator = float(np.dot(values[:-1], values[:-1])) if len(values) >= 3 else 0.0
    ar = float(np.dot(values[:-1], values[1:]) / denominator) if denominator > 1e-16 else 0.0
    ar_residual = values[1:] - ar * values[:-1]

    residual_indexes = rng.integers(0, len(ar_residual), size=(count, horizon))
    state = np.full(count, float(values[-1]), dtype=float)
    ar_paths = np.zeros(count, dtype=float)
    for step in range(horizon):
        state = ar * state + ar_residual[residual_indexes[:, step]]
        ar_paths += state

    windows = np.convolve(values, np.ones(horizon), mode="valid")
    historical = windows[rng.integers(0, len(windows), size=count)]
    block_indexes = _stationary_bootstrap_batch(
        rng, rows=len(centered), paths=count, horizon=horizon,
        mean_block=min(10, horizon),
    )
    block = np.sum(centered[block_indexes], axis=1) + mu * horizon
    return {
        "random_walk": np.zeros(count, dtype=float),
        "drift_random_walk": np.full(count, mu * horizon, dtype=float),
        "ar1": ar_paths,
        "gbm": rng.normal(mu * horizon, sigma * np.sqrt(horizon), size=count),
        "historical_simulation": historical,
        "block_bootstrap": block,
    }


def _weekly_forecast_origins(
    dates: tuple[str, ...], *, outer_start: str, horizon: int = 63,
) -> tuple[tuple[int, int], ...]:
    """Return `(as_of_index, first_target_index)` for completed weekly closes.

    The weekly origin is the final completed session in each ISO week.  Its
    close and return are therefore part of the training window; the first
    forecast target is the following completed session.  Keeping both
    coordinates explicit prevents the prior one-session origin drift.
    """
    weekly_last: dict[tuple[int, int], int] = {}
    for index in range(max(800, horizon), len(dates) - horizon):
        if dates[index] < outer_start:
            continue
        iso = date.fromisoformat(dates[index]).isocalendar()
        weekly_last[(iso.year, iso.week)] = index
    return tuple((as_of_index, as_of_index + 1) for as_of_index in sorted(weekly_last.values()))


def _origin_seed(model_id: str, model_version: int, as_of: str) -> int:
    return deterministic_seed(model_id, model_version, as_of)


def ensemble_history_21d(
    scores: list[OriginScore], *, lookback: int = 52,
) -> tuple[list[float], list[float]]:
    """Return the prior-origin CRPS coordinates used by the ensemble contract."""
    rows = sorted(
        (row for row in scores if row.horizon == 21),
        key=lambda row: row.date,
    )[-lookback:]
    return (
        [float(row.expanding_crps) for row in rows],
        [float(row.rolling_crps) for row in rows],
    )


def summarize_backtest_v2(
    scores: list[OriginScore], *, minimum_origins: int = 250,
) -> dict[str, Any]:
    """Apply the V2 coverage and paired long-horizon bootstrap contract.

    The shared V1 summary provides the metric definitions.  V2 replaces only
    the publication-gate coordinates that are stricter in its preregistration:
    coverage is checked for every published horizon, and the 21/63-session
    loss difference is averaged within each weekly origin before resampling.
    This preserves time order and cross-horizon dependence.
    """
    rows = list(scores)
    summary = summarize_backtest(rows, minimum_origins=minimum_origins)
    reasons = [
        reason for reason in summary["reasons"]
        if "coverage가 76~84% 밖" not in reason
        and "coverage가 45~55% 밖" not in reason
        and "21·63일 결합 CRPS 차이" not in reason
    ]

    by_horizon_date = {
        horizon: {row.date: row for row in rows if row.horizon == horizon}
        for horizon in (21, 63)
    }
    common_dates = sorted(set(by_horizon_date[21]) & set(by_horizon_date[63]))
    best_names = {
        horizon: summary["horizons"].get(str(horizon), {}).get("best_baseline")
        for horizon in (21, 63)
    }
    paired_differences: list[float] = []
    if all(best_names.values()):
        for origin_date in common_dates:
            differences = []
            for horizon in (21, 63):
                row = by_horizon_date[horizon][origin_date]
                differences.append(
                    float(row.model_crps - row.baseline_crps[str(best_names[horizon])])
                )
            paired_differences.append(float(np.mean(differences)))
    ci_low, ci_high = _stationary_bootstrap_mean_ci(
        np.asarray(paired_differences, dtype=float), seed=19_960_107,
    )

    for horizon in (1, 5, 21, 63):
        metric = summary["horizons"].get(str(horizon))
        if not metric:
            continue
        if not 0.76 <= float(metric["coverage_p10_p90"]) <= 0.84:
            reasons.append(f"{horizon}일 p10-p90 coverage가 76~84% 밖")
        if not 0.45 <= float(metric["coverage_p25_p75"]) <= 0.55:
            reasons.append(f"{horizon}일 p25-p75 coverage가 45~55% 밖")
    if not np.isfinite(ci_high) or ci_high > 0:
        reasons.append("21·63일 결합 CRPS 차이의 stationary-bootstrap 90% CI 상단이 0 초과")

    summary["long_horizon_loss_difference_ci90"] = {
        "lower": ci_low,
        "upper": ci_high,
        "origin_count": len(paired_differences),
        "method": "weekly_origin_mean_of_21d_and_63d_raw_loss_differences",
    }
    summary["reasons"] = reasons
    summary["gate_pass"] = not reasons
    summary["status"] = "pass" if not reasons else "hold"
    return summary


def walk_forward_backtest_v2(
    *,
    dates: tuple[str, ...],
    endog: np.ndarray,
    exog: np.ndarray,
    endog_names: tuple[str, ...],
    exog_names: tuple[str, ...],
    model_id: str,
    model_version: int,
    outer_start: str = "2007-01-01",
    path_count: int = 20000,
    initial_expanding_crps: tuple[float, ...] | list[float] = (),
    initial_rolling_crps: tuple[float, ...] | list[float] = (),
) -> tuple[list[OriginScore], dict[str, Any]]:
    """Evaluate completed weekly origins without changing V1 or durable state."""
    origins = _weekly_forecast_origins(dates, outer_start=outer_start, horizon=63)
    scores: list[OriginScore] = []
    expanding_history = [float(value) for value in initial_expanding_crps]
    rolling_history = [float(value) for value in initial_rolling_crps]
    if len(expanding_history) != len(rolling_history):
        raise ValueError("initial ensemble CRPS histories must have equal length")
    for as_of_index, forecast_start in origins:
        training_endog = endog[:forecast_start]
        training_exog = exog[:forecast_start]
        expanding = select_ridge_varx_v2(
            training_endog,
            training_exog,
            endog_names=endog_names,
            exog_names=exog_names,
        )
        rolling_start = max(0, forecast_start - 2520)
        rolling = select_ridge_varx_v2(
            training_endog,
            training_exog,
            endog_names=endog_names,
            exog_names=exog_names,
            train_start=rolling_start,
        )
        weight_left, weight_right, _ = ensemble_weights(expanding_history, rolling_history)
        as_of = dates[as_of_index]
        seed = _origin_seed(model_id, model_version, as_of)
        block_length, ewma_lambda, _ = select_distribution_parameters_v2(
            np.vstack((expanding.residuals, rolling.residuals)), seed=seed,
        )
        simulated = simulate_correlated_paths_v2(
            (expanding, rolling),
            weights=(weight_left, weight_right),
            endog_history=training_endog,
            exog_last=training_exog[-1],
            anchor=1.0,
            path_count=path_count,
            horizon=63,
            block_length=block_length,
            ewma_lambda=ewma_lambda,
            seed=seed,
        )
        expanding_only = simulate_correlated_paths_v2(
            (expanding, rolling),
            weights=(1.0, 0.0),
            endog_history=training_endog,
            exog_last=training_exog[-1],
            anchor=1.0,
            path_count=path_count,
            horizon=63,
            block_length=block_length,
            ewma_lambda=ewma_lambda,
            seed=seed + 2,
        )
        rolling_only = simulate_correlated_paths_v2(
            (expanding, rolling),
            weights=(0.0, 1.0),
            endog_history=training_endog,
            exog_last=training_exog[-1],
            anchor=1.0,
            path_count=path_count,
            horizon=63,
            block_length=block_length,
            ewma_lambda=ewma_lambda,
            seed=seed + 3,
        )
        log_paths = np.log(simulated["index_paths"])
        expanding_log_paths = np.log(expanding_only["index_paths"])
        rolling_log_paths = np.log(rolling_only["index_paths"])
        rng = np.random.default_rng(seed + 1)
        for horizon in (1, 5, 21, 63):
            samples = log_paths[:, horizon - 1]
            actual_daily = endog[forecast_start: forecast_start + horizon, 0]
            actual = float(np.sum(actual_daily))
            baselines = _baseline_samples_v2(
                training_endog[:, 0], horizon=horizon, count=path_count, rng=rng,
            )
            quantiles = np.quantile(samples, (0.10, 0.25, 0.50, 0.75, 0.90))
            touch_actual = bool(np.min(np.exp(np.cumsum(actual_daily))) <= 0.90)
            touch_probability = float(
                np.mean(np.min(simulated["index_paths"][:, :horizon], axis=1) <= 0.90)
            )
            row = OriginScore(
                date=as_of,
                horizon=horizon,
                actual_log_return=actual,
                model_crps=sample_crps(samples, actual),
                baseline_crps={
                    name: sample_crps(values, actual) for name, values in baselines.items()
                },
                median=float(quantiles[2]),
                p10=float(quantiles[0]),
                p25=float(quantiles[1]),
                p75=float(quantiles[3]),
                p90=float(quantiles[4]),
                direction_correct=bool((quantiles[2] >= 0) == (actual >= 0)),
                first_touch_actual=touch_actual,
                first_touch_probability=touch_probability,
                expanding_crps=sample_crps(expanding_log_paths[:, horizon - 1], actual),
                rolling_crps=sample_crps(rolling_log_paths[:, horizon - 1], actual),
                block_length=block_length,
                ewma_lambda=ewma_lambda,
            )
            scores.append(row)
            if horizon == 21:
                expanding_history.append(row.expanding_crps)
                rolling_history.append(row.rolling_crps)
    summary = summarize_backtest_v2(scores)
    summary["ensemble_initial_history_origins"] = min(
        len(initial_expanding_crps), len(initial_rolling_crps), 52,
    )
    return scores, summary
