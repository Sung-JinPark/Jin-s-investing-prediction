from __future__ import annotations

import copy

import numpy as np
import pytest

from ai_fc.market_context.contracts import MarketContextError
from ai_fc.market_context.evaluation import evaluate_resolutions, score_distribution, score_path_functionals


def _rows(count=40):
    dates = np.busday_offset(np.datetime64("2025-01-02"), np.arange(count))
    result = []
    for index, day in enumerate(dates):
        for horizon in (5, 21, 63):
            target = np.busday_offset(day, horizon)
            # Keep nominal average coverage so quality gates are independently
            # testable rather than hidden by an intentionally biased fixture.
            coverage50, coverage80 = index % 2 == 0, index % 5 != 0
            baseline = {"crps": 10., "wis": 11., "median_error": (-1.) ** index,
                        "coverage50": coverage50, "coverage80": coverage80}
            combined = {**baseline, "crps": 9., "wis": 10.}
            result.append({"forecast_id": f"forecast-{index}", "anchor_date": str(day),
                           "as_of": f"{day}T22:00:00Z", "horizon": horizon, "target_date": str(target),
                           "available_at": f"{target}T23:00:00Z", "data_grade": "captured_forward",
                           "scores": {"baseline": baseline, "combined": combined,
                                      "market_only": baseline, "event_only": baseline, "fhs": None}})
    return result


def test_empirical_crps_matches_direct_pairwise_definition_including_parameter_mixture():
    # A bimodal mixture must be scored as its actual draws, not reduced to one
    # fitted Gaussian with the same first two moments.
    values = np.array([80., 81., 120., 121.])
    actual = 104.
    expected = np.abs(values - actual).mean() - .5 * np.abs(values[:, None] - values[None, :]).mean()
    result = score_distribution(values, actual)
    assert result["crps"] == pytest.approx(expected)
    assert result["median_error"] == -3.5
    assert result["sample_count"] == 4
    assert result["wis"] > 0


def test_pointmass_scores_and_interval_coverage_have_known_values():
    result = score_distribution([100.] * 20, 105.)
    assert result["crps"] == 5.
    assert result["wis"] == 5.
    assert result["coverage50"] is False
    assert result["coverage80"] is False
    assert score_distribution([100.], 100.)["crps"] == 0
    with pytest.raises(MarketContextError, match="finite"):
        score_distribution([100., np.nan], 105.)


def test_path_functionals_use_daily_drawdown_and_fixed_barrier_not_terminal_price():
    paths = np.array([[89., 110.], [105., 110.]])
    result = score_path_functionals(paths, [88., 111.], anchor=100.)
    assert result["touch_probability"] == .5
    assert result["touch_outcome"] is True
    assert result["touch_brier"] == .25
    assert result["actual_max_drawdown_magnitude"] == pytest.approx(.12)
    assert result["max_drawdown"]["crps"] > 0
    assert result["probability_unit"] == "fraction"


def test_weekend_repeat_origin_chooses_earliest_issue_for_all_horizons():
    rows = _rows(40)
    repeated = []
    for original in rows:
        duplicate = copy.deepcopy(original)
        duplicate["forecast_id"] += "-weekend"
        duplicate["as_of"] = duplicate["as_of"].replace("22:00", "23:00")
        duplicate["scores"]["combined"]["crps"] = 1.
        repeated.append(duplicate)
    result = evaluate_resolutions(rows + repeated, bootstrap_count=20)
    assert result["unique_origin_count"] == 40
    assert result["comparisons"]["combined"]["21"]["origin_count"] == 40
    assert result["comparisons"]["combined"]["21"]["candidate_crps"] == 9.
    assert result["excluded"]["later_issuance_same_anchor"] == 120
    assert result["status"] == "insufficient_data"
    assert result["comparison_gaps"]["fhs"] == ["5", "21", "63"]


def test_conflicting_duplicate_resolution_and_retrospective_rows_do_not_enter_score():
    rows = _rows(1)
    altered = copy.deepcopy(rows[0])
    altered["scores"]["combined"]["crps"] = .1
    with pytest.raises(MarketContextError, match="conflicting duplicate"):
        evaluate_resolutions(rows + [altered], bootstrap_count=20)
    for row in rows:
        row["data_grade"] = "latest_reconstructed"
    result = evaluate_resolutions(rows, bootstrap_count=20)
    assert result["unique_origin_count"] == 0
    assert result["excluded"]["not_captured_forward"] == 3


def test_primary_threshold_can_pass_before63_sample_gate_when63_not_promotion_basis():
    rows = _rows(252)
    result = evaluate_resolutions(rows, bootstrap_count=20)
    assert result["comparisons"]["combined"]["21"]["nonoverlapping_blocks"] == 12
    assert result["status"] == "research_criteria_met"
    assert result["automatic_promotion"] is False
    assert result["predictive_validation"] == "not_established"
    assert result["complete_comparison_set"] is False  # MissingFHS remains explicit.
    stricter = evaluate_resolutions(rows, bootstrap_count=20, use_63_for_promotion=True)
    assert stricter["status"] == "insufficient_data"
    assert "fewer_than8_nonoverlapping63_session_blocks" in stricter["reasons"]


def test_secondary_deterioration_and_coverage_failure_block_research_criteria():
    rows = _rows(252)
    for row in rows:
        if row["horizon"] == 5:
            row["scores"]["combined"]["crps"] = 10.3
        if row["horizon"] == 21:
            row["scores"]["combined"]["coverage80"] = False
    result = evaluate_resolutions(rows, bootstrap_count=20)
    assert result["status"] == "research_criteria_not_met"
    assert "secondary5_missing_or_more_than2percent_worse" in result["reasons"]
    assert "primary_coverage_diagnostic_failure" in result["reasons"]


def test_grouped_confidence_interval_is_deterministic_and_not_horizon_row_count():
    rows = _rows(252)
    first = evaluate_resolutions(rows, bootstrap_count=30)
    assert first == evaluate_resolutions(list(reversed(rows)), bootstrap_count=30)
    primary = first["comparisons"]["combined"]["21"]
    assert primary["origin_count"] == 252
    assert primary["one_sided95_delta_crps_upper"] == -1.
    assert primary["bootstrap_block_sessions"] == 63
