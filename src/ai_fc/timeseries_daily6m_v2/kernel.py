"""Numerical kernel of the daily6m v2 shadow (pure numpy/scipy, no file I/O).

* fresh EWMA variance: the variance used for the forecast horizon includes the
  origin-day residual (sigma2_{T+1|T}); historical standardisation stays lagged
  exactly as in the sealed V2 ``_ewma_scale`` (copied, not imported).
* mean-reverting variance term structure (term_structure arm only).
* selection-only CRN stationary bootstrap and CRN/hysteresis distribution
  selection on an anchored validation grid.
* a copy of the V2 joint simulator that preserves the sealed generator
  consumption order, so ``fresh=False, arms=("main",)`` reproduces
  ``simulate_correlated_paths_v2`` bit for bit.
* 39-level quantile grid and its trapezoid CRPS approximation.

No lead-width multiplier exists here (rejected in the contract, D3).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ai_fc.timeseries.backtest import sample_crps
from ai_fc.timeseries_v2.model import _stationary_bootstrap_batch

from .contracts import ARMS, Daily6mV2ContractError

SELECTION_SEED = 20261111
BLOCK_CANDIDATES = (5, 10, 21)
LAMBDA_CANDIDATES = (0.94, 0.97)
DEFAULT_SELECTION = (10, 0.97)
SLOW_EWMA_LAMBDA = 0.996
GRID_LEVELS = tuple(round(i / 40, 3) for i in range(1, 40))
BAND_LEVELS = (0.10, 0.25, 0.50, 0.75, 0.90)
BAND_NAMES = ("p10", "p25", "p50", "p75", "p90")
BAND_ROWS = tuple(GRID_LEVELS.index(level) for level in BAND_LEVELS)


# ---------------------------------------------------------------- variance
def _lagged_variance(residuals: np.ndarray, decay: float) -> np.ndarray:
    """Copy of the sealed V2 ``_ewma_scale`` recursion: variance[t] uses e_0..e_{t-1} only."""
    from scipy.signal import lfilter
    squared = np.square(residuals)
    variance = np.empty_like(squared, dtype=float)
    variance[0] = np.maximum(squared[0], 1e-16)
    if len(squared) > 1:
        initial = np.asarray(decay * variance[0], dtype=float).reshape((1, *squared.shape[1:]))
        filtered, _ = lfilter([1.0 - decay], [1.0, -decay], squared[:-1], axis=0, zi=initial)
        variance[1:] = filtered
    return variance


def fresh_ewma_scale(residuals: np.ndarray, decay: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (scale, fresh, lagged_last) with fresh = decay*lagged[-1] + (1-decay)*e_T**2 (per column, >=1e-16)."""
    values = np.asarray(residuals, dtype=float)
    variance = _lagged_variance(values, decay)
    fresh = np.maximum(decay * variance[-1] + (1.0 - decay) * np.square(values[-1]), 1e-16)
    scale = np.sqrt(fresh) / np.sqrt(np.maximum(variance, 1e-16))
    return scale, fresh, variance[-1]


def lagged_ewma_scale(residuals: np.ndarray, decay: float) -> np.ndarray:
    """The v1 (sealed V2) definition latest/historical, bit for bit."""
    variance = _lagged_variance(np.asarray(residuals, dtype=float), decay)
    latest = np.sqrt(np.maximum(variance[-1], 1e-16))
    historical = np.sqrt(np.maximum(variance, 1e-16))
    return latest / historical


def variance_term_structure(fresh: np.ndarray, long_run: np.ndarray, persistence: np.ndarray, horizon: int) -> np.ndarray:
    """g[k-1, j] = sqrt(max(L_j + phi_j**(k-1)*(fresh_j - L_j), 1e-16) / max(fresh_j, 1e-16)); g[0, :] == 1."""
    fresh = np.atleast_1d(np.asarray(fresh, dtype=float))
    long_run = np.atleast_1d(np.asarray(long_run, dtype=float))
    phi = np.atleast_1d(np.asarray(persistence, dtype=float))
    if horizon <= 0 or not (fresh.shape == long_run.shape == phi.shape) or np.any(phi < 0) or np.any(phi > 1):
        raise Daily6mV2ContractError("variance term structure needs matching columns and 0 <= phi <= 1")
    steps = np.arange(horizon, dtype=float)[:, None]
    variance = long_run[None, :] + np.power(phi[None, :], steps) * (fresh - long_run)[None, :]
    growth = np.sqrt(np.maximum(variance, 1e-16) / np.maximum(fresh, 1e-16)[None, :])
    growth[0, :] = 1.0
    return growth


def long_run_variance(residuals: np.ndarray, rule: str) -> np.ndarray:
    values = np.asarray(residuals, dtype=float)
    if rule == "slow_ewma_0.996":
        return fresh_ewma_scale(values, SLOW_EWMA_LAMBDA)[1]
    if rule == "sample_mean_square":
        return np.mean(values ** 2, axis=0)
    raise Daily6mV2ContractError("unregistered long-run variance rule: " + str(rule))


# ---------------------------------------------------------------- selection
def crn_stationary_bootstrap(rng: np.random.Generator, *, rows: int, paths: int, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    """Selection only: pre-draw starts and uniforms independently of the block length."""
    if rows <= 0 or paths <= 0 or horizon <= 0:
        raise Daily6mV2ContractError("CRN bootstrap dimensions must be positive")
    starts = rng.integers(0, rows, size=(paths, horizon))
    uniforms = rng.random((paths, horizon))
    return starts, uniforms


def crn_bootstrap_indexes(starts: np.ndarray, uniforms: np.ndarray, *, rows: int, mean_block: int) -> np.ndarray:
    """Circular stationary bootstrap from shared random numbers (restart if u < 1/mean_block)."""
    if mean_block <= 0:
        raise Daily6mV2ContractError("mean block must be positive")
    indexes = np.empty(starts.shape, dtype=np.int64)
    indexes[:, 0] = starts[:, 0]
    threshold = 1.0 / float(mean_block)
    for step in range(1, starts.shape[1]):
        restart = uniforms[:, step] < threshold
        indexes[:, step] = np.where(restart, starts[:, step], (indexes[:, step - 1] + 1) % rows)
    return indexes


def selection_key(block: int, decay: float) -> str:
    return f"block_{int(block)}__ewma_{float(decay):.2f}"


def anchored_validation_origins(count: int, horizon: int = 21, maximum: int = 52) -> list[int]:
    validation_count = min(maximum, (count - 252) // horizon)
    if validation_count <= 0:
        return []
    candidates = [position for position in range(252, count - horizon + 1) if position % horizon == 0]
    return candidates[-validation_count:]


def select_distribution_crn(residuals: np.ndarray, *, previous: tuple[int, float] | list | None,
                            constants: dict[str, Any]) -> dict[str, Any]:
    """CRN replicated selection on the anchored grid with 1 MC-SD hysteresis."""
    settings = constants.get("selection", constants)
    seed = int(settings.get("seed", SELECTION_SEED))
    replicates = int(settings["replicates"])
    paths = int(settings["paths"])
    horizon = int(settings["validation_horizon"])
    threshold = float(settings.get("hysteresis_mc_sd", 1.0))
    default = tuple(settings.get("default_incumbent", DEFAULT_SELECTION))
    default = (int(default[0]), float(default[1]))
    previous_tuple = None if previous is None else (int(previous[0]), float(previous[1]))
    values = np.asarray(residuals, dtype=float)
    candidates = [(block, decay) for decay in LAMBDA_CANDIDATES for block in BLOCK_CANDIDATES]
    if len(values) < 500:
        return {"chosen": list(default), "best": list(default), "incumbent": list(default),
                "previous": None if previous_tuple is None else list(previous_tuple), "fallback": True,
                "mean_margin": None, "mc_sd": None, "switched": previous_tuple is not None and previous_tuple != default,
                "scores": {}, "validation_origins": 0}
    origins = anchored_validation_origins(len(values), horizon)
    scales = {decay: {origin: fresh_ewma_scale(values[:origin], decay)[0] for origin in origins} for decay in LAMBDA_CANDIDATES}
    scores = {candidate: np.zeros(replicates) for candidate in candidates}
    for replicate in range(replicates):
        totals = {candidate: 0.0 for candidate in candidates}
        for sequence, origin in enumerate(origins):
            training = values[:origin]
            rng = np.random.default_rng([seed, replicate, sequence])
            starts, uniforms = crn_stationary_bootstrap(rng, rows=len(training), paths=paths, horizon=horizon)
            actual = float(np.sum(values[origin:origin + horizon, 0]))
            for block in BLOCK_CANDIDATES:
                indexes = crn_bootstrap_indexes(starts, uniforms, rows=len(training), mean_block=block)
                for decay in LAMBDA_CANDIDATES:
                    scale = scales[decay][origin]
                    sample = np.sum(training[indexes, 0] * scale[indexes, 0], axis=1)
                    totals[(block, decay)] += sample_crps(sample, actual)
        for candidate in candidates:
            scores[candidate][replicate] = totals[candidate] / len(origins)
    best = min(candidates, key=lambda candidate: (float(scores[candidate].mean()), selection_key(*candidate)))
    incumbent = previous_tuple if previous_tuple in scores else default
    margin = scores[incumbent] - scores[best]
    mc_sd = float(np.std(margin, ddof=1) / math.sqrt(replicates)) if replicates > 1 else 0.0
    mean_margin = float(np.mean(margin))
    chosen = best if best != incumbent and mean_margin > threshold * mc_sd else incumbent
    return {"chosen": list(chosen), "best": list(best), "incumbent": list(incumbent),
            "previous": None if previous_tuple is None else list(previous_tuple), "fallback": False,
            "mean_margin": mean_margin, "mc_sd": mc_sd,
            "switched": previous_tuple is not None and tuple(chosen) != previous_tuple,
            "scores": {selection_key(*candidate): float(scores[candidate].mean()) for candidate in candidates},
            "validation_origins": len(origins)}


# ---------------------------------------------------------------- simulation
def simulate_paths_v2_arms(fits, *, weights, endog_history, exog_last, anchor, path_count, horizon,
                           block_length, ewma_lambda, seed, persistence, anchor_rule,
                           arms=ARMS, fresh: bool = True) -> dict[str, Any]:
    """Copy of the sealed V2 simulator (same generator order) with per-arm variance treatment."""
    if path_count <= 0 or horizon <= 0:
        raise Daily6mV2ContractError("path_count and horizon must be positive")
    if abs(sum(weights) - 1.0) > 1e-12 or min(weights) < 0:
        raise Daily6mV2ContractError("ensemble weights must be fractions summing to one")
    unknown = [arm for arm in arms if arm not in ARMS]
    if unknown or not arms:
        raise Daily6mV2ContractError("unregistered arm")
    history = np.asarray(endog_history, dtype=float)
    exog = np.asarray(exog_last, dtype=float)
    rng = np.random.default_rng(seed)
    assignments = rng.choice(2, size=path_count, p=np.asarray(weights, dtype=float))
    log_returns = {arm: np.empty((path_count, horizon), dtype=float) for arm in arms}
    diagnostics = []
    for model_index, fit in enumerate(fits):
        selected = np.flatnonzero(assignments == model_index)
        count = len(selected)
        if count == 0:
            diagnostics.append(None)
            continue
        residuals = np.asarray(fit.residuals, dtype=float)
        if len(residuals) < max(30, block_length):
            raise Daily6mV2ContractError("insufficient multivariate residual history")
        bootstrap = _stationary_bootstrap_batch(rng, rows=len(residuals), paths=count, horizon=horizon, mean_block=block_length)
        if fresh:
            scales, fresh_variance, lagged_last = fresh_ewma_scale(residuals, ewma_lambda)
        else:
            scales = lagged_ewma_scale(residuals, ewma_lambda)
            fresh_variance = lagged_last = np.maximum(_lagged_variance(residuals, ewma_lambda)[-1], 1e-16)
        base = residuals[bootstrap] * scales[bootstrap]
        long_run = long_run_variance(residuals, anchor_rule)
        diagnostics.append({"fresh_over_lagged_sd": np.sqrt(fresh_variance / np.maximum(lagged_last, 1e-16)).tolist(),
                            "long_run_over_fresh": (long_run / fresh_variance).tolist()})
        for arm in arms:
            innovations = base
            if arm == "term_structure":
                growth = variance_term_structure(fresh_variance, long_run, persistence, horizon)
                innovations = base * growth[None, :, :]
            path_history = np.broadcast_to(history[-fit.lag:], (count, fit.lag, history.shape[1])).copy()
            for step in range(horizon):
                lagged = np.concatenate([path_history[:, -offset, :] for offset in range(1, fit.lag + 1)], axis=1)
                if fit.exog_names:
                    lagged = np.column_stack((lagged, np.broadcast_to(exog, (count, len(exog)))))
                scaled = (lagged - fit.scaler.median) / fit.scaler.iqr
                predicted = fit.coefficients[0] + scaled @ fit.coefficients[1:]
                if arm == "zero_drift":
                    predicted = np.array(predicted, dtype=float, copy=True)
                    predicted[:, 0] = 0.0
                next_values = predicted + innovations[:, step, :]
                log_returns[arm][selected, step] = next_values[:, 0]
                if fit.lag == 1:
                    path_history[:, 0, :] = next_values
                else:
                    path_history[:, :-1, :] = path_history[:, 1:, :]
                    path_history[:, -1, :] = next_values
    result: dict[str, Any] = {"assignments": assignments, "diagnostics": diagnostics}
    for arm in arms:
        result[arm] = {"log_returns": log_returns[arm], "index_paths": float(anchor) * np.exp(np.cumsum(log_returns[arm], axis=1))}
    return result


# ---------------------------------------------------------------- summaries and scores
def _require_paths(index_paths: np.ndarray, anchor: float) -> np.ndarray:
    paths = np.asarray(index_paths, dtype=float)
    if paths.ndim != 2 or not paths.shape[0] or not np.isfinite(paths).all() or np.any(paths <= 0) \
            or not math.isfinite(float(anchor)) or float(anchor) <= 0:
        raise Daily6mV2ContractError("v2 paths must be finite and positive (no clipping applied)")
    return paths


def quantile_grid_unrounded(index_paths: np.ndarray, *, anchor: float) -> np.ndarray:
    paths = _require_paths(index_paths, anchor)
    quantiles = np.quantile(paths, GRID_LEVELS, axis=0)
    grid = np.log(quantiles / float(anchor))
    if not np.isfinite(grid).all():
        raise Daily6mV2ContractError("quantile grid is not finite")
    return grid


def quantile_grid(index_paths: np.ndarray, *, anchor: float) -> np.ndarray:
    """39 log quantiles ln(q/anchor), shape (39, H), rounded to 10 decimals."""
    return np.round(quantile_grid_unrounded(index_paths, anchor=anchor), 10)


def pinball(tau: float, error: float) -> float:
    return error * (tau - (1.0 if error < 0 else 0.0))


def crps_grid39(y: float, q) -> float:
    """2 * explicit trapezoid over tau of the pinball losses at the 39 grid levels."""
    values = [float(item) for item in q]
    if len(values) != len(GRID_LEVELS) or not math.isfinite(float(y)) or not all(math.isfinite(item) for item in values):
        raise Daily6mV2ContractError("CRPS39 needs 39 finite quantiles and a finite outcome")
    losses = [pinball(tau, float(y) - value) for tau, value in zip(GRID_LEVELS, values)]
    total = 0.0
    for index in range(len(GRID_LEVELS) - 1):
        total += (GRID_LEVELS[index + 1] - GRID_LEVELS[index]) * (losses[index] + losses[index + 1]) / 2.0
    return 2.0 * total


def qs5(y: float, bands: dict[str, float], anchor: float) -> float:
    return (2.0 / 5.0) * sum(pinball(tau, float(y) - math.log(float(bands[name]) / float(anchor)))
                             for tau, name in zip(BAND_LEVELS, BAND_NAMES))


def summarize_compact(index_paths: np.ndarray, *, anchor: float, future_dates: list[str]) -> list[dict[str, Any]]:
    """Subset of the v1 joint-path summary from the same matrix (bands and daily/origin rise probabilities)."""
    paths = _require_paths(index_paths, anchor)
    if paths.shape[1] != len(future_dates) or future_dates != sorted(set(future_dates)):
        raise Daily6mV2ContractError("one strictly increasing date per simulated session is required")
    previous = np.column_stack((np.full(paths.shape[0], float(anchor)), paths[:, :-1]))
    bands = np.quantile(paths, BAND_LEVELS, axis=0)
    daily = np.mean(paths > previous, axis=0)
    origin = np.mean(paths > anchor, axis=0)
    return [{"date": day, "band_index": {name: float(bands[level, step]) for level, name in enumerate(BAND_NAMES)},
             "probability_up_from_previous": float(daily[step]), "probability_up_from_origin": float(origin[step])}
            for step, day in enumerate(future_dates)]
