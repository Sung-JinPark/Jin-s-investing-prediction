"""Direct quantile elastic-net expert with training-only robust scaling."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class QuantileLinearModel:
    quantile: float
    intercept: float
    coefficients: np.ndarray
    median: np.ndarray
    iqr: np.ndarray

    def predict(self, values: np.ndarray) -> np.ndarray:
        return self.intercept + ((values - self.median) / self.iqr) @ self.coefficients


def fit(values: np.ndarray, target: np.ndarray, *, quantile: float, alpha: float, l1_ratio: float, max_iter: int = 10_000, tolerance: float = 1e-7) -> QuantileLinearModel:
    x = np.asarray(values, dtype=float); y = np.asarray(target, dtype=float)
    if not 0 < quantile < 1 or not 0 <= l1_ratio <= 1:
        raise ValueError("invalid quantile or l1_ratio")
    median = np.median(x, axis=0); iqr = np.subtract(*np.percentile(x, [75, 25], axis=0)); iqr[iqr == 0] = 1
    scaled = (x - median) / iqr
    def objective(params):
        residual = y - (params[0] + scaled @ params[1:])
        pinball = np.maximum(quantile * residual, (quantile - 1) * residual).mean()
        beta = params[1:]
        return pinball + alpha * (l1_ratio * np.abs(beta).sum() + (1 - l1_ratio) * .5 * np.square(beta).sum())
    initial = np.r_[np.quantile(y, quantile), np.zeros(x.shape[1])]
    result = minimize(objective, initial, method="Powell", options={"maxiter": max_iter, "xtol": tolerance, "ftol": tolerance})
    if not result.success:
        raise RuntimeError(f"quantile optimization failed: {result.message}")
    return QuantileLinearModel(quantile, float(result.x[0]), result.x[1:].copy(), median, iqr)


def rearrange(predictions: np.ndarray) -> np.ndarray:
    return np.sort(np.asarray(predictions, dtype=float), axis=-1)
