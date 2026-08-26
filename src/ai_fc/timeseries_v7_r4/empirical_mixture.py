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


def _cross_absolute_distance(left: np.ndarray, right: np.ndarray) -> float:
    """Return mean |X-Y| without materializing the Cartesian product."""
    ordered = np.sort(right)
    cumulative = np.concatenate(([0.0], np.cumsum(ordered, dtype=np.float64)))
    positions = np.searchsorted(ordered, left, side="right")
    below = left * positions - cumulative[positions]
    above = (cumulative[-1] - cumulative[positions]) - left * (ordered.size - positions)
    return float(np.sum(below + above) / (left.size * ordered.size))


def _precompute_objective_terms(
    checked: Sequence[Sequence[np.ndarray]], observations: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    model_count = len(checked)
    first = np.zeros(model_count, dtype=np.float64)
    pairwise = np.zeros((model_count, model_count), dtype=np.float64)
    for case_index, actual in enumerate(observations):
        samples = [model[case_index] for model in checked]
        for index, values in enumerate(samples):
            first[index] += float(np.mean(np.abs(values - actual)))
        for left in range(model_count):
            for right in range(left, model_count):
                distance = _cross_absolute_distance(samples[left], samples[right])
                pairwise[left, right] += distance
                if left != right:
                    pairwise[right, left] += distance
    return first / observations.size, pairwise / observations.size


def _objective(first: np.ndarray, pairwise: np.ndarray, weights: np.ndarray) -> float:
    return float(weights @ first - 0.5 * weights @ pairwise @ weights)


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

    first, pairwise = _precompute_objective_terms(checked, observations)
    return _objective(first, pairwise, mixture_weights)


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
    first, pairwise = _precompute_objective_terms(checked, observations)
    e0_weights = np.zeros(model_count, dtype=np.float64)
    e0_weights[0] = 1.0
    e0_score = _objective(first, pairwise, e0_weights)
    challenger_scores = []
    for index in range(1, model_count):
        single = np.zeros(model_count, dtype=np.float64)
        single[index] = 1.0
        challenger_scores.append(_objective(first, pairwise, single))
    if not challenger_scores or min(challenger_scores) >= e0_score - improvement_tolerance:
        return EmpiricalMixtureResult(tuple(e0_weights), e0_score, True)

    initial = np.full(model_count, (1.0 - e0_floor) / model_count)
    initial[0] += e0_floor
    result = minimize(
        lambda candidate: _objective(first, pairwise, candidate),
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
    mixture_score = _objective(first, pairwise, weights)
    if mixture_score >= e0_score - improvement_tolerance:
        return EmpiricalMixtureResult(tuple(e0_weights), e0_score, True)
    return EmpiricalMixtureResult(exact, mixture_score, False)
