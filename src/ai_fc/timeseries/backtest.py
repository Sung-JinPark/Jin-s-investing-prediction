"""Rolling-origin evaluation and preregistered publication gates."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

import numpy as np

from .model import (
    TimeSeriesModelError,
    ensemble_weights,
    select_distribution_parameters,
    select_ridge_varx,
    simulate_correlated_paths,
)


def sample_crps(samples: np.ndarray, actual: float) -> float:
    """CRPS for an empirical distribution in O(n log n)."""
    values = np.sort(np.asarray(samples, dtype=float))
    if values.size == 0:
        raise ValueError("CRPS requires at least one sample")
    first = float(np.mean(np.abs(values - actual)))
    ranks = np.arange(1, len(values) + 1, dtype=float)
    pairwise_mean = float(2.0 * np.sum((2.0 * ranks - len(values) - 1.0) * values) / len(values) ** 2)
    return first - 0.5 * pairwise_mean


def pinball_loss(value: float, actual: float, quantile: float) -> float:
    error = actual - value
    return float(max(quantile * error, (quantile - 1.0) * error))


def _historical_cumulative_samples(
    returns: np.ndarray, *, horizon: int, count: int, rng: np.random.Generator,
) -> np.ndarray:
    if len(returns) < horizon + 30:
        raise TimeSeriesModelError("insufficient baseline return history")
    windows = np.convolve(returns, np.ones(horizon), mode="valid")
    return rng.choice(windows, size=count, replace=True)


def _block_return_samples(
    returns: np.ndarray, *, horizon: int, count: int, mean_block: int,
    rng: np.random.Generator,
) -> np.ndarray:
    output = np.empty(count, dtype=float)
    restart = 1.0 / mean_block
    for path in range(count):
        total = 0.0
        index = int(rng.integers(0, len(returns)))
        for step in range(horizon):
            if step == 0 or rng.random() < restart:
                index = int(rng.integers(0, len(returns)))
            else:
                index = (index + 1) % len(returns)
            total += float(returns[index])
        output[path] = total
    return output


def _baseline_samples(
    returns: np.ndarray, *, horizon: int, count: int, rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    centered = returns - mu
    if len(returns) >= 3 and float(np.dot(returns[:-1], returns[:-1])) > 1e-16:
        ar = float(np.dot(returns[:-1], returns[1:]) / np.dot(returns[:-1], returns[:-1]))
    else:
        ar = 0.0
    ar_residual = returns[1:] - ar * returns[:-1]
    ar_paths = np.empty(count, dtype=float)
    for path in range(count):
        state = float(returns[-1])
        total = 0.0
        for _ in range(horizon):
            state = ar * state + float(rng.choice(ar_residual))
            total += state
        ar_paths[path] = total
    return {
        "random_walk": np.zeros(count, dtype=float),
        "drift_random_walk": np.full(count, mu * horizon, dtype=float),
        "ar1": ar_paths,
        "gbm": rng.normal(mu * horizon, sigma * math.sqrt(horizon), size=count),
        "historical_simulation": _historical_cumulative_samples(
            returns, horizon=horizon, count=count, rng=rng,
        ),
        "block_bootstrap": _block_return_samples(
            centered, horizon=horizon, count=count, mean_block=min(10, horizon), rng=rng,
        ) + mu * horizon,
    }


def _stationary_bootstrap_mean_ci(
    differences: np.ndarray, *, confidence: float = 0.90, mean_block: int = 10,
    replications: int = 2000, seed: int = 0,
) -> tuple[float, float]:
    values = np.asarray(differences, dtype=float)
    if len(values) < 20:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    means = np.empty(replications, dtype=float)
    restart = 1.0 / float(mean_block)
    for replication in range(replications):
        total = 0.0
        index = int(rng.integers(0, len(values)))
        for step in range(len(values)):
            if step == 0 or rng.random() < restart:
                index = int(rng.integers(0, len(values)))
            else:
                index = (index + 1) % len(values)
            total += values[index]
        means[replication] = total / len(values)
    tail = (1.0 - confidence) / 2.0
    return float(np.quantile(means, tail)), float(np.quantile(means, 1.0 - tail))


def diebold_mariano_hac(loss_difference: np.ndarray, *, horizon: int) -> dict[str, float | int | None]:
    """Two-sided DM statistic with a Bartlett/Newey-West long-run variance."""
    values = np.asarray(loss_difference, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 20:
        return {"statistic": None, "p_value": None, "hac_lags": 0, "observations": len(values)}
    centered = values - float(np.mean(values))
    max_lag = min(len(values) - 1, max(1, int(math.ceil(horizon / 5))))
    long_run = float(np.dot(centered, centered) / len(values))
    for lag in range(1, max_lag + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / len(values))
        long_run += 2.0 * (1.0 - lag / (max_lag + 1.0)) * covariance
    variance_mean = max(long_run / len(values), 1e-18)
    statistic = float(np.mean(values) / math.sqrt(variance_mean))
    return {
        "statistic": statistic,
        "p_value": float(math.erfc(abs(statistic) / math.sqrt(2.0))),
        "hac_lags": max_lag,
        "observations": len(values),
    }


@dataclass(frozen=True)
class OriginScore:
    date: str
    horizon: int
    actual_log_return: float
    model_crps: float
    baseline_crps: dict[str, float]
    median: float
    p10: float
    p25: float
    p75: float
    p90: float
    direction_correct: bool
    first_touch_actual: bool
    first_touch_probability: float
    expanding_crps: float
    rolling_crps: float
    block_length: int = 10
    ewma_lambda: float = 0.97


def summarize_backtest(
    scores: Iterable[OriginScore], *, minimum_origins: int = 250,
) -> dict[str, Any]:
    rows = list(scores)
    by_horizon: dict[int, list[OriginScore]] = {}
    for row in rows:
        by_horizon.setdefault(row.horizon, []).append(row)
    horizon_metrics: dict[str, Any] = {}
    loss_differences: list[float] = []
    for horizon in (1, 5, 21, 63):
        subset = by_horizon.get(horizon, [])
        if not subset:
            continue
        actual = np.asarray([row.actual_log_return for row in subset])
        median = np.asarray([row.median for row in subset])
        model_crps = np.asarray([row.model_crps for row in subset])
        baseline_names = sorted(subset[0].baseline_crps)
        baseline_means = {
            name: float(np.mean([row.baseline_crps[name] for row in subset]))
            for name in baseline_names
        }
        best_name = min(baseline_means, key=baseline_means.get)
        best_rows = np.asarray([row.baseline_crps[best_name] for row in subset])
        if horizon in (21, 63):
            loss_differences.extend((model_crps - best_rows).tolist())
        error = median - actual
        scale = float(np.mean(np.abs(np.diff(actual)))) if len(actual) > 1 else math.nan
        horizon_metrics[str(horizon)] = {
            "origins": len(subset),
            "mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(np.square(error)))),
            "mase": None if not np.isfinite(scale) or scale <= 1e-16 else float(np.mean(np.abs(error)) / scale),
            "directional_accuracy": float(np.mean([row.direction_correct for row in subset])),
            "crps": float(np.mean(model_crps)),
            "pinball": {
                "p10": float(np.mean([pinball_loss(row.p10, row.actual_log_return, 0.10) for row in subset])),
                "p50": float(np.mean([pinball_loss(row.median, row.actual_log_return, 0.50) for row in subset])),
                "p90": float(np.mean([pinball_loss(row.p90, row.actual_log_return, 0.90) for row in subset])),
            },
            "coverage_p10_p90": float(np.mean([row.p10 <= row.actual_log_return <= row.p90 for row in subset])),
            "coverage_p25_p75": float(np.mean([row.p25 <= row.actual_log_return <= row.p75 for row in subset])),
            "width_p10_p90": float(np.mean([row.p90 - row.p10 for row in subset])),
            "width_p25_p75": float(np.mean([row.p75 - row.p25 for row in subset])),
            "first_touch_brier": float(np.mean([
                (row.first_touch_probability - float(row.first_touch_actual)) ** 2 for row in subset
            ])),
            "first_touch_log_score": float(np.mean([
                -(float(row.first_touch_actual) * math.log(min(max(row.first_touch_probability, 1e-12), 1 - 1e-12))
                  + (1.0 - float(row.first_touch_actual))
                  * math.log(1.0 - min(max(row.first_touch_probability, 1e-12), 1 - 1e-12)))
                for row in subset
            ])),
            "best_baseline": best_name,
            "best_baseline_crps": baseline_means[best_name],
            "crps_improvement_vs_best": float(
                (baseline_means[best_name] - np.mean(model_crps)) / baseline_means[best_name]
            ) if baseline_means[best_name] > 0 else 0.0,
            "diebold_mariano": diebold_mariano_hac(model_crps - best_rows, horizon=horizon),
        }
    ci_low, ci_high = _stationary_bootstrap_mean_ci(
        np.asarray(loss_differences), seed=19_960_107,
    )
    counts = [len(by_horizon.get(horizon, [])) for horizon in (1, 5, 21, 63)]
    common_origins = min(counts) if counts else 0
    reasons: list[str] = []
    if common_origins < minimum_origins:
        reasons.append(f"평가 원점 {common_origins}개로 최소 {minimum_origins}개 미달")
    for horizon in (1, 5):
        metric = horizon_metrics.get(str(horizon)) or {}
        if metric and metric["crps_improvement_vs_best"] < -0.02:
            reasons.append(f"{horizon}일 CRPS가 최우수 기준선보다 2% 넘게 열등")
    long_metrics = [horizon_metrics.get(str(horizon)) for horizon in (21, 63)]
    if all(long_metrics):
        improvement = float(np.mean([item["crps_improvement_vs_best"] for item in long_metrics]))
        if improvement < 0.02:
            reasons.append("21·63일 평균 CRPS 개선이 2% 미만")
        for horizon, item in zip((21, 63), long_metrics, strict=True):
            if not 0.76 <= item["coverage_p10_p90"] <= 0.84:
                reasons.append(f"{horizon}일 p10-p90 coverage가 76~84% 밖")
            if not 0.45 <= item["coverage_p25_p75"] <= 0.55:
                reasons.append(f"{horizon}일 p25-p75 coverage가 45~55% 밖")
    if not np.isfinite(ci_high) or ci_high > 0:
        reasons.append("21·63일 결합 CRPS 차이의 stationary-bootstrap 90% CI 상단이 0 초과")
    regimes = {
        "great_financial_crisis_2008": ("2008-01-01", "2009-06-30"),
        "pandemic_2020": ("2020-02-01", "2020-12-31"),
        "tightening_2022": ("2022-01-01", "2022-12-31"),
    }
    regime_coverage: dict[str, Any] = {}
    long_rows = by_horizon.get(63, [])
    for regime, (start, end) in regimes.items():
        subset = [row for row in long_rows if start <= row.date <= end]
        coverage = None if not subset else float(np.mean([
            row.p10 <= row.actual_log_return <= row.p90 for row in subset
        ]))
        regime_coverage[regime] = {"origins": len(subset), "coverage_p10_p90": coverage}
        if not subset:
            reasons.append(f"필수 위기 국면 누락: {regime}")
        elif coverage is not None and coverage < 0.70:
            reasons.append(f"{regime} p10-p90 coverage가 70% 미만")
    return {
        "schema_version": 1,
        "status": "pass" if not reasons else "hold",
        "gate_pass": not reasons,
        "origin_count": common_origins,
        "horizons": horizon_metrics,
        "long_horizon_loss_difference_ci90": {"lower": ci_low, "upper": ci_high},
        "regime_coverage": regime_coverage,
        "ensemble_crps_history_21d": {
            "expanding": [row.expanding_crps for row in by_horizon.get(21, [])][-52:],
            "rolling_10y": [row.rolling_crps for row in by_horizon.get(21, [])][-52:],
        },
        "distribution_selection": {
            "block_length_counts": {
                str(value): sum(row.block_length == value for row in by_horizon.get(21, []))
                for value in (5, 10, 21)
            },
            "ewma_lambda_counts": {
                f"{value:.2f}": sum(abs(row.ewma_lambda - value) < 1e-12 for row in by_horizon.get(21, []))
                for value in (0.94, 0.97)
            },
        },
        "reasons": reasons,
    }


def walk_forward_backtest(
    *,
    dates: tuple[str, ...],
    endog: np.ndarray,
    exog: np.ndarray,
    endog_names: tuple[str, ...],
    exog_names: tuple[str, ...],
    outer_start: str = "2007-01-01",
    path_count: int = 1000,
) -> tuple[list[OriginScore], dict[str, Any]]:
    """Evaluate completed weekly origins without writing any durable artifact."""
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
        expanding = select_ridge_varx(
            training_endog, training_exog,
            endog_names=endog_names, exog_names=exog_names,
        )
        rolling_start = max(0, origin - 2520)
        rolling = select_ridge_varx(
            training_endog, training_exog,
            endog_names=endog_names, exog_names=exog_names,
            train_start=rolling_start,
        )
        weight_left, weight_right, _ = ensemble_weights(expanding_history, rolling_history)
        seed = int.from_bytes(hashlib.sha256(dates[origin].encode()).digest()[:8], "big")
        block_length, ewma_lambda, _ = select_distribution_parameters(
            np.vstack((expanding.residuals, rolling.residuals)), seed=seed,
        )
        simulated = simulate_correlated_paths(
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
        expanding_only = simulate_correlated_paths(
            (expanding, rolling), weights=(1.0, 0.0),
            endog_history=training_endog, exog_last=training_exog[-1], anchor=1.0,
            path_count=path_count, horizon=63, block_length=block_length, ewma_lambda=ewma_lambda,
            seed=seed + 2,
        )
        rolling_only = simulate_correlated_paths(
            (expanding, rolling), weights=(0.0, 1.0),
            endog_history=training_endog, exog_last=training_exog[-1], anchor=1.0,
            path_count=path_count, horizon=63, block_length=block_length, ewma_lambda=ewma_lambda,
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
            touch_probability = float(np.mean(np.min(simulated["index_paths"][:, :horizon], axis=1) <= 0.90))
            row = OriginScore(
                date=dates[origin],
                horizon=horizon,
                actual_log_return=actual,
                model_crps=sample_crps(samples, actual),
                baseline_crps={name: sample_crps(values, actual) for name, values in baselines.items()},
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
