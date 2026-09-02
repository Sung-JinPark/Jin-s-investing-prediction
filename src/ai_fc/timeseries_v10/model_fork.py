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
    # B5 — filtered-historical-simulation reconstruction of the long-horizon
    # marginals.  Empty tuple disables it (identity); path-level metrics
    # (first touch) always remain engine-based.
    fhs_horizons: tuple[int, ...] = ()
    fhs_vol_projection: str = "current_ewma"
    fhs_tilt_omega: float = 0.0
    fhs_tilt_cap_sigma: float = 0.25
    # ── V10 연구 격자 (전부 기본값 = V8 챔피언 퇴화 — identity_test가 강제) ──
    # W1: B5 z-풀 상태 근접도 가중 quantile. None = 원본 경로 그대로 (비트 동일).
    w1_kappa: float | None = None
    w1_state: str = "ewma97_variance_ratio"
    # W3: 상태의존 블렌드 w(s)=clip(0.75+γ(s−1), 0.5, 0.9). None = 정적 상수.
    w3_blend_gamma: float | None = None
    # W2: (fhs, historical, block_bootstrap) K성분 혼합. None = 2성분 원본 경로.
    w2_mix_weights: tuple[float, float, float] | None = None
    # W4: 재보정 맵 {empirical, isotonic_pav} × 상태 층수 {1, 2}.
    w4_recal_map: str = "empirical"
    w4_recal_layers: int = 1

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
            "fhs_horizons": [int(h) for h in self.fhs_horizons],
            "fhs_vol_projection": self.fhs_vol_projection,
            "fhs_tilt_omega": float(self.fhs_tilt_omega),
            "fhs_tilt_cap_sigma": float(self.fhs_tilt_cap_sigma),
            "w1_kappa": self.w1_kappa,
            "w1_state": self.w1_state,
            "w3_blend_gamma": self.w3_blend_gamma,
            "w2_mix_weights": None if self.w2_mix_weights is None else [
                float(value) for value in self.w2_mix_weights
            ],
            "w4_recal_map": self.w4_recal_map,
            "w4_recal_layers": int(self.w4_recal_layers),
        }

    def is_v10_degenerate(self) -> bool:
        """True iff every V10 knob is at its V8-champion identity value."""
        return (
            self.w1_kappa is None
            and self.w3_blend_gamma is None
            and self.w2_mix_weights is None
            and self.w4_recal_map == "empirical"
            and int(self.w4_recal_layers) == 1
        )

    def is_v2_identity(self) -> bool:
        return (
            self.phi is None
            and all(value == 0.0 for value in self.omega_by_horizon.values())
            and all(value == 1.0 for value in self.blend_weight_by_horizon.values())
            and self.pit_recalibration_shrinkage is None
            and not self.fhs_horizons
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


def _ewma_variance_series(returns: np.ndarray, decay: float) -> np.ndarray:
    """The V2 EWMA variance recursion over a one-dimensional return series."""
    squared = np.square(np.asarray(returns, dtype=float))
    if squared.ndim != 1 or not len(squared):
        raise TimeSeriesModelError("returns must be a non-empty vector")
    variance = np.empty_like(squared)
    variance[0] = max(float(squared[0]), 1e-16)
    lam = float(decay)
    for index in range(1, len(squared)):
        variance[index] = lam * variance[index - 1] + (1.0 - lam) * squared[index - 1]
    return variance


def fhs_horizon_samples(
    training_returns: np.ndarray,
    *,
    horizon: int,
    ewma_lambda: float,
    burn_in: int = 60,
    vol_projection: str = "current_ewma",
    term_structure_phi: float = 0.97,
    unconditional_window_sessions: int = 2520,
    mu_hat_window_sessions: int | None = None,
    tilt_omega: float = 0.0,
    tilt_cap_sigma: float = 0.25,
    engine_mean: float | None = None,
    state_values: np.ndarray | None = None,
    state_now: float | None = None,
    kappa: float | None = None,
) -> np.ndarray:
    """B5: reconstruct the h-session return distribution from history.

    Overlapping h-session historical window sums are standardized by the EWMA
    volatility prevailing at each window's own start, then recomposed at the
    origin's projected volatility around the PIT unconditional drift, with an
    optional bounded tilt toward the engine's conditional mean.  Everything is
    a deterministic function of the training window — no random draws, no
    iterated extrapolation, and the worst case collapses to a recentered
    historical simulation.
    """
    returns = np.asarray(training_returns, dtype=float)
    if returns.ndim != 1 or len(returns) < max(800, horizon + burn_in + 30):
        raise TimeSeriesModelError("insufficient training history for FHS reconstruction")
    if horizon <= 0 or burn_in < 0:
        raise TimeSeriesModelError("horizon and burn-in must be positive")
    omega = float(tilt_omega)
    if not 0.0 <= omega <= 1.0:
        raise TimeSeriesModelError(f"tilt omega must be a fraction; observed {omega}")
    variance = _ewma_variance_series(returns, ewma_lambda)
    window_sums = np.convolve(returns, np.ones(horizon), mode="valid")
    start_vol = np.sqrt(np.maximum(variance[: len(window_sums)], 1e-16))
    keep = np.arange(len(window_sums)) >= int(burn_in)
    if mu_hat_window_sessions is not None:
        mu_source = returns[-int(mu_hat_window_sessions):]
    else:
        mu_source = returns
    mu_hat = float(np.mean(mu_source))
    z_scores = (window_sums[keep] - mu_hat * horizon) / (start_vol[keep] * np.sqrt(horizon))
    v_now = float(variance[-1])
    if vol_projection == "current_ewma":
        projected_variance = v_now
    elif vol_projection == "term_structure_phi_0.97":
        window = min(int(unconditional_window_sessions), len(returns))
        v_bar = max(float(np.mean(np.square(returns[-window:]))), 1e-16)
        phi = float(term_structure_phi)
        steps = np.arange(1, horizon + 1, dtype=float)
        projected_variance = float(np.mean(v_bar + np.power(phi, steps) * (v_now - v_bar)))
    else:
        raise TimeSeriesModelError(f"unknown FHS vol projection: {vol_projection}")
    sigma_projected = math.sqrt(max(projected_variance, 1e-16))
    dispersion = z_scores * sigma_projected * math.sqrt(horizon)
    center = mu_hat * horizon
    if omega > 0.0:
        if engine_mean is None:
            raise TimeSeriesModelError("engine mean is required for a non-zero FHS tilt")
        spread = float(np.std(dispersion, ddof=1))
        bound = float(tilt_cap_sigma) * max(spread, 1e-12)
        center += float(np.clip(omega * (float(engine_mean) - center), -bound, bound))
    values = center + dispersion
    # W1 (V10): 상태 근접도 가중 재표집 — RNG 무접촉·결정론. κ가 없거나 0이면
    # 원본 배열을 그대로 반환한다 (명시 분기 = 비트 동일 항등, identity_test가 강제).
    if kappa is not None and float(kappa) > 0.0:
        if state_values is None or state_now is None:
            raise TimeSeriesModelError("W1 requires state values aligned to the z pool")
        states = np.asarray(state_values, dtype=float)
        if len(states) < len(window_sums):
            raise TimeSeriesModelError("W1 state series shorter than the window pool")
        pool_states = states[: len(window_sums)][keep]
        weights = np.exp(-float(kappa) * np.abs(float(state_now) - pool_states))
        return weighted_midpoint_quantiles(values, weights, count=len(values))
    return values


def weighted_midpoint_quantiles(
    values: np.ndarray, weights: np.ndarray, *, count: int,
) -> np.ndarray:
    """Deterministic weighted empirical quantiles at midpoint levels.

    Step-CDF inversion of the weighted point-mass distribution — no random
    draws, output length fixed to ``count`` so every downstream consumer sees
    the same array shape as the unweighted pool.
    """
    order = np.argsort(values, kind="stable")
    sorted_values = np.asarray(values, dtype=float)[order]
    sorted_weights = np.asarray(weights, dtype=float)[order]
    total = float(sorted_weights.sum())
    if not np.isfinite(total) or total <= 0.0:
        raise TimeSeriesModelError("W1 weights must sum to a positive finite mass")
    cumulative = np.cumsum(sorted_weights) / total
    levels = (np.arange(count) + 0.5) / count
    positions = np.searchsorted(cumulative, levels, side="left")
    positions = np.clip(positions, 0, len(sorted_values) - 1)
    return sorted_values[positions]


def mixture_quantile_function_k(
    sample_sets: list[np.ndarray], weights: list[float], *, levels: np.ndarray,
) -> np.ndarray:
    """K-component generalisation of the weighted point-mass mixture inverse.

    Each component contributes point masses w_k/len(x_k); the two-component
    original stays untouched so the degenerate configuration keeps its exact
    code path.
    """
    total = float(np.sum(weights))
    if not math.isclose(total, 1.0, abs_tol=1e-9):
        raise TimeSeriesModelError("K-mixture weights must sum to one")
    values: list[np.ndarray] = []
    masses: list[np.ndarray] = []
    for samples, weight in zip(sample_sets, weights):
        array = np.asarray(samples, dtype=float)
        if len(array) == 0 or weight < 0.0:
            raise TimeSeriesModelError("K-mixture components must be non-empty, weights non-negative")
        values.append(array)
        masses.append(np.full(len(array), float(weight) / len(array)))
    merged = np.concatenate(values)
    mass = np.concatenate(masses)
    order = np.argsort(merged, kind="stable")
    cumulative = np.cumsum(mass[order])
    positions = np.clip(
        np.searchsorted(cumulative, np.asarray(levels, dtype=float), side="left"),
        0, len(merged) - 1,
    )
    return merged[order][positions]


def mixture_cdf_at_k(
    sample_sets: list[np.ndarray], weights: list[float], *, value: float,
) -> float:
    """K-component mixture CDF at a point (PIT for the W2 branch)."""
    total = 0.0
    for samples, weight in zip(sample_sets, weights):
        array = np.asarray(samples, dtype=float)
        total += float(weight) * float(np.mean(array <= value))
    return float(np.clip(total, 0.0, 1.0))


def recalibration_levels_pav(
    pit_history: np.ndarray, *, target_levels: np.ndarray, shrinkage: float,
    grid_bins: int = 25,
) -> np.ndarray:
    """W4: coarsened isotonic PIT map — a smoothed alternative to the raw
    empirical quantile inversion.

    The empirical map is evaluated on a fixed coarse grid, monotonicity is
    enforced with pool-adjacent-violators (defensive — quantiles are already
    monotone), and targets interpolate linearly between grid knots before the
    same identity shrinkage as B4.  Strengthening below shrinkage 0.5 is
    prohibited by contract (E9 lesson).
    """
    history = np.asarray(pit_history, dtype=float)
    if len(history) == 0:
        raise TimeSeriesModelError("PIT history required for recalibration")
    if not 0.0 <= float(shrinkage) <= 1.0:
        raise TimeSeriesModelError("shrinkage must be a fraction")
    grid = (np.arange(int(grid_bins)) + 0.5) / int(grid_bins)
    knots = np.quantile(history, grid)
    # Pool-adjacent-violators: cumulative-max pass keeps the map monotone.
    knots = np.maximum.accumulate(knots)
    targets = np.asarray(target_levels, dtype=float)
    inverted = np.interp(targets, grid, knots)
    remapped = (1.0 - float(shrinkage)) * inverted + float(shrinkage) * targets
    return np.clip(remapped, 0.0, 1.0)


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
