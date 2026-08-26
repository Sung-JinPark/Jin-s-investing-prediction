import pytest

from ai_fc.timeseries_v7_r4.probability_up_calibration import (
    ProbabilityCase,
    authoritative_temporal_cross_fit,
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


def test_authoritative_temporal_cross_fit_uses_only_earlier_calibration_origins():
    origins = [f"2020-01-{day:02d}" for day in range(1, 9)]
    export = {
        "source_store": "authoritative_postgresql",
        "five_role_plan": {
            "role_origins": {"calibration": origins, "outer": ["2020-02-01"]},
            "role_hashes": {"calibration": "calibration-hash", "outer": "outer-hash"},
        },
        "labels": [{"origin_session": "2019-12-31", "horizon_sessions": 1,
                    "mature_at": "2019-12-31", "value": -.01}] + [
            {"origin_session": origin, "horizon_sessions": 1,
             "mature_at": origin, "value": (-1 if index % 3 == 0 else 1) * .01}
            for index, origin in enumerate(origins)
        ],
    }

    family = authoritative_temporal_cross_fit(export, 1, minimum_train_size=4)

    assert family["calibration_role_origin_count"] == 8
    assert family["fit_role"] == "calibration_temporal_cross_fit"
    assert family["evaluation_role"] == "calibration_cross_fit_holdout"
    assert family["evaluation_rows"] == 4
    assert family["future_training_rows_used"] is False
    assert family["probability_unit"] == "fraction"
    assert family["probability_bounds"] == "PASS"
    assert family["row_use_counters"]["outer_rows_used"] == 0
    assert family["row_use_counters"]["qualification_score_rows_used"] == 0
    assert family["report"]["base_rate_brier"] >= 0
    assert family["report"]["direction"]["balanced_brier"] >= 0
