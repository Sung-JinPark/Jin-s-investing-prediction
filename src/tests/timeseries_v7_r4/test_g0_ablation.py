import pytest

from ai_fc.timeseries_v7_r4.g0_ablation import generate_g0_ablation


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
