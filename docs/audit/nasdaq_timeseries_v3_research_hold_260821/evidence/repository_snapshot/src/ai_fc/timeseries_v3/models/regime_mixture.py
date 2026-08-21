"""Regularized soft regime probabilities and conditional residual mixture."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


REGIMES = (
    "calm_uptrend", "normal_range", "tightening_real_yield_shock",
    "high_vol_drawdown", "post_crisis_rebound", "liquidity_stress",
)


def softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exp = np.exp(shifted)
    return exp / exp.sum()


@dataclass(frozen=True)
class SoftRegimeModel:
    median: np.ndarray
    scale: np.ndarray
    centers: np.ndarray
    minimum_probability: float = 0.01

    @classmethod
    def fit(cls, features: np.ndarray, *, minimum_probability: float = 0.01) -> "SoftRegimeModel":
        x = np.asarray(features, dtype=float)
        median = np.nanmedian(x, axis=0)
        scale = np.nanpercentile(x, 75, axis=0) - np.nanpercentile(x, 25, axis=0)
        scale = np.where(scale > 1e-12, scale, 1.0)
        z = np.where(np.isfinite(x), x, median)
        z = (z - median) / scale
        # Deterministic prototypes: trend, volatility/drawdown, rate shock and liquidity axes.
        centers = np.zeros((len(REGIMES), z.shape[1]))
        width = min(z.shape[1], 6)
        prototypes = np.array([
            [1.2, -0.8, 0.0, 0.0, 0.2, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [-0.4, 0.5, 1.2, 0.8, 0.8, -0.2],
            [-1.2, 1.6, 0.3, 0.2, 0.4, -0.6],
            [1.6, 1.0, -0.4, -0.3, -0.2, 0.5],
            [-0.8, 1.0, 0.5, 0.8, 1.2, -1.2],
        ])
        centers[:, :width] = prototypes[:, :width]
        return cls(median, scale, centers, minimum_probability)

    def probabilities(self, features: np.ndarray) -> dict[str, float]:
        row = np.asarray(features, dtype=float)
        row = np.where(np.isfinite(row), row, self.median)
        z = (row - self.median) / self.scale
        logits = -0.5 * np.mean((self.centers - z) ** 2, axis=1)
        probabilities = softmax(logits)
        probabilities = np.maximum(probabilities, self.minimum_probability)
        probabilities /= probabilities.sum()
        return {name: float(value) for name, value in zip(REGIMES, probabilities, strict=True)}


def mix_regime_residuals(
    residual_pools: dict[str, np.ndarray], probabilities: dict[str, float], *,
    count: int, rng: np.random.Generator,
) -> np.ndarray:
    labels = [name for name in REGIMES if name in residual_pools and len(residual_pools[name])]
    if not labels:
        raise ValueError("no eligible regime residual pools")
    weights = np.array([probabilities[name] for name in labels], dtype=float)
    weights /= weights.sum()
    selected = rng.choice(len(labels), size=count, p=weights)
    output = np.empty(count)
    for index, label in enumerate(labels):
        mask = selected == index
        if mask.any():
            output[mask] = rng.choice(np.asarray(residual_pools[label]), size=int(mask.sum()), replace=True)
    return output
