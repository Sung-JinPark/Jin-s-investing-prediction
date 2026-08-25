"""Direct horizon location/scale/tail experts and deterministic distributions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import stats


class ModelFitError(RuntimeError):
    """A preregistered candidate failed without being silently repaired."""


QUANTILE_LEVELS = np.asarray([0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])


def robust_matrix_fit(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    median = np.zeros(values.shape[1]); q1 = np.zeros(values.shape[1]); q3 = np.ones(values.shape[1])
    for column in range(values.shape[1]):
        sample = values[np.isfinite(values[:, column]), column]
        if sample.size:
            median[column] = float(np.median(sample)); q1[column] = float(np.quantile(sample, .25)); q3[column] = float(np.quantile(sample, .75))
    scale = q3 - q1; scale = np.where(np.isfinite(scale) & (scale > 1e-10), scale, 1.0)
    return median, scale


def robust_transform(values: np.ndarray, median: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return (np.where(np.isfinite(values), values, median) - median) / scale


@dataclass
class DirectDistributionModel:
    alpha: float
    df: float
    family: str
    raw_feature_count: int
    active_feature_indices: np.ndarray
    active_feature_names: tuple[str, ...]
    feature_median: np.ndarray
    feature_scale: np.ndarray
    location_coef: np.ndarray
    scale_coef: np.ndarray
    residual_scale: float
    quantile_coef: np.ndarray | None = None
    quantile_estimators: tuple[Any, ...] | None = None
    evt_threshold: float | None = None
    evt_shape: float | None = None
    evt_scale: float | None = None

    @staticmethod
    def _augment(z: np.ndarray, family: str) -> np.ndarray:
        if family == "ex_ante_soft_regime_mixture":
            stress = np.nanmean(np.abs(z[:, : min(8, z.shape[1])]), axis=1, keepdims=True)
            return np.c_[z, z * np.clip(stress, 0, 3)]
        return z

    @staticmethod
    def _fit_quantile_elastic_net(z: np.ndarray, y: np.ndarray, *, alpha: float) -> np.ndarray:
        """Deterministic IRLS approximation to pinball-loss elastic net.

        The asymmetric absolute-loss weights target the requested quantile while
        ElasticNet supplies the preregistered L1/L2 penalty.  The approximation is
        deliberately fixed (iterations, l1_ratio and tolerance) before evaluation.
        """
        import warnings

        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import ElasticNet

        rows: list[np.ndarray] = []
        regularization = max(1e-7, alpha * 1e-4)
        for level in (0.10, 0.50, 0.90):
            model = ElasticNet(
                alpha=regularization,
                l1_ratio=0.35,
                fit_intercept=True,
                max_iter=5000,
                tol=1e-4,
                selection="cyclic",
            )
            weights = np.ones(len(y), dtype=float)
            for _ in range(6):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", ConvergenceWarning)
                    model.fit(z, y, sample_weight=weights)
                if any(issubclass(item.category, ConvergenceWarning) for item in caught):
                    raise ModelFitError("quantile elastic-net failed to converge under preregistered settings")
                residual = y - model.predict(z)
                asymmetric = np.where(residual >= 0.0, level, 1.0 - level)
                weights = np.minimum(50.0, asymmetric / np.maximum(np.abs(residual), 1e-4))
                weights /= max(float(np.mean(weights)), 1e-12)
            rows.append(np.r_[model.intercept_, model.coef_])
        return np.asarray(rows, dtype=float)

    @classmethod
    def fit(
        cls,
        features: np.ndarray,
        target: np.ndarray,
        *,
        alpha: float,
        df: float,
        family: str = "student_t_location_scale",
        feature_names: list[str] | tuple[str, ...] | None = None,
    ) -> "DirectDistributionModel":
        try:
            from sklearn.ensemble import HistGradientBoostingRegressor
            from sklearn.linear_model import Ridge
        except ImportError as exc: raise RuntimeError("install ai-fc[timeseries-v5] for direct models") from exc
        names = tuple(feature_names or (f"feature_{index}" for index in range(features.shape[1])))
        if len(names) != features.shape[1]:
            raise ValueError("feature_names length does not match the feature matrix")
        challenger_families = {"ex_ante_soft_regime_mixture", "student_t_evt_tail"}
        active = np.asarray(
            [index for index, name in enumerate(names) if family in challenger_families or not name.startswith("challenger_")],
            dtype=int,
        )
        if not active.size:
            raise ValueError("direct model has no active features")
        selected_features = features[:, active]
        mask = np.isfinite(target) & (np.isfinite(selected_features).sum(axis=1) >= max(1, selected_features.shape[1] // 2)); x = selected_features[mask]; y = target[mask]
        if len(y) < 100: raise ValueError("insufficient direct-model training rows")
        median, scale = robust_matrix_fit(x); z = cls._augment(robust_transform(x, median, scale), family)
        weights = np.exp(np.linspace(-4.0, 0.0, len(y))) if family == "dynamic_linear_state_space" else None
        location = Ridge(alpha=alpha, fit_intercept=True).fit(z, y, sample_weight=weights)
        quantile_coef = cls._fit_quantile_elastic_net(z, y, alpha=alpha) if family == "quantile_elastic_net" else None
        quantile_estimators: tuple[Any, ...] | None = None
        if family == "quantile_hist_gradient_boosting":
            quantile_estimators = tuple(
                HistGradientBoostingRegressor(
                    loss="quantile",
                    quantile=level,
                    learning_rate=0.05,
                    max_iter=80,
                    max_leaf_nodes=7,
                    min_samples_leaf=max(12, min(30, len(y) // 25)),
                    l2_regularization=max(0.0, alpha),
                    random_state=0,
                ).fit(z, y)
                for level in (0.10, 0.50, 0.90)
            )
        residual = y - location.predict(z)
        absolute = np.log(np.abs(residual) + max(1e-6, float(np.nanmedian(np.abs(residual))) * 0.05))
        scale_model = Ridge(alpha=max(alpha, 1.0), fit_intercept=True).fit(z, absolute)
        evt_threshold = evt_shape = evt_scale = None
        if family == "student_t_evt_tail":
            absolute_residual = np.abs(residual)
            evt_threshold = float(np.quantile(absolute_residual, 0.90))
            exceedances = absolute_residual[absolute_residual > evt_threshold] - evt_threshold
            if len(exceedances) >= 30 and float(np.max(exceedances)) > 0:
                fitted_shape, _, fitted_scale = stats.genpareto.fit(exceedances, floc=0.0)
                evt_shape = float(np.clip(fitted_shape, -0.25, 0.75))
                evt_scale = max(1e-8, float(fitted_scale))
        return cls(
            alpha,
            df,
            family,
            features.shape[1],
            active,
            tuple(names[index] for index in active),
            median,
            scale,
            np.r_[location.intercept_, location.coef_],
            np.r_[scale_model.intercept_, scale_model.coef_],
            max(1e-6, float(np.std(residual, ddof=1))),
            quantile_coef=quantile_coef,
            quantile_estimators=quantile_estimators,
            evt_threshold=evt_threshold,
            evt_shape=evt_shape,
            evt_scale=evt_scale,
        )

    def _design(self, row: np.ndarray) -> np.ndarray:
        raw = np.asarray(row, dtype=float)
        if raw.shape[0] != self.raw_feature_count:
            raise ValueError("prediction row does not match fitted raw feature count")
        z = robust_transform(raw[self.active_feature_indices][None, :], self.feature_median, self.feature_scale)
        return np.r_[1.0, self._augment(z, self.family)[0]]

    @staticmethod
    def _quantile_grid(lower: float, center: float, upper: float) -> np.ndarray:
        ordered = np.maximum.accumulate(np.asarray([lower, center, upper], dtype=float))
        lower, center, upper = (float(value) for value in ordered)
        left = max(center - lower, 1e-8)
        right = max(upper - center, 1e-8)
        normal_10 = abs(float(stats.norm.ppf(0.10)))
        return np.asarray(
            [
                center - left * abs(float(stats.norm.ppf(0.01))) / normal_10,
                center - left * abs(float(stats.norm.ppf(0.05))) / normal_10,
                lower,
                center - left * abs(float(stats.norm.ppf(0.25))) / normal_10,
                center,
                center + right * float(stats.norm.ppf(0.75)) / normal_10,
                upper,
                center + right * float(stats.norm.ppf(0.95)) / normal_10,
                center + right * float(stats.norm.ppf(0.99)) / normal_10,
            ],
            dtype=float,
        )

    def predict(self, row: np.ndarray, *, sample_count: int = 4000) -> dict[str, Any]:
        design = self._design(row)
        location = float(design @ self.location_coef)
        predicted_abs = float(np.exp(np.clip(design @ self.scale_coef, -12, 2)))
        scale = max(self.residual_scale * 0.25, predicted_abs / stats.t.ppf(0.75, self.df))
        u = (np.arange(sample_count, dtype=float) + 0.5) / sample_count
        if self.quantile_coef is not None:
            direct = self.quantile_coef @ design
            quantiles = self._quantile_grid(*direct)
            samples = np.interp(u, QUANTILE_LEVELS, quantiles)
            location = float(quantiles[4])
        elif self.quantile_estimators is not None:
            raw = np.asarray(row, dtype=float)
            z = robust_transform(raw[self.active_feature_indices][None, :], self.feature_median, self.feature_scale)
            direct = [float(model.predict(z)[0]) for model in self.quantile_estimators]
            quantiles = self._quantile_grid(*direct)
            samples = np.interp(u, QUANTILE_LEVELS, quantiles)
            location = float(quantiles[4])
        else:
            samples = location + scale * stats.t.ppf(u, self.df)
            if self.family == "student_t_evt_tail" and self.evt_threshold is not None and self.evt_shape is not None and self.evt_scale is not None:
                centered = samples - location
                absolute = np.abs(centered)
                mask = absolute > self.evt_threshold
                if np.any(mask):
                    tail_u = u[mask]
                    tail_rank = np.where(tail_u < 0.5, (0.05 - tail_u) / 0.05, (tail_u - 0.95) / 0.05)
                    tail_rank = np.clip(tail_rank, 1e-6, 1 - 1e-6)
                    magnitude = self.evt_threshold + stats.genpareto.ppf(tail_rank, c=self.evt_shape, loc=0.0, scale=self.evt_scale)
                    centered[mask] = np.sign(centered[mask]) * magnitude
                    samples = location + centered
            quantiles = np.quantile(samples, QUANTILE_LEVELS)
        samples = np.sort(np.asarray(samples, dtype=float))
        quantiles = np.maximum.accumulate(np.asarray(quantiles, dtype=float))
        return {"location": location, "scale": scale, "df": self.df, "quantiles": quantiles, "samples": samples, "up_probability": float(np.mean(samples > 0.0))}


def approximate_anchor_samples(p10: float, p90: float, *, sample_count: int = 4000) -> np.ndarray:
    center = (p10 + p90) / 2.0; scale = max(1e-8, (p90 - p10) / (2 * stats.norm.ppf(0.90))); u = (np.arange(sample_count, dtype=float) + 0.5) / sample_count
    return center + scale * stats.norm.ppf(u)


def convex_mix_samples(anchor: np.ndarray, direct: np.ndarray, direct_weight: float) -> np.ndarray:
    if not 0 <= direct_weight <= 1: raise ValueError("convex weight outside [0,1]")
    return np.sort((1.0 - direct_weight) * np.sort(anchor) + direct_weight * np.sort(direct))


def empirical_crps(samples: np.ndarray, actual: float) -> float:
    values = np.sort(np.asarray(samples, dtype=float)); count = len(values); first = float(np.mean(np.abs(values - actual))); coefficients = 2 * np.arange(1, count + 1) - count - 1; pair = float(np.sum(coefficients * values) / (count * count))
    return first - pair


def choose_spec_inner(
    features: np.ndarray,
    target: np.ndarray,
    *,
    specs: list[dict[str, float]],
    feature_names: list[str] | tuple[str, ...] | None = None,
    purge_rows: int = 14,
    validation_rows: int = 52,
) -> tuple[dict[str, float], dict[str, float | None]]:
    usable = len(target) - purge_rows; split = usable - validation_rows
    if split < 150: raise ModelFitError("inner selection history is incomplete")
    train_x, train_y = features[:split], target[:split]; val_x, val_y = features[split:usable], target[split:usable]; scores: dict[str, float | None] = {}
    for index, spec in enumerate(specs):
        try:
            model = DirectDistributionModel.fit(train_x, train_y, alpha=float(spec["alpha"]), df=float(spec["df"]), family=str(spec.get("family", "student_t_location_scale")), feature_names=feature_names); losses = []
            for row, actual in zip(val_x, val_y, strict=True):
                if np.isfinite(actual): losses.append(empirical_crps(model.predict(row, sample_count=512)["samples"], float(actual)))
            scores[str(index)] = float(np.mean(losses)) if losses else float("inf")
        except (ModelFitError, ValueError, FloatingPointError):
            scores[str(index)] = None
    valid = [index for index in range(len(specs)) if scores[str(index)] is not None and np.isfinite(float(scores[str(index)]))]
    if not valid: raise ModelFitError("all preregistered direct candidates failed the inner fold")
    selected = min(valid, key=lambda value: float(scores[str(value)])); return specs[selected], scores


FROZEN_SPECS: tuple[dict[str, float | str], ...] = (
    {"id": "E1-a01-d6", "family": "quantile_elastic_net", "alpha": 0.1, "df": 6.0},
    {"id": "E1-a1-d6", "family": "quantile_elastic_net", "alpha": 1.0, "df": 6.0},
    {"id": "E2-a01-d4", "family": "student_t_location_scale", "alpha": 0.1, "df": 4.0},
    {"id": "E2-a1-d4", "family": "student_t_location_scale", "alpha": 1.0, "df": 4.0},
    {"id": "E2-a10-d4", "family": "student_t_location_scale", "alpha": 10.0, "df": 4.0},
    {"id": "E2-a1-d10", "family": "student_t_location_scale", "alpha": 1.0, "df": 10.0},
    {"id": "E3-hgb-q", "family": "quantile_hist_gradient_boosting", "alpha": 0.1, "df": 6.0},
    {"id": "E5-soft", "family": "ex_ante_soft_regime_mixture", "alpha": 3.0, "df": 5.0},
    {"id": "E6-tail", "family": "student_t_evt_tail", "alpha": 3.0, "df": 4.0},
    {"id": "E6-tail-a10", "family": "student_t_evt_tail", "alpha": 10.0, "df": 6.0},
    {"id": "E4-state", "family": "dynamic_linear_state_space", "alpha": 30.0, "df": 8.0},
)
