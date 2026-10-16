from __future__ import annotations

import numpy as np
import pytest

from ai_fc.market_context.contracts import AXES, MarketContextError
from ai_fc.market_context.model import horizon_basis, project_paths, score_state, summarize_paths
from ai_fc.quant.mc import gbm_paths


def _sessions(count=252, start="2026-10-15"):
    return np.busday_offset(np.datetime64(start), np.arange(1, count + 1)).astype(str).tolist()


def _closes():
    return (100 * np.exp(np.cumsum(np.random.default_rng(9).normal(.0003, .01, 300)))).tolist()


def _event(**changes):
    return {"event_id": "incident1", "revision_id": "revision1", "family": "cpi_surprise",
            "axis": "inflation", "surprise_z": 2.0, "available_at": "2026-10-01T12:30:00Z",
            "effective_session": "2026-10-01", "numerical_eligible": True, **changes}


def test_score_uses_session_age_and_masks_unsupported_family_before_aggregation():
    days = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]
    reference = _event(revision_id="ref", event_id="ref", family="unsupported")
    result = score_state([_event(), reference], as_of="2026-10-08T21:00:00Z",
                         session_dates=days, eligible_families={"cpi_surprise"})
    offset = AXES.index("inflation") * 3
    assert result["numerical_vector"][offset] == pytest.approx(1.0)
    assert result["reference_vector"][offset] == pytest.approx(2.0)
    assert result["events"][0]["age_sessions"] == 5
    assert result["coverage"]["numerical_event_count"] == 1
    assert result["event_ids_by_family"]["cpi_surprise"] == ["incident1"]
    assert "unsupported" in result["state_by_family"]  # kept for later family-gated training


def test_missing_surprise_is_audited_and_known_afterclose_news_has_age_zero():
    result = score_state([_event(surprise_z=None), _event(revision_id="after", effective_session="2026-10-02")],
                         as_of="2026-10-01T23:00:00Z", session_dates=["2026-10-01"],
                         eligible_families={"cpi_surprise"})
    assert result["numerical_vector"][3:6] == [2.0] * 3
    assert result["coverage"]["missing_surprise_count"] == 1
    assert result["events"][0]["exclusion_reason"] == "missing_validated_surprise"
    assert result["events"][1]["age_sessions"] == 0
    assert result["events"][1]["used_numerically"] is True


def test_future_event_and_duplicate_revision_rejected():
    with pytest.raises(MarketContextError, match="future event"):
        score_state([_event(available_at="2026-10-02T12:30:00Z")],
                    as_of="2026-10-01T21:00:00Z", session_dates=["2026-10-01"])
    with pytest.raises(MarketContextError, match="unique revision"):
        score_state([_event(), _event()], as_of="2026-10-01T21:00:00Z", session_dates=["2026-10-01"])


def test_zero_context_is_exact_unchanged_gbm_even_with_parameter_draws():
    closes, days = _closes(), _sessions()
    artifact = {"status": "ready", "coef": [.01] * 21, "scale": [2.] * 21,
                "bootstrap_coefficients": [[.02] * 21, [.03] * 21]}
    result = project_paths(closes, state=[0.] * 21, coefficients=artifact, future_dates=days, n_paths=100)
    original = gbm_paths(closes, lookback=252, horizon=252, n=100, seed=42)
    assert np.array_equal(result["baseline_paths"], original)
    assert np.array_equal(result["candidate_paths"], original)
    assert result["numerical_context_applied"] is False


def test_location_shift_uses_raw_coefficients_once_and_caps_extra_drift_at63():
    state, coef = [0.] * 21, [0.] * 21
    state[0], coef[0] = 2., .0004
    result = project_paths(_closes(), state=state, coefficients={"coef": coef, "scale": [10.] * 21},
                           future_dates=_sessions(), n_paths=30)
    delta = np.asarray(result["delta_log"])
    assert delta[20] == pytest.approx(2 * .0004 * horizon_basis([21])[0, 0])
    assert np.all(delta[62:] == delta[62])
    assert np.allclose(np.log(result["candidate_paths"] / result["baseline_paths"]), delta[None, :])
    assert result["attribution"]["growth"]["21"] == pytest.approx(delta[20])
    assert result["attribution_basis"]["growth"] == [2 * .0004, 0., 0.]
    reconstructed = horizon_basis(np.arange(1, 253)) @ np.concatenate(
        [result["attribution_basis"][axis] for axis in result["attribution_basis"]])
    assert np.array_equal(reconstructed, delta)


def test_parameter_uncertainty_keeps_one_coefficient_draw_per_entire_path():
    state, coef = [0.] * 21, [0.] * 21
    state[0], coef[0] = 1., .001
    draws = np.zeros((2, 21))
    draws[:, 0] = [.0005, .0015]
    result = project_paths(_closes(), state=state, coefficients={"coef": coef,
                           "bootstrap_coefficients": draws.tolist()}, future_dates=_sessions(), n_paths=40)
    shifts = np.log(result["candidate_paths"] / result["baseline_paths"])
    implied = shifts / horizon_basis(np.arange(1, 253))[:, 0]
    assert np.allclose(implied, implied[:, :1])
    assert len(np.unique(np.round(implied[:, 0], 10))) == 2
    assert result["parameter_uncertainty_applied"] is True


def test_probability_is_paired_daily_not_change_in_median_and_ties_are_separate():
    paths = np.array([[100., 101.], [99., 99.], [110., 109.]])
    result = summarize_paths(paths, anchor=100., future_dates=["2026-10-16", "2026-10-19"])
    day = result["daily"][1]
    assert day["probability_up_from_previous"] == pytest.approx(1 / 3)
    assert day["probability_down_from_previous"] == pytest.approx(1 / 3)
    assert day["index_quantiles"]["p50"] == 101.
    assert result["diagnostics"]["probability_unit"] == "fraction"


def test_representative_is_full_real_draw_with_typical_roughness_and_no_relaxation():
    paths = gbm_paths(_closes(), lookback=252, horizon=252, n=4000, seed=42)
    result = summarize_paths(paths, anchor=_closes()[-1], future_dates=_sessions(), baseline_paths=paths)
    selected = result["representative"]
    assert selected["status"] == "ok"
    assert selected["values"] == [_closes()[-1], *paths[selected["path_id"]].tolist()]
    assert len(selected["values"]) == 253
    assert selected["selection_relaxed"] is False
    assert .25 <= selected["metric_percentile_ranks"][2] <= .75
    assert not np.all(np.diff(selected["values"]) >= 0)
    assert result["diagnostics"]["exact_baseline_identity"] is True
    assert summarize_paths(paths, anchor=_closes()[-1], future_dates=_sessions())["representative"] == selected


def test_invalid_paths_and_nonfinite_coefficient_are_rejected_without_clipping():
    with pytest.raises(MarketContextError, match="finite positive"):
        summarize_paths(np.array([[0.]]), anchor=100, future_dates=["2026-10-16"])
    with pytest.raises(MarketContextError, match="finite number"):
        project_paths(_closes(), state=[0.] * 21, coefficients={"coef": [float("nan")] * 21},
                      future_dates=_sessions(), n_paths=10)


def test_signed_drawdown_is_instantaneous_pathwise_and_recovers_at_new_high():
    paths = np.array([[90., 110.], [80., 90.], [120., 110.]])
    result = summarize_paths(paths, anchor=100., future_dates=["2026-10-16", "2026-10-19"])
    # Second date pathwise drawdowns are0, -10%, and -8.333%, respectively.
    assert result["records"][1]["drawdown_quantiles"]["p50"] == pytest.approx(110 / 120 - 1)
    # Historical maximum does not disappear when the first path recovers.
    assert result["records"][1]["max_drawdown_magnitude_quantiles"]["p50"] == pytest.approx(.1)
    assert result["records"][1]["drawdown_quantiles"]["p95"] <= 0


def test_single_eligible_realization_is_selected_but_empty_intersection_is_not_relaxed():
    one = np.array([[99., 101.]])
    result = summarize_paths(one, anchor=100., future_dates=["2026-10-16", "2026-10-19"])
    assert result["representative"]["status"] == "ok"
    assert result["representative"]["values"] == [100., 99., 101.]
    two = np.array([[99., 101.], [101., 99.]])
    missing = summarize_paths(two, anchor=100., future_dates=["2026-10-16", "2026-10-19"])
    assert missing["representative"]["status"] == "unavailable"
    assert missing["representative"]["reason"] == "no_jointly_typical_paths"
    assert missing["representative"]["selection_relaxed"] is False
