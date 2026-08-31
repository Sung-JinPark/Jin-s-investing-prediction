"""Deterministic baselines, leakage-safe splits, and probabilistic scores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .quant.mc import gbm_paths


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    p, y = np.asarray(probabilities, dtype=float), np.asarray(outcomes, dtype=float)
    if p.shape != y.shape or p.size == 0 or np.any((p < 0) | (p > 1)):
        raise ValueError("Brier inputs must be aligned non-empty probabilities in [0,1]")
    return float(np.mean((p - y) ** 2))


def log_score(probabilities: Sequence[float], outcomes: Sequence[int], eps: float = 1e-12) -> float:
    p, y = np.asarray(probabilities, dtype=float), np.asarray(outcomes, dtype=float)
    if p.shape != y.shape or p.size == 0 or np.any((p < 0) | (p > 1)):
        raise ValueError("log-score inputs must be aligned probabilities in [0,1]")
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def pinball_loss(actual: Sequence[float], forecast: Sequence[float], quantile: float) -> float:
    if not 0 < quantile < 1:
        raise ValueError("quantile must be in (0,1)")
    y, q = np.asarray(actual, dtype=float), np.asarray(forecast, dtype=float)
    if y.shape != q.shape or y.size == 0:
        raise ValueError("pinball inputs must be aligned and non-empty")
    error = y - q
    return float(np.mean(np.maximum(quantile * error, (quantile - 1) * error)))


def crps_ensemble(actual: Sequence[float], samples: np.ndarray) -> float:
    """Empirical CRPS: E|X-y| - 0.5 E|X-X'|."""
    y = np.asarray(actual, dtype=float)
    x = np.asarray(samples, dtype=float)
    if x.ndim == 1:
        x = x[None, :]
    if x.shape[0] != y.size or x.shape[1] < 2:
        raise ValueError("samples must have shape (n_observations, n_draws>=2)")
    first = np.mean(np.abs(x - y[:, None]), axis=1)
    ordered = np.sort(x, axis=1)
    n = ordered.shape[1]
    weights = 2 * np.arange(1, n + 1) - n - 1
    pairwise_half = np.sum(ordered * weights, axis=1) / (n * n)
    return float(np.mean(first - pairwise_half))


def interval_diagnostics(
    actual: Sequence[float], lower: Sequence[float], upper: Sequence[float]
) -> dict[str, float]:
    y, lo, hi = map(lambda values: np.asarray(values, dtype=float), (actual, lower, upper))
    if y.shape != lo.shape or y.shape != hi.shape or y.size == 0 or np.any(lo > hi):
        raise ValueError("invalid interval inputs")
    return {
        "coverage": float(np.mean((y >= lo) & (y <= hi))),
        "mean_width": float(np.mean(hi - lo)),
    }


@dataclass(frozen=True)
class WalkForwardSplit:
    train: range
    test: range


def expanding_walk_forward(
    n: int, *, min_train: int, test_size: int, purge: int = 0, embargo: int = 0
) -> list[WalkForwardSplit]:
    if min_train < 1 or test_size < 1 or purge < 0 or embargo < 0:
        raise ValueError("invalid walk-forward parameters")
    splits: list[WalkForwardSplit] = []
    test_start = min_train + purge
    while test_start + test_size <= n:
        train_end = test_start - purge
        splits.append(WalkForwardSplit(range(0, train_end), range(test_start, test_start + test_size)))
        test_start += test_size + embargo
    return splits


def _log_returns(closes: Sequence[float]) -> np.ndarray:
    values = np.asarray(closes, dtype=float)
    if values.size < 3 or np.any(values <= 0):
        raise ValueError("at least three positive closes are required")
    return np.diff(np.log(values))


def _paths_from_returns(last: float, sampled: np.ndarray) -> np.ndarray:
    return last * np.exp(np.cumsum(sampled, axis=1))


def run_baseline_suite(
    closes: Sequence[float], *, horizon: int, n_paths: int = 2_000, seed: int = 42,
    event_outcomes: Sequence[int] = (), event_months: Sequence[int] = (), target_month: int | None = None,
) -> dict[str, dict]:
    """Run the six preregistered baselines on one deterministic snapshot."""
    returns = _log_returns(closes)
    rng = np.random.default_rng(seed)
    mean, sigma = float(returns.mean()), float(returns.std(ddof=1))
    rw = _paths_from_returns(float(closes[-1]), rng.normal(mean, sigma, (n_paths, horizon)))
    hist = _paths_from_returns(
        float(closes[-1]), rng.choice(returns, size=(n_paths, horizon), replace=True))
    block_len = max(2, min(20, int(round(len(returns) ** (1 / 3)))))
    block = np.empty((n_paths, horizon), dtype=float)
    max_start = max(1, len(returns) - block_len + 1)
    for row in range(n_paths):
        cursor = 0
        while cursor < horizon:
            start = int(rng.integers(0, max_start))
            chunk = returns[start:start + block_len]
            take = min(len(chunk), horizon - cursor)
            block[row, cursor:cursor + take] = chunk[:take]
            cursor += take
    block_paths = _paths_from_returns(float(closes[-1]), block)
    gbm = gbm_paths(list(closes), lookback=min(252, len(closes) - 1), horizon=horizon,
                    n=n_paths, seed=seed)

    outcomes = np.asarray(event_outcomes, dtype=float)
    unconditional = float(outcomes.mean()) if outcomes.size else None
    seasonal = unconditional
    if outcomes.size and event_months and target_month is not None:
        months = np.asarray(event_months)
        selected = outcomes[months == target_month]
        seasonal = float(selected.mean()) if selected.size else unconditional
    return {
        "bl.rw_drift": {"kind": "paths", "paths": rw, "seed": seed},
        "bl.uncond_base": {"kind": "event_probability", "probability": unconditional},
        "bl.seasonal_base": {"kind": "event_probability", "probability": seasonal},
        "bl.hist_sim": {"kind": "paths", "paths": hist, "seed": seed},
        "bl.block_boot": {"kind": "paths", "paths": block_paths, "seed": seed,
                          "block_length": block_len},
        "bl.gbm_v1": {"kind": "paths", "paths": gbm, "seed": seed},
    }


def clustered_bootstrap_mean(
    values: Sequence[float], *, n_boot: int = 10_000, seed: int = 42,
    confidence: float = 0.95,
) -> dict[str, float | int | None]:
    data = np.asarray(values, dtype=float)
    if data.size == 0:
        return {"n_unique": 0, "mean": None, "ci_lo": None, "ci_hi": None}
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=float)
    for idx in range(n_boot):
        means[idx] = rng.choice(data, size=data.size, replace=True).mean()
    alpha = (1 - confidence) / 2
    return {
        "n_unique": int(data.size),
        "mean": float(data.mean()),
        "ci_lo": float(np.quantile(means, alpha)),
        "ci_hi": float(np.quantile(means, 1 - alpha)),
    }
