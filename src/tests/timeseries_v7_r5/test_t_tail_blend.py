from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r5.t_tail_blend import fit_student_df, t_tail_blend_samples


def test_pi_zero_is_byte_exact_e0() -> None:
    e0 = np.asarray([-0.2, -0.01, 0.03, 0.4], dtype=np.float64)
    result = t_tail_blend_samples(e0, sigma_hat=99.0, degrees_of_freedom=3.0, pi=0.0)
    assert np.array_equal(result, e0)


def test_positive_pi_preserves_center_and_changes_tail_shape() -> None:
    e0 = np.linspace(-1.0, 1.0, 100)
    result = t_tail_blend_samples(e0, sigma_hat=2.0, degrees_of_freedom=5.0, pi=0.3)
    assert np.mean(result) == pytest.approx(np.mean(e0), abs=1e-12)
    assert not np.array_equal(result, e0)
    assert np.all(np.diff(result) >= 0)


def test_df_fit_is_restricted_to_r4_s2_grid() -> None:
    rng = np.random.default_rng(20260827)
    result = fit_student_df(rng.standard_t(5.0, 5000) * np.sqrt(3.0 / 5.0))
    assert result in (3.0, 5.0, 8.0, 12.0)


def test_unregistered_pi_is_rejected() -> None:
    with pytest.raises(ValueError, match="preregistered"):
        t_tail_blend_samples([-1.0, 1.0], sigma_hat=1.0,
                             degrees_of_freedom=5.0, pi=0.11)
