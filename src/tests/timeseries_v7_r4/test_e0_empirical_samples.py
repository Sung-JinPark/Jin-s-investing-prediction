from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r4.e0_empirical_samples import (
    E0_BLOCK_BOOTSTRAP_CONTRACT,
    E0SampleSet,
    EvaluationPath,
    empirical_crps,
    generate_e0_samples,
)


def test_one_sample_identity_is_bound_across_the_evaluation_path() -> None:
    samples = E0SampleSet.create(
        origin_session="2026-08-25",
        horizon_sessions=21,
        seed=17,
        values=[0.03, -0.02, 0.01, 0.04],
    )
    path = EvaluationPath.bind(samples)

    assert path.score(actual=0.01).sample_set_hash == samples.sample_set_hash
    assert path.stacking_input().sample_set_hash == samples.sample_set_hash
    assert path.calibration_input().sample_set_hash == samples.sample_set_hash
    assert path.forecast().sample_set_hash == samples.sample_set_hash

    other = E0SampleSet.create(
        origin_session="2026-08-25", horizon_sessions=21, seed=18,
        values=[0.03, -0.02, 0.01, 0.04],
    )
    with pytest.raises(ValueError, match="sample-set hash mismatch"):
        path.forecast(sample_set=other)


def test_empirical_distribution_cannot_be_reconstructed_from_quantiles() -> None:
    with pytest.raises(ValueError, match="quantiles cannot reconstruct"):
        E0SampleSet.from_quantiles(
            origin_session="2026-08-25", horizon_sessions=21,
            quantiles={0.1: -0.02, 0.5: 0.01, 0.9: 0.04},
        )


def test_e0_only_score_is_reproducible_from_exact_samples() -> None:
    first = E0SampleSet.create(
        origin_session="2026-08-25", horizon_sessions=63, seed=99,
        values=np.array([-0.08, -0.01, 0.02, 0.05, 0.12]),
    )
    replay = E0SampleSet.from_receipt(first.receipt())

    assert replay.sample_set_hash == first.sample_set_hash
    assert replay.values == first.values
    assert empirical_crps(replay.values, 0.03) == empirical_crps(first.values, 0.03)


def test_frozen_e0_block_bootstrap_is_coordinate_deterministic_and_pit_only() -> None:
    sessions = np.array([
        "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
        "2026-01-08", "2026-01-09",
    ])
    returns = np.array([0.01, -0.02, 0.03, 0.04, 99.0, 100.0])

    first = generate_e0_samples(
        origin_session="2026-01-08", horizon_sessions=2,
        sessions=sessions, one_session_returns=returns,
        sample_count=8, root_seed=41,
    )
    replay = generate_e0_samples(
        origin_session="2026-01-08", horizon_sessions=2,
        sessions=sessions, one_session_returns=returns,
        sample_count=8, root_seed=41,
    )

    assert E0_BLOCK_BOOTSTRAP_CONTRACT["algorithm"] == "historical_moving_block_bootstrap"
    assert first.receipt() == replay.receipt()
    assert len(first.values) == 8
    # The origin return and later observations are not available before forecast.
    assert max(first.values) < 1.0


def test_e0_generator_rejects_non_monotonic_or_insufficient_history() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        generate_e0_samples(
            origin_session="2026-01-08", horizon_sessions=2,
            sessions=["2026-01-02", "2026-01-02", "2026-01-03"],
            one_session_returns=[0.1, 0.2, 0.3], sample_count=4, root_seed=1,
        )
    with pytest.raises(ValueError, match="eligible history"):
        generate_e0_samples(
            origin_session="2026-01-03", horizon_sessions=2,
            sessions=["2026-01-02", "2026-01-03"],
            one_session_returns=[0.1, 0.2], sample_count=4, root_seed=1,
        )
