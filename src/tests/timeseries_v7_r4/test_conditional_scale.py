import pytest

from ai_fc.timeseries_v7_r4.conditional_scale import (
    ScaleCase,
    authoritative_calibration_cases,
    build_source_receipt,
    fit_conditional_scale,
)


def _case(case_id, state, central, actual, width):
    return ScaleCase(case_id, "calibration", state, central, actual, width)


def test_scale_varies_by_ex_ante_state_and_intervals_are_nested():
    rows = []
    for index in range(40):
        state = "normal" if index < 20 else "stress"
        shock = (1 if index % 2 else -1) * (.01 if state == "normal" else .04)
        rows.append(_case(str(index), state, .002, .002 + shock, .04))

    fitted = fit_conditional_scale(rows)
    normal = fitted.states["normal"]
    stress = fitted.states["stress"]

    assert stress.volatility_scale > normal.volatility_scale
    assert normal.central_scale == pytest.approx(stress.central_scale)
    assert normal.half_width_50 <= normal.half_width_80 <= normal.half_width_90
    assert stress.half_width_50 <= stress.half_width_80 <= stress.half_width_90


def test_fit_fails_closed_on_role_state_width_and_duplicate_identity():
    valid = _case("a", "normal", 0.0, .01, .02)
    with pytest.raises(ValueError, match="calibration role"):
        fit_conditional_scale([ScaleCase("x", "evaluation", "normal", 0, 0, .1)])
    with pytest.raises(ValueError, match="ex-ante state"):
        fit_conditional_scale([ScaleCase("x", "calibration", "", 0, 0, .1)])
    with pytest.raises(ValueError, match="positive"):
        fit_conditional_scale([ScaleCase("x", "calibration", "normal", 0, 0, 0)])
    with pytest.raises(ValueError, match="unique"):
        fit_conditional_scale([valid, valid])


def test_authoritative_cases_use_only_fixed_calibration_role():
    export = {
        "source_store": "authoritative_postgresql",
        "snapshot_hash": "snapshot",
        "five_role_plan": {
            "role_origins": {
                "train": ["2020-01-01"], "selection": ["2020-01-02"],
                "stacking": ["2020-01-03"], "calibration": ["2020-01-06"],
                "outer": ["2020-01-07"],
            },
            "role_hashes": {role: role + "-hash" for role in
                            ("train", "selection", "stacking", "calibration", "outer")},
        },
        "labels": [
            {"origin_session": "2019-12-30", "horizon_sessions": 1,
             "mature_at": "2019-12-31", "value": -.02},
            {"origin_session": "2020-01-01", "horizon_sessions": 1,
             "mature_at": "2020-01-02", "value": .01},
            {"origin_session": "2020-01-06", "horizon_sessions": 1,
             "mature_at": "2020-01-07", "value": .03},
            {"origin_session": "2020-01-07", "horizon_sessions": 1,
             "mature_at": "2020-01-08", "value": .04},
        ],
    }

    cases, receipt = authoritative_calibration_cases(export, 1)

    assert [case.case_id for case in cases] == ["h1:2020-01-06"]
    assert receipt["role_hashes"]["calibration"] == "calibration-hash"
    assert receipt["row_use_counters"] == {
        "calibration_fit_rows": 1,
        "train_fit_rows": 0,
        "selection_fit_rows": 0,
        "stacking_fit_rows": 0,
        "outer_rows_used": 0,
        "legacy_review_pack_score_rows_used": 0,
        "qualification_score_rows_used": 0,
    }


def test_corrected_receipt_binds_fixed_sources_and_zero_diagnostic_rows():
    source = build_source_receipt("snapshot", "g2", "calibration")

    assert source == {
        "r4_snapshot_hash": "snapshot",
        "g2_artifact_sha256": "g2",
        "calibration_role_hash": "calibration",
        "legacy_review_pack_score_rows_used": 0,
        "qualification_score_rows_used": 0,
        "outer_rows_used": 0,
        "outer_origin_intersection": 0,
    }
