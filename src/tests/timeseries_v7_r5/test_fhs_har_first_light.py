from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r5.fhs_har_first_light import (
    _mixture_quantiles,
    e1_fhs_samples,
    stationary_bootstrap_mean,
)


def test_e1_registered_degenerate_boundary_is_exact_e0() -> None:
    e0 = np.asarray([-0.2, 0.0, 0.3], dtype=np.float64)
    result = e1_fhs_samples(e0, center=99.0, sigma_hat=123.0,
                            standardized_residuals=[-7.0, 8.0], degenerate_to_e0=True)
    assert np.array_equal(result, e0)
    assert np.max(np.abs(result - e0)) == 0.0


def test_e1_standardized_residual_factorization() -> None:
    result = e1_fhs_samples([0.0], center=0.01, sigma_hat=0.02,
                            standardized_residuals=[-1.0, 0.0, 2.0])
    assert result == pytest.approx([-0.01, 0.01, 0.05])


def test_stationary_bootstrap_is_deterministic_and_finite() -> None:
    first = stationary_bootstrap_mean(np.linspace(-1, 1, 50), mean_block_length=10,
                                      replications=100, seed=7)
    second = stationary_bootstrap_mean(np.linspace(-1, 1, 50), mean_block_length=10,
                                       replications=100, seed=7)
    assert np.array_equal(first, second)
    assert np.isfinite(first).all()


def test_weighted_mixture_quantiles_are_monotone_and_respect_pure_endpoints() -> None:
    e0 = np.asarray([-2.0, 0.0, 2.0])
    e1 = np.asarray([10.0, 11.0, 12.0])
    mixed = _mixture_quantiles(e0, e1, (0.5, 0.5))
    pure = _mixture_quantiles(e0, e1, (1.0, 0.0))
    assert tuple(sorted(mixed)) == mixed
    assert min(pure) >= min(e0) and max(pure) <= max(e0)
