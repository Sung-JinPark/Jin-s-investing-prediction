import pytest

from ai_fc.timeseries_v7_r4.g0_ablation import (
    frozen_evaluation_grid,
    generate_g0_ablation,
    replay_exact_e0_grid,
)


def test_frozen_grid_preserves_holiday_shortened_week_coordinates():
    score_rows = [
        {"origin_session": "2020-04-09", "horizon": 1},  # Good Friday closed
        {"origin_session": "2020-04-09", "horizon": 5},
        {"origin_session": "2020-04-17", "horizon": 1},
    ]

    grid = frozen_evaluation_grid(score_rows)

    assert grid["origins"] == ["2020-04-09", "2020-04-17"]
    assert grid["coordinates"] == [
        ("2020-04-09", 1), ("2020-04-09", 5), ("2020-04-17", 1),
    ]
    assert len(grid["origin_grid_hash"]) == 64
    assert len(grid["coordinate_grid_hash"]) == 64


def test_destructive_components_zeroed_and_qualification_runs_once():
    calls = []
    rows = [
        {"origin_session": "2020-03-02", "horizon": 1, "actual": .1,
         "baseline_crps": .04, "bad_crps": .08, "good_crps": .02},
        {"origin_session": "2020-03-09", "horizon": 1, "actual": -.1,
         "baseline_crps": .04, "bad_crps": .06, "good_crps": .03},
    ]

    report = generate_g0_ablation(
        rows, component_columns={"bad": "bad_crps", "good": "good_crps"},
        stress_windows={"pandemic": ("2020-03-01", "2020-03-31")},
        qualify=lambda: calls.append("qualified") or {"qualified": True},
    )

    assert calls == ["qualified"]
    assert report["component_ablations"]["bad"]["weight"] == 0.0
    assert report["component_ablations"]["good"]["weight"] > 0.0
    assert report["e0_only_skill"][0]["skill"] == pytest.approx(.6)
    assert report["e0_only_stress"][0]["suite"] == "pandemic"
    assert report["qualification_count"] == 1


def test_qualification_and_invalid_score_rows_fail_closed():
    with pytest.raises(ValueError, match="qualification"):
        generate_g0_ablation([], component_columns={}, stress_windows={},
                             qualify=lambda: {"qualified": False})


def test_replays_exact_e0_for_each_coordinate_and_preserves_stage_identity():
    labels = [
        {"target_id": "a", "origin_session": "2020-01-03", "horizon_sessions": 1,
         "label_end_session": "2020-01-06", "mature_at": "2020-01-06T21:00:00+00:00", "value": .01},
        {"target_id": "b", "origin_session": "2020-01-10", "horizon_sessions": 1,
         "label_end_session": "2020-01-13", "mature_at": "2020-01-13T21:00:00+00:00", "value": -.02},
    ]
    calls = []
    report = replay_exact_e0_grid(
        labels,
        evaluation_origins=["2020-01-10"],
        r4_snapshot_hash="a" * 64,
        qualify=lambda: calls.append(1) or {"qualified": True},
        five_role_validation_proof=True,
        component_scores={"bad": {("2020-01-10", 1): .03}},
        stress_windows={"period": ("2020-01-01", "2020-01-31")},
    )
    assert calls == [1]
    assert report["exact_replay_count"] == 1
    assert report["sample_identity_failures"] == 0
    assert report["approximate_baseline_rows_used"] == 0
    assert report["source"]["r4_snapshot_hash"] == "a" * 64
    assert report["component_ablations"]["bad"]["weight"] == 0.0
