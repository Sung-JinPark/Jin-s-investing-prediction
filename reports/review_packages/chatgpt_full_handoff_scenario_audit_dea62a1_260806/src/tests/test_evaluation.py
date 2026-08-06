from __future__ import annotations

import numpy as np
import pytest

from ai_fc.evaluation import (
    brier_score, clustered_bootstrap_mean, crps_ensemble, expanding_walk_forward,
    interval_diagnostics, log_score, pinball_loss, run_baseline_suite,
)


def test_reference_scores_and_intervals() -> None:
    assert brier_score([0.0, 1.0], [0, 1]) == 0.0
    assert log_score([0.1, 0.9], [0, 1]) < log_score([0.4, 0.6], [0, 1])
    assert pinball_loss([0, 2], [1, 1], 0.5) == pytest.approx(0.5)
    assert crps_ensemble([0], np.asarray([[-1, 1]], dtype=float)) == pytest.approx(0.5)
    assert interval_diagnostics([1, 3], [0, 0], [2, 2]) == {"coverage": 0.5, "mean_width": 2.0}


def test_walk_forward_purge_prevents_overlap() -> None:
    splits = expanding_walk_forward(30, min_train=10, test_size=5, purge=3, embargo=2)
    assert splits
    assert all(max(split.train) + 3 < min(split.test) for split in splits)


def test_six_baselines_are_deterministic() -> None:
    closes = (100 * np.exp(np.linspace(0, .2, 300))).tolist()
    one = run_baseline_suite(closes, horizon=10, n_paths=50, seed=7, event_outcomes=[0, 1])
    two = run_baseline_suite(closes, horizon=10, n_paths=50, seed=7, event_outcomes=[0, 1])
    assert set(one) == {"bl.rw_drift", "bl.uncond_base", "bl.seasonal_base",
                        "bl.hist_sim", "bl.block_boot", "bl.gbm_v1"}
    for key in ("bl.rw_drift", "bl.hist_sim", "bl.block_boot", "bl.gbm_v1"):
        assert np.array_equal(one[key]["paths"], two[key]["paths"])
    assert clustered_bootstrap_mean([0.1, 0.2], n_boot=100, seed=1)["n_unique"] == 2
