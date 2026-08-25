"""True joint Student-t location/log-scale negative likelihood."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln


def nll_and_gradient(params: np.ndarray, values: np.ndarray, target: np.ndarray, df: float) -> tuple[float, np.ndarray]:
    x = np.c_[np.ones(len(values)), np.asarray(values, dtype=float)]
    y = np.asarray(target, dtype=float)
    width = x.shape[1]; beta = params[:width]; gamma = params[width:]
    location = x @ beta; eta = np.clip(x @ gamma, -12, 12); scale = np.exp(eta)
    z = (y - location) / scale
    constant = gammaln((df + 1) / 2) - gammaln(df / 2) - .5 * np.log(df * np.pi)
    losses = -constant + eta + (df + 1) / 2 * np.log1p(z * z / df)
    d_location = -(df + 1) * z / (df + z * z) / scale
    d_eta = 1 - (df + 1) * z * z / (df + z * z)
    gradient = np.r_[x.T @ d_location, x.T @ d_eta] / len(y)
    return float(losses.mean()), gradient


@dataclass(frozen=True)
class StudentTModel:
    location_coefficients: np.ndarray
    log_scale_coefficients: np.ndarray
    degrees_of_freedom: float

    def parameters(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
        x = np.c_[np.ones(len(values)), values]
        return x @ self.location_coefficients, np.exp(np.clip(x @ self.log_scale_coefficients, -12, 12)), self.degrees_of_freedom


def fit(values: np.ndarray, target: np.ndarray, *, degrees_of_freedom: float, ridge_alpha: float = 0.0) -> StudentTModel:
    x = np.asarray(values, dtype=float); y = np.asarray(target, dtype=float); width = x.shape[1] + 1
    initial = np.r_[np.zeros(width), np.log(max(np.std(y), 1e-3)), np.zeros(width - 1)]
    def objective(params):
        value, gradient = nll_and_gradient(params, x, y, degrees_of_freedom)
        penalty = .5 * ridge_alpha * (np.square(params[1:width]).sum() + np.square(params[width + 1:]).sum())
        penalized = gradient.copy(); penalized[1:width] += ridge_alpha * params[1:width]; penalized[width + 1:] += ridge_alpha * params[width + 1:]
        return value + penalty, penalized
    result = minimize(objective, initial, jac=True, method="L-BFGS-B")
    if not result.success: raise RuntimeError(result.message)
    return StudentTModel(result.x[:width].copy(), result.x[width:].copy(), degrees_of_freedom)
