from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r5.e0_rescale import rescale_e0_samples


def test_lambda_zero_is_byte_exact_e0() -> None:
    e0 = np.asarray([-0.3, 0.1, 0.2], dtype=np.float64)
    result = rescale_e0_samples(e0, sigma_hat=99.0, exponent=0.0)
    assert np.array_equal(result, e0)


def test_lambda_one_replaces_e0_scale_and_preserves_center() -> None:
    e0 = np.asarray([-1.0, 0.0, 1.0], dtype=np.float64)
    result = rescale_e0_samples(e0, sigma_hat=2.0, exponent=1.0)
    assert np.mean(result) == pytest.approx(np.mean(e0))
    assert np.std(result, ddof=1) == pytest.approx(2.0)


def test_unregistered_lambda_is_rejected() -> None:
    with pytest.raises(ValueError, match="preregistered"):
        rescale_e0_samples([-1.0, 1.0], sigma_hat=1.0, exponent=0.1)
