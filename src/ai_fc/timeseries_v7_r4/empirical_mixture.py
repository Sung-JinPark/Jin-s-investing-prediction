"""Constrained CRPS stacking for empirical predictive distributions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class EmpiricalMixtureResult:
    weights: tuple[float, ...]
    crps: float
    used_e0_only_fallback: bool


def _validated_inputs(
    forecasts: Sequence[Sequence[Iterable[float]]], actuals: Iterable[float],
) -> tuple[list[list[np.ndarray]], np.ndarray]:
    observations = np.asarray(tuple(actuals), dtype=np.float64)
    if observations.ndim != 1 or observations.size == 0 or not np.isfinite(observations).all():
        raise ValueError("finite non-empty actuals are required")
    if not forecasts:
        raise ValueError("E0 and at least zero challenger forecasts are required")
    checked: list[list[np.ndarray]] = []
    for model in forecasts:
        if len(model) != observations.size:
            raise ValueError("each model must forecast every actual")
        cases: list[np.ndarray] = []
        for samples in model:
            values = np.asarray(tuple(samples), dtype=np.float64)
            if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
                raise ValueError("empirical forecast samples must be finite and non-empty")
            cases.append(values)
        checked.append(cases)
    return checked, observations


def empirical_mixture_crps(
    forecasts: Sequence[Sequence[Iterable[float]]],
    actuals: Iterable[float],
    weights: Iterable[float],
) -> float:
    """Return mean exact CRPS, including cross-model sample distances."""
    checked, observations = _validated_inputs(forecasts, actuals)
    mixture_weights = np.asarray(tuple(weights), dtype=np.float64)
    if (mixture_weights.shape != (len(checked),)
            or not np.isfinite(mixture_weights).all()
            or np.any(mixture_weights < 0.0)
            or not np.isclose(mixture_weights.sum(), 1.0, atol=1e-10)):
        raise ValueError("weights must be finite, non-negative, and sum to one")

    scores: list[float] = []
    for case_index, actual in enumerate(observations):
        samples = [model[case_index] for model in checked]
        first = sum(
            mixture_weights[index] * np.mean(np.abs(values - actual))
            for index, values in enumerate(samples)
        )
        pairwise = 0.0
        for left, left_values in enumerate(samples):
            for right, right_values in enumerate(samples):
                pairwise += mixture_weights[left] * mixture_weights[right] * float(
                    np.mean(np.abs(left_values[:, None] - right_values[None, :]))
                )
        scores.append(float(first - 0.5 * pairwise))
    return float(np.mean(scores))


def optimize_empirical_mixture(
    forecasts: Sequence[Sequence[Iterable[float]]],
    actuals: Iterable[float],
    *,
    e0_floor: float = 0.0,
    improvement_tolerance: float = 1e-12,
) -> EmpiricalMixtureResult:
    """Fit simplex weights while retaining E0 and its configured floor."""
    checked, observations = _validated_inputs(forecasts, actuals)
    if not np.isfinite(e0_floor) or not 0.0 <= e0_floor <= 1.0:
        raise ValueError("e0_floor must be in [0, 1]")
    if improvement_tolerance < 0.0 or not np.isfinite(improvement_tolerance):
        raise ValueError("improvement_tolerance must be finite and non-negative")

    model_count = len(checked)
    e0_weights = np.zeros(model_count, dtype=np.float64)
    e0_weights[0] = 1.0
    e0_score = empirical_mixture_crps(checked, observations, e0_weights)
    challenger_scores = []
    for index in range(1, model_count):
        single = np.zeros(model_count, dtype=np.float64)
        single[index] = 1.0
        challenger_scores.append(empirical_mixture_crps(checked, observations, single))
    if not challenger_scores or min(challenger_scores) >= e0_score - improvement_tolerance:
        return EmpiricalMixtureResult(tuple(e0_weights), e0_score, True)

    initial = np.full(model_count, (1.0 - e0_floor) / model_count)
    initial[0] += e0_floor
    result = minimize(
        lambda candidate: empirical_mixture_crps(checked, observations, candidate),
        initial,
        method="SLSQP",
        bounds=[(e0_floor, 1.0)] + [(0.0, 1.0)] * (model_count - 1),
        constraints={"type": "eq", "fun": lambda candidate: candidate.sum() - 1.0},
        options={"ftol": 1e-12, "maxiter": 1000},
    )
    if not result.success:
        raise RuntimeError(f"empirical mixture optimization failed: {result.message}")
    weights = np.maximum(result.x, 0.0)
    weights[0] = min(1.0, max(weights[0], e0_floor))
    challenger_total = weights[1:].sum()
    if challenger_total == 0.0:
        weights[:] = 0.0
        weights[0] = 1.0
    else:
        weights[1:] *= (1.0 - weights[0]) / challenger_total
    exact = tuple(float(weight) for weight in weights)
    return EmpiricalMixtureResult(
        exact, empirical_mixture_crps(checked, observations, exact), False,
    )
