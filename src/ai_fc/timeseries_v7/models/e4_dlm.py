"""Filtered dynamic linear random-walk state model."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class FilteredDLM:
    states: np.ndarray
    covariances: np.ndarray
    process_variance: float
    observation_variance: float


def filter_states(values: np.ndarray, target: np.ndarray, *, process_variance: float, observation_variance: float) -> FilteredDLM:
    x = np.asarray(values, dtype=float); y = np.asarray(target, dtype=float); width = x.shape[1]
    state = np.zeros(width); covariance = np.eye(width) * 10
    states=[]; covariances=[]
    for row, observed in zip(x, y):
        predicted_cov = covariance + np.eye(width) * process_variance
        innovation_variance = float(row @ predicted_cov @ row + observation_variance)
        gain = predicted_cov @ row / innovation_variance
        state = state + gain * (observed - row @ state)
        covariance = predicted_cov - np.outer(gain, row) @ predicted_cov
        states.append(state.copy()); covariances.append(covariance.copy())
    return FilteredDLM(np.asarray(states), np.asarray(covariances), process_variance, observation_variance)
