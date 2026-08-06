from ai_fc.era_analog import build_era_analog


def test_era_analog_is_log_normalized_and_reference_only() -> None:
    model = build_era_analog({
        "run_ts": "2099-01-02T00:00:00",
        "analog": {"asof": "2099-01-01", "closest_era": "dotcom", "distance": 0.2},
        "overlay": {"ai": [100, 200], "dotcom": [100, 1000]},
    })

    assert model["status"] == "ok"
    assert model["probability_space"] == "reference_only"
    series = {item["id"]: item for item in model["series"]}
    assert series["ai"]["log10_index"] == [0.0, 0.30103]
    assert series["dotcom"]["log10_index"] == [0.0, 1.0]
    assert series["ai"]["result_known"] is False
    assert series["dotcom"]["result_known"] is True
    assert series["dotcom"]["overlay_start"] == "1995-01"
    assert series["dotcom"]["model_anchor"] == "1996-01"
    assert series["dotcom"]["anchor_month"] == "1996-01"
    assert model["anchor_sensitivity"]["status"] == "not_computed"


def test_era_analog_empty_state_does_not_invent_curves() -> None:
    model = build_era_analog(None)
    assert model["status"] == "empty"
    assert model["series"] == []


def test_small_knn_forward_is_case_list_only_with_run_asof() -> None:
    model = build_era_analog({
        "run_ts": "2099-01-02T00:00:00",
        "analog": {
            "asof": "2099-01-01", "model_run_asof": "2098-12-20",
            "fwd_return_dist": {"n": 5},
            "forward_cases": [{"date": "1999-01-31", "fwd_1m": -0.1}],
        },
        "overlay": {"ai": [100, 101], "dotcom": [100, 102]},
    })
    assert model["run_asof"] == "2098-12-20"
    assert model["forward_reference"]["display_mode"] == "case_list"
    assert model["forward_reference"]["median_emphasis_allowed"] is False
    assert model["forward_reference"]["cases"][0]["date"] == "1999-01-31"
