from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from ai_fc.market_context.contracts import MarketContextError
from ai_fc.market_context.model import horizon_basis
from ai_fc.market_context.training import evaluate_model, fit_model


def _samples(count=310, start="2015-01-05", effect=.0004):
    days = np.busday_offset(np.datetime64(start), np.arange(count)).astype(str)
    rng = np.random.default_rng(92)
    kernel = horizon_basis([5, 21, 63])[:, 0]
    result = []
    for index, day in enumerate(days):
        state = np.zeros(21)
        state[0] = rng.normal()
        baseline = (.0002 - .01 ** 2 / 2) * np.array([5, 21, 63])
        targets = baseline + state[0] * effect * kernel + rng.normal(0, .00004, 3)
        future = {str(h): str(np.busday_offset(np.datetime64(day), h)) for h in (5, 21, 63)}
        # Stable incident identities occur repeatedly in state snapshots and
        # must count once, never once per snapshot or per article revision.
        ids = [f"event-{i}" for i in range(min(40, index + 1))]
        result.append({"origin_date": day, "as_of": f"{day}T21:00:00+00:00",
                       "state": state.tolist(), "state_by_family": {"growth_surprise": state.tolist()},
                       "event_ids_by_family": {"growth_surprise": ids},
                       "baseline_mu": .0002, "baseline_sigma": .01,
                       "targets": {str(h): float(targets[j]) for j, h in enumerate((5, 21, 63))},
                       "target_available_at": {str(h): f"{future[str(h)]}T21:00:00+00:00" for h in (5, 21, 63)}})
    return result


def test_minimum_training_sessions_blocks_without_fabricated_fit():
    model = fit_model(_samples(40), train_cutoff="2020-01-01T00:00:00Z")
    assert model["status"] == "blocked"
    assert model["reason"] == "insufficient_matured_pit_sessions"
    assert model["coef"] == [0.] * 21
    assert model["predictive_validation"] == "not_established"


def test_event_floor_counts_unique_incidents_not_repeated_snapshots():
    samples = _samples(100)
    for row in samples:
        row["event_ids_by_family"] = {"growth_surprise": ["same-incident"]}
    model = fit_model(samples, train_cutoff="2020-01-01T00:00:00Z", minimum_sessions=80, bootstrap_count=0)
    assert model["status"] == "blocked"
    assert model["reason"] == "insufficient_unique_events_per_family"
    assert model["diagnostics"]["event_family_counts"] == {"growth_surprise": 1}


def test_ridge_recovers_known_drift_in_raw_units_and_purges_nested_folds():
    model = fit_model(_samples(), train_cutoff="2020-01-01T00:00:00Z", minimum_sessions=250, bootstrap_count=4)
    assert model["status"] == "ready"
    assert model["coef"][0] == pytest.approx(.0004, rel=.03)
    assert np.asarray(model["bootstrap_coefficients"]).shape == (4, 21)
    assert model["coefficient_units"] == "raw_feature"
    assert model["diagnostics"]["fit_intercept"] is False
    assert model["diagnostics"]["center_features"] is False
    for split in model["diagnostics"]["outer_splits"] + model["diagnostics"]["final_inner_splits"]:
        assert datetime.fromisoformat(split["last_train_target_at"]) < datetime.fromisoformat(split["first_validation_as_of"])
        for inner in split.get("inner_splits", []):
            assert datetime.fromisoformat(inner["last_train_target_at"]) < datetime.fromisoformat(inner["first_validation_as_of"])
    assert model == fit_model(_samples(), train_cutoff="2020-01-01T00:00:00Z", minimum_sessions=250, bootstrap_count=4)


def test_matured_label_filter_does_not_train_on_future_realizations():
    samples = _samples(100)
    result = fit_model(samples, train_cutoff=samples[70]["as_of"], minimum_sessions=60, bootstrap_count=0)
    assert result["status"] == "blocked"
    assert result["diagnostics"]["matured_sessions"] == 8
    assert result["diagnostics"]["excluded"]["unmatured_target"] > 0
    assert result["diagnostics"]["excluded"]["origin_after_train_cutoff"] == 29


def test_future_state_or_impossible_label_timestamp_rejected():
    samples = _samples(5)
    samples[0]["state_available_at"] = "2015-01-06T21:00:00+00:00"
    with pytest.raises(MarketContextError, match="future state"):
        fit_model(samples, train_cutoff="2020-01-01T00:00:00Z", minimum_sessions=2)
    samples = _samples(5)
    samples[0]["target_available_at"]["5"] = samples[0]["as_of"]
    with pytest.raises(MarketContextError, match="follow origin"):
        fit_model(samples, train_cutoff="2020-01-01T00:00:00Z", minimum_sessions=2)


def test_family_floor_is_applied_before_aggregate_and_rare_family_cannot_contaminate():
    samples = _samples(100)
    for row in samples:
        rare = np.zeros(21)
        rare[3] = 1e6
        row["state_by_family"]["rare_unsupported"] = rare.tolist()
        row["event_ids_by_family"]["rare_unsupported"] = ["rare1"]
    model = fit_model(samples, train_cutoff="2020-01-01T00:00:00Z", minimum_sessions=80, bootstrap_count=0)
    assert model["active_families"] == ["growth_surprise"]
    assert model["coef"][3] == 0.


def test_heldout_crps_rejects_training_overlap_and_reports_dependence_limit():
    training = _samples()
    cutoff = "2016-12-01T21:00:00+00:00"
    model = fit_model(training, train_cutoff=cutoff, minimum_sessions=250, bootstrap_count=0)
    with pytest.raises(MarketContextError, match="overlap"):
        evaluate_model(training, model, as_of="2020-01-01T00:00:00Z", bootstrap_count=20)
    heldout = _samples(40, start="2017-01-03")
    result = evaluate_model(heldout, model, as_of="2020-01-01T00:00:00Z", bootstrap_count=20)
    assert result["status"] == "research_criteria_not_met"
    assert result["by_horizon"]["21"]["candidate_crps"] < result["by_horizon"]["21"]["baseline_crps"]
    assert result["predictive_validation"] == "not_established"
    assert result["automatic_promotion"] is False
