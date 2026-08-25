"""Preregistered V6 direct-horizon distribution candidates E0-E7.

The estimators in this module are deliberately small, deterministic reference
implementations.  Their parameter coordinates come from the frozen V6
contract; callers are not allowed to add an ad-hoc coordinate after seeing an
outer result.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import optimize, stats


QUANTILES = np.asarray([0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])


class DistributionModelError(RuntimeError):
    pass


def empirical_crps(samples: np.ndarray, actual: float) -> float:
    values = np.sort(np.asarray(samples, dtype=float))
    if values.ndim != 1 or len(values) == 0 or not np.all(np.isfinite(values)) or not math.isfinite(actual):
        raise DistributionModelError("CRPS inputs must be finite and nonempty")
    n = len(values)
    coefficients = 2 * np.arange(1, n + 1) - n - 1
    return float(np.mean(np.abs(values - actual)) - np.sum(coefficients * values) / (n * n))


@dataclass(frozen=True)
class RobustScaler:
    median: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, values: np.ndarray) -> "RobustScaler":
        median = np.nanmedian(values, axis=0)
        q25 = np.nanquantile(values, 0.25, axis=0)
        q75 = np.nanquantile(values, 0.75, axis=0)
        scale = np.where((q75 - q25) > 1e-10, q75 - q25, 1.0)
        median = np.where(np.isfinite(median), median, 0.0)
        return cls(median, scale)

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (np.where(np.isfinite(values), values, self.median) - self.median) / self.scale


@dataclass(frozen=True)
class DistributionForecast:
    candidate_id: str
    quantiles: np.ndarray
    samples: np.ndarray
    up_probability: float
    runtime_parameters: dict[str, Any]

    def validate(self) -> None:
        if self.quantiles.shape != QUANTILES.shape or np.any(np.diff(self.quantiles) < 0):
            raise DistributionModelError("forecast quantiles are not monotone")
        if not 0 <= self.up_probability <= 1 or not np.all(np.isfinite(self.samples)):
            raise DistributionModelError("forecast probability/samples invalid")


def samples_from_quantiles(quantiles: np.ndarray, sample_count: int = 4000) -> np.ndarray:
    values = np.maximum.accumulate(np.asarray(quantiles, dtype=float))
    u = (np.arange(sample_count, dtype=float) + 0.5) / sample_count
    return np.interp(u, QUANTILES, values, left=values[0], right=values[-1])


@dataclass
class E0ExactAnchor:
    samples: np.ndarray
    training_hash: str

    @classmethod
    def fit(cls, labels: np.ndarray) -> "E0ExactAnchor":
        values = np.sort(np.asarray(labels, dtype=float)[np.isfinite(labels)])
        if len(values) < 100:
            raise DistributionModelError("E0 requires at least 100 matured labels")
        return cls(values, hashlib.sha256(values.tobytes()).hexdigest())

    def predict(self) -> DistributionForecast:
        forecast = DistributionForecast(
            "E0", np.quantile(self.samples, QUANTILES), self.samples.copy(),
            float(np.mean(self.samples > 0)), {"representation": "exact_samples", "training_hash": self.training_hash},
        )
        forecast.validate()
        return forecast


@dataclass
class E1QuantileElasticNet:
    scaler: RobustScaler
    coefficients: np.ndarray
    alpha: float
    l1_ratio: float

    @staticmethod
    def _fit_level(x: np.ndarray, y: np.ndarray, level: float, alpha: float, l1_ratio: float, max_iter: int, tolerance: float) -> np.ndarray:
        design = np.c_[np.ones(len(x)), x]
        initial = np.linalg.lstsq(design, y, rcond=None)[0]
        eps = 1e-8
        def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
            residual = y - design @ beta
            loss = np.where(residual >= 0, level * residual, (level - 1) * residual).mean()
            penalty = alpha * (l1_ratio * np.sqrt(beta[1:] ** 2 + eps).sum() + 0.5 * (1 - l1_ratio) * np.sum(beta[1:] ** 2))
            gradient = -(design.T @ np.where(residual >= 0, level, level - 1)) / len(y)
            gradient[1:] += alpha * (l1_ratio * beta[1:] / np.sqrt(beta[1:] ** 2 + eps) + (1 - l1_ratio) * beta[1:])
            return float(loss + penalty), gradient
        result = optimize.minimize(objective, initial, jac=True, method="L-BFGS-B", options={"maxiter": max_iter, "ftol": tolerance})
        if not result.success:
            raise DistributionModelError(f"E1 optimization failed: {result.message}")
        return result.x

    @classmethod
    def fit(cls, x: np.ndarray, y: np.ndarray, *, alpha: float, l1_ratio: float, max_iter: int = 10000, tolerance: float = 1e-7) -> "E1QuantileElasticNet":
        mask = np.isfinite(y) & (np.isfinite(x).sum(axis=1) >= max(1, x.shape[1] // 2))
        if mask.sum() < 150:
            raise DistributionModelError("E1 has insufficient training rows")
        scaler = RobustScaler.fit(x[mask])
        z = scaler.transform(x[mask])
        coefficients = np.asarray([cls._fit_level(z, y[mask], q, alpha, l1_ratio, max_iter, tolerance) for q in QUANTILES])
        return cls(scaler, coefficients, alpha, l1_ratio)

    def predict(self, row: np.ndarray) -> DistributionForecast:
        design = np.r_[1.0, self.scaler.transform(np.asarray(row)[None, :])[0]]
        quantiles = np.maximum.accumulate(self.coefficients @ design)
        samples = samples_from_quantiles(quantiles)
        result = DistributionForecast("E1", quantiles, samples, float(np.mean(samples > 0)), {"alpha": self.alpha, "l1_ratio": self.l1_ratio})
        result.validate(); return result


@dataclass
class E2StudentT:
    scaler: RobustScaler
    location_coef: np.ndarray
    scale_coef: np.ndarray
    degrees_of_freedom: int
    ridge_alpha: float
    scale_floor: float

    @classmethod
    def fit(cls, x: np.ndarray, y: np.ndarray, *, degrees_of_freedom: int, ridge_alpha: float, scale_floor: float = 1e-6) -> "E2StudentT":
        from sklearn.linear_model import Ridge
        mask = np.isfinite(y) & (np.isfinite(x).sum(axis=1) >= max(1, x.shape[1] // 2))
        if mask.sum() < 150: raise DistributionModelError("E2 has insufficient training rows")
        scaler = RobustScaler.fit(x[mask]); z = scaler.transform(x[mask]); target = y[mask]
        location = Ridge(alpha=ridge_alpha).fit(z, target)
        residual = target - location.predict(z)
        log_scale = np.log(np.maximum(np.abs(residual), scale_floor))
        scale = Ridge(alpha=ridge_alpha).fit(z, log_scale)
        return cls(scaler, np.r_[location.intercept_, location.coef_], np.r_[scale.intercept_, scale.coef_], degrees_of_freedom, ridge_alpha, scale_floor)

    def predict(self, row: np.ndarray) -> DistributionForecast:
        design = np.r_[1.0, self.scaler.transform(np.asarray(row)[None, :])[0]]
        location = float(design @ self.location_coef)
        predicted_mad = max(self.scale_floor, float(np.exp(np.clip(design @ self.scale_coef, -20, 5))))
        scale = predicted_mad / float(stats.t.ppf(0.75, self.degrees_of_freedom))
        quantiles = location + scale * stats.t.ppf(QUANTILES, self.degrees_of_freedom)
        u = (np.arange(4000) + 0.5) / 4000
        samples = location + scale * stats.t.ppf(u, self.degrees_of_freedom)
        result = DistributionForecast("E2", quantiles, samples, float(np.mean(samples > 0)), {"degrees_of_freedom": self.degrees_of_freedom, "ridge_alpha": self.ridge_alpha, "scale_floor": self.scale_floor})
        result.validate(); return result


@dataclass
class E3QuantileHGB:
    scaler: RobustScaler
    estimators: tuple[Any, ...]
    parameters: dict[str, Any]

    @classmethod
    def fit(cls, x: np.ndarray, y: np.ndarray, **parameters: Any) -> "E3QuantileHGB":
        from sklearn.ensemble import HistGradientBoostingRegressor
        mask = np.isfinite(y) & (np.isfinite(x).sum(axis=1) >= max(1, x.shape[1] // 2))
        if mask.sum() < 150: raise DistributionModelError("E3 has insufficient training rows")
        scaler = RobustScaler.fit(x[mask]); z = scaler.transform(x[mask]); target = y[mask]
        estimators = tuple(HistGradientBoostingRegressor(
            loss="quantile", quantile=float(level), learning_rate=float(parameters["learning_rate"]),
            max_leaf_nodes=int(parameters["max_leaf_nodes"]), max_iter=int(parameters["max_iter"]),
            l2_regularization=float(parameters["l2_regularization"]), min_samples_leaf=int(parameters["min_samples_leaf"]),
            random_state=0,
        ).fit(z, target) for level in QUANTILES)
        return cls(scaler, estimators, dict(parameters))

    def predict(self, row: np.ndarray) -> DistributionForecast:
        z = self.scaler.transform(np.asarray(row)[None, :])
        quantiles = np.maximum.accumulate(np.asarray([model.predict(z)[0] for model in self.estimators]))
        samples = samples_from_quantiles(quantiles)
        result = DistributionForecast("E3", quantiles, samples, float(np.mean(samples > 0)), self.parameters)
        result.validate(); return result


@dataclass
class E4BayesianDynamicLinear:
    """Filtered-only discounted dynamic linear model.

    State updates are performed in training order and the returned state is the
    final filtered state.  There is no backward smoother, which would make the
    historical coefficient state depend on later observations.
    """

    scaler: RobustScaler
    state_mean: np.ndarray
    state_covariance: np.ndarray
    observation_variance: float
    state_discount: float
    prior_variance: float

    @classmethod
    def fit(
        cls,
        x: np.ndarray,
        y: np.ndarray,
        *,
        state_discount: float,
        prior_variance: float,
    ) -> "E4BayesianDynamicLinear":
        mask = np.isfinite(y) & (np.isfinite(x).sum(axis=1) >= max(1, x.shape[1] // 2))
        if mask.sum() < 150:
            raise DistributionModelError("E4 has insufficient training rows")
        scaler = RobustScaler.fit(x[mask])
        z = scaler.transform(x[mask])
        target = np.asarray(y[mask], dtype=float)
        design = np.c_[np.ones(len(z)), z]
        state = np.zeros(design.shape[1], dtype=float)
        covariance = np.eye(design.shape[1], dtype=float) * float(prior_variance)
        observation_variance = max(float(np.var(target[: min(100, len(target))])), 1e-8)
        for row, value in zip(design, target, strict=True):
            prior_covariance = covariance / float(state_discount)
            forecast_variance = float(row @ prior_covariance @ row + observation_variance)
            gain = prior_covariance @ row / forecast_variance
            residual = float(value - row @ state)
            state = state + gain * residual
            covariance = prior_covariance - np.outer(gain, row) @ prior_covariance
            covariance = (covariance + covariance.T) / 2
            observation_variance = max(1e-8, 0.98 * observation_variance + 0.02 * residual * residual)
        return cls(scaler, state, covariance, observation_variance, state_discount, prior_variance)

    def predict(self, row: np.ndarray) -> DistributionForecast:
        design = np.r_[1.0, self.scaler.transform(np.asarray(row)[None, :])[0]]
        location = float(design @ self.state_mean)
        scale = math.sqrt(max(1e-10, float(design @ self.state_covariance @ design + self.observation_variance)))
        quantiles = location + scale * stats.norm.ppf(QUANTILES)
        u = (np.arange(4000, dtype=float) + 0.5) / 4000
        samples = location + scale * stats.norm.ppf(u)
        result = DistributionForecast(
            "E4",
            quantiles,
            samples,
            float(np.mean(samples > 0)),
            {
                "observation_family": "gaussian",
                "state_discount": self.state_discount,
                "prior_variance": self.prior_variance,
                "filtered_state_only": True,
            },
        )
        result.validate()
        return result


@dataclass
class E5SoftRegimePartialPooling:
    scaler: RobustScaler
    gate: Any
    global_coefficients: np.ndarray
    regime_coefficients: np.ndarray
    regime_scales: np.ndarray
    global_shrinkage: float
    minimum_effective_sample_size: int
    cluster_rebalanced: bool

    @staticmethod
    def _rebalance_labels(
        z: np.ndarray,
        labels: np.ndarray,
        centers: np.ndarray,
        minimum_size: int,
    ) -> tuple[np.ndarray, bool]:
        """Deterministically enforce the preregistered regime ESS floor.

        Vanilla k-means can create a tiny stress cluster even when the overall
        training sample easily satisfies the frozen minimum.  Rejecting every
        coordinate in that case is an implementation failure, not a research
        result.  We retain the fitted centroids and move only the observations
        nearest to a deficient centroid from donor clusters that remain above
        the same floor.  The threshold and regime count are unchanged.
        """

        balanced = np.asarray(labels, dtype=int).copy()
        counts = np.bincount(balanced, minlength=len(centers)).astype(int)
        changed = False
        for target in np.argsort(counts):
            needed = max(0, int(minimum_size - counts[target]))
            if needed == 0:
                continue
            donors = np.where(counts[balanced] > minimum_size)[0]
            if len(donors) < needed:
                raise DistributionModelError("E5 minimum effective sample size cannot be rebalanced")
            distances = np.sum((z[donors] - centers[target]) ** 2, axis=1)
            order = np.lexsort((donors, distances))
            chosen = donors[order[:needed]]
            for index in chosen:
                source = balanced[index]
                balanced[index] = int(target)
                counts[source] -= 1
                counts[target] += 1
            changed = True
        if np.min(counts) < minimum_size:
            raise DistributionModelError("E5 minimum effective sample size not met after rebalance")
        return balanced, changed

    @classmethod
    def fit(
        cls,
        x: np.ndarray,
        y: np.ndarray,
        *,
        global_shrinkage: float,
        regime_count: int = 3,
        minimum_effective_sample_size: int = 50,
    ) -> "E5SoftRegimePartialPooling":
        from sklearn.cluster import KMeans
        from sklearn.linear_model import LogisticRegression, Ridge

        mask = np.isfinite(y) & (np.isfinite(x).sum(axis=1) >= max(1, x.shape[1] // 2))
        if mask.sum() < regime_count * minimum_effective_sample_size:
            raise DistributionModelError("E5 has insufficient training rows")
        scaler = RobustScaler.fit(x[mask])
        z = scaler.transform(x[mask])
        target = np.asarray(y[mask], dtype=float)
        cluster = KMeans(n_clusters=regime_count, random_state=0, n_init=20).fit(z)
        labels, cluster_rebalanced = cls._rebalance_labels(
            z,
            cluster.labels_,
            cluster.cluster_centers_,
            minimum_effective_sample_size,
        )
        counts = np.bincount(labels, minlength=regime_count)
        if np.min(counts) < minimum_effective_sample_size:
            raise DistributionModelError("E5 minimum effective sample size not met")
        gate = LogisticRegression(max_iter=2000, random_state=0).fit(z, labels)
        global_model = Ridge(alpha=1.0).fit(z, target)
        global_coefficients = np.r_[global_model.intercept_, global_model.coef_]
        design = np.c_[np.ones(len(z)), z]
        regime_coefficients = []
        regime_scales = []
        for regime in range(regime_count):
            regime_mask = labels == regime
            local_model = Ridge(alpha=1.0).fit(z[regime_mask], target[regime_mask])
            local = np.r_[local_model.intercept_, local_model.coef_]
            pooled = float(global_shrinkage) * global_coefficients + (1 - float(global_shrinkage)) * local
            residual = target[regime_mask] - design[regime_mask] @ pooled
            regime_coefficients.append(pooled)
            regime_scales.append(max(float(np.std(residual, ddof=1)), 1e-6))
        return cls(
            scaler,
            gate,
            global_coefficients,
            np.asarray(regime_coefficients),
            np.asarray(regime_scales),
            float(global_shrinkage),
            int(minimum_effective_sample_size),
            cluster_rebalanced,
        )

    def predict(self, row: np.ndarray) -> DistributionForecast:
        z = self.scaler.transform(np.asarray(row)[None, :])
        probabilities = self.gate.predict_proba(z)[0]
        design = np.r_[1.0, z[0]]
        locations = self.regime_coefficients @ design
        counts = np.floor(probabilities * 4000).astype(int)
        counts[int(np.argmax(probabilities))] += 4000 - int(counts.sum())
        pieces: list[np.ndarray] = []
        for index, count in enumerate(counts):
            if count <= 0:
                continue
            u = (np.arange(count, dtype=float) + 0.5) / count
            pieces.append(locations[index] + self.regime_scales[index] * stats.norm.ppf(u))
        samples = np.sort(np.concatenate(pieces))
        result = DistributionForecast(
            "E5",
            np.quantile(samples, QUANTILES),
            samples,
            float(np.mean(samples > 0)),
            {
                "regime_count": len(probabilities),
                "gate_family": "multinomial_logistic",
                "global_shrinkage": self.global_shrinkage,
                "minimum_effective_sample_size": self.minimum_effective_sample_size,
                "cluster_rebalanced": self.cluster_rebalanced,
                "future_regime_label": "prohibited",
                "regime_probabilities": probabilities.tolist(),
            },
        )
        result.validate()
        return result


@dataclass
class E6AsymmetricEVTTail:
    scaler: RobustScaler
    location_coefficients: np.ndarray
    residual_body: np.ndarray
    lower_threshold: float
    upper_threshold: float
    lower_shape: float
    lower_scale: float
    upper_shape: float
    upper_scale: float
    threshold_quantile: float

    @classmethod
    def fit(
        cls,
        x: np.ndarray,
        y: np.ndarray,
        *,
        threshold_quantile: float,
        minimum_exceedances_per_tail: int = 40,
        shape_bounds: tuple[float, float] = (-0.45, 0.45),
    ) -> "E6AsymmetricEVTTail":
        from sklearn.linear_model import Ridge

        mask = np.isfinite(y) & (np.isfinite(x).sum(axis=1) >= max(1, x.shape[1] // 2))
        if mask.sum() < 200:
            raise DistributionModelError("E6 has insufficient training rows")
        scaler = RobustScaler.fit(x[mask])
        z = scaler.transform(x[mask])
        target = np.asarray(y[mask], dtype=float)
        model = Ridge(alpha=1.0).fit(z, target)
        coefficients = np.r_[model.intercept_, model.coef_]
        residual = target - np.c_[np.ones(len(z)), z] @ coefficients
        lower_threshold = float(np.quantile(residual, 1 - threshold_quantile))
        upper_threshold = float(np.quantile(residual, threshold_quantile))
        lower_excess = lower_threshold - residual[residual < lower_threshold]
        upper_excess = residual[residual > upper_threshold] - upper_threshold
        if min(len(lower_excess), len(upper_excess)) < minimum_exceedances_per_tail:
            raise DistributionModelError("E6 minimum tail exceedances not met")

        def fit_tail(excess: np.ndarray) -> tuple[float, float]:
            shape, _, scale = stats.genpareto.fit(excess, floc=0)
            # Contract-required shrinkage toward the exponential global tail.
            shape = float(np.clip(0.5 * shape, shape_bounds[0], shape_bounds[1]))
            scale = max(1e-8, float(0.5 * scale + 0.5 * np.mean(excess)))
            return shape, scale

        lower_shape, lower_scale = fit_tail(lower_excess)
        upper_shape, upper_scale = fit_tail(upper_excess)
        return cls(
            scaler,
            coefficients,
            np.sort(residual),
            lower_threshold,
            upper_threshold,
            lower_shape,
            lower_scale,
            upper_shape,
            upper_scale,
            float(threshold_quantile),
        )

    def predict(self, row: np.ndarray) -> DistributionForecast:
        design = np.r_[1.0, self.scaler.transform(np.asarray(row)[None, :])[0]]
        location = float(design @ self.location_coefficients)
        u = (np.arange(4000, dtype=float) + 0.5) / 4000
        lower_mass = 1 - self.threshold_quantile
        upper_start = self.threshold_quantile
        residual_samples = np.quantile(self.residual_body, u)
        lower = u < lower_mass
        upper = u > upper_start
        if lower.any():
            tail_probability = np.clip(u[lower] / lower_mass, 1e-9, 1 - 1e-9)
            residual_samples[lower] = self.lower_threshold - stats.genpareto.ppf(
                1 - tail_probability, self.lower_shape, loc=0, scale=self.lower_scale
            )
        if upper.any():
            tail_probability = np.clip((u[upper] - upper_start) / (1 - upper_start), 1e-9, 1 - 1e-9)
            residual_samples[upper] = self.upper_threshold + stats.genpareto.ppf(
                tail_probability, self.upper_shape, loc=0, scale=self.upper_scale
            )
        samples = np.sort(location + residual_samples)
        result = DistributionForecast(
            "E6",
            np.quantile(samples, QUANTILES),
            samples,
            float(np.mean(samples > 0)),
            {
                "threshold_quantile": self.threshold_quantile,
                "lower_upper_fit_separate": True,
                "minimum_exceedances_per_tail": 40,
                "shape_bounds": [-0.45, 0.45],
                "shrinkage_to_global": "required_applied_0.5",
            },
        )
        result.validate()
        return result


@dataclass
class E7PITAnalogTrajectory:
    scaler: RobustScaler
    training_features: np.ndarray
    training_labels: np.ndarray
    precision: np.ndarray
    neighbor_count: int
    spacing_rows: int

    @classmethod
    def fit(
        cls,
        x: np.ndarray,
        y: np.ndarray,
        *,
        neighbor_count: int,
        minimum_temporal_spacing_sessions: int = 126,
    ) -> "E7PITAnalogTrajectory":
        mask = np.isfinite(y) & (np.isfinite(x).sum(axis=1) >= max(1, x.shape[1] // 2))
        if mask.sum() < 250:
            raise DistributionModelError("E7 has insufficient training rows")
        scaler = RobustScaler.fit(x[mask])
        z = scaler.transform(x[mask])
        covariance = np.cov(z, rowvar=False)
        precision = np.linalg.pinv(covariance + np.eye(covariance.shape[0]) * 1e-6)
        # Canonical origins are weekly; ceil(126 / 5) preserves at least 126
        # trading sessions between selected historical analog origins.
        spacing_rows = int(math.ceil(minimum_temporal_spacing_sessions / 5))
        if neighbor_count * spacing_rows > len(z) + spacing_rows:
            raise DistributionModelError("E7 temporal-spacing neighbor count is infeasible")
        return cls(scaler, z, np.asarray(y[mask], dtype=float), precision, int(neighbor_count), spacing_rows)

    def predict(self, row: np.ndarray) -> DistributionForecast:
        target = self.scaler.transform(np.asarray(row)[None, :])[0]
        delta = self.training_features - target
        distance = np.einsum("ij,jk,ik->i", delta, self.precision, delta)
        selected: list[int] = []
        for index in np.argsort(distance, kind="stable"):
            if all(abs(int(index) - other) >= self.spacing_rows for other in selected):
                selected.append(int(index))
            if len(selected) == self.neighbor_count:
                break
        if len(selected) != self.neighbor_count:
            raise DistributionModelError("E7 could not satisfy temporal spacing")
        analogs = np.sort(self.training_labels[np.asarray(selected)])
        indexes = np.linspace(0, len(analogs) - 1, 4000).round().astype(int)
        samples = analogs[indexes]
        result = DistributionForecast(
            "E7",
            np.quantile(samples, QUANTILES),
            samples,
            float(np.mean(samples > 0)),
            {
                "distance": "robust_mahalanobis",
                "neighbor_count": self.neighbor_count,
                "minimum_temporal_spacing_sessions": self.spacing_rows * 5,
                "future_outcome_in_distance": "prohibited",
            },
        )
        result.validate()
        return result


def convex_sample_mixture(forecasts: list[DistributionForecast], weights: np.ndarray, sample_count: int = 4000) -> DistributionForecast:
    weights = np.asarray(weights, dtype=float)
    if len(weights) != len(forecasts) or np.any(weights < 0) or not np.isclose(weights.sum(), 1):
        raise DistributionModelError("ensemble weights must be nonnegative and sum to one")
    counts = np.floor(weights * sample_count).astype(int)
    counts[np.argmax(weights)] += sample_count - counts.sum()
    pieces = []
    for forecast, count in zip(forecasts, counts, strict=True):
        if count:
            indexes = np.linspace(0, len(forecast.samples) - 1, count).round().astype(int)
            pieces.append(forecast.samples[indexes])
    samples = np.sort(np.concatenate(pieces))
    result = DistributionForecast("ENSEMBLE", np.quantile(samples, QUANTILES), samples, float(np.mean(samples > 0)), {"weights": weights.tolist(), "constituents": [f.candidate_id for f in forecasts]})
    result.validate(); return result
