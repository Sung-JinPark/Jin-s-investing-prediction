"""V8 calibrated distribution layer on top of the frozen V2 VARX engine.

Every kernel here is a preregistered, bounded transform of the V2 simulated
distribution.  With neutral parameters (``phi=None``, ``omega=0``, ``w=1``)
each kernel is an exact identity, so V8 reproduces the V2 paths bit for bit —
the E0 identity that the hermetic test suite enforces.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ai_fc.timeseries.model import RidgeVARXFit, TimeSeriesModelError
from ai_fc.timeseries_v2.model import (
    _ewma_scale,
    _stationary_bootstrap_batch,
)


HORIZONS = (1, 5, 21, 63)


@dataclass(frozen=True)
class DistributionConfigV8:
    """One preregistered point of the B1/B2/B3 research grids.

    The default instance is the exact V2 identity.
    """

    # B1 — volatility term structure: s_h^2 = vbar + phi^h (v_now - vbar).
    # None keeps the V2 constant-scale projection.
    phi: float | str | None = None
    unconditional_window_sessions: int = 2520
    # B2 — bounded location anchor toward the PIT unconditional drift.
    # All-zero omega keeps the V2 location.
    omega_by_horizon: dict[int, float] = field(
        default_factory=lambda: {1: 0.0, 5: 0.0, 21: 0.0, 63: 0.0},
    )
    sigma_cap: float = 0.25
    mu_hat_window_sessions: int | None = None  # None = expanding
    # B3 — convex blend with the historical-simulation baseline.  w=1 keeps
    # the pure model distribution.
    blend_weight_by_horizon: dict[int, float] = field(
        default_factory=lambda: {1: 1.0, 5: 1.0, 21: 1.0, 63: 1.0},
    )
    # B4 — walk-forward monotone PIT recalibration fitted on matured past
    # forecasts only.  None disables it (identity); the value is the
    # preregistered shrinkage toward identity.
    pit_recalibration_shrinkage: float | None = None

    def as_manifest(self) -> dict[str, Any]:
        return {
            "phi": self.phi,
            "unconditional_window_sessions": int(self.unconditional_window_sessions),
            "omega_by_horizon": {str(key): float(value) for key, value in sorted(self.omega_by_horizon.items())},
            "sigma_cap": float(self.sigma_cap),
            "mu_hat_window_sessions": self.mu_hat_window_sessions,
            "blend_weight_by_horizon": {
                str(key): float(value) for key, value in sorted(self.blend_weight_by_horizon.items())
            },
            "pit_recalibration_shrinkage": self.pit_recalibration_shrinkage,
        }

    def is_v2_identity(self) -> bool:
        return (
            self.phi is None
            and all(value == 0.0 for value in self.omega_by_horizon.values())
            and all(value == 1.0 for value in self.blend_weight_by_horizon.values())
            and self.pit_recalibration_shrinkage is None
        )


def _fitted_ar1_phi(log_variance: np.ndarray) -> float:
    """Deterministic AR(1) coefficient of the log EWMA-variance series."""
    series = np.asarray(log_variance, dtype=float)
    if len(series) < 64:
        return 0.97
    centered = series - float(np.mean(series))
    denominator = float(np.dot(centered[:-1], centered[:-1]))
    if denominator <= 1e-16:
        return 0.97
    phi = float(np.dot(centered[:-1], centered[1:]) / denominator)
    return min(max(phi, 0.0), 0.999)


def volatility_term_structure(
    residuals: np.ndarray,
    *,
    decay: float,
    phi: float | str | None,
    horizon: int,
    unconditional_window_sessions: int = 2520,
) -> np.ndarray:
    """Per-step multiplier m_t so projected vol mean-reverts to its long run.

    V2 rescales every bootstrap innovation to today's EWMA vol for all 63
    steps.  V8 multiplies step t by ``sqrt(v_t / v_now)`` where
    ``v_t = vbar + phi^(t+1) (v_now - vbar)``.  ``phi=None`` returns ones —
    the exact V2 identity.
    """
    values = np.asarray(residuals, dtype=float)
    if values.ndim != 2 or not len(values):
        raise TimeSeriesModelError("residual matrix must be two-dimensional and non-empty")
    if horizon <= 0:
        raise TimeSeriesModelError("horizon must be positive")
    if phi is None:
        return np.ones((horizon, values.shape[1]), dtype=float)
    squared = np.square(values)
    # Reproduce the V2 EWMA recursion endpoint for v_now (same update rule
    # as _ewma_scale's lfilter form, written explicitly).
    variance = np.empty_like(squared)
    variance[0] = np.maximum(squared[0], 1e-16)
    lam = float(decay)
    for index in range(1, len(squared)):
        variance[index] = lam * variance[index - 1] + (1.0 - lam) * squared[index - 1]
    v_now = np.maximum(variance[-1], 1e-16)
    window = min(int(unconditional_window_sessions), len(squared))
    v_bar = np.maximum(np.mean(squared[-window:], axis=0), 1e-16)
    if phi == "fitted_ar1":
        phi_value = _fitted_ar1_phi(np.log(np.maximum(variance[:, 0], 1e-16)))
    else:
        phi_value = float(phi)
    if not 0.0 <= phi_value < 1.0:
        raise TimeSeriesModelError(f"phi must be in [0,1); observed {phi_value}")
    steps = np.arange(1, horizon + 1, dtype=float)[:, None]
    v_t = v_bar[None, :] + np.power(phi_value, steps) * (v_now - v_bar)[None, :]
    return np.sqrt(np.maximum(v_t, 1e-16) / v_now[None, :])


def simulate_calibrated_paths_v8(
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
    step_scale: np.ndarray | None = None,
) -> dict[str, object]:
    """The V2 correlated path simulator with an optional per-step vol path.

    With ``step_scale=None`` this consumes the generator in exactly the V2
    order and reproduces ``simulate_correlated_paths_v2`` bit for bit.
    """
    if path_count <= 0 or horizon <= 0:
        raise TimeSeriesModelError("path_count and horizon must be positive")
    if abs(sum(weights) - 1.0) > 1e-12 or min(weights) < 0:
        raise TimeSeriesModelError("ensemble weights must be fractions summing to one")
    if step_scale is not None:
        step_scale = np.asarray(step_scale, dtype=float)
        if step_scale.shape[0] != horizon:
            raise TimeSeriesModelError("step_scale must cover every simulation step")
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
        if step_scale is not None:
            innovations = innovations * step_scale[None, :, :]
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


def bounded_location_shift(
    cumulative_log_paths: np.ndarray,
    *,
    training_returns: np.ndarray,
    omega_by_horizon: dict[int, float],
    sigma_cap: float,
    mu_hat_window_sessions: int | None = None,
) -> np.ndarray:
    """Per-step additive shift pulling the path mean toward the PIT drift.

    The target shift at each evaluation horizon h is
    ``clip(omega_h * (mu_hat*h - mean_cum_h), +-sigma_cap*sigma_h)`` and the
    per-step schedule interpolates linearly between grid horizons, so paths
    stay coherent across horizons.  All-zero omega returns zeros (identity).
    A hard endpoint is impossible by construction: the shift is bounded by
    ``sigma_cap`` standard deviations of the simulated distribution.
    """
    paths = np.asarray(cumulative_log_paths, dtype=float)
    if paths.ndim != 2:
        raise TimeSeriesModelError("cumulative log paths must be (paths, horizon)")
    horizon = paths.shape[1]
    if all(float(omega_by_horizon.get(h, 0.0)) == 0.0 for h in HORIZONS):
        return np.zeros(horizon, dtype=float)
    if not 0.0 < float(sigma_cap) <= 1.0:
        raise TimeSeriesModelError("sigma_cap must be in (0, 1]")
    returns = np.asarray(training_returns, dtype=float)
    if mu_hat_window_sessions is not None:
        returns = returns[-int(mu_hat_window_sessions):]
    if len(returns) < 252:
        raise TimeSeriesModelError("insufficient training history for the drift anchor")
    mu_hat = float(np.mean(returns))
    grid = [h for h in HORIZONS if h <= horizon]
    targets: dict[int, float] = {0: 0.0}
    for h in grid:
        omega = float(omega_by_horizon.get(h, 0.0))
        if not 0.0 <= omega <= 1.0:
            raise TimeSeriesModelError(f"omega must be a fraction; observed {omega}")
        mean_cum = float(np.mean(paths[:, h - 1]))
        sigma = float(np.std(paths[:, h - 1], ddof=1))
        raw = omega * (mu_hat * h - mean_cum)
        bound = float(sigma_cap) * max(sigma, 1e-12)
        targets[h] = float(np.clip(raw, -bound, bound))
    shift = np.zeros(horizon, dtype=float)
    previous_h, previous_target = 0, 0.0
    for h in grid:
        span = h - previous_h
        step_increment = (targets[h] - previous_target) / span
        for step in range(previous_h, h):
            shift[step] = step_increment
        previous_h, previous_target = h, targets[h]
    if previous_h < horizon:
        shift[previous_h:] = 0.0
    return shift


def cramer_distance(x_samples: np.ndarray, y_samples: np.ndarray) -> float:
    """Cramér distance ``integral (F-G)^2 dx`` between two empirical samples.

    This is the exact interaction term of the convex-blend CRPS identity:
    ``CRPS(wF+(1-w)G, y) = w CRPS(F,y) + (1-w) CRPS(G,y) - w(1-w) d(F,G)``.
    """
    x = np.sort(np.asarray(x_samples, dtype=float))
    y = np.sort(np.asarray(y_samples, dtype=float))
    if not len(x) or not len(y):
        raise TimeSeriesModelError("empty sample set")
    merged = np.concatenate((x, y))
    order = np.argsort(merged, kind="mergesort")
    values = merged[order]
    is_x = order < len(x)
    fx_steps = np.cumsum(is_x) / len(x)
    gy_steps = np.cumsum(~is_x) / len(y)
    widths = np.diff(values)
    difference = (fx_steps - gy_steps)[:-1]
    return float(np.sum(np.square(difference) * widths))


def mixture_crps(
    model_crps: float,
    baseline_crps: float,
    *,
    weight: float,
    distance: float,
) -> float:
    """Exact CRPS of the convex mixture without resampling."""
    w = float(weight)
    if not 0.0 <= w <= 1.0:
        raise TimeSeriesModelError(f"blend weight must be a fraction; observed {w}")
    return w * float(model_crps) + (1.0 - w) * float(baseline_crps) - w * (1.0 - w) * float(distance)


def mixture_quantiles(
    model_samples: np.ndarray,
    baseline_samples: np.ndarray,
    *,
    weight: float,
    quantiles: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90),
) -> np.ndarray:
    """Quantiles of the weighted mixture of two empirical distributions."""
    w = float(weight)
    if not 0.0 <= w <= 1.0:
        raise TimeSeriesModelError(f"blend weight must be a fraction; observed {w}")
    if w == 1.0:
        return np.quantile(np.asarray(model_samples, dtype=float), quantiles)
    if w == 0.0:
        return np.quantile(np.asarray(baseline_samples, dtype=float), quantiles)
    return mixture_quantile_function(
        model_samples, baseline_samples, weight=w,
        levels=np.asarray(quantiles, dtype=float),
    )


def mixture_quantile_function(
    model_samples: np.ndarray,
    baseline_samples: np.ndarray,
    *,
    weight: float,
    levels: np.ndarray,
) -> np.ndarray:
    """Evaluate the weighted-mixture quantile function at arbitrary levels."""
    w = float(weight)
    if not 0.0 <= w <= 1.0:
        raise TimeSeriesModelError(f"blend weight must be a fraction; observed {w}")
    targets = np.asarray(levels, dtype=float)
    if np.any(targets < 0.0) or np.any(targets > 1.0):
        raise TimeSeriesModelError("quantile levels must be fractions")
    x = np.asarray(model_samples, dtype=float)
    if w == 1.0:
        return np.quantile(x, targets)
    y = np.asarray(baseline_samples, dtype=float)
    if w == 0.0:
        return np.quantile(y, targets)
    merged = np.concatenate((x, y))
    order = np.argsort(merged, kind="mergesort")
    values = merged[order]
    point_mass = np.where(order < len(x), w / len(x), (1.0 - w) / len(y))
    cdf = np.cumsum(point_mass)
    positions = np.minimum(np.searchsorted(cdf, targets, side="left"), len(values) - 1)
    return values[positions]


def mixture_cdf_at(
    model_samples: np.ndarray,
    baseline_samples: np.ndarray,
    *,
    weight: float,
    value: float,
) -> float:
    """CDF of the weighted mixture evaluated at one point (the PIT value)."""
    w = float(weight)
    if not 0.0 <= w <= 1.0:
        raise TimeSeriesModelError(f"blend weight must be a fraction; observed {w}")
    model_part = float(np.mean(np.asarray(model_samples, dtype=float) <= value))
    if w == 1.0:
        return model_part
    baseline_part = float(np.mean(np.asarray(baseline_samples, dtype=float) <= value))
    return w * model_part + (1.0 - w) * baseline_part


def recalibration_levels(
    pit_history: np.ndarray,
    *,
    target_levels: np.ndarray,
    shrinkage: float,
) -> np.ndarray:
    """Map target quantile levels through the inverse empirical PIT calibration.

    With calibration map ``g = ecdf(past PITs)``, the recalibrated quantile at
    level q is the predictive quantile at ``g^{-1}(q)``.  ``shrinkage`` pulls
    that level back toward identity: ``u* = (1-s) g^{-1}(q) + s q``.  A
    perfectly calibrated history (uniform PITs) leaves levels unchanged in
    expectation, so the transform is anchored at identity.
    """
    s = float(shrinkage)
    if not 0.0 <= s <= 1.0:
        raise TimeSeriesModelError(f"shrinkage must be a fraction; observed {s}")
    history = np.asarray(pit_history, dtype=float)
    if history.ndim != 1 or not len(history):
        raise TimeSeriesModelError("PIT history must be a non-empty vector")
    if np.any(history < 0.0) or np.any(history > 1.0):
        raise TimeSeriesModelError("PIT values must be fractions")
    targets = np.asarray(target_levels, dtype=float)
    inverted = np.quantile(history, targets)
    return np.clip((1.0 - s) * inverted + s * targets, 0.0, 1.0)


def experiment_id(config: DistributionConfigV8, *, bundle_hash: str, code_hash: str) -> str:
    seed = {
        "config": config.as_manifest(),
        "bundle_hash": bundle_hash,
        "code_hash": code_hash,
    }
    body = hashlib.sha256(
        repr(sorted(_flatten(seed))).encode("utf-8")
    ).hexdigest()
    return f"tsv8-exp-{body[:20]}"


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        rows: list[tuple[str, str]] = []
        for key in sorted(value):
            rows.extend(_flatten(value[key], f"{prefix}/{key}"))
        return rows
    return [(prefix, repr(value))]


def is_finite_or_raise(name: str, value: float) -> float:
    if not math.isfinite(float(value)):
        raise TimeSeriesModelError(f"{name} is not finite")
    return float(value)
