"""Horizon-specific conditional scale and heavy-tail transformation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HorizonScaleModel:
    coefficients: dict[int, np.ndarray]
    feature_median: np.ndarray
    feature_scale: np.ndarray
    minimum_scale: float = 0.50
    maximum_scale: float = 2.50

    @classmethod
    def fit(
        cls, features: np.ndarray, realized_targets: dict[int, np.ndarray],
        anchor_scale: dict[int, np.ndarray], *, alpha: float = 10.0,
    ) -> "HorizonScaleModel":
        x = np.asarray(features, dtype=float)
        median = np.nanmedian(x, axis=0)
        scale = np.nanpercentile(x, 75, axis=0) - np.nanpercentile(x, 25, axis=0)
        scale = np.where(scale > 1e-12, scale, 1.0)
        x = np.where(np.isfinite(x), x, median)
        design = np.column_stack((np.ones(len(x)), (x - median) / scale))
        coefficients: dict[int, np.ndarray] = {}
        for horizon, target in realized_targets.items():
            denominator = np.maximum(np.asarray(anchor_scale[horizon], dtype=float), 1e-8)
            y = np.log(np.maximum(np.abs(np.asarray(target, dtype=float)), 1e-8) / denominator)
            mask = np.isfinite(y) & np.isfinite(design).all(axis=1)
            penalty = np.eye(design.shape[1]) * alpha
            penalty[0, 0] = 0.0
            coefficients[int(horizon)] = np.linalg.solve(
                design[mask].T @ design[mask] + penalty, design[mask].T @ y[mask],
            )
        return cls(coefficients, median, scale)

    def scale_ratio(self, features: np.ndarray, horizon: int) -> float:
        row = np.asarray(features, dtype=float)
        row = np.where(np.isfinite(row), row, self.feature_median)
        design = np.concatenate(([1.0], (row - self.feature_median) / self.feature_scale))
        ratio = float(np.exp(design @ self.coefficients[int(horizon)]))
        return float(np.clip(ratio, self.minimum_scale, self.maximum_scale))

    def transform(self, samples: dict[int, np.ndarray], features: np.ndarray) -> dict[int, np.ndarray]:
        output: dict[int, np.ndarray] = {}
        for horizon, values in samples.items():
            array = np.asarray(values, dtype=float)
            center = float(np.median(array))
            output[int(horizon)] = center + self.scale_ratio(features, horizon) * (array - center)
        return output


def downside_semivariance(returns: np.ndarray, window: int = 21) -> np.ndarray:
    values = np.asarray(returns, dtype=float)
    output = np.full(values.size, np.nan)
    for index in range(window - 1, values.size):
        sample = np.minimum(values[index - window + 1:index + 1], 0.0)
        output[index] = float(np.mean(sample * sample))
    return output
