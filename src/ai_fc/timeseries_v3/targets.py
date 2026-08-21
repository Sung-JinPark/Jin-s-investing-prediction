"""Direct cumulative-return targets and index reconstruction."""

from __future__ import annotations

import numpy as np


HORIZONS = (1, 5, 21, 63)


def direct_log_return_targets(prices: np.ndarray, horizons: tuple[int, ...] = HORIZONS) -> dict[int, np.ndarray]:
    values = np.asarray(prices, dtype=float)
    if values.ndim != 1 or values.size <= max(horizons) or np.any(values <= 0):
        raise ValueError("positive one-dimensional price history longer than max horizon required")
    log_prices = np.log(values)
    output: dict[int, np.ndarray] = {}
    for horizon in horizons:
        target = np.full(values.size, np.nan, dtype=float)
        target[:-horizon] = log_prices[horizon:] - log_prices[:-horizon]
        output[int(horizon)] = target
    return output


def cumulative_returns_from_daily(daily_log_returns: np.ndarray, horizons: tuple[int, ...] = HORIZONS) -> dict[int, float]:
    values = np.asarray(daily_log_returns, dtype=float)
    if values.ndim != 1 or values.size < max(horizons):
        raise ValueError("daily returns must cover every requested horizon")
    return {horizon: float(np.sum(values[:horizon])) for horizon in horizons}


def index_from_log_return(anchor: float, log_return: np.ndarray | float) -> np.ndarray:
    if anchor <= 0:
        raise ValueError("anchor must be positive")
    return float(anchor) * np.exp(np.asarray(log_return, dtype=float))
