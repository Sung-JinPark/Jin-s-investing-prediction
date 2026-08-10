"""Scenario V5.1 time, circularity, artifact, timing, and display gates."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ai_fc.scenario_v5.contracts import canonical_hash
from ai_fc.scenario_v5.hardening import (
    CANDIDATE_RELATIVE,
    _build_receipt_content,
    _model_content,
    apply_dependency_cap,
    load_current_candidate,
    validate_approved_report_view,
    validate_candidate_v5_1,
)


ROOT = Path(__file__).parents[2]


def _candidate() -> dict:
    return json.loads((ROOT / CANDIDATE_RELATIVE).read_text(encoding="utf-8"))


def _rehash(payload: dict) -> dict:
    payload["model_content_sha256"] = canonical_hash(_model_content(payload))
    payload["build_receipt"]["model_content_sha256"] = payload["model_content_sha256"]
    payload["build_receipt_sha256"] = canonical_hash(
        _build_receipt_content(payload["build_receipt"]))
    return payload


def test_v5_1_candidate_is_strict_and_source_exact() -> None:
    candidate = _candidate()
    assert all(
        row["view_id"] != "human_model_risk:dotcom_upside_no_repeat_correction_260810"
        for row in candidate["evidence_views"]
    )
    result = validate_candidate_v5_1(candidate, ROOT)
    assert result["ok"], result["errors"]


def test_no_hardcoded_aug4_horizon_and_started_window_is_blocked() -> None:
    source = (ROOT / "src/ai_fc/scenario_v5/evidence.py").read_text(encoding="utf-8")
    assert '"horizon_start": "2026-08-04"' not in source
    rows = [row for row in _candidate()["evidence_views"]
            if row.get("question_id") == "nasdaq-corr10-augoct-2026"
            and row.get("origin_type") == "registered_forecast"]
    assert len(rows) == 1
    row = rows[0]
    assert row["original_horizon_start"] == "2026-08-01"
    assert row["time_alignment_status"] == "BLOCKED_NEEDS_REFORECAST"
    assert row["transport_validated"] is False
    assert row["used_numerically"] is False
    assert row["state_drift"]["gate_pass"] is False
    assert math.isclose(row["state_drift"]["spot_to_barrier_distance_at_forecast"], -.0445031081, abs_tol=1e-8)
    assert math.isclose(row["state_drift"]["spot_to_barrier_distance_at_candidate"], -.0745336995, abs_tol=1e-8)


def test_started_unconditional_and_unvalidated_survival_views_fail() -> None:
    payload = _candidate()
    row = next(row for row in payload["evidence_views"]
               if row.get("time_alignment_status") == "BLOCKED_NEEDS_REFORECAST")
    row["used_numerically"] = True
    result = validate_candidate_v5_1(_rehash(payload))
    assert not result["ok"]
    assert any("non-current view used" in error for error in result["errors"])
    row["time_alignment_status"] = "SURVIVAL_CONDITIONED"
    result = validate_candidate_v5_1(_rehash(payload))
    assert not result["ok"]
    assert any("unvalidated transported" in error for error in result["errors"])


def test_endogenous_ancestor_views_are_reference_only_and_fail_if_used() -> None:
    payload = _candidate()
    rows = [row for row in payload["evidence_views"]
            if row.get("numerical_status") == "REFERENCE_ONLY_ENDOGENOUS"]
    assert {row.get("question_id") for row in rows} >= {
        "nasdaq-ath-eoy-2026", "nasdaq-eoy-above-jul9-2026"}
    assert all(not row["used_numerically"] for row in rows)
    rows[0]["used_numerically"] = True
    result = validate_candidate_v5_1(_rehash(payload))
    assert not result["ok"]
    assert any("circular" in error for error in result["errors"])


def test_dependency_dedup_and_cluster_cap_are_solver_inputs() -> None:
    base = {
        "origin_release_id": "release", "dependency_cluster_id": "shared",
        "target_asset": "^IXIC", "horizon_end": "2026-12-31",
        "view_kind": "terminal_probability", "quality": {"effective_strength": 0.30},
    }
    a = {**deepcopy(base), "view_id": "a"}
    duplicate = {**deepcopy(base), "view_id": "a-requoted"}
    independent = {**deepcopy(base), "view_id": "b", "origin_release_id": "release-2"}
    rows, diagnostics = apply_dependency_cap([a, duplicate, independent], cluster_cap=.35)
    assert len(rows) == 2
    assert diagnostics["duplicates_removed"] == ["a"]
    assert math.isclose(sum(row["quality"]["effective_strength"] for row in rows), .35)
    assert diagnostics["clusters"][0]["cap_binding"] is True


def test_strict_validator_numeric_date_quantile_length_and_member_mutations() -> None:
    mutations = []
    p = _candidate(); p["conditional_distribution"]["scenarios"]["S1"]["probability"] = True; mutations.append((p, "non-boolean"))
    p = _candidate(); p["conditional_distribution"]["scenarios"]["S1"]["bands"]["p50"][3] = float("nan"); mutations.append((p, "finite"))
    p = _candidate(); p["conditional_distribution"]["scenarios"]["S1"]["bands"]["p50"][3] = float("inf"); mutations.append((p, "finite"))
    p = _candidate(); p["conditional_distribution"]["dates"][2] = p["conditional_distribution"]["dates"][1]; mutations.append((p, "unique"))
    p = _candidate(); p["conditional_distribution"]["dates"][1], p["conditional_distribution"]["dates"][2] = p["conditional_distribution"]["dates"][2], p["conditional_distribution"]["dates"][1]; mutations.append((p, "sorted"))
    p = _candidate(); p["conditional_distribution"]["scenarios"]["S1"]["bands"]["p10"][3] = p["conditional_distribution"]["scenarios"]["S1"]["bands"]["p90"][3] + 1; mutations.append((p, "monotone"))
    p = _candidate(); p["conditional_distribution"]["scenarios"]["S1"]["bands"]["p25"].pop(); mutations.append((p, "length"))
    p = _candidate(); p["conditional_distribution"]["scenarios"]["S1"]["representative_path_values"][4] += 10; mutations.append((p, "replay"))
    for payload, message in mutations:
        result = validate_candidate_v5_1(_rehash(payload), ROOT if message == "replay" else None)
        assert not result["ok"], message
        assert any(message in error for error in result["errors"]), result["errors"]


def test_ess_visibility_probability_space_and_source_hash_mutations() -> None:
    payload = _candidate()
    payload["conditional_distribution"]["scenarios"]["S1"]["band_visibility"]["p10_p90"] = False
    assert any("ESS visibility" in error for error in validate_candidate_v5_1(_rehash(payload))["errors"])
    payload = _candidate()
    payload["conditional_distribution"]["scenarios"]["S1"]["probability_space"] = "reference_only"
    assert any("probability-space" in error for error in validate_candidate_v5_1(_rehash(payload))["errors"])
    payload = _candidate()
    payload["source_snapshot"]["sha256"] = "0" * 64
    assert any("source snapshot hash changed" in error for error in validate_candidate_v5_1(_rehash(payload), ROOT)["errors"])
    payload = _candidate()
    payload["evidence_views"][0]["source_sha256"] = "0" * 64
    assert any("evidence source hash changed" in error for error in validate_candidate_v5_1(_rehash(payload), ROOT)["errors"])
    payload = _candidate()
    payload["posterior_diagnostics"]["view_fit"] = [{"view_id": "synthetic", "residual": .2, "tolerance": .1}]
    assert any("residual exceeds tolerance" in error for error in validate_candidate_v5_1(_rehash(payload))["errors"])
    payload = _candidate()
    payload["event_states"][0]["price_jump"] = .01
    assert any("unmapped event jump" in error for error in validate_candidate_v5_1(_rehash(payload))["errors"])
    payload = _candidate()
    payload["posterior_diagnostics"]["dependency_diagnostics"]["clusters"] = [{"dependency_cluster_id": "bad", "capped_strength": .36, "cap": .35}]
    assert any("cluster strength cap exceeded" in error for error in validate_candidate_v5_1(_rehash(payload))["errors"])


def test_future_and_naive_available_at_fail() -> None:
    payload = _candidate()
    payload["evidence_views"][0]["available_at"] = "2026-08-01T00:00:00"
    assert any("naive/invalid" in error for error in validate_candidate_v5_1(_rehash(payload))["errors"])
    payload = _candidate()
    cutoff = datetime.fromisoformat(payload["knowledge_cutoff"])
    payload["evidence_views"][0]["available_at"] = (cutoff + timedelta(days=1)).isoformat()
    assert any("future evidence" in error for error in validate_candidate_v5_1(_rehash(payload))["errors"])


def test_runtime_loader_current_and_stale_states() -> None:
    generated = datetime.fromisoformat(_candidate()["generated_at"])
    relaxed = load_current_candidate(ROOT, generated + timedelta(minutes=1), 5)
    assert relaxed["runtime_gate"]["display_eligible"]
    strict = load_current_candidate(ROOT, generated + timedelta(minutes=1), 1)
    assert strict["status"] == "stale_or_invalid"
    assert strict["runtime_gate"]["display_eligible"] is False
    assert any("candidate is stale" in reason
               for reason in strict["runtime_gate"]["reasons"])
    stale = load_current_candidate(ROOT, datetime(2026, 8, 12, 8, tzinfo=timezone.utc), 1)
    assert stale["status"] == "stale_or_invalid"
    assert stale["runtime_gate"]["display_eligible"] is False
    assert "STALE/INVALID" in stale["banner"]


def test_correction_timing_is_distribution_not_exact_date() -> None:
    timing = _candidate()["correction_timing_distribution"]
    assert timing["exact_date_forecast"] is False
    assert len(timing["dates"]) == len(timing["density"]) == len(timing["cdf"])
    assert np.all(np.diff(timing["cdf"]) >= -1e-15)
    assert "2026-10-02" in timing["cdf_points"]
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    assert "10월 2일 저점 예측" not in script
    assert "exact date forecast=false" in script


def test_october_2_is_sampling_coordinate_not_baseline_exact_trough() -> None:
    legacy_path = ROOT / "data/scenarios/candidates/scenario_v5_evidence_conditioned_legacy_prior_v1_latest.json"
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    dates = legacy["conditional_distribution"]["dates"]
    s1 = legacy["conditional_distribution"]["scenarios"]["S1"]["representative_path_values"]
    assert dates[int(np.argmin(s1))] == "2026-10-01"
    sampled = [0, *range(5, len(dates), 5)]
    if sampled[-1] != len(dates) - 1:
        sampled.append(len(dates) - 1)
    assert "2026-10-02" in [dates[index] for index in sampled]
    assert _candidate()["correction_timing_distribution"]["exact_date_forecast"] is False


def test_p50_primary_member_secondary_and_2027_common_continuation() -> None:
    payload = _candidate()
    display = payload["display_contract"]
    assert display["primary_line"] == "conditional_weighted_p50"
    assert display["secondary_line"] == "one_actual_member"
    assert display["three_distinct_2027_paths"] is False
    assert payload["distinctness_2027"]["gate_pass"] is False
    assert all(row["normalized_p50_level_correlation"] > .98
               for row in payload["distinctness_2027"]["pairs"])
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    assert "ONE SIMULATED MEMBER · EXACT DATES ARE NOT FORECAST" in script
    assert "conditional weighted p50" in script
    assert "common-model continuation" in script
    assert "RCFHS-SB v1 shadow" not in script


def test_approved_report_contract_rejects_llm_only_or_incomplete_rows() -> None:
    errors = validate_approved_report_view({"used_numerically": True, "probability_space": "physical_event"})
    assert errors
    assert any("human_approval_receipt" in error or "human approval" in error for error in errors)
    scoped = validate_approved_report_view({
        "used_numerically": True,
        "probability_space": "physical_event",
        "applicable_candidate_ids": "scenario_v5_2_scenario_clustered_db_v4",
    })
    assert "applicable_candidate_ids must be a non-empty string list" in scoped


def test_model_content_hash_is_deterministic_and_receipt_is_separate() -> None:
    payload = _candidate()
    assert payload["model_content_sha256"] == canonical_hash(_model_content(payload))
    changed = deepcopy(payload)
    changed["generated_at"] = "2099-01-01T00:00:00+00:00"
    changed["build_receipt"]["generated_at"] = changed["generated_at"]
    assert canonical_hash(_model_content(changed)) == payload["model_content_sha256"]
    assert canonical_hash(_build_receipt_content(changed["build_receipt"])) != payload["build_receipt_sha256"]
