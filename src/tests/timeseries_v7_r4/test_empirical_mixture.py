from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import OptimizeResult

import ai_fc.timeseries_v7_r4.empirical_mixture as mixture_module
from ai_fc.timeseries_v7_r4.empirical_mixture import (
    empirical_mixture_crps,
    optimize_empirical_mixture,
)


def test_objective_uses_cross_model_pairwise_sample_distances() -> None:
    forecasts = [[np.array([0.0])], [np.array([2.0])]]

    # E|X-y| is 1 for either model, while the mixture pairwise term is 0.5.
    assert empirical_mixture_crps(forecasts, [1.0], [0.5, 0.5]) == pytest.approx(0.5)


def test_optimizer_enforces_non_negative_weights_and_e0_floor() -> None:
    forecasts = [
        [np.array([0.0]), np.array([0.0])],
        [np.array([1.0]), np.array([1.0])],
    ]
    result = optimize_empirical_mixture(forecasts, [1.0, 1.0], e0_floor=0.3)

    assert result.weights[0] >= 0.3
    assert all(weight >= 0.0 for weight in result.weights)
    assert sum(result.weights) == pytest.approx(1.0)


def test_no_individually_better_challenger_selects_exact_e0_only() -> None:
    forecasts = [
        [np.array([0.0]), np.array([1.0])],
        [np.array([2.0]), np.array([3.0])],
        [np.array([-3.0]), np.array([-2.0])],
    ]
    result = optimize_empirical_mixture(forecasts, [0.0, 1.0], e0_floor=0.1)

    assert result.weights == (1.0, 0.0, 0.0)
    assert result.used_e0_only_fallback is True


def test_final_non_improving_solution_falls_back_to_exact_e0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forecasts = [
        [np.array([0.0]), np.array([0.0])],
        [np.array([1.0]), np.array([1.0])],
    ]

    monkeypatch.setattr(
        mixture_module,
        "minimize",
        lambda *args, **kwargs: OptimizeResult(success=True, x=np.array([1.0, 0.0])),
    )
    result = optimize_empirical_mixture(forecasts, [1.0, 1.0], e0_floor=0.1)

    assert result.weights == (1.0, 0.0)
    assert result.used_e0_only_fallback is True


def test_cross_distance_does_not_materialize_sample_cartesian_product() -> None:
    forecasts = [[np.arange(10_000.0)], [np.arange(10_000.0) + 1.0]]

    assert empirical_mixture_crps(forecasts, [0.0], [0.5, 0.5]) >= 0.0
