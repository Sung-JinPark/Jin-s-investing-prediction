"""Direct horizon anchor-error model with bounded corrections."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _robust_fit_matrix(features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = np.asarray(features, dtype=float)
    median = np.nanmedian(values, axis=0)
    scale = np.nanpercentile(values, 75, axis=0) - np.nanpercentile(values, 25, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, 1.0)
    clean = np.where(np.isfinite(values), values, median)
    standardized = (clean - median) / scale
    return np.column_stack((np.ones(len(values)), standardized)), median, scale


@dataclass(frozen=True)
class DirectHorizonModel:
    horizons: tuple[int, ...]
    coefficients: dict[int, np.ndarray]
    feature_median: np.ndarray
    feature_scale: np.ndarray
    correction_sigma_bounds: dict[int, float]
    alpha: float

    @classmethod
    def fit(
        cls, features: np.ndarray, residual_targets: dict[int, np.ndarray], *,
        alpha: float, correction_sigma_bounds: dict[int, float],
    ) -> "DirectHorizonModel":
        design, median, scale = _robust_fit_matrix(features)
        coefficients: dict[int, np.ndarray] = {}
        for horizon, target in residual_targets.items():
            y = np.asarray(target, dtype=float)
            mask = np.isfinite(y) & np.isfinite(design).all(axis=1)
            if mask.sum() < design.shape[1] + 20:
                raise ValueError(f"insufficient direct target rows for horizon {horizon}")
            x = design[mask]
            penalty = np.eye(x.shape[1]) * float(alpha)
            penalty[0, 0] = 0.0
            coefficients[int(horizon)] = np.linalg.solve(x.T @ x + penalty, x.T @ y[mask])
        return cls(tuple(sorted(coefficients)), coefficients, median, scale, dict(correction_sigma_bounds), alpha)

    def location_corrections(self, features: np.ndarray, anchor_samples: dict[int, np.ndarray]) -> dict[int, float]:
        row = np.asarray(features, dtype=float).reshape(-1)
        row = np.where(np.isfinite(row), row, self.feature_median)
        design = np.concatenate(([1.0], (row - self.feature_median) / self.feature_scale))
        corrections: dict[int, float] = {}
        for horizon in self.horizons:
            raw = float(design @ self.coefficients[horizon])
            sigma = float(np.std(anchor_samples[horizon], ddof=1))
            bound = float(self.correction_sigma_bounds[horizon]) * sigma
            corrections[horizon] = float(np.clip(raw, -bound, bound))
        return corrections

    def predict_samples(self, features: np.ndarray, anchor_samples: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
        corrections = self.location_corrections(features, anchor_samples)
        return {horizon: np.asarray(anchor_samples[horizon]) + corrections[horizon] for horizon in self.horizons}


def select_alpha_by_horizon_crps(
    features: np.ndarray, residual_targets: dict[int, np.ndarray], anchor_samples_by_row: dict[int, np.ndarray],
    *, alphas: tuple[float, ...], correction_sigma_bounds: dict[int, float], validation_start: int,
) -> tuple[float, dict[float, float]]:
    """Select one preregistered alpha using direct-horizon CRPS, never one-day MSE."""
    from ..backtest import empirical_crps

    scores: dict[float, float] = {}
    train = slice(0, validation_start)
    for alpha in alphas:
        model = DirectHorizonModel.fit(
            features[train], {h: values[train] for h, values in residual_targets.items()},
            alpha=alpha, correction_sigma_bounds=correction_sigma_bounds,
        )
        losses: list[float] = []
        for row in range(validation_start, len(features)):
            anchors = {h: anchor_samples_by_row[h][row] for h in residual_targets}
            prediction = model.predict_samples(features[row], anchors)
            for horizon, target in residual_targets.items():
                actual = float(target[row] + np.median(anchors[horizon]))
                losses.append(empirical_crps(prediction[horizon], actual))
        scores[float(alpha)] = float(np.mean(losses))
    selected = min(scores, key=scores.get)
    return float(selected), scores


@dataclass(frozen=True)
class AnalogQuantileModel:
    features: np.ndarray
    targets: dict[int, np.ndarray]
    median: np.ndarray
    scale: np.ndarray
    neighbors: dict[int, int]
    conditional_weight: float
    correction_sigma_bounds: dict[int, float]

    @classmethod
    def fit(
        cls, features: np.ndarray, targets: dict[int, np.ndarray], *, neighbors: int | dict[int, int],
        conditional_weight: float, correction_sigma_bounds: dict[int, float],
    ) -> "AnalogQuantileModel":
        x = np.asarray(features, dtype=float)
        median = np.nanmedian(x, axis=0)
        scale = np.nanpercentile(x, 75, axis=0) - np.nanpercentile(x, 25, axis=0)
        scale = np.where(scale > 1e-12, scale, 1.0)
        if not 0.0 <= conditional_weight <= 1.0:
            raise ValueError("analog conditional weight must be in [0,1]")
        neighbor_map = (
            {int(horizon): int(neighbors) for horizon in targets}
            if isinstance(neighbors, int) else {int(horizon): int(value) for horizon, value in neighbors.items()}
        )
        if set(neighbor_map) != set(targets):
            raise ValueError("analog neighbor selection must cover every direct horizon")
        return cls(x, {h: np.asarray(v, dtype=float) for h, v in targets.items()}, median, scale, neighbor_map, conditional_weight, dict(correction_sigma_bounds))

    def predict_samples(
        self, features: np.ndarray, anchor_samples: dict[int, np.ndarray], *,
        count: int, rng: np.random.Generator,
    ) -> dict[int, np.ndarray]:
        row = np.asarray(features, dtype=float)
        clean = np.where(np.isfinite(self.features), self.features, self.median)
        target = np.where(np.isfinite(row), row, self.median)
        distances = np.mean(((clean - target) / self.scale) ** 2, axis=1)
        ordered = np.argsort(distances)
        output: dict[int, np.ndarray] = {}
        for horizon, anchor in anchor_samples.items():
            selected = ordered[: max(20, min(self.neighbors[horizon], len(distances)))]
            source = self.targets[horizon][selected]
            source = source[np.isfinite(source)]
            if source.size < 20:
                output[horizon] = np.asarray(anchor, dtype=float).copy()
                continue
            anchor_array = np.asarray(anchor, dtype=float)
            conditional = rng.choice(source, size=count, replace=True)
            anchor_draw = rng.choice(anchor_array, size=count, replace=True)
            anchor_median = float(np.median(anchor_array))
            delta = float(np.median(conditional) - anchor_median)
            bound = self.correction_sigma_bounds[horizon] * float(np.std(anchor_array, ddof=1))
            conditional += float(np.clip(delta, -bound, bound)) - delta
            choose = rng.random(count) < self.conditional_weight
            output[horizon] = np.where(choose, conditional, anchor_draw)
        return output
