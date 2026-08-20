"""V2-only numerical kernels that preserve the preregistered VARX semantics.

The V1 selector refits the same robust-scaled design once for every ridge
penalty.  V2 batches those seven solves after constructing each purged design
once.  Candidate grids, purge, embargo, predictions, and tie-breaking remain
identical; only redundant linear algebra is removed.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable

import numpy as np

from ai_fc.timeseries.backtest import sample_crps
from ai_fc.timeseries.model import (
    RidgeVARXFit,
    RobustScaler,
    TimeSeriesModelError,
    fit_ridge_varx,
)


def _design(
    endog: np.ndarray,
    exog: np.ndarray,
    *,
    lag: int,
) -> tuple[np.ndarray, np.ndarray]:
    rows = []
    for index in range(lag, len(endog)):
        pieces = [endog[index - offset] for offset in range(1, lag + 1)]
        if exog.shape[1]:
            pieces.append(exog[index - 1])
        rows.append(np.concatenate(pieces))
    return np.vstack(rows), endog[lag:]


def _prediction_row(
    history: np.ndarray,
    exog_row: np.ndarray,
    *,
    lag: int,
    scaler: RobustScaler,
) -> np.ndarray:
    pieces = [history[-offset] for offset in range(1, lag + 1)]
    if exog_row.size:
        pieces.append(np.asarray(exog_row, dtype=float))
    raw = np.concatenate(pieces)
    return np.concatenate(([1.0], scaler.transform(raw[None, :])[0]))


def select_ridge_varx_v2(
    endog: np.ndarray,
    exog: np.ndarray,
    *,
    endog_names: tuple[str, ...],
    exog_names: tuple[str, ...],
    lag_candidates: Iterable[int] = (1, 2, 5),
    alpha_candidates: Iterable[float] = (1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0),
    purge: int = 63,
    embargo: int = 5,
    train_start: int = 0,
    train_end: int | None = None,
) -> RidgeVARXFit:
    """Select the same lag/ridge grid as V1 using batched penalty solves."""
    train_end = len(endog) if train_end is None else int(train_end)
    local_y = np.asarray(endog[train_start:train_end], dtype=float)
    local_x = np.asarray(exog[train_start:train_end], dtype=float)
    lags = tuple(int(value) for value in lag_candidates)
    alphas = np.asarray(tuple(float(value) for value in alpha_candidates), dtype=float)
    if local_y.ndim != 2 or local_y.shape[1] != len(endog_names):
        raise TimeSeriesModelError("endogenous matrix/name mismatch")
    if local_x.ndim != 2 or local_x.shape != (len(local_y), len(exog_names)):
        raise TimeSeriesModelError("exogenous matrix/name mismatch")
    if not lags or not len(alphas):
        raise TimeSeriesModelError("lag and ridge grids must be non-empty")
    if len(local_y) < max(320, purge + max(lags) + 32):
        raise TimeSeriesModelError("at least 320 completed sessions are required for inner selection")
    origins = list(range(max(252, purge + 64), len(local_y), max(embargo, 21)))
    if len(origins) > 52:
        origins = origins[-52:]

    squared_errors: dict[tuple[int, float], list[float]] = {
        (lag, float(alpha)): [] for lag in lags for alpha in alphas
    }
    for origin in origins:
        fit_end = origin - purge
        for lag in lags:
            if fit_end <= lag + 64:
                continue
            raw_design, targets = _design(local_y[:fit_end], local_x[:fit_end], lag=lag)
            if not np.isfinite(raw_design).all() or not np.isfinite(targets).all():
                raise TimeSeriesModelError("VARX training matrix contains missing or infinite values")
            scaler = RobustScaler.fit(raw_design)
            scaled = scaler.transform(raw_design)
            design = np.column_stack((np.ones(len(scaled)), scaled))
            gram = design.T @ design
            rhs = design.T @ targets
            penalty = np.eye(design.shape[1], dtype=float)
            penalty[0, 0] = 0.0
            systems = gram[None, :, :] + alphas[:, None, None] * penalty[None, :, :]
            right_sides = np.broadcast_to(rhs, (len(alphas), *rhs.shape))
            coefficients = np.linalg.solve(systems, right_sides)
            row = _prediction_row(
                local_y[:origin], local_x[origin - 1], lag=lag, scaler=scaler,
            )
            predictions = np.einsum("p,apm->am", row, coefficients)
            target = local_y[origin]
            for alpha_index, alpha in enumerate(alphas):
                squared_errors[(lag, float(alpha))].append(
                    float((target[0] - predictions[alpha_index, 0]) ** 2)
                )

    candidates = [
        (float(np.mean(errors)), lag, alpha)
        for (lag, alpha), errors in squared_errors.items()
        if errors
    ]
    if not candidates:
        raise TimeSeriesModelError("no purged inner selection origins were available")
    score, lag, alpha = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    fitted = fit_ridge_varx(
        endog,
        exog,
        lag=lag,
        alpha=alpha,
        endog_names=endog_names,
        exog_names=exog_names,
        train_start=train_start,
        train_end=train_end,
    )
    return RidgeVARXFit(
        lag=fitted.lag,
        alpha=fitted.alpha,
        endog_names=fitted.endog_names,
        exog_names=fitted.exog_names,
        predictor_names=fitted.predictor_names,
        coefficients=fitted.coefficients,
        scaler=fitted.scaler,
        residuals=fitted.residuals,
        train_start=fitted.train_start,
        train_end=fitted.train_end,
        selection_score=float(score) if math.isfinite(score) else score,
    )


def _stationary_bootstrap_batch(
    rng: np.random.Generator,
    *,
    rows: int,
    paths: int,
    horizon: int,
    mean_block: int,
) -> np.ndarray:
    if rows <= 0 or paths <= 0 or horizon <= 0 or mean_block <= 0:
        raise TimeSeriesModelError("stationary bootstrap dimensions must be positive")
    indexes = np.empty((paths, horizon), dtype=np.int64)
    current = rng.integers(0, rows, size=paths)
    indexes[:, 0] = current
    restart_probability = 1.0 / float(mean_block)
    for step in range(1, horizon):
        current = (current + 1) % rows
        restart = rng.random(paths) < restart_probability
        if np.any(restart):
            current[restart] = rng.integers(0, rows, size=int(np.sum(restart)))
        indexes[:, step] = current
    return indexes


def _ewma_scale(residuals: np.ndarray, decay: float) -> np.ndarray:
    squared = np.square(residuals)
    variance = np.empty_like(squared)
    variance[0] = np.maximum(squared[0], 1e-16)
    for index in range(1, len(residuals)):
        variance[index] = decay * variance[index - 1] + (1.0 - decay) * squared[index - 1]
    latest = np.sqrt(np.maximum(variance[-1], 1e-16))
    historical = np.sqrt(np.maximum(variance, 1e-16))
    return latest / historical


def select_distribution_parameters_v2(
    residuals: np.ndarray,
    *,
    block_candidates: Iterable[int] = (5, 10, 21),
    ewma_candidates: Iterable[float] = (0.94, 0.97),
    validation_horizon: int = 21,
    seed: int = 0,
) -> tuple[int, float, dict[str, float]]:
    """Select the frozen block/EWMA grid with a batched stationary bootstrap."""
    values = np.asarray(residuals, dtype=float)
    if len(values) < 500:
        return 10, 0.97, {"fallback": math.nan}
    validation_count = min(52, (len(values) - 252) // validation_horizon)
    origins = list(
        range(len(values) - validation_count * validation_horizon, len(values), validation_horizon)
    )
    scores: dict[str, float] = {}
    for block in block_candidates:
        for decay in ewma_candidates:
            candidate_scores: list[float] = []
            for sequence, origin in enumerate(origins):
                training = values[:origin]
                if len(training) < 252:
                    continue
                rng = np.random.default_rng(seed + sequence + int(block * 100 + decay * 1000))
                scales = _ewma_scale(training, float(decay))
                indexes = _stationary_bootstrap_batch(
                    rng,
                    rows=len(training),
                    paths=1000,
                    horizon=validation_horizon,
                    mean_block=int(block),
                )
                samples = np.sum(training[indexes, 0] * scales[indexes, 0], axis=1)
                actual_window = values[origin:origin + validation_horizon]
                if len(actual_window) == validation_horizon:
                    candidate_scores.append(sample_crps(samples, float(np.sum(actual_window[:, 0]))))
            key = f"block_{int(block)}__ewma_{float(decay):.2f}"
            scores[key] = float(np.mean(candidate_scores)) if candidate_scores else math.inf
    selected = min(scores, key=lambda key: (scores[key], key))
    block_part, ewma_part = selected.split("__")
    return (
        int(block_part.removeprefix("block_")),
        float(ewma_part.removeprefix("ewma_")),
        scores,
    )


def simulate_correlated_paths_v2(
    fits: tuple[RidgeVARXFit, RidgeVARXFit],
    *,
    weights: tuple[float, float],
    endog_history: np.ndarray,
    exog_last: np.ndarray,
    anchor: float,
    path_count: int,
    horizon: int,
    block_length: int,
    ewma_lambda: float,
    seed: int,
) -> dict[str, object]:
    """Simulate the same correlated VARX residual process in path batches."""
    if path_count <= 0 or horizon <= 0:
        raise TimeSeriesModelError("path_count and horizon must be positive")
    if abs(sum(weights) - 1.0) > 1e-12 or min(weights) < 0:
        raise TimeSeriesModelError("ensemble weights must be fractions summing to one")
    history = np.asarray(endog_history, dtype=float)
    exog = np.asarray(exog_last, dtype=float)
    rng = np.random.default_rng(seed)
    assignments = rng.choice(2, size=path_count, p=np.asarray(weights, dtype=float))
    log_return_paths = np.empty((path_count, horizon), dtype=float)
    innovation_paths = np.empty((path_count, horizon, history.shape[1]), dtype=float)
    for model_index, fit in enumerate(fits):
        selected_paths = np.flatnonzero(assignments == model_index)
        count = len(selected_paths)
        if count == 0:
            continue
        residuals = np.asarray(fit.residuals, dtype=float)
        if len(residuals) < max(30, block_length):
            raise TimeSeriesModelError("insufficient multivariate residual history")
        bootstrap = _stationary_bootstrap_batch(
            rng,
            rows=len(residuals),
            paths=count,
            horizon=horizon,
            mean_block=block_length,
        )
        scales = _ewma_scale(residuals, ewma_lambda)
        path_history = np.broadcast_to(
            history[-fit.lag:], (count, fit.lag, history.shape[1]),
        ).copy()
        innovations = residuals[bootstrap] * scales[bootstrap]
        for step in range(horizon):
            lagged = np.concatenate(
                [path_history[:, -offset, :] for offset in range(1, fit.lag + 1)], axis=1,
            )
            if fit.exog_names:
                lagged = np.column_stack((lagged, np.broadcast_to(exog, (count, len(exog)))))
            scaled = (lagged - fit.scaler.median) / fit.scaler.iqr
            predicted = fit.coefficients[0] + scaled @ fit.coefficients[1:]
            next_values = predicted + innovations[:, step, :]
            log_return_paths[selected_paths, step] = next_values[:, 0]
            innovation_paths[selected_paths, step, :] = innovations[:, step, :]
            if fit.lag == 1:
                path_history[:, 0, :] = next_values
            else:
                path_history[:, :-1, :] = path_history[:, 1:, :]
                path_history[:, -1, :] = next_values
    index_paths = float(anchor) * np.exp(np.cumsum(log_return_paths, axis=1))
    path_hash = hashlib.sha256(
        np.ascontiguousarray(index_paths, dtype=np.float64).tobytes()
    ).hexdigest()
    return {
        "log_returns": log_return_paths,
        "innovations": innovation_paths,
        "index_paths": index_paths,
        "assignments": assignments,
        "path_hash": path_hash,
    }
