"""Scenario V5.2 macro-actualized model and presentation gates."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.scenario_v5.contracts import (
    canonical_hash,
    canonical_numerical_hash,
    compare_protected_append_only,
    compare_protected_hashes,
    file_hash,
    protected_hashes,
)
from ai_fc.scenario_v5_2.artifact import _model_content, dashboard_projection, validate_candidate
from ai_fc.scenario_v5_2.audit import PACKAGE_RELATIVE, render_dashboard
from ai_fc.scenario_v5_2.engine import (
    CANDIDATE_RELATIVE, KNOWLEDGE_CUTOFF, ScenarioV52Error,
    SOURCE_PATHS, _evidence_registry, evidence_scores, generate_prior,
    load_inputs, numerical_source_approval_gate, source_file_hash,
)
from ai_fc.authoritative_statistics import (
    load_authoritative_source_policy,
    persist_raw_artifact,
)
from ai_fc.scenario_v5_2.event_learning import (
    EventLearningError, active_events, append_event, event_score_summary,
)
from ai_fc.scenario_v5_2.separation import (
    load_separation_contract, structural_event_adapter,
)


ROOT = Path(__file__).parents[2]


def _candidate() -> dict:
    return json.loads((ROOT / CANDIDATE_RELATIVE).read_text(encoding="utf-8"))


def _rehash(payload: dict) -> dict:
    payload["model_content_sha256"] = canonical_numerical_hash(
        _model_content(payload)
    )
    payload["build_receipt"]["model_content_sha256"] = payload["model_content_sha256"]
    payload["build_receipt_sha256"] = canonical_hash(payload["build_receipt"])
    return payload


def test_numerical_model_hash_ignores_only_machine_epsilon_noise() -> None:
    baseline = {"path": [1.0, 0.1234567890123], "schema": ("a", "b")}
    machine_noise = {
        "path": [1.0 + 4e-16, 0.1234567890123 - 4e-16],
        "schema": ["a", "b"],
    }
    material_change = {"path": [1.0, 0.1234567900123], "schema": ["a", "b"]}
    assert canonical_numerical_hash(baseline) == canonical_numerical_hash(machine_noise)
    assert canonical_numerical_hash(baseline) != canonical_numerical_hash(material_change)


def test_structural_counterfactual_hashes_use_cross_platform_precision() -> None:
    source = (ROOT / "src/ai_fc/scenario_v5_2/engine.py").read_text(
        encoding="utf-8"
    )
    assert source.count("decimal_places=10") >= 2


def test_review_package_uses_central_review_tree() -> None:
    assert PACKAGE_RELATIVE.parent.as_posix() == "reports/reviews/current/scenario_v5_2"


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


def test_private_report_perturbations_cannot_change_numerical_scores() -> None:
    inputs = load_inputs(ROOT)
    baseline = evidence_scores(inputs)
    perturbed = deepcopy(inputs)
    perturbed["labor"]["consensus"]["nonfarm_payroll_change"] = 9_999_999
    perturbed["rates"]["snapshots"]["pre_jobs_previous_day"]["meetings"] = {
        meeting: {"3.50-3.75": 1.0}
        for meeting in perturbed["rates"]["snapshots"]["pre_jobs_previous_day"][
            "meetings"
        ]
    }
    perturbed["rates"]["snapshots"]["post_jobs_current"]["meetings"] = {
        meeting: {"4.25-4.50": 1.0}
        for meeting in perturbed["rates"]["snapshots"]["post_jobs_current"][
            "meetings"
        ]
    }
    for row in perturbed["rates"]["aggregate_hike_probability"].values():
        row.update({"pre": 0.0, "post": 1.0, "delta": 1.0})
    perturbed["market"]["observations"].update({
        "us_10y_yield_change": -.25,
        "vix_change": -50.0,
        "dollar_index_change": -25.0,
    })
    changed = evidence_scores(perturbed)

    for component in ("labor_growth_risk", "policy_relief", "cross_asset_relief"):
        assert changed[component]["raw"] == baseline[component]["raw"]
        assert changed[component]["bounded_score"] == baseline[component]["bounded_score"]
    assert changed["source_event_revision_ids"] == baseline["source_event_revision_ids"]
    assert "payroll_surprise_z" not in baseline["labor_growth_risk"]["components"]
    assert baseline["labor_growth_risk"]["components"][
        "private_consensus_used_numerically"
    ] is False


def test_unapproved_secondary_rate_and_cross_asset_sources_are_reference_only() -> None:
    inputs = load_inputs(ROOT)
    scores = evidence_scores(inputs)
    registry = _evidence_registry(ROOT, inputs)
    rate = next(row for row in registry
                if row["evidence_id"] == "fed_rate_distribution_pre_post")
    cross_asset = next(row for row in registry
                       if row["evidence_id"] == "post_jobs_cross_asset_state")
    consensus = next(row for row in registry
                     if row["evidence_id"] == "kiplinger_jobs_consensus_and_commentary")

    assert rate["used_numerically"] is False and rate["effective_strength"] == 0.0
    assert cross_asset["used_numerically"] is False \
        and cross_asset["effective_strength"] == 0.0
    assert consensus["used_numerically"] is False
    assert scores["policy_relief"]["components"]["base_policy_relief_raw"] == 0.0
    assert scores["cross_asset_relief"]["raw"] == 0.0
    assert inputs["rates"]["dataset_id"] not in scores["source_event_revision_ids"]
    assert rate["source_approval"]["status"] == \
        "BLOCKED_NO_AUTHORITATIVE_APPROVED_SOURCE_RECEIPT"
    assert cross_asset["source_approval"]["status"] == \
        "BLOCKED_NO_AUTHORITATIVE_APPROVED_SOURCE_RECEIPT"


def test_numerical_source_approval_requires_authority_domain_and_hash(
    tmp_path: Path,
) -> None:
    contract = ROOT / "data/contracts/authoritative_statistics_sources.yaml"
    target_contract = tmp_path / "data/contracts/authoritative_statistics_sources.yaml"
    target_contract.parent.mkdir(parents=True)
    target_contract.write_bytes(contract.read_bytes())
    policy = load_authoritative_source_policy(target_contract)
    store = tmp_path / "data/statistics/official_store"
    raw_receipt = persist_raw_artifact(
        store,
        policy,
        source_id="cme_group",
        payload=b'{"probabilities":"archived"}\n',
        source_uri="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
        fetched_at="2026-08-08T04:35:00+00:00",
        http_status=200,
        media_type="application/json",
        series_ids=("fed_rate_distribution",),
    )
    source_path = (
        Path("data/statistics/official_store") / raw_receipt.artifact_path
    ).as_posix()
    raw = tmp_path / source_path
    cutoff = datetime.fromisoformat("2026-08-10T00:00:00+00:00")
    receipt = {
        "receipt_id": "source-approval:cme-fedwatch:2026-08-07:r1",
        "raw_receipt_id": raw_receipt.receipt_id,
        "policy_source_id": "cme_group",
        "approval_scope": "fed_rate_distribution",
        "approval_status": "approved",
        "numerical_use_approved": True,
        "authority_name": "CME Group",
        "authority_class": "official_exchange",
        "source_url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
        "source_path": source_path,
        "source_sha256": file_hash(raw),
        "available_at": "2026-08-08T04:35:00+00:00",
    }
    approved = numerical_source_approval_gate(
        tmp_path, {
            "raw_source_path": source_path,
            "authoritative_source_receipt": receipt,
        },
        approval_scope="fed_rate_distribution", cutoff=cutoff,
    )
    assert approved["used_numerically"] is True
    assert approved["status"] == "APPROVED_AUTHORITATIVE_SOURCE_RECEIPT"

    private_domain = deepcopy(receipt)
    private_domain["source_url"] = "https://www.investing.com/central-banks/fed-rate-monitor"
    blocked = numerical_source_approval_gate(
        tmp_path, {
            "raw_source_path": source_path,
            "authoritative_source_receipt": private_domain,
        },
        approval_scope="fed_rate_distribution", cutoff=cutoff,
    )
    assert blocked["used_numerically"] is False
    assert blocked["status"] == "BLOCKED_SOURCE_RECEIPT_DOMAIN"

    bad_hash = deepcopy(receipt)
    bad_hash["source_sha256"] = "0" * 64
    blocked = numerical_source_approval_gate(
        tmp_path, {
            "raw_source_path": source_path,
            "authoritative_source_receipt": bad_hash,
        },
        approval_scope="fed_rate_distribution", cutoff=cutoff,
    )
    assert blocked["used_numerically"] is False
    assert blocked["status"] == "BLOCKED_SOURCE_RECEIPT_FILE_OR_HASH"

    blocked = numerical_source_approval_gate(
        tmp_path, {
            "raw_source_path": "data/raw/rates/unrelated_private_capture.html",
            "authoritative_source_receipt": receipt,
        },
        approval_scope="fed_rate_distribution", cutoff=cutoff,
    )
    assert blocked["used_numerically"] is False
    assert blocked["status"] == "BLOCKED_SOURCE_RECEIPT_LINEAGE"


def test_growth_risk_and_blocked_policy_attribution_are_separate() -> None:
    payload = _candidate()
    scores = payload["evidence_scores"]
    assert scores["labor_growth_risk"]["bounded_score"] > 0
    assert scores["policy_relief"]["bounded_score"] == 0
    assert scores["policy_relief"]["source_gate"]["used_numerically"] is False
    for row in payload["evidence_attribution"].values():
        assert abs(row["additivity_residual"]) < 1e-12
        assert row["policy_relief_effect"] == 0
    above = payload["evidence_attribution"]["terminal_above_anchor_2026"]
    assert above["labor_growth_risk_effect"] < 0
    assert above["cross_asset_state_effect"] == 0


def test_event_day_return_is_anchor_only_and_zero_future_jump() -> None:
    payload = _candidate()
    assert payload["anchor"]["event_day_return_role"] == \
        "latest_completed_market_anchor_only"
    assert payload["anchor"]["future_event_jump"] == 0
    assert payload["circularity_control"]["realized_event_return_coefficient"] == 0
    assert payload["circularity_control"]["full_equals_explicit_zero_event_reaction"] is True
    assert payload["circularity_control"]["gate_pass"] is True


def test_forecast_anchor_tracks_latest_completed_official_snapshot() -> None:
    payload = _candidate()
    official = json.loads(
        (ROOT / "data/scenarios/nasdaq_latest.json").read_text(encoding="utf-8")
    )
    assert payload["anchor"]["date"] == official["asof"]
    assert math.isclose(payload["anchor"]["close"], official["anchor"])
    assert payload["distribution"]["forecast_boundary"] == official["asof"]
    assert payload["forecast_time_transport"]["source_snapshot_id"] == \
        official["snapshot_id"]
    assert payload["forecast_time_transport"]["historical_transport_step"] == 0.0


def test_valuation_is_fail_closed_without_vintage_complete_cross_era_history() -> None:
    gate = _candidate()["model"]["valuation_and_earnings_gate"]
    assert gate["status"] == \
        "REFERENCE_ONLY_MISSING_POINT_IN_TIME_CROSS_ERA_HISTORY"
    assert gate["stale_Cyclically_adjusted_PE_substitution"] is False
    assert gate["fabricated_low_PER_feature"] is False
    mapping = gate["source_mapping"]
    assert mapping["shiller_cape_proxy"]["numerical_status"].startswith("D0_blocked")
    assert mapping["sec_eps_revision_panel"]["numerical_status"].startswith("D0_blocked")
    assert "capex_not_eps" in mapping["sec_eps_revision_panel"]["numerical_status"]
    assert mapping["market_implied_rate_distribution"]["numerical_status"] == (
        "reference_only_blocked_unapproved_source_receipt"
    )


def test_four_ablations_have_quantitative_and_concentrated_results() -> None:
    payload = _candidate()
    rows = payload["ablations"]
    assert list(rows) == ["prior_only", "labor_only", "labor_rate", "full_evidence"]
    values = [row["probabilities"]["terminal_above_anchor_2026"] for row in rows.values()]
    assert len(set(values)) == 3
    assert rows["labor_only"]["probabilities"] == rows["labor_rate"]["probabilities"]
    for row in rows.values():
        assert row["weight_diagnostics"]["gates_pass"]
        assert math.isclose(row["weight_diagnostics"]["weight_sum"], 1.0, abs_tol=1e-12)
        assert math.isclose(sum(row["probabilities"]["scenario_probabilities"].values()), 1.0)
    components = payload["component_ablations"]
    assert set(components) == {
        "policy_only", "growth_only", "combined_growth_and_policy",
        "macro_full_without_dotcom", "dotcom_upside_increment", "report_view_increment",
    }
    assert components["policy_only"]["probabilities"] == \
        rows["prior_only"]["probabilities"]


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
    assert dotcom["no_repeat_direction_gate_applicable"] is False
    assert dotcom["no_repeat_direction_gate_pass"] is True
    increment = payload["component_ablations"]["dotcom_upside_increment"]
    assert increment["scenario_strength"] == dotcom["scenario_strength"]
    assert dotcom["dependency_cap"] == .60
    shares = dotcom["path_engine_share_by_scenario"]
    assert shares["S1"]["S1_dotcom_easing_multilayer"] == 1.0
    assert shares["S2"]["S2_balanced_soft_landing_layer"] == 1.0
    assert shares["S3"]["S3_tightening_stress_layer"] == 1.0


def test_three_scenarios_use_distinct_frozen_database_clusters() -> None:
    payload = _candidate()
    generator = payload["model"]["generator_audit"]
    assert generator["engine_mixture_probability"] == {
        "S1_dotcom_easing_multilayer": 1 / 3,
        "S2_balanced_soft_landing_layer": 1 / 3,
        "S3_tightening_stress_layer": 1 / 3,
    }
    assert generator["path_count_by_engine"] == {
        "S1_dotcom_easing_multilayer": 3000,
        "S2_balanced_soft_landing_layer": 3000,
        "S3_tightening_stress_layer": 3000,
    }
    assert generator["cluster_assignment_information_set"] == "origin_state_features_only"
    assert generator["individual_origin_outcome_selection"] is False
    assert generator["gate_pass"]
    scenarios = generator["scenarios"]
    assert [scenarios[key]["source_group"] for key in ("S1", "S2", "S3")] == [
        "expansion_and_easing_episode_db",
        "non_crisis_soft_landing_episode_db",
        "tightening_and_financial_stress_episode_db",
    ]
    assert all(row["clustering_uses_forward_outcomes"] is False
               for row in scenarios.values())
    assert all(row["outcomes_used_after_assignment_for_cluster_label_only"] is True
               for row in scenarios.values())
    assert all(len(row["cluster_assignments_sha256"]) == 64 for row in scenarios.values())
    returns = [scenarios[key]["selected_cluster"]["outcome_medians"]["forward_return_252d"]
               for key in ("S1", "S2", "S3")]
    assert returns[0] > returns[1] > returns[2]
    assert abs(scenarios["S2"]["selected_cluster"]["outcome_medians"][
        "forward_return_126d"
    ]) < .08
    assert generator["label_gates"]["S2_moderate_126d"] is True
    assert generator["episode_interval_overlap_count"] == 0
    assert generator["feature_schemas_distinct"] is True
    assert generator["residual_pool_hashes_unique"] is True
    assert generator["fixed_phase_template_active"] is False
    assert generator["phase_repetition_gates_pass"] is True


def test_dotcom_strength_sensitivity_is_monotonic_and_concentrated() -> None:
    sensitivity = _candidate()["sensitivity_analysis"]
    assert sensitivity["gate_pass"]
    assert [row["S1_strength"] for row in sensitivity["rows"]] == [.40, .60]
    probabilities = [row["scenario_probabilities"]["S1"] for row in sensitivity["rows"]]
    assert probabilities == sorted(probabilities) and len(set(probabilities)) == 2
    assert all(row["weight_gates_pass"] for row in sensitivity["rows"])
    assert [row["B_generator_dotcom_block_share"]
            for row in sensitivity["B_generator_rows"]] == [.40, .60]
    assert sensitivity["above_cap_shadow_only"] == [.70, .80]
    assert sensitivity["above_cap_never_active"] is True


def test_abc_weight_spaces_and_generator_block_provenance_are_separate() -> None:
    payload = _candidate()
    contract = yaml.safe_load(
        (ROOT / "data/contracts/scenario_v5_2_weights.yaml").read_text(encoding="utf-8")
    )
    spaces = payload["weight_spaces"]
    assert contract["weight_spaces"]["A_evidence_strength"]["active"] == .60
    assert contract["weight_spaces"]["B_generator_dotcom_block_share"]["active"] == .60
    assert spaces["A_evidence_strength"] == {
        "value": .60, "role": "post_generation_S1_likelihood",
        "changes_path_geometry": False,
    }
    assert spaces["B_generator_dotcom_block_share"]["value"] == .60
    assert spaces["B_generator_dotcom_block_share"]["changes_path_geometry"] is True
    assert spaces["C_mixture_probability"]["directly_settable"] is False
    assert math.isclose(sum(spaces["C_mixture_probability"]["value"].values()), 1.0)
    generator = payload["model"]["generator_audit"]
    s1 = generator["scenarios"]["S1"]["sampling"]
    assert s1["generator"] == "s1_empirical_variable_episode_sampler_v3"
    assert generator["B_generator_dotcom_block_share"] == .60
    assert .55 <= s1["realized_dotcom_session_share"] <= .65
    assert len(s1["block_provenance_sha256"]) == 64
    assert {row["episode_group"] for row in s1["block_provenance_sample"]} \
        <= {"dotcom", "easing", "ai_expansion"}
    assert len(s1["residual_pool_sha256"]) == 64
    assert s1["fixed_phase_template"] is False
    assert s1["phase_repetition_gate"]["gate_pass"] is True
    assert all(row["sampling"]["residual_scale"] == 1.0
               for row in generator["scenarios"].values())
    assert generator["promotion_sample_gates"] == {
        "S1": True, "S2": False, "S3": True,
    }
    assert generator["promotion_sample_gate_pass"] is False
    assert payload["distinctness"]["sample_adequacy"]["gate_pass"] is False
    assert payload["distinctness"]["sample_adequacy"][
        "failure_is_promotion_blocking_not_path_mutating"
    ] is True


def test_report_only_distinctness_is_measured_without_path_mutation() -> None:
    payload = _candidate()
    distinctness = payload["distinctness"]
    assert distinctness["operational_mode"] == "report_only"
    assert distinctness["threshold_calibration"] == {
        "observations": 0, "minimum": 30,
        "upper_bound_rule": "shadow_distribution_p75",
        "lower_bound_rule": "shadow_distribution_p25",
        "threshold_run_id": None,
    }
    assert distinctness["threshold_gate_evaluated"] is False
    assert distinctness["gate_pass"] is None
    assert distinctness["promotion_eligible"] is False
    assert distinctness["descriptive_checks"][
        "paths_unchanged_by_distinctness_evaluation"
    ] is True
    assert distinctness["descriptive_checks"]["medoid_path_ids_unique"] is True
    assert distinctness["descriptive_checks_pass"] is True
    assert distinctness["descriptive_checks"][
        "S1_S2_log_level_correlation_materially_below_0_963_baseline"
    ] is True
    assert distinctness["descriptive_checks"][
        "episode_interval_intersection_zero"
    ] is True
    assert distinctness["descriptive_checks"][
        "independent_residual_pool_hashes"
    ] is True
    baseline = distinctness["baseline_comparison"]
    assert baseline["baseline"] == .963
    assert baseline["fixed_absolute_target_used"] is False
    assert baseline["material_reduction_gate_pass"] is True
    assert baseline["redesigned_shadow"] <= .943
    assert len({
        row["central_path_bundle"]["medoid_path_id"]
        for row in payload["conditional_small_multiples"]["scenarios"].values()
    }) == 3
    assert all(row["first_touch_minus_10_ks"] > 0
               for row in distinctness["pairs"])


def test_structural_event_adapter_changes_episode_and_duration_selection() -> None:
    contract, _ = load_separation_contract(ROOT)
    def scores(policy: float, growth: float, inflation: float) -> dict:
        return {
            "policy_relief": {"bounded_score": policy},
            "labor_growth_risk": {"bounded_score": growth},
            "inflation_risk": {"bounded_score": inflation},
            "source_event_revision_ids": ["release-r1"],
        }
    zero = structural_event_adapter(scores(0.0, 0.0, 0.0), contract)
    changed = structural_event_adapter(scores(0.6, 0.8, 0.3), contract)
    assert zero["structural_update_applied"] is False
    assert changed["structural_update_applied"] is True
    assert changed["probability_only_update"] is False
    assert changed["dependency_cap_gate_pass"] is True
    assert changed["maximum_absolute_log_weight_adjustment"] \
        <= changed["dependency_cap"]
    assert changed["episode_group_weight_multipliers"] \
        != zero["episode_group_weight_multipliers"]
    assert changed["phase_duration_selection_tilts"] \
        != zero["phase_duration_selection_tilts"]
    assert changed["source_event_revision_ids"] == ["release-r1"]


def test_structural_event_ablation_matches_effective_authoritative_adapter() -> None:
    payload = _candidate()
    ablation = payload["structural_event_ablation"]
    assert ablation["probability_weights_applied"] is False
    assert ablation["same_seed_and_registered_episode_libraries"] is True
    assert ablation["paths_differ_all_scenarios"] is False
    assert ablation["path_differences_match_effective_adapter"] is True
    assert set(ablation["scenarios"]) == {"S1", "S2", "S3"}
    assert all(
        row["paths_differ"] == row["sampling_distribution_changed"]
        and row["path_difference_matches_effective_adapter"]
        for row in ablation["scenarios"].values()
    )
    adapter = payload["event_learning"]["structural_adapter"]
    assert adapter["probability_only_update"] is False
    assert adapter["source_event_revision_ids"] == [
        "BLS_EMPSIT_2026_07_2026_08_07"
    ]


def test_s2_is_not_an_arithmetic_mean_and_short_horizon_is_visibly_distinct() -> None:
    scenarios = _candidate()["conditional_small_multiples"]["scenarios"]
    s1 = np.asarray(scenarios["S1"]["bands"]["p50"])
    s2 = np.asarray(scenarios["S2"]["bands"]["p50"])
    s3 = np.asarray(scenarios["S3"]["bands"]["p50"])
    assert not np.allclose(s2, (s1 + s3) / 2.0, rtol=1e-5, atol=1e-5)
    anchor = s1[0]
    one_month_returns = np.asarray([s1[21], s2[21], s3[21]]) / anchor - 1.0
    assert one_month_returns[0] > one_month_returns[1] > one_month_returns[2]
    assert one_month_returns.max() - one_month_returns.min() > .05


def test_generator_dependency_cap_blocks_above_060_outside_shadow() -> None:
    inputs = load_inputs(ROOT)
    with np.testing.assert_raises_regex(ScenarioV52Error, "0.60 cap"):
        generate_prior(
            ROOT, inputs, path_count_per_engine=30,
            generator_dotcom_share=.70,
        )
    paths, _, engines, _, audit = generate_prior(
        ROOT, inputs, path_count_per_engine=30,
        generator_dotcom_share=.70, allow_shadow_cap_exceed=True,
    )
    assert paths.shape[0] == 90 and set(engines) == {0, 1, 2}
    assert audit["B_above_cap_shadow_only"] is True


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


def test_distribution_spaces_stay_separate_while_research_ui_is_shared_scale(tmp_path: Path) -> None:
    payload = _candidate()
    assert payload["distribution"]["probability_space"] == "total_path_mixture"
    assert payload["display_contract"]["main_chart_scenario_lines"] is True
    assert payload["display_contract"]["main_chart"] == \
        "shared_log_axis_three_conditional_p50_with_total_mixture_band"
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
    assert display["primary_line"] == "three_scenario_conditional_p50_lines"
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


def test_seed_path_count_and_independent_phase_sampling_primitives() -> None:
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
        "S1_dotcom_easing_multilayer": 80,
        "S2_balanced_soft_landing_layer": 80,
        "S3_tightening_stress_layer": 80,
    }
    assert not np.array_equal(a, seed_variant)
    assert np.array_equal(a, block_variant)
    assert audit_a["legacy_block_restart_probability_active"] is False
    assert audit_a["restart_policy"] == "empirical_scenario_native_phase_transitions"
    assert np.isfinite(a).all() and (a > 0).all()


def test_dashboard_projection_fresh_and_stale_fallback() -> None:
    cutoff = datetime.fromisoformat(_candidate()["knowledge_cutoff"])
    fresh = dashboard_projection(
        ROOT, cutoff,
        maximum_age_trading_days=1,
    )
    assert fresh["runtime_gate"]["display_eligible"] is True
    assert fresh["status"] == "degraded"
    assert fresh["semantic_reference"] == {
        "candidate_id": "scenario_v5_2_scenario_clustered_db_v4",
        "model_version": "complete_separation_empirical_episode_databases_v6",
        "rules_version": "weights-v3+complete-separation-v1",
    }
    assert fresh["governance"]["champion_eligible"] is False
    assert fresh["governance"]["default_surface"] == "customer_default_display_only"
    assert fresh["governance"]["gates"]["direct_event_observations"] == {
        "observations": 1, "minimum": 60, "pass": False,
    }
    calibration_rows = (
        ROOT / "data/scenarios/band_calibration.csv"
    ).read_text(encoding="utf-8").splitlines()[1:]
    assert fresh["governance"]["gates"]["band_calibration"]["observations"] == \
        len(calibration_rows)
    assert fresh["governance"]["gates"]["human_approval"]["approval_run_id"] is None
    assert fresh["governance"]["gates"]["scenario_native_origin_minimums"]["pass"] is False
    assert fresh["governance"]["gates"]["empirical_kernel_calibration"]["pass"] is False
    s2 = fresh["model"]["cluster_disclosure"]["S2"]
    assert s2["source_group"] == "non_crisis_soft_landing_episode_db"
    assert s2["source_origin_count"] > 0
    assert s2["selected_cluster_origin_count"] > 0
    assert s2["simulation_path_count"] == 3000
    assert s2["generator"] == "s2_empirical_variable_episode_sampler_v3"
    assert s2["fixed_phase_template"] is False
    assert s2["phase_repetition_gate"]["gate_pass"] is True
    assert len(s2["residual_pool_sha256"]) == 64
    assert fresh["model"]["database_layer_gate"][
        "episode_interval_overlap_count"
    ] == 0
    assert fresh["model"]["database_layer_gate"][
        "feature_schemas_distinct"
    ] is True
    assert fresh["model"]["database_layer_gate"][
        "unique_residual_pool_count"
    ] == 3
    dotcom = fresh["dotcom_scenario_weighting"]
    assert dotcom["dependency_cap"] == .60
    assert dotcom["requested_sensitivity_policy"]["0.80"] == \
        "blocked_above_dependency_cap"
    source_dates = _candidate()["distribution"]["dates"]
    projected_dates = fresh["distribution"]["dates"]
    dense_end = min(len(source_dates), 110)
    source_index = {value: index for index, value in enumerate(source_dates)}
    projected_indexes = [source_index[value] for value in projected_dates]
    assert projected_indexes == sorted(set(projected_indexes))
    assert projected_indexes[0] == 0
    assert projected_indexes[-1] == len(source_dates) - 1
    shape_end = (
        datetime.fromisoformat(source_dates[0]) + timedelta(days=90)
    ).date().isoformat()
    near_term_indexes = [
        index for index in projected_indexes if source_dates[index] <= shape_end
    ]
    assert max(
        right - left for left, right in zip(near_term_indexes, near_term_indexes[1:])
    ) <= 7
    assert len(projected_dates) < len(source_dates)
    assert len([date for date in projected_dates if date <= "2026-11-10"]) >= 13
    for scenario in ("S1", "S2", "S3"):
        assert len(fresh["conditional_small_multiples"]["scenarios"][scenario][
            "bands"
        ]["p50"]) == len(projected_dates)
    stale_now = cutoff
    elapsed_trading_days = 0
    while elapsed_trading_days <= 1:
        stale_now += timedelta(days=1)
        if stale_now.weekday() < 5:
            elapsed_trading_days += 1
    stale = dashboard_projection(ROOT, stale_now, maximum_age_trading_days=1)
    assert stale["status"] == "stale_or_invalid"
    assert stale["runtime_gate"]["display_eligible"] is False
    assert any("age" in reason for reason in stale["runtime_gate"]["reasons"])


def test_projection_preserves_direction_changes() -> None:
    cutoff = datetime.fromisoformat(_candidate()["knowledge_cutoff"])
    projected = dashboard_projection(
        ROOT, cutoff, maximum_age_trading_days=1,
    )
    dates = projected["conditional_small_multiples"]["dates"]
    near_term_end = (
        datetime.fromisoformat(dates[0]) + timedelta(days=90)
    ).date().isoformat()
    end = max(index for index, day in enumerate(dates) if day <= near_term_end)
    assert end + 1 >= 14

    expected_minimum_runs = {"S1": 3, "S2": 10, "S3": 4}
    returns = {}
    for scenario, minimum in expected_minimum_runs.items():
        values = projected["conditional_small_multiples"]["scenarios"][
            scenario
        ]["bands"]["p50"][:end + 1]
        direction_runs = []
        for left, right in zip(values, values[1:]):
            sign = 1 if right > left else -1 if right < left else 0
            if sign and (not direction_runs or direction_runs[-1] != sign):
                direction_runs.append(sign)
        assert len(direction_runs) >= minimum, (scenario, direction_runs)
        returns[scenario] = values[-1] / values[0] - 1

    assert returns["S1"] > .10
    assert abs(returns["S2"]) < .02
    assert returns["S3"] < -.10
    assert returns["S1"] - returns["S3"] > .24


def test_repository_dashboard_routes_v5_2_with_correct_semantics() -> None:
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "src/ai_fc/dashboard_parts/dashboard.css").read_text(encoding="utf-8")
    assert "renderScenarioV52" in script
    assert "SAME SCALE · LOG VIEW" in script
    assert 'data-scale="log"' in script
    assert 'data-history-share="0.25"' in script
    assert 'data-forecast-share="0.75"' in script
    assert 'data-time-zone="forecast"' in script
    assert 'data-scenario-p50="${key}"' in script
    assert 'data-path-role="${key}-actual-medoid"' in script
    assert "연구 코호트 가중치" in script
    assert "특정 날짜 확정 아님" in script
    assert "0.80은 cap 초과로 차단" in script
    assert "정의상 0" in script
    assert "Math.round(Number(value)*100)" in script
    assert "let rangeKey='quarter'" in script
    assert "A · B · C 분리" in script
    assert "C는 직접 입력하지 않습니다" in script
    assert "이전 방식의 그래프로 자동 전환하지 않습니다" in script
    assert "a candidate failure must never silently replace the requested chart" in script
    assert "modelView:'research'" in script
    assert "research_only_explicit_route" not in script
    assert "CONDITIONAL SMALL MULTIPLES" not in script
    assert "같은 DB를 색만 바꾼 그래프가 아닙니다" in script
    assert "fixed_phase_template_active" in script
    assert "구조 선택에 반영" in script
    assert ".scenario-v52-range" in css
    assert ".scenario-v52-readout" in css
    assert "@media(max-width:620px)" in css


def test_pages_rebuilds_when_v5_2_projection_changes() -> None:
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert '- "src/ai_fc/scenario_v5_2/**"' in workflow


def test_every_protected_data_refresh_rebuilds_and_replay_verifies_v5_2() -> None:
    workflows = [
        ROOT / ".github/workflows/scenario-refresh.yml",
        ROOT / ".github/workflows/investing-refresh.yml",
        ROOT / ".github/workflows/ai-regime-refresh.yml",
    ]
    for workflow in workflows:
        source = workflow.read_text(encoding="utf-8")
        assert "scenario-v5-2-build --force" in source
        assert "scenario-v5-2-verify --replay" in source
        assert source.index("scenario-v5-2-build --force") < source.index("git add")
    investing = workflows[1].read_text(encoding="utf-8")
    assert investing.index("python -m ai_fc forecast --due") \
        < investing.index("scenario-v5-2-build --force")


def test_v52_method_changes_are_append_only_and_disclose_the_default_decision() -> None:
    rows = [json.loads(line) for line in (ROOT / "data/method_changes.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [row["event_id"] for row in rows]
    introduction = "method:scenario-v5-2-research-surface:2026-08-10"
    correction = "method:future-default-champion-gate:2026-08-11"
    assert introduction in ids and correction in ids
    assert ids.index(introduction) < ids.index(correction)
    correction_row = next(row for row in rows if row["event_id"] == correction)
    assert correction_row["supersedes"] == introduction
    assert "1/60" in correction_row["reason"] and "3/60" in correction_row["reason"]
    redesign = "method:scenario-v5-2-distinct-path-generators:2026-08-11"
    assert redesign in ids and ids.index(correction) < ids.index(redesign)
    redesign_row = next(row for row in rows if row["event_id"] == redesign)
    assert redesign_row["contract"] == "data/contracts/scenario_v5_2_weights.yaml"
    assert redesign_row["official_snapshot_overwritten"] is False
    multilayer = "method:scenario-v5-2-independent-multilayer-db:2026-08-11:r5"
    assert multilayer in ids
    multilayer_row = next(row for row in rows if row["event_id"] == multilayer)
    assert multilayer_row["supersedes"].endswith(":r4")
    assert multilayer_row["official_snapshot_overwritten"] is False
    complete = "method:scenario-v5-2-complete-separation-v2:2026-08-11:r7"
    assert complete in ids and ids.index(multilayer) < ids.index(complete)
    complete_row = next(row for row in rows if row["event_id"] == complete)
    assert complete_row["supersedes"].endswith(":r6")
    assert complete_row["candidate_model_content_sha256"] == \
        "af81a99886090687ec6b0a4da27c58017837a5bae2a3b01f329c399e8be81bd8"
    assert len(_candidate()["model_content_sha256"]) == 64
    assert complete_row["contracts"] == [
        "data/contracts/scenario_v5_2_weights.yaml",
        "data/contracts/scenario_v5_3_separation.yaml",
    ]
    assert complete_row["official_snapshot_overwritten"] is False
    assert complete_row["champion_changed"] is False
    display_contract = (
        "method:scenario-v5-2-display-promotion-contract:2026-08-12:r8"
    )
    assert display_contract in ids and ids.index(complete) < ids.index(display_contract)
    display_row = next(row for row in rows if row["event_id"] == display_contract)
    assert display_row["semantic_reference"] == {
        "candidate_id": "scenario_v5_2_scenario_clustered_db_v4",
        "model_version": "complete_separation_empirical_episode_databases_v6",
        "rules_version": "weights-v3+complete-separation-v1",
    }
    assert display_row["artifact_hash_role"] == "informational_only"
    assert display_row["display_promotion_status"] == "pending_operator_approval"
    assert display_row["champion_changed"] is False
    approval = "method:scenario-v5-2-display-promotion-approved:2026-08-12:r9"
    assert approval in ids and ids.index(display_contract) < ids.index(approval)
    approval_row = next(row for row in rows if row["event_id"] == approval)
    assert approval_row["supersedes"] == display_contract
    assert approval_row["display_promotion_status"] == "approved"
    assert approval_row["champion_changed"] is False
    receipts = [json.loads(line) for line in (
        ROOT / "data/display_promotions/approval_receipts.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line.strip()]
    original_receipt = next(
        row for row in receipts
        if row["receipt_id"] == "display-approval:future-v52:2026-08-12:r1"
    )
    assert original_receipt["receipt_id"] in approval_row["approval_receipt"]
    assert original_receipt["semantic_reference"] == display_row["semantic_reference"]

    customer_default = "method:future-three-scenario-customer-default:2026-08-18:r13"
    assert customer_default in ids and ids.index(approval) < ids.index(customer_default)
    customer_row = next(row for row in rows if row["event_id"] == customer_default)
    assert customer_row["supersedes"] == approval
    assert customer_row["display_only"] is True
    latest_receipt = receipts[-1]
    assert latest_receipt["receipt_id"] == "display-approval:future-v52:2026-08-18:r2"
    assert latest_receipt["semantic_reference"] == display_row["semantic_reference"]


def test_mutations_fail_probability_dates_circularity_and_distinctness() -> None:
    mutations = []
    p = _candidate(); p["ablations"]["full_evidence"]["probabilities"]["new_ath_by_2026"] = 1.01; mutations.append((p, "outside"))
    p = _candidate(); p["distribution"]["dates"][2] = p["distribution"]["dates"][1]; mutations.append((p, "unique"))
    p = _candidate(); p["circularity_control"]["realized_event_return_coefficient"] = .01; mutations.append((p, "double counted"))
    p = _candidate(); p["distinctness_2027"]["gate_pass"] = False; mutations.append((p, "distinctness"))
    p = _candidate(); p["display_contract"]["october_2_exact_date_forecast"] = True; mutations.append((p, "October 2"))
    p = _candidate(); p["dotcom_scenario_weighting"]["path_engine_share_by_scenario"]["S2"]["S1_dotcom_easing_multilayer"] = .90; p["dotcom_scenario_weighting"]["path_engine_share_by_scenario"]["S2"]["S2_balanced_soft_landing_layer"] = .10; mutations.append((p, "isolated"))
    p = _candidate(); p["model"]["generator_audit"]["scenarios"]["S1"]["clustering_uses_forward_outcomes"] = True; mutations.append((p, "cluster audit"))
    p = _candidate(); p["evidence_registry"][0]["approved_cap"] = .90; mutations.append((p, "unauthorized"))
    p = _candidate(); p["weight_spaces"]["B_generator_dotcom_block_share"]["value"] = .80; mutations.append((p, "A/B/C"))
    p = _candidate(); p["distinctness"]["threshold_gate_evaluated"] = True; mutations.append((p, "report-only"))
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


def test_runtime_protected_gate_allows_append_but_rejects_mutation() -> None:
    before = {
        "files": {"data/scenarios/archive/a.json": "a" * 64},
        "manifest_sha256": "before",
    }
    appended = {
        "files": {
            **before["files"],
            "data/scenarios/archive/b.json": "b" * 64,
        },
        "manifest_sha256": "after-append",
    }
    append_result = compare_protected_append_only(before, appended)
    assert append_result["ok"] is True
    assert append_result["added"] == ["data/scenarios/archive/b.json"]
    assert append_result["changed"] == append_result["removed"] == []

    mutated = {
        "files": {"data/scenarios/archive/a.json": "c" * 64},
        "manifest_sha256": "after-mutation",
    }
    mutation_result = compare_protected_append_only(before, mutated)
    assert mutation_result["ok"] is False
    assert mutation_result["changed"] == ["data/scenarios/archive/a.json"]

    auxiliary_before = {
        "files": {"forecasts/.hashes.ots": "1" * 64},
        "manifest_sha256": "before-proof-refresh",
    }
    auxiliary_after = {
        "files": {"forecasts/.hashes.ots": "2" * 64},
        "manifest_sha256": "after-proof-refresh",
    }
    auxiliary_result = compare_protected_append_only(
        auxiliary_before, auxiliary_after
    )
    assert auxiliary_result["ok"] is True
    assert auxiliary_result["changed"] == []
    assert auxiliary_result["refreshed_auxiliary"] == ["forecasts/.hashes.ots"]


def test_candidate_runtime_gate_uses_append_only_manifest_and_consumed_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _candidate()
    before = payload["build_receipt"]["protected_before"]
    appended = deepcopy(before)
    appended["files"]["data/scenarios/archive/future-append.json"] = "f" * 64
    appended["manifest_sha256"] = canonical_hash(appended["files"])
    monkeypatch.setattr("ai_fc.scenario_v5_2.artifact.protected_hashes", lambda _root: appended)
    assert validate_candidate(payload, ROOT, replay=False)["ok"] is True

    changed = deepcopy(before)
    first_path = sorted(changed["files"])[0]
    changed["files"][first_path] = "0" * 64
    changed["manifest_sha256"] = canonical_hash(changed["files"])
    monkeypatch.setattr("ai_fc.scenario_v5_2.artifact.protected_hashes", lambda _root: changed)
    result = validate_candidate(payload, ROOT, replay=False)
    assert result["ok"] is False
    assert any("protected existing file changed" in error for error in result["errors"])

    monkeypatch.setattr("ai_fc.scenario_v5_2.artifact.protected_hashes", lambda _root: before)
    original_source_hash = source_file_hash(ROOT, SOURCE_PATHS[0])
    monkeypatch.setattr(
        "ai_fc.scenario_v5_2.artifact.source_file_hash",
        lambda root, relative: "0" * 64 if relative == SOURCE_PATHS[0]
        else source_file_hash(root, relative),
    )
    consumed_result = validate_candidate(payload, ROOT, replay=False)
    assert original_source_hash != "0" * 64
    assert consumed_result["ok"] is False
    assert any(f"source hash mismatch: {SOURCE_PATHS[0]}" in error
               for error in consumed_result["errors"])


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
