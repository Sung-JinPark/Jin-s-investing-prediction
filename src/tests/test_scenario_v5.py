"""Scenario V5 model-risk, PIT, probability, and display-contract tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from ai_fc.scenario_v5.artifact import CANDIDATE_RELATIVE, validate_candidate, verify_candidate
from ai_fc.scenario_v5.engine import reproduce_legacy_prior


ROOT = Path(__file__).parents[2]


def _candidate() -> dict:
    return json.loads((ROOT / CANDIDATE_RELATIVE).read_text(encoding="utf-8"))


def _snapshot() -> dict:
    return json.loads((ROOT / "data/scenarios/nasdaq_latest.json").read_text(encoding="utf-8"))


def test_candidate_contract_and_source_snapshot_hash() -> None:
    payload = _candidate()
    assert validate_candidate(payload)["ok"]
    result = verify_candidate(ROOT)
    assert result["ok"]
    assert result["source_snapshot_unchanged"]
    assert result["source_snapshot_current_sha256"] == payload["source_snapshot"]["sha256"]


def test_identity_is_honest_legacy_prior_not_rcfhs() -> None:
    identity = _candidate()["identity"]
    assert identity["candidate_id"] == "scenario_v5_evidence_conditioned_legacy_prior_v1"
    assert identity["prior_engine"] == "legacy_gbm_reproduced_extended_v2"
    assert identity["is_rcfhs"] is False
    assert "official" not in identity["promotion_state"].lower()


def test_prior_reproduces_snapshot_partition_exactly() -> None:
    snapshot = _snapshot()
    payload = _candidate()
    official_paths, _official_dates = reproduce_legacy_prior(snapshot)
    paths, dates = reproduce_legacy_prior(snapshot, n_paths=payload["prior"]["path_count"])
    assert np.array_equal(paths[:official_paths.shape[0]], official_paths)
    end = max(index for index, day in enumerate(dates)
              if day <= snapshot["model"]["classification_date"])
    hit = (paths[:, :end + 1] > snapshot["ath"]).any(axis=1)
    above = paths[:, end] > snapshot["reference_price"]
    counts = [int(hit.sum()), int((~hit & above).sum()), int((~hit & ~above).sum())]
    scenarios = payload["conditional_distribution"]["scenarios"]
    assert counts == [scenarios[key]["path_count"] for key in ("S1", "S2", "S3")]
    assert paths.shape == (payload["prior"]["path_count"], 252)


def test_evidence_is_point_in_time_and_probability_units_are_explicit() -> None:
    payload = _candidate()
    cutoff = datetime.fromisoformat(payload["knowledge_cutoff"])
    for row in payload["evidence_views"]:
        available = datetime.fromisoformat(row["available_at"])
        assert available.tzinfo is not None
        assert available <= cutoff
        assert row["source_sha256"]
        if row["unit"] == "fraction":
            assert 0 <= row["target"] <= 1


def test_only_registered_physical_views_are_numerical() -> None:
    rows = _candidate()["evidence_views"]
    numerical = [row for row in rows if row["used_numerically"]]
    blocked = [row for row in rows if not row["used_numerically"]]
    assert len(numerical) == 3
    assert {row["origin_type"] for row in numerical} == {"registered_forecast"}
    assert {row["probability_space"] for row in numerical} == {"physical_event"}
    assert blocked
    assert all(row["view_kind"] == "event_probability"
               or row["probability_space"] in {"risk_neutral_terminal", "reference_only"}
               for row in blocked)
    assert sum(row["view_kind"] == "event_probability"
               and row["origin_type"] == "registered_forecast" for row in blocked) == 3


def test_entropy_pooling_fit_and_concentration_gates() -> None:
    posterior = _candidate()["posterior_diagnostics"]
    assert posterior["converged"]
    assert posterior["gates_pass"]
    assert posterior["effective_sample_size"] >= 1000
    assert posterior["maximum_path_weight"] <= 0.005
    assert posterior["top_one_percent_weight_share"] <= 0.35
    assert abs(posterior["weight_sum"] - 1) < 1e-10
    assert all(abs(row["residual"]) <= row["tolerance"] for row in posterior["view_fit"])


def test_scenario_partition_and_conditional_bands() -> None:
    distribution = _candidate()["conditional_distribution"]
    scenarios = distribution["scenarios"]
    assert abs(sum(row["probability"] for row in scenarios.values()) - 1) < 1e-10
    assert sum(row["path_count"] for row in scenarios.values()) == _candidate()["prior"]["path_count"]
    assert len(distribution["dates"]) == 253
    for row in scenarios.values():
        columns = np.asarray([row["bands"][f"p{q}"] for q in (5, 10, 25, 50, 75, 90, 95)])
        assert columns.shape == (7, 253)
        assert (np.diff(columns, axis=0) >= 0).all()
        assert row["weighted_effective_sample_size"] >= 200


def test_representatives_are_actual_distinct_members() -> None:
    payload = _candidate()
    paths, _dates = reproduce_legacy_prior(
        _snapshot(), n_paths=payload["prior"]["path_count"])
    member_ids = []
    for row in payload["conditional_distribution"]["scenarios"].values():
        path_id = row["representative_path_id"]
        expected = np.concatenate(([payload["source_snapshot"]["anchor"]], paths[path_id]))
        assert np.allclose(expected, row["representative_path_values"], atol=0.005)
        assert row["representative_selection"]["member_path"] is True
        member_ids.append(path_id)
    assert len(set(member_ids)) == 3


def test_same_shape_gate_passes_with_non_degenerate_paths() -> None:
    diagnostics = _candidate()["conditional_distribution"]["same_shape_diagnostics"]
    assert diagnostics["gate_pass"]
    assert _candidate()["conditional_distribution"]["representative_lines_visible"]
    assert all(not row["same_shape_flag"] for row in diagnostics["pairs"])
    assert max(abs(row["weekly_return_correlation"]) for row in diagnostics["pairs"]) < 0.5


def test_unmapped_event_impacts_are_exactly_zero() -> None:
    states = _candidate()["event_states"]
    assert states
    assert all(row["price_jump"] == 0 for row in states)
    assert all(row["posterior_price_weighting"] is False for row in states)
    assert all(row["mapping_status"] == "blocked_no_approved_mapping" for row in states)
    mapped_states = [row for row in states if row["probability_views"]]
    assert {row["date"] for row in mapped_states} >= {
        "2026-08-07", "2026-08-26", "2026-10-28"
    }


def test_dashboard_contains_v5_default_and_hide_gate() -> None:
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    assert "scenarioV5FlowModel(officialScenario,v5)" in script
    assert "shadowScenario=DATA.scenario_v4_shadow" in script
    assert "v5.banner" in script
    assert "sc.representative_lines_visible===false?[]" in script
    assert "conditional weighted p50" in script
    assert "scenarioV5ConditionalFanMarkup(v5)" in script
    assert "scenarioV5EvidenceMarkup(v5)" in script
    assert "EVENT STATE ONLY" in script
    assert "visibility.p10_p90" in script
    assert "fan gated" in script
