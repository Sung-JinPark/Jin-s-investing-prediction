from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r5.stacking_reassessment import (
    ar1_horizon_location,
    f_location_samples,
    fit_ar1,
    mixture_quantiles,
)


def test_f_delta_zero_is_byte_exact_e0() -> None:
    e0 = np.asarray([-0.1, 0.0, 0.2], dtype=np.float64)
    assert np.array_equal(f_location_samples(e0, forecast_location=99.0, delta=0.0), e0)


def test_ar1_fit_and_direct_horizon_location_are_finite() -> None:
    rng = np.random.default_rng(7)
    values = np.zeros(1000)
    for index in range(1, len(values)):
        values[index] = 0.001 + 0.4 * values[index - 1] + rng.normal(0, 0.01)
    intercept, phi = fit_ar1(values)
    assert intercept == pytest.approx(0.001, abs=0.002)
    assert phi == pytest.approx(0.4, abs=0.1)
    assert np.isfinite(ar1_horizon_location(values[-1], intercept=intercept, phi=phi, horizon=21))


def test_multimodel_mixture_quantiles_are_monotone() -> None:
    quantiles = mixture_quantiles(
        [np.asarray([-1.0, 0.0, 1.0]), np.asarray([-2.0, 0.0, 2.0])], [0.4, 0.6])
    assert len(quantiles) == 19
    assert all(left <= right for left, right in zip(quantiles, quantiles[1:]))


def test_f_delta_above_approved_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="preregistered"):
        f_location_samples([-1.0, 1.0], forecast_location=0.1, delta=0.25)
