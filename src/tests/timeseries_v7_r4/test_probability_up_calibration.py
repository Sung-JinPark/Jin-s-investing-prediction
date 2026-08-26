import pytest

from ai_fc.timeseries_v7_r4.probability_up_calibration import (
    ProbabilityCase,
    authoritative_calibration_cases,
    evaluate_probability_calibration,
    fit_probability_calibrator,
)


def _case(case_id, role, probability, actual):
    return ProbabilityCase(case_id, role, probability, actual)


def test_zero_threshold_calibration_uses_disjoint_evidence_and_reports_diagnostics():
    calibration = [
        _case("c1", "calibration", .1, -1),
        _case("c2", "calibration", .2, -1),
        _case("c3", "calibration", .8, 1),
        _case("c4", "calibration", .9, 1),
    ]
    evaluation = [
        _case("e1", "evaluation", .15, -2),
        _case("e2", "evaluation", .25, 0),  # zero is not up
        _case("e3", "evaluation", .75, 2),
        _case("e4", "evaluation", .85, 1),
    ]
    fitted = fit_probability_calibrator(calibration)
    report = evaluate_probability_calibration(fitted, evaluation, reliability_bins=2)

    assert report.calibration_case_ids == ("c1", "c2", "c3", "c4")
    assert report.evaluation_case_ids == ("e1", "e2", "e3", "e4")
    assert report.brier <= report.base_rate_brier
    assert sum(item.count for item in report.reliability_curve) == 4
    assert report.direction.positive_count == report.direction.negative_count == 2
    assert report.direction.balanced_brier >= 0


def test_probability_calibration_fails_closed_on_roles_overlap_and_units():
    with pytest.raises(ValueError, match="calibration role"):
        fit_probability_calibrator([_case("x", "evaluation", .5, 1)])
    fitted = fit_probability_calibrator([
        _case("c1", "calibration", .2, -1),
        _case("c2", "calibration", .8, 1),
    ])
    with pytest.raises(ValueError, match="evaluation role"):
        evaluate_probability_calibration(fitted, [_case("e", "prospective", .5, 1)])
    with pytest.raises(ValueError, match="disjoint"):
        evaluate_probability_calibration(fitted, [_case("c1", "evaluation", .5, 1)])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        fit_probability_calibrator([_case("bad", "calibration", 50, 1)])


def test_authoritative_cases_use_fixed_calibration_role_and_pit_history_only():
    export = {
        "source_store": "authoritative_postgresql",
        "snapshot_hash": "snapshot",
        "five_role_plan": {
            "role_origins": {"train": ["2020-01-01"], "selection": [], "stacking": [],
                             "calibration": ["2020-01-06"], "outer": ["2020-01-07"]},
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
        ],
    }

    cases, receipt = authoritative_calibration_cases(export, 1)

    assert [case.case_id for case in cases] == ["h1:2020-01-06"]
    assert cases[0].probability_up == pytest.approx(.5)
    assert receipt["role_hashes"]["calibration"] == "calibration-hash"
    assert receipt["row_use_counters"] == {
        "calibration_fit_rows": 1, "train_fit_rows": 0, "selection_fit_rows": 0,
        "stacking_fit_rows": 0, "outer_rows_used": 0,
        "legacy_review_pack_score_rows_used": 0, "qualification_score_rows_used": 0,
    }
