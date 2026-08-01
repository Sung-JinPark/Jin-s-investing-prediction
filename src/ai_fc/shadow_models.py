"""Display/evaluation-only quantitative challengers; no promotion or pooling occurs here."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Sequence

import numpy as np
from scipy.optimize import minimize


def ewma_variance(returns: Sequence[float], decay: float = 0.94) -> float:
    values = np.asarray(returns, dtype=float)
    if values.size < 2 or not 0 < decay < 1:
        raise ValueError("EWMA needs at least two returns and decay in (0,1)")
    variance = float(values.var(ddof=1))
    for value in values:
        variance = decay * variance + (1 - decay) * float(value * value)
    return variance


@dataclass(frozen=True)
class Garch11Fit:
    omega: float
    alpha: float
    beta: float
    variance: float
    converged: bool


def fit_garch11(returns: Sequence[float]) -> Garch11Fit:
    values = np.asarray(returns, dtype=float)
    if values.size < 60:
        raise ValueError("GARCH(1,1) shadow requires at least 60 returns")
    initial_var = float(values.var(ddof=1))

    def objective(params: np.ndarray) -> float:
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
            return 1e30
        variance = initial_var
        loss = 0.0
        for previous, current in zip(values[:-1], values[1:]):
            variance = omega + alpha * previous * previous + beta * variance
            loss += np.log(variance) + current * current / variance
        return float(loss)

    result = minimize(
        objective, np.asarray([initial_var * .05, .08, .88]), method="Nelder-Mead",
        options={"maxiter": 2_000, "xatol": 1e-12, "fatol": 1e-12})
    omega, alpha, beta = map(float, result.x)
    variance = initial_var
    for previous in values:
        variance = omega + alpha * previous * previous + beta * variance
    return Garch11Fit(omega, alpha, beta, float(variance), bool(result.success))


def regime_block_bootstrap(
    returns: Sequence[float], *, horizon: int, n_paths: int = 2_000,
    block_length: int = 10, seed: int = 42,
) -> np.ndarray:
    """Bootstrap blocks from the current volatility regime (median split)."""
    values = np.asarray(returns, dtype=float)
    if values.size < block_length * 3:
        raise ValueError("insufficient history for regime block bootstrap")
    rolling = np.asarray([
        values[max(0, idx - 19):idx + 1].std(ddof=0) for idx in range(values.size)
    ])
    current_high = rolling[-1] >= np.median(rolling)
    eligible = np.flatnonzero((rolling >= np.median(rolling)) == current_high)
    starts = eligible[eligible <= len(values) - block_length]
    if starts.size == 0:
        raise ValueError("no blocks in the current regime")
    rng = np.random.default_rng(seed)
    out = np.empty((n_paths, horizon), dtype=float)
    for row in range(n_paths):
        cursor = 0
        while cursor < horizon:
            start = int(rng.choice(starts))
            block = values[start:start + block_length]
            take = min(block.size, horizon - cursor)
            out[row, cursor:cursor + take] = block[:take]
            cursor += take
    return out


def breeden_litzenberger_density(
    strikes: Sequence[float], call_prices: Sequence[float], *,
    risk_free_rate: float, maturity_years: float,
) -> dict[str, np.ndarray | str]:
    """Finite-difference risk-neutral terminal density from a call-price smile."""
    k, calls = np.asarray(strikes, dtype=float), np.asarray(call_prices, dtype=float)
    if k.size < 5 or k.shape != calls.shape or np.any(np.diff(k) <= 0) or maturity_years <= 0:
        raise ValueError("ordered strike/call arrays with at least five points are required")
    first = np.gradient(calls, k)
    second = np.gradient(first, k)
    density = np.maximum(0.0, exp(risk_free_rate * maturity_years) * second)
    mass = float(np.trapezoid(density, k))
    if mass <= 0:
        raise ValueError("option smile does not imply a positive density")
    density /= mass
    return {
        "strikes": k,
        "density": density,
        "probability_space": "risk_neutral_terminal",
        "usage": "reference_only",
    }
