"""Scenario V5.2 macro-actualized model and presentation gates."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from ai_fc.scenario_v5.contracts import canonical_hash, compare_protected_hashes, protected_hashes
from ai_fc.scenario_v5_2.artifact import _model_content, dashboard_projection, validate_candidate
from ai_fc.scenario_v5_2.audit import render_dashboard
from ai_fc.scenario_v5_2.engine import (
    CANDIDATE_RELATIVE, KNOWLEDGE_CUTOFF, generate_prior, load_inputs,
)
from ai_fc.scenario_v5_2.event_learning import (
    EventLearningError, active_events, append_event, event_score_summary,
)


ROOT = Path(__file__).parents[2]


def _candidate() -> dict:
    return json.loads((ROOT / CANDIDATE_RELATIVE).read_text(encoding="utf-8"))


def _rehash(payload: dict) -> dict:
    payload["model_content_sha256"] = canonical_hash(_model_content(payload))
    payload["build_receipt"]["model_content_sha256"] = payload["model_content_sha256"]
    payload["build_receipt_sha256"] = canonical_hash(payload["build_receipt"])
    return payload


def test_candidate_passes_strict_validation_and_sources() -> None:
    result = validate_candidate(_candidate(), ROOT, replay=False)
    assert result["ok"], result["errors"]


def test_july_jobs_actual_was_not_available_to_v5_1() -> None:
    inputs = load_inputs(ROOT)
    v51 = inputs["v51"]
    labor = inputs["labor"]
    assert datetime.fromisoformat(v51["knowledge_cutoff"]) < datetime.fromisoformat(labor["available_at"])
    assert v51["pit_integrity"]["numerical_view_count"] == 0
    serialized = json.dumps(v51["evidence_views"], ensure_ascii=False).lower()
    assert "bls_empsit_2026_07_2026_08_07" not in serialized
    assert "nonfarm_payroll_change" not in serialized


def test_bls_actual_revision_and_participation_contract() -> None:
    labor = load_inputs(ROOT)["labor"]
    actual = labor["actual"]
    assert actual["nonfarm_payroll_change"] == -23000
    assert actual["unemployment_rate"] == .041
    assert actual["labor_force_participation_rate"] == .614
    assert actual["employment_population_ratio"] == .589
    assert labor["combined_revision"] == -103000
    assert [row["revision"] for row in labor["revisions"]] == [-66000, -37000]
    assert labor["missing_fields"] == []
    assert labor["units"]["rates"] == "fraction"
    macro_contract = yaml.safe_load(
        (ROOT / "data/contracts/macro_release_v1.yaml").read_text(encoding="utf-8")
    )
    report_contract = yaml.safe_load(
        (ROOT / "data/contracts/report_view_v2.yaml").read_text(encoding="utf-8")
    )
    assert macro_contract["validation"]["missing_value_policy"] == "reject_required_field"
    assert macro_contract["validation"]["silent_zero_fill"] is False
    assert report_contract["numerical_use_gates"]["narrative_to_number_conversion"] == "forbidden"
    assert report_contract["numerical_use_gates"]["endogenous_scenario_ancestor"] == "reference_only"


def test_full_fed_target_range_distributions_and_pre_post_moves() -> None:
    rates = load_inputs(ROOT)["rates"]
    assert rates["probability_unit"] == "fraction"
    for snapshot in rates["snapshots"].values():
        for distribution in snapshot["meetings"].values():
            assert math.isclose(sum(distribution.values()), 1.0, abs_tol=.0015)
            assert all(0 <= value <= 1 for value in distribution.values())
    moves = rates["aggregate_hike_probability"]
    assert math.isclose(moves["2026-09-30"]["delta"], -.117)
    assert math.isclose(moves["2026-10-28"]["delta"], -.095)
    assert math.isclose(moves["2026-12-09"]["delta"], -.072)


def test_growth_risk_policy_relief_and_attribution_are_separate() -> None:
    payload = _candidate()
    scores = payload["evidence_scores"]
    assert scores["labor_growth_risk"]["bounded_score"] > 0
    assert scores["policy_relief"]["bounded_score"] > 0
    for row in payload["evidence_attribution"].values():
        assert abs(row["additivity_residual"]) < 1e-12
        assert row["labor_growth_risk_effect"] != row["policy_relief_effect"]
    above = payload["evidence_attribution"]["terminal_above_anchor_2026"]
    assert above["labor_growth_risk_effect"] < 0
    assert above["policy_relief_effect"] > 0


def test_event_day_return_is_anchor_only_and_zero_future_jump() -> None:
    payload = _candidate()
    assert payload["anchor"]["event_day_return_role"] == "historical_anchor_only"
    assert payload["anchor"]["future_event_jump"] == 0
    assert payload["circularity_control"]["realized_event_return_coefficient"] == 0
    assert payload["circularity_control"]["full_equals_explicit_zero_event_reaction"] is True
    assert payload["circularity_control"]["gate_pass"] is True


def test_four_ablations_have_quantitative_and_concentrated_results() -> None:
    payload = _candidate()
    rows = payload["ablations"]
    assert list(rows) == ["prior_only", "labor_only", "labor_rate", "full_evidence"]
    values = [row["probabilities"]["terminal_above_anchor_2026"] for row in rows.values()]
    assert len(set(values)) == 4
    for row in rows.values():
        assert row["weight_diagnostics"]["gates_pass"]
        assert math.isclose(row["weight_diagnostics"]["weight_sum"], 1.0, abs_tol=1e-12)
        assert math.isclose(sum(row["probabilities"]["scenario_probabilities"].values()), 1.0)
    components = payload["component_ablations"]
    assert set(components) == {
        "policy_only", "growth_only", "combined_growth_and_policy",
        "macro_full_without_dotcom", "dotcom_upside_increment", "report_view_increment",
    }
    assert components["policy_only"]["probabilities"]["terminal_above_anchor_2026"] \
        > rows["prior_only"]["probabilities"]["terminal_above_anchor_2026"]


def test_dotcom_weight_is_strongest_in_s1_without_cherry_picking() -> None:
    payload = _candidate()
    dotcom = payload["dotcom_scenario_weighting"]
    assert dotcom["scenario_strength"] == {"S1": .60, "S2": 0.0, "S3": 0.0}
    assert dotcom["one_month_negative_target_preserved"] is True
    assert dotcom["forward_return_targets"]["one_month"] < 0
    assert dotcom["single_cycle_limitation"] is True
    assert dotcom["forced_endpoint"] is False
    assert dotcom["forced_october_direction"] is False
    assert dotcom["S1_probability_increment"] > 0
    assert dotcom["S1_no_repeat_probability_after_dotcom"] \
        > dotcom["S1_no_repeat_probability_before_dotcom"]
    increment = payload["component_ablations"]["dotcom_upside_increment"]
    assert increment["scenario_strength"] == dotcom["scenario_strength"]
    assert dotcom["dependency_cap"] == .60
    shares = dotcom["path_engine_share_by_scenario"]
    assert shares["S1"]["S1_dotcom_expansion_cluster"] == 1.0
    assert shares["S2"]["S2_modern_baseline_cluster"] == 1.0
    assert shares["S3"]["S3_macro_tightening_stress_cluster"] == 1.0


def test_three_scenarios_use_distinct_frozen_database_clusters() -> None:
    payload = _candidate()
    generator = payload["model"]["generator_audit"]
    assert generator["engine_mixture_probability"] == {
        "S1_dotcom_expansion_cluster": 1 / 3,
        "S2_modern_baseline_cluster": 1 / 3,
        "S3_macro_tightening_stress_cluster": 1 / 3,
    }
    assert generator["path_count_by_engine"] == {
        "S1_dotcom_expansion_cluster": 3000,
        "S2_modern_baseline_cluster": 3000,
        "S3_macro_tightening_stress_cluster": 3000,
    }
    assert generator["cluster_assignment_information_set"] == "origin_state_features_only"
    assert generator["individual_origin_outcome_selection"] is False
    assert generator["gate_pass"]
    scenarios = generator["scenarios"]
    assert [scenarios[key]["source_group"] for key in ("S1", "S2", "S3")] == [
        "dotcom_price_state_db",
        "modern_general_market_state_db",
        "macro_tightening_financial_conditions_db",
    ]
    assert all(row["clustering_uses_forward_outcomes"] is False
               for row in scenarios.values())
    assert all(row["outcomes_used_after_assignment_for_cluster_label_only"] is True
               for row in scenarios.values())
    assert all(len(row["cluster_assignments_sha256"]) == 64 for row in scenarios.values())
    returns = [scenarios[key]["selected_cluster"]["outcome_medians"]["forward_return_252d"]
               for key in ("S1", "S2", "S3")]
    assert returns[0] > returns[1] > returns[2]
    assert returns[0] - returns[2] > .50
    assert abs(scenarios["S2"]["selected_cluster"]["outcome_medians"][
        "forward_return_126d"
    ]) < .05
    assert generator["label_gates"]["S2_sideways_126d"] is True


def test_dotcom_strength_sensitivity_is_monotonic_and_concentrated() -> None:
    sensitivity = _candidate()["sensitivity_analysis"]
    assert sensitivity["gate_pass"]
    assert [row["S1_strength"] for row in sensitivity["rows"]] == [.28, .45, .60]
    probabilities = [row["scenario_probabilities"]["S1"] for row in sensitivity["rows"]]
    assert probabilities == sorted(probabilities) and len(set(probabilities)) == 3
    assert all(row["weight_gates_pass"] for row in sensitivity["rows"])


def _cpi_event(revision_id: str = "cpi-2026-08-r1") -> dict:
    return {
        "event_id": "cpi-2026-08", "revision_id": revision_id, "kind": "cpi",
        "reference_period": "2026-07", "published_at": "2026-08-12T12:30:00+00:00",
        "available_at": "2026-08-12T12:30:01+00:00",
        "as_of": "2026-08-12T12:31:00+00:00",
        "retrieved_at": "2026-08-12T12:32:00+00:00",
        "source_url": "https://example.invalid/cpi-release",
        "source_sha256": "0" * 64,
        "actual": {"headline_yoy": .031},
        "consensus": {"headline_yoy": .030},
        "unit_metadata": {"headline_yoy": "fraction"},
        "mapping": {"metric": "headline_yoy", "standardization_scale": .001},
    }


def test_event_learning_is_append_only_pit_safe_and_revision_aware(tmp_path: Path) -> None:
    first, appended = append_event(tmp_path, _cpi_event())
    assert appended is True and first["scores"]["inflation_risk"] > 0
    replay, appended_again = append_event(tmp_path, _cpi_event())
    assert appended_again is False and replay["record_sha256"] == first["record_sha256"]
    correction = _cpi_event("cpi-2026-08-r2")
    correction["supersedes"] = "cpi-2026-08-r1"
    correction["actual"] = {"headline_yoy": .029}
    correction["published_at"] = "2026-08-12T13:00:00+00:00"
    correction["available_at"] = "2026-08-12T13:00:01+00:00"
    correction["as_of"] = "2026-08-12T13:01:00+00:00"
    correction["retrieved_at"] = "2026-08-12T13:02:00+00:00"
    append_event(tmp_path, correction)
    active = active_events(tmp_path)
    assert [row["revision_id"] for row in active] == ["cpi-2026-08-r2"]
    summary = event_score_summary(tmp_path)
    assert summary["active_event_count"] == summary["numerical_event_count"] == 1
    assert summary["raw_weighted_scores"]["inflation_risk"] < 0
    assert len((tmp_path / "data/scenarios/candidates/event_learning/events.jsonl")
               .read_text(encoding="utf-8").splitlines()) == 2


def test_event_learning_rejects_future_vintage_and_bad_correction(tmp_path: Path) -> None:
    future = _cpi_event()
    future["available_at"] = "2026-08-12T12:33:00+00:00"
    with np.testing.assert_raises_regex(EventLearningError, "available <= as_of"):
        append_event(tmp_path, future)
    append_event(tmp_path, _cpi_event())
    wrong = _cpi_event("cpi-2026-08-r2")
    wrong["supersedes"] = "missing-revision"
    with np.testing.assert_raises_regex(EventLearningError, "supersedes"):
        append_event(tmp_path, wrong)


def test_main_is_mixture_and_scenarios_are_conditional_small_multiples(tmp_path: Path) -> None:
    payload = _candidate()
    assert payload["distribution"]["probability_space"] == "total_path_mixture"
    assert payload["display_contract"]["main_chart_scenario_lines"] is False
    assert payload["conditional_small_multiples"]["probability_space"] == "scenario_conditional"
    assert set(payload["conditional_small_multiples"]["scenarios"]) == {"S1", "S2", "S3"}
    dashboard = render_dashboard(tmp_path, payload)
    source = dashboard.read_text(encoding="utf-8")
    assert 'data-chart-role="total-mixture"' in source
    assert 'data-path-role="p50-primary"' in source
    assert source.count('data-scenario="') == 3
    assert 'data-forecast-boundary="true"' in source
    assert "CONDITIONAL ON THIS SCENARIO" in source
    assert "NOT THE OVERALL FORECAST" in source
    assert "@media(max-width:850px)" in source
    assert "NaN" not in source and "Infinity" not in source


def test_p50_has_no_fake_wiggle_and_bundle_is_actual_members() -> None:
    payload = _candidate()
    display = payload["display_contract"]
    bundle = payload["distribution"]["central_path_bundle"]
    assert display["primary_line"] == "total_mixture_weighted_p50"
    assert display["fake_wiggle"] is False
    assert bundle["fake_wiggle_applied"] is False
    assert bundle["p50_smoothing"].startswith("none")
    assert len(bundle["members"]) == bundle["member_count"] == 7
    assert bundle["medoid_path_id"].startswith("path_")
    assert all(len(row["values"]) == len(payload["distribution"]["dates"])
               for row in bundle["members"])
    assert bundle["realism_gate_pass"]
    assert bundle["no_piecewise_linear_endpoint_path"]
    assert bundle["no_common_residual_gate"]
    assert all(row["gate_pass"] for row in bundle["member_diagnostics"])


def test_october_2_is_not_an_exact_date_forecast() -> None:
    payload = _candidate()
    timing = payload["first_touch_distribution"]
    assert timing["exact_date_forecast"] is False
    assert payload["display_contract"]["october_2_exact_date_forecast"] is False
    assert timing["october_2_role"].startswith("ordinary CDF coordinate")
    index = timing["dates"].index("2026-10-02")
    assert math.isclose(timing["cdf_at_2026_10_02"], timing["cdf"][index], abs_tol=1e-10)
    assert np.all(np.diff(timing["cdf"]) >= -1e-12)


def test_dependency_cap_circularity_and_2027_distinctness_gates() -> None:
    payload = _candidate()
    dependency = payload["dependency_control"]
    assert dependency["gate_pass"]
    assert dependency["default_cluster_cap"] == .35
    assert dependency["approved_cluster_overrides"]["dotcom_single_cycle_analog"]["cap"] == .60
    assert all(row["effective_strength"] <= row["cap"]
               for row in dependency["clusters"])
    ancestor = next(row for row in payload["evidence_registry"]
                    if row["evidence_id"] == "v5_1_ancestor_candidate")
    assert ancestor["used_numerically"] is False
    assert payload["distinctness_2027"]["gate_pass"]
    assert payload["distinctness_2027"]["partition_information_cutoff"] \
        == "historical_origin_state_only"
    assert payload["distinctness_2027"]["partition_uses_forward_outcomes_for_assignment"] is False
    assert payload["distinctness_2027"]["partition_uses_2027_outcomes"] is False
    assert all(row["distinct_metric_count"] >= 2
               for row in payload["distinctness_2027"]["pairs"])
    assert all(row["distribution_gate_count"] >= 3
               for row in payload["distinctness_2027"]["pairs"])


def test_pre_post_comparison_includes_paths_probabilities_and_timing() -> None:
    comparison = _candidate()["pre_post_jobs_comparison"]
    before = comparison["before_jobs_prior_only"]
    after = comparison["after_jobs_full_evidence"]
    for row in (before, after):
        assert set(row["scenario_probabilities"]) == {"S1", "S2", "S3"}
        assert 0 < row["first_touch_minus_10_by_october_end"] < 1
        assert row["year_end_p50"] > 0
        timing = row["first_touch_distribution"]
        assert timing["exact_date_forecast"] is False
        assert all(timing["conditional_on_touch_quantiles"].values())
    assert before["year_end_p50"] != after["year_end_p50"]
    assert before["first_touch_distribution"]["cdf"] != after["first_touch_distribution"]["cdf"]


def test_seed_path_count_and_block_length_sensitivity_primitives() -> None:
    inputs = load_inputs(ROOT)
    a, dates_a, engines_a, _, audit_a = generate_prior(
        ROOT, inputs, seed=71, path_count_per_engine=80, block_restart_probability=.10
    )
    replay, dates_replay, engines_replay, _, audit_replay = generate_prior(
        ROOT, inputs, seed=71, path_count_per_engine=80, block_restart_probability=.10
    )
    seed_variant, _, _, _, seed_audit = generate_prior(
        ROOT, inputs, seed=72, path_count_per_engine=80, block_restart_probability=.10
    )
    block_variant, _, _, _, _ = generate_prior(
        ROOT, inputs, seed=71, path_count_per_engine=80, block_restart_probability=.20
    )
    assert a.shape == (240, len(dates_a))
    assert np.array_equal(a, replay)
    assert dates_a == dates_replay and np.array_equal(engines_a, engines_replay)
    assert audit_a == audit_replay
    assert {
        key: row["cluster_assignments_sha256"]
        for key, row in audit_a["scenarios"].items()
    } == {
        key: row["cluster_assignments_sha256"]
        for key, row in seed_audit["scenarios"].items()
    }
    assert audit_a["path_count_by_engine"] == {
        "S1_dotcom_expansion_cluster": 80,
        "S2_modern_baseline_cluster": 80,
        "S3_macro_tightening_stress_cluster": 80,
    }
    assert not np.array_equal(a, seed_variant)
    assert not np.array_equal(a, block_variant)
    assert np.isfinite(a).all() and (a > 0).all()


def test_dashboard_projection_fresh_and_stale_fallback() -> None:
    fresh = dashboard_projection(
        ROOT, datetime.fromisoformat("2026-08-10T04:00:00+00:00"),
        maximum_age_trading_days=1,
    )
    assert fresh["runtime_gate"]["display_eligible"] is True
    assert fresh["status"] == "degraded"
    assert len(fresh["distribution"]["dates"]) < len(_candidate()["distribution"]["dates"])
    stale = dashboard_projection(
        ROOT, datetime.fromisoformat("2026-08-12T04:00:00+00:00"),
        maximum_age_trading_days=1,
    )
    assert stale["status"] == "stale_or_invalid"
    assert stale["runtime_gate"]["display_eligible"] is False
    assert any("age" in reason for reason in stale["runtime_gate"]["reasons"])


def test_repository_dashboard_routes_v5_2_with_correct_semantics() -> None:
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "src/ai_fc/dashboard_parts/dashboard.css").read_text(encoding="utf-8")
    assert "renderScenarioV52" in script
    assert "PRIMARY · TOTAL MIXTURE" in script
    assert "CONDITIONAL ON THIS SCENARIO" in script
    assert "NOT THE OVERALL FORECAST" in script
    assert 'data-path-role="mixture-p50"' in script
    assert 'data-path-role="weighted-medoid"' in script
    assert "exact_date_forecast=false" in script
    assert "DOTCOM SCENARIO WEIGHT" in script
    assert "EVENT ADAPTATION" in script
    assert "S1 강·S2/S3 약" in script
    assert "scenario-v52-scenarios" in css
    assert "@media(max-width:900px)" in css


def test_mutations_fail_probability_dates_circularity_and_distinctness() -> None:
    mutations = []
    p = _candidate(); p["ablations"]["full_evidence"]["probabilities"]["new_ath_by_2026"] = 1.01; mutations.append((p, "outside"))
    p = _candidate(); p["distribution"]["dates"][2] = p["distribution"]["dates"][1]; mutations.append((p, "unique"))
    p = _candidate(); p["circularity_control"]["realized_event_return_coefficient"] = .01; mutations.append((p, "double counted"))
    p = _candidate(); p["distinctness_2027"]["gate_pass"] = False; mutations.append((p, "distinctness"))
    p = _candidate(); p["display_contract"]["october_2_exact_date_forecast"] = True; mutations.append((p, "October 2"))
    p = _candidate(); p["dotcom_scenario_weighting"]["path_engine_share_by_scenario"]["S2"]["S1_dotcom_expansion_cluster"] = .90; p["dotcom_scenario_weighting"]["path_engine_share_by_scenario"]["S2"]["S2_modern_baseline_cluster"] = .10; mutations.append((p, "isolated"))
    p = _candidate(); p["model"]["generator_audit"]["scenarios"]["S1"]["clustering_uses_forward_outcomes"] = True; mutations.append((p, "cluster audit"))
    p = _candidate(); p["evidence_registry"][0]["approved_cap"] = .90; mutations.append((p, "unauthorized"))
    for payload, expected in mutations:
        result = validate_candidate(_rehash(payload), ROOT, replay=False)
        assert not result["ok"]
        assert any(expected in error for error in result["errors"]), result["errors"]


def test_protected_snapshot_ledger_and_archive_hashes_are_unchanged() -> None:
    payload = _candidate()
    before = payload["build_receipt"]["protected_before"]
    comparison = compare_protected_hashes(before, protected_hashes(ROOT))
    assert comparison["ok"], comparison
    assert comparison["added"] == comparison["removed"] == comparison["changed"] == []


def test_protected_hashes_normalize_git_text_eol_but_keep_ledgers_byte_exact(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "data/cross_asset/archive/sample.json"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b'{\r\n  "value": 1\r\n}\r\n')
    archive_crlf = protected_hashes(tmp_path)["files"][archive.relative_to(tmp_path).as_posix()]
    archive.write_bytes(b'{\n  "value": 1\n}\n')
    archive_lf = protected_hashes(tmp_path)["files"][archive.relative_to(tmp_path).as_posix()]
    assert archive_crlf == archive_lf

    ledger = tmp_path / "calibration/ledger.csv"
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b"a,b\r\n1,2\r\n")
    ledger_crlf = protected_hashes(tmp_path)["files"][ledger.relative_to(tmp_path).as_posix()]
    ledger.write_bytes(b"a,b\n1,2\n")
    ledger_lf = protected_hashes(tmp_path)["files"][ledger.relative_to(tmp_path).as_posix()]
    assert ledger_crlf != ledger_lf
