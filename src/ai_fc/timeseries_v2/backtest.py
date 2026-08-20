"""V2 walk-forward evaluator using the numerically equivalent batched selector."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import numpy as np

from ai_fc.timeseries.backtest import (
    OriginScore,
    _baseline_samples,
    sample_crps,
    summarize_backtest,
)
from ai_fc.timeseries.model import (
    ensemble_weights,
)

from .model import (
    select_distribution_parameters_v2,
    select_ridge_varx_v2,
    simulate_correlated_paths_v2,
)


def walk_forward_backtest_v2(
    *,
    dates: tuple[str, ...],
    endog: np.ndarray,
    exog: np.ndarray,
    endog_names: tuple[str, ...],
    exog_names: tuple[str, ...],
    outer_start: str = "2007-01-01",
    path_count: int = 20000,
) -> tuple[list[OriginScore], dict[str, Any]]:
    """Evaluate completed weekly origins without changing V1 or durable state."""
    weekly_last: dict[tuple[int, int], int] = {}
    for index in range(max(800, 63), len(dates) - 63):
        if dates[index] < outer_start:
            continue
        iso = date.fromisoformat(dates[index]).isocalendar()
        weekly_last[(iso.year, iso.week)] = index
    origins = sorted(weekly_last.values())
    scores: list[OriginScore] = []
    expanding_history: list[float] = []
    rolling_history: list[float] = []
    for origin in origins:
        training_endog = endog[:origin]
        training_exog = exog[:origin]
        expanding = select_ridge_varx_v2(
            training_endog,
            training_exog,
            endog_names=endog_names,
            exog_names=exog_names,
        )
        rolling_start = max(0, origin - 2520)
        rolling = select_ridge_varx_v2(
            training_endog,
            training_exog,
            endog_names=endog_names,
            exog_names=exog_names,
            train_start=rolling_start,
        )
        weight_left, weight_right, _ = ensemble_weights(expanding_history, rolling_history)
        seed = int.from_bytes(hashlib.sha256(dates[origin].encode()).digest()[:8], "big")
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
            actual_daily = endog[origin: origin + horizon, 0]
            actual = float(np.sum(actual_daily))
            baselines = _baseline_samples(
                training_endog[:, 0], horizon=horizon, count=path_count, rng=rng,
            )
            quantiles = np.quantile(samples, (0.10, 0.25, 0.50, 0.75, 0.90))
            touch_actual = bool(np.min(np.exp(np.cumsum(actual_daily))) <= 0.90)
            touch_probability = float(
                np.mean(np.min(simulated["index_paths"][:, :horizon], axis=1) <= 0.90)
            )
            row = OriginScore(
                date=dates[origin],
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
    return scores, summarize_backtest(scores)
