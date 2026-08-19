"""Leakage-controlled Ridge VARX fitting and correlated path simulation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np


class TimeSeriesModelError(RuntimeError):
    """The preregistered time-series model cannot be fit without changing scope."""


@dataclass(frozen=True)
class RobustScaler:
    median: np.ndarray
    iqr: np.ndarray

    @classmethod
    def fit(cls, values: np.ndarray) -> "RobustScaler":
        median = np.nanmedian(values, axis=0)
        q25 = np.nanquantile(values, 0.25, axis=0)
        q75 = np.nanquantile(values, 0.75, axis=0)
        iqr = q75 - q25
        iqr = np.where(np.isfinite(iqr) & (np.abs(iqr) > 1e-12), iqr, 1.0)
        return cls(median=median, iqr=iqr)

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (np.asarray(values, dtype=float) - self.median) / self.iqr


@dataclass(frozen=True)
class RidgeVARXFit:
    lag: int
    alpha: float
    endog_names: tuple[str, ...]
    exog_names: tuple[str, ...]
    predictor_names: tuple[str, ...]
    coefficients: np.ndarray
    scaler: RobustScaler
    residuals: np.ndarray
    train_start: int
    train_end: int
    selection_score: float

    def design_row(self, history: np.ndarray, exog_row: np.ndarray) -> np.ndarray:
        if history.shape[0] < self.lag:
            raise TimeSeriesModelError("insufficient endogenous lags for prediction")
        pieces = [history[-lag] for lag in range(1, self.lag + 1)]
        if self.exog_names:
            pieces.append(np.asarray(exog_row, dtype=float))
        raw = np.concatenate(pieces)
        return self.scaler.transform(raw[None, :])[0]

    def predict(self, history: np.ndarray, exog_row: np.ndarray) -> np.ndarray:
        scaled = self.design_row(history, exog_row)
        return self.coefficients[0] + scaled @ self.coefficients[1:]

    def target_contributions(
        self, history: np.ndarray, exog_row: np.ndarray, *, target_index: int = 0,
    ) -> dict[str, float]:
        scaled = self.design_row(history, exog_row)
        values = {"intercept": float(self.coefficients[0, target_index])}
        for name, value, coefficient in zip(
            self.predictor_names, scaled, self.coefficients[1:, target_index], strict=True,
        ):
            values[name] = float(value * coefficient)
        return values

    def manifest(self) -> dict[str, Any]:
        return {
            "lag": self.lag,
            "alpha": self.alpha,
            "endogenous": list(self.endog_names),
            "exogenous": list(self.exog_names),
            "predictors": list(self.predictor_names),
            "coefficients": self.coefficients.tolist(),
            "scaler": {"median": self.scaler.median.tolist(), "iqr": self.scaler.iqr.tolist()},
            "residual_count": int(self.residuals.shape[0]),
            "residual_hash": _array_hash(self.residuals),
            "train_start": self.train_start,
            "train_end": self.train_end,
            "selection_score": self.selection_score,
        }


def _array_hash(values: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(values, dtype=np.float64)
    return hashlib.sha256(contiguous.tobytes()).hexdigest()


def deterministic_seed(model_id: str, model_version: int, as_of: str) -> int:
    digest = hashlib.sha256(f"{model_id}|{model_version}|{as_of}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _design(
    endog: np.ndarray, exog: np.ndarray, *, lag: int,
    endog_names: tuple[str, ...], exog_names: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
    endog = np.asarray(endog, dtype=float)
    exog = np.asarray(exog, dtype=float)
    if endog.ndim != 2 or endog.shape[1] != len(endog_names):
        raise TimeSeriesModelError("endogenous matrix/name mismatch")
    if exog.ndim != 2 or exog.shape[0] != endog.shape[0] or exog.shape[1] != len(exog_names):
        raise TimeSeriesModelError("exogenous matrix/name mismatch")
    if len(endog) <= lag:
        raise TimeSeriesModelError("training matrix shorter than requested lag")
    rows: list[np.ndarray] = []
    for time_index in range(lag, len(endog)):
        parts = [endog[time_index - offset] for offset in range(1, lag + 1)]
        if exog.shape[1]:
            parts.append(exog[time_index - 1])
        rows.append(np.concatenate(parts))
    names = tuple(
        f"{name}_lag{offset}"
        for offset in range(1, lag + 1)
        for name in endog_names
    ) + tuple(f"{name}_lag1" for name in exog_names)
    return np.vstack(rows), endog[lag:], names


def _fit_given(
    endog: np.ndarray, exog: np.ndarray, *, lag: int, alpha: float,
    endog_names: tuple[str, ...], exog_names: tuple[str, ...],
    train_start: int = 0, train_end: int | None = None, selection_score: float = math.nan,
) -> RidgeVARXFit:
    train_end = len(endog) if train_end is None else train_end
    sliced_endog = np.asarray(endog[train_start:train_end], dtype=float)
    sliced_exog = np.asarray(exog[train_start:train_end], dtype=float)
    x, y, names = _design(
        sliced_endog, sliced_exog, lag=lag,
        endog_names=endog_names, exog_names=exog_names,
    )
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise TimeSeriesModelError("VARX training matrix contains missing or infinite values")
    scaler = RobustScaler.fit(x)
    z = scaler.transform(x)
    design = np.column_stack((np.ones(len(z)), z))
    penalty = np.eye(design.shape[1], dtype=float) * float(alpha)
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    residuals = y - design @ coefficients
    return RidgeVARXFit(
        lag=lag,
        alpha=float(alpha),
        endog_names=endog_names,
        exog_names=exog_names,
        predictor_names=names,
        coefficients=coefficients,
        scaler=scaler,
        residuals=residuals,
        train_start=train_start,
        train_end=train_end,
        selection_score=float(selection_score),
    )


def fit_ridge_varx(
    endog: np.ndarray,
    exog: np.ndarray,
    *,
    lag: int,
    alpha: float,
    endog_names: tuple[str, ...],
    exog_names: tuple[str, ...],
    train_start: int = 0,
    train_end: int | None = None,
) -> RidgeVARXFit:
    """Public fixed-hyperparameter fit used by synthetic recovery tests."""
    return _fit_given(
        endog,
        exog,
        lag=lag,
        alpha=alpha,
        endog_names=endog_names,
        exog_names=exog_names,
        train_start=train_start,
        train_end=train_end,
    )


def select_ridge_varx(
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
    """Select lag and ridge alpha inside the outer-origin training set only."""
    train_end = len(endog) if train_end is None else train_end
    local_y = np.asarray(endog[train_start:train_end], dtype=float)
    local_x = np.asarray(exog[train_start:train_end], dtype=float)
    if len(local_y) < max(320, purge + max(lag_candidates) + 32):
        raise TimeSeriesModelError("at least 320 completed sessions are required for inner selection")
    # Purged rolling origins are spaced by at least the embargo. No result after an
    # origin can enter the fit used to score that origin.
    origins = list(range(max(252, purge + 64), len(local_y), max(embargo, 21)))
    if len(origins) > 52:
        origins = origins[-52:]
    candidates: list[tuple[float, int, float]] = []
    for lag in lag_candidates:
        for alpha in alpha_candidates:
            errors: list[float] = []
            for origin in origins:
                fit_end = origin - purge
                if fit_end <= lag + 64:
                    continue
                fitted = _fit_given(
                    local_y[:fit_end], local_x[:fit_end], lag=int(lag), alpha=float(alpha),
                    endog_names=endog_names, exog_names=exog_names,
                )
                prediction = fitted.predict(local_y[:origin], local_x[origin - 1])
                errors.append(float((local_y[origin, 0] - prediction[0]) ** 2))
            if errors:
                candidates.append((float(np.mean(errors)), int(lag), float(alpha)))
    if not candidates:
        raise TimeSeriesModelError("no purged inner selection origins were available")
    score, lag, alpha = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    return _fit_given(
        endog, exog, lag=lag, alpha=alpha,
        endog_names=endog_names, exog_names=exog_names,
        train_start=train_start, train_end=train_end, selection_score=score,
    )


def ensemble_weights(
    expanding_crps: Iterable[float], rolling_crps: Iterable[float], *, minimum: float = 0.25,
    maximum: float = 0.75, lookback: int = 52,
) -> tuple[float, float, str]:
    left = np.asarray(list(expanding_crps), dtype=float)[-lookback:]
    right = np.asarray(list(rolling_crps), dtype=float)[-lookback:]
    valid = np.isfinite(left) & np.isfinite(right) & (left > 0) & (right > 0)
    if int(valid.sum()) < lookback:
        return 0.5, 0.5, "insufficient_52_origin_history"
    inverse_left = 1.0 / float(left[valid].mean())
    inverse_right = 1.0 / float(right[valid].mean())
    raw = inverse_left / (inverse_left + inverse_right)
    weight_left = float(np.clip(raw, minimum, maximum))
    return weight_left, 1.0 - weight_left, "inverse_crps_52_origin"


def _stationary_bootstrap_indices(
    rng: np.random.Generator, *, rows: int, horizon: int, mean_block: int,
) -> np.ndarray:
    indices = np.empty(horizon, dtype=int)
    index = int(rng.integers(0, rows))
    restart_probability = 1.0 / float(mean_block)
    for step in range(horizon):
        if step == 0 or rng.random() < restart_probability:
            index = int(rng.integers(0, rows))
        else:
            index = (index + 1) % rows
        indices[step] = index
    return indices


def _ewma_scale(residuals: np.ndarray, decay: float) -> np.ndarray:
    squared = np.square(residuals)
    variance = np.empty_like(squared)
    variance[0] = np.maximum(squared[0], 1e-16)
    for index in range(1, len(residuals)):
        variance[index] = decay * variance[index - 1] + (1.0 - decay) * squared[index - 1]
    latest = np.sqrt(np.maximum(variance[-1], 1e-16))
    historical = np.sqrt(np.maximum(variance, 1e-16))
    return latest / historical


def select_distribution_parameters(
    residuals: np.ndarray,
    *,
    block_candidates: Iterable[int] = (5, 10, 21),
    ewma_candidates: Iterable[float] = (0.94, 0.97),
    validation_horizon: int = 21,
    seed: int = 0,
) -> tuple[int, float, dict[str, float]]:
    """Choose block/EWMA settings on a trailing internal residual validation set."""
    values = np.asarray(residuals, dtype=float)
    if len(values) < 500:
        return 10, 0.97, {"fallback": math.nan}
    from .backtest import sample_crps

    validation_count = min(52, (len(values) - 252) // validation_horizon)
    origins = list(range(len(values) - validation_count * validation_horizon, len(values), validation_horizon))
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
                samples = np.empty(1000, dtype=float)
                for path in range(len(samples)):
                    indexes = _stationary_bootstrap_indices(
                        rng, rows=len(training), horizon=validation_horizon,
                        mean_block=int(block),
                    )
                    samples[path] = float(np.sum(training[indexes, 0] * scales[indexes, 0]))
                actual = float(np.sum(values[origin:origin + validation_horizon, 0]))
                if len(values[origin:origin + validation_horizon]) == validation_horizon:
                    candidate_scores.append(sample_crps(samples, actual))
            key = f"block_{int(block)}__ewma_{float(decay):.2f}"
            scores[key] = float(np.mean(candidate_scores)) if candidate_scores else math.inf
    selected = min(scores, key=lambda key: (scores[key], key))
    parts = selected.split("__")
    return int(parts[0].removeprefix("block_")), float(parts[1].removeprefix("ewma_")), scores


def simulate_correlated_paths(
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
) -> dict[str, Any]:
    if path_count <= 0 or horizon <= 0:
        raise TimeSeriesModelError("path_count and horizon must be positive")
    if abs(sum(weights) - 1.0) > 1e-12 or min(weights) < 0:
        raise TimeSeriesModelError("ensemble weights must be fractions summing to one")
    rng = np.random.default_rng(seed)
    assignments = rng.choice(2, size=path_count, p=np.asarray(weights, dtype=float))
    log_return_paths = np.empty((path_count, horizon), dtype=float)
    innovation_paths = np.empty((path_count, horizon, endog_history.shape[1]), dtype=float)
    for path_index, model_index in enumerate(assignments):
        fit = fits[int(model_index)]
        history = np.asarray(endog_history, dtype=float).copy()
        residuals = fit.residuals
        if len(residuals) < max(30, block_length):
            raise TimeSeriesModelError("insufficient multivariate residual history")
        bootstrap = _stationary_bootstrap_indices(
            rng, rows=len(residuals), horizon=horizon, mean_block=block_length,
        )
        scales = _ewma_scale(residuals, ewma_lambda)
        for step, residual_index in enumerate(bootstrap):
            predicted = fit.predict(history, exog_last)
            innovation = residuals[residual_index] * scales[residual_index]
            innovation_paths[path_index, step] = innovation
            next_value = predicted + innovation
            log_return_paths[path_index, step] = next_value[0]
            history = np.vstack((history, next_value))
    cumulative = np.cumsum(log_return_paths, axis=1)
    index_paths = float(anchor) * np.exp(cumulative)
    return {
        "log_returns": log_return_paths,
        "innovations": innovation_paths,
        "index_paths": index_paths,
        "assignments": assignments,
        "path_hash": _array_hash(index_paths),
    }


def summarize_paths(
    index_paths: np.ndarray, *, anchor: float, horizons: Iterable[int] = (1, 5, 21, 63),
) -> dict[str, Any]:
    paths = np.asarray(index_paths, dtype=float)
    if paths.ndim != 2 or paths.shape[0] == 0:
        raise TimeSeriesModelError("index paths must be a non-empty matrix")
    quantiles = (0.10, 0.25, 0.50, 0.75, 0.90)
    full = np.quantile(paths, quantiles, axis=0)
    horizon_rows: dict[str, Any] = {}
    for horizon in horizons:
        if horizon > paths.shape[1]:
            continue
        terminal = paths[:, horizon - 1]
        terminal_quantiles = np.quantile(terminal, quantiles)
        returns = terminal / float(anchor) - 1.0
        running_min = np.minimum.accumulate(paths[:, :horizon], axis=1)
        running_max = np.maximum.accumulate(
            np.column_stack((np.full(paths.shape[0], float(anchor)), paths[:, :horizon])), axis=1,
        )[:, 1:]
        drawdown = paths[:, :horizon] / running_max - 1.0
        horizon_rows[str(horizon)] = {
            "point_return": float(np.median(returns)),
            "median_index": float(terminal_quantiles[2]),
            "quantiles": {
                name: float(value) for name, value in zip(
                    ("p10", "p25", "p50", "p75", "p90"), terminal_quantiles, strict=True,
                )
            },
            "probability_up": float(np.mean(terminal > anchor)),
            "maximum_drawdown_p50": float(np.median(np.min(drawdown, axis=1))),
            "first_touch_minus_10": float(np.mean(np.min(running_min, axis=1) <= anchor * 0.90)),
        }
    return {
        "horizons": horizon_rows,
        "path_quantiles": {
            name: values.tolist() for name, values in zip(
                ("p10", "p25", "p50", "p75", "p90"), full, strict=True,
            )
        },
    }


def model_content_hash(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
