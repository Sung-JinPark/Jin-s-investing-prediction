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
    assert model["anchor_sensitivity"]["status"] == "not_computed"


def test_era_analog_empty_state_does_not_invent_curves() -> None:
    model = build_era_analog(None)
    assert model["status"] == "empty"
    assert model["series"] == []
