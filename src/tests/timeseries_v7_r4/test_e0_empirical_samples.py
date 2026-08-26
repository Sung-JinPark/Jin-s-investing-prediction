from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r4.e0_empirical_samples import (
    E0_EXACT_EMPIRICAL_CONTRACT,
    E0SampleSet,
    EvaluationPath,
    empirical_crps,
    fit_exact_empirical_anchor,
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


def test_frozen_e0_is_exact_matured_direct_horizon_labels_and_pit_only() -> None:
    labels = [
        {"origin_session": "2025-11-03", "horizon_sessions": 21,
         "value": 0.01, "available_at": "2025-12-03T00:00:00Z"},
        {"origin_session": "2025-12-01", "horizon_sessions": 21,
         "value": -0.02, "available_at": "2026-01-02T00:00:00Z"},
        {"origin_session": "2025-12-01", "horizon_sessions": 63,
         "value": 99.0, "available_at": "2026-01-02T00:00:00Z"},
        {"origin_session": "2026-01-05", "horizon_sessions": 21,
         "value": 100.0, "available_at": "2026-02-04T00:00:00Z"},
    ]
    first = fit_exact_empirical_anchor(
        origin_session="2026-01-08", horizon_sessions=21, labels=labels,
    )
    replay = fit_exact_empirical_anchor(
        origin_session="2026-01-08", horizon_sessions=21, labels=reversed(labels),
    )

    assert E0_EXACT_EMPIRICAL_CONTRACT["algorithm"] == "exact_empirical_anchor"
    assert first.receipt() == replay.receipt()
    assert first.values == (0.01, -0.02)
    assert first.seed == 0


def test_exact_empirical_anchor_rejects_no_matured_labels() -> None:
    with pytest.raises(ValueError, match="matured direct-horizon"):
        fit_exact_empirical_anchor(
            origin_session="2026-01-03", horizon_sessions=21,
            labels=[{"origin_session": "2025-12-01", "horizon_sessions": 21,
                     "value": 0.1, "available_at": "2026-01-04T00:00:00Z"}],
        )
