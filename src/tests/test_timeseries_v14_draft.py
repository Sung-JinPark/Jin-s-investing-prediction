"""V14 조건부 전이 트랙 — draft 계약 불변식.

이 계약은 draft_prereg 다. 개시(track_open)·무장(armed)은 사용자 결정이며 계약 자체가 승인이 아니다.
여기서 고정하는 것: ① 파싱 가능 ② draft 지위(track_open false · armed false · t0) ③ V13 홀드아웃 창
재사용 불허 ④ 자동화 부재(verb·워크플로·패키지 0) ⑤ θ 가 V13 동결값과 동일 ⑥ 검정 0회 공시 ⑦ V13
prohibitions 전부 승계 + V14 신설 3건 ⑧ 라이브 전진 게이트 사전등록(60 · n 비례 퇴화 · 새 seed)
⑨ 저장소에 없는 도구 이름 미기재.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v14_conditional.draft.yaml"
PARENT = ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml"
PARENT_COEFFICIENTS = ROOT / "data/timeseries_v13/vol/champion_coefficients.json"
PREREG_DOC = ROOT / "docs/design/v14_conditional_transition_prereg_draft_261021.md"
CLI = ROOT / "src/ai_fc/cli.py"
WORKFLOWS = ROOT / ".github/workflows"

V14_NEW_PROHIBITIONS = (
    "anchoring_mapped_probability_into_llm_digest",
    "holdout_reuse_of_v13_window",
    "post_hoc_conditioning_threshold_change",
)
# 블루프린트 §5.1 — 저장소에 없는 도구. 사전등록에 이름이 나오면 실행 불가능한 약속이 된다.
UNIMPLEMENTED_TOOL_NAMES = ("romano", "benjamini", "holm", "bonferroni", "conformal",
                            "model confidence set", "ladder_mcs")


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _parent() -> dict:
    return yaml.safe_load(PARENT.read_text(encoding="utf-8"))


def test_contract_parses_and_carries_draft_identity() -> None:
    contract = _contract()
    assert contract["schema_version"] == 1
    assert contract["contract_id"] == "timeseries_v14_conditional"
    assert contract["model_id"] == "event_probability.volatility_v14_conditional"
    assert contract["model_version"] == 14
    assert contract["status"] == "draft_prereg"
    assert contract["lineage"]["parent"] == "timeseries_v13_vol"
    assert contract["lineage"]["parent_untouched"] is True


def test_track_is_closed_and_gates_are_disarmed() -> None:
    contract = _contract()
    protocol = contract["development_protocol"]
    assert protocol["track_open"] is False
    assert contract["gates"]["armed"] is False
    assert contract["gates"]["evaluated_candidates"] == 0
    assert protocol["maximum_development_evaluations"] == 4
    assert protocol["evaluations_spent"] == 0
    assert protocol["ledgers_created"] is False
    assert protocol["preregistered_before_results"] is True
    assert protocol["ledger_append_only"] is True
    # 원장 경로는 선언만 — 파일·디렉터리는 track_open 전에 존재하면 안 된다
    for key in ("experiment_ledger", "approvals_ledger", "live_ledger", "live_resolutions_ledger"):
        path = protocol[key]
        assert path.startswith("data/timeseries_v14/ledgers/"), key
        assert not (ROOT / path).exists(), f"{key} 가 track_open 전에 생성됐다"
    assert not (ROOT / "data/timeseries_v14").exists()


def test_v13_holdout_window_is_contaminated_and_not_reusable() -> None:
    contract = _contract()
    holdout = contract["window"]["holdout"]
    assert holdout["window"] == ["2015-01-01", "2018-12-31"]
    assert holdout["status"] == "contaminated_by_construction"
    assert holdout["reuse_allowed"] is False
    assert "재사용" in holdout["why"] or "불허" in holdout["why"]
    assert holdout["bytes_read_for_this_draft"] == 0
    stopping = contract["stopping_points"]["holdout"]
    assert stopping["status"] == "contaminated_by_construction"
    assert stopping["reuse_allowed"] is False
    assert stopping["execution_path"] == "absent_by_construction"
    sealed = contract["stopping_points"]["sealed"]
    assert sealed["execution_path"] == "absent_by_construction"
    assert sealed["requires_explicit_user_approval"] is True
    assert contract["window"]["sealed"]["bytes_read_for_this_draft"] == 0
    assert contract["window"]["verdict_window"] == "live_forward"
    assert contract["irreversible"]["holdout_slots"] == 0
    assert contract["prohibitions"]["v14_specific"]["holdout_reuse_of_v13_window"] is True


def test_design_window_and_split_are_inherited_unchanged_from_v13() -> None:
    contract, parent = _contract(), _parent()
    assert contract["window"]["design"] == parent["data_policy"]["design_window"]
    assert contract["data_policy"]["design_window"] == parent["data_policy"]["design_window"]
    assert contract["window"]["split"] == parent["split"]
    assert contract["data_policy"]["source"] == parent["data_policy"]["source"]
    assert contract["data_policy"]["series"] == parent["data_policy"]["series"]
    assert contract["data_policy"]["no_write_to_sealed"] is True
    assert contract["data_policy"]["no_fred_key_in_loop"] is True


def test_no_automation_exists_for_v14() -> None:
    # ★ 정지점: 승인 원문 없이는 verb·워크플로·패키지 자체가 없다 (V9/V13 패턴).
    cli_text = CLI.read_text(encoding="utf-8")
    assert "timeseries-v14" not in cli_text
    assert "timeseries_v14" not in cli_text
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        assert "timeseries-v14" not in workflow.read_text(encoding="utf-8"), workflow.name
    assert not (ROOT / "src/ai_fc/timeseries_v14").exists()
    assert not (ROOT / "src/ai_fc/timeseries_v14.py").exists()
    contract = _contract()
    assert contract["live_forward_gate"]["execution_path"] == "absent_by_construction"
    assert contract["irreversible"]["auto_execution_path"] == "absent_by_construction"
    assert contract["irreversible"]["user_approval_text_required"] is True


def test_theta_is_the_v13_frozen_value() -> None:
    contract, parent = _contract(), _parent()
    theta = contract["targets"]["rv_conditional_transition"]["theta"]
    assert theta == 0.1694207105468098
    # V13 계약 targets 는 4자리 고정값, rung-5 블록은 동결 중앙값 전체 자릿수를 문자열로 싣는다
    assert round(theta, 4) == parent["targets"]["rv_exceedance"]["theta"]
    assert contract["targets"]["rv_conditional_transition"]["theta_registered_in_v13_targets"] == \
        parent["targets"]["rv_exceedance"]["theta"]
    assert repr(theta) in PARENT.read_text(encoding="utf-8")
    frozen = json.loads(PARENT_COEFFICIENTS.read_text(encoding="utf-8"))
    assert abs(theta - frozen["rv_nan_fill_median"]) < 1e-12
    assert contract["targets"]["rv_conditional_transition"]["horizons"] == parent["targets"]["rv_exceedance"]["horizons"]


def test_targets_are_six_conditional_cells_with_operational_thresholds() -> None:
    targets = _contract()["targets"]
    vix = targets["vix_conditional_transition"]
    assert vix["K"] == 25
    assert vix["horizons"] == [5, 21, 63]
    assert "VIX_close_t < 20" in vix["conditioning"]
    assert "하드룰" in vix["conditioning_rationale"]
    assert "통계" in vix["conditioning_rationale"]  # 통계가 통과하도록 고른 값이 아님을 명기
    rv = targets["rv_conditional_transition"]
    assert rv["horizons"] == [5, 21, 63]
    assert "<= theta" in rv["conditioning"]
    assert targets["cell_count"] == 6
    assert len(vix["cells"]) + len(rv["cells"]) == 6
    assert targets["m1_target_non_overlap"]["status"] == "partial_disclosed"


def test_display_tier_is_internal_and_holdout_status_is_live_forward() -> None:
    publication = _contract()["publication"]
    assert publication["display_tier"] == "t0_internal"
    assert publication["display_tiers_allowed"] == ["t0_internal", "t2_hidden_panel", "t3_live_card"]
    assert "t4" not in " ".join(publication["display_tiers_allowed"]).lower()
    assert publication["holdout_status"] == "not_applicable_live_forward"
    assert publication["reference_opinion_only"] is True
    assert publication["t3_without_holdout_requires_bold_caveat"] is True
    assert publication["wiring_eligible_cells"] == []


def test_metadata_discloses_zero_tests_and_zero_label_computation() -> None:
    contract = _contract()
    discipline = contract["metadata"]["drafting_discipline"]
    assert "검정 0회" in discipline
    assert "라벨 계산 0회" in discipline
    assert contract["metadata"]["numbers_newly_computed"] == 0
    assert contract["metadata"]["prereg_commit"] is None
    head = CONTRACT.read_text(encoding="utf-8").split("schema_version:")[0]
    assert "계약 자체가 승인이 아니다" in head
    assert "검정 0회" in head
    resources = contract["irreversible"]["resources_consumed_by_this_draft"]
    assert resources == {"holdout": 0, "sealed": 0, "evaluations": 0, "usd": 0}


def test_prohibitions_superset_v13_plus_three_new() -> None:
    contract, parent = _contract(), _parent()
    inherited = contract["prohibitions"]["inherited_from_v13"]
    for key, value in parent["prohibitions"].items():
        assert inherited.get(key) is value is True, f"V13 prohibition {key} 누락 또는 완화"
    specific = contract["prohibitions"]["v14_specific"]
    for key in V14_NEW_PROHIBITIONS:
        assert specific[key] is True, key


def test_campaign_prior_tests_is_unit_explicit_with_pending_placeholders() -> None:
    prior = _contract()["lineage"]["campaign_prior_tests"]
    assert prior["unit"] == "mixed_units_documented"
    assert prior["breakdown"] == {"v8": 12, "v9": 7, "v10": 12, "v11": 48, "v12": 16, "v13": 81}
    assert prior["value_at_draft"] == sum(prior["breakdown"].values())
    assert prior["unit_notes"]["v11"] == "cell_tests"
    assert "rung" in prior["unit_notes"]["v13"]
    for key in ("v13_rung7", "v13_rung8"):
        assert "집행 후 기입" in prior["pending_placeholders"][key], key
    lo, hi = prior["consistent_range"]
    assert lo <= prior["value_at_draft"] <= hi


def test_live_forward_gate_is_preregistered_with_n_proportional_degeneracy() -> None:
    gate = _contract()["live_forward_gate"]
    assert gate["registered_before_results"] is True
    assert gate["evidence_at_registration"] == {"live_ledger_rows": 0, "matured_origins": 0, "track_open": False}
    assert gate["minimum_matured_origins_per_cell"] == 60
    assert "20261021" in gate["uncertainty"] and "CI90" in gate["uncertainty"]
    assert "hold" in gate["demotion_rule"] and "자동 재무장 없음" in gate["demotion_rule"]
    assert "0.10" in gate["negative_control"]
    degeneracy = gate["degeneracy"]
    assert "max(5" in degeneracy["min_events_rule"] and "0.1" in degeneracy["min_events_rule"]
    assert "untestable" in degeneracy["min_events_rule"] and "강등 아님" in degeneracy["min_events_rule"]
    assert "판정 다리" in degeneracy["episode_count"]  # 국면 수는 라벨만
    assert "무효" in degeneracy["null_above_threshold"] and "강등 아님" in degeneracy["null_above_threshold"]
    assert "과반" in gate["termination_T7_form"]["rule"]
    assert any("수정 금지" in rule for rule in gate["prohibitions"])
    # 설계 게이트의 seed 도 새 값이어야 한다 (V13 20260907 과 구분)
    design_gate = _contract()["gate"]
    assert design_gate["uncertainty"]["seed"] == 20261021
    assert design_gate["uncertainty"]["block_length"] == 13 and design_gate["uncertainty"]["replicates"] == 2000
    assert design_gate["multiplicity"]["method"] == "family_p_binomial"
    assert design_gate["negative_control"]["p_permutation_forbidden"] is True
    assert design_gate["mde"]["printed_before_results"] == "required"


def test_episode_guard_form_is_fixed_but_unmeasured() -> None:
    guard = _contract()["episode_guard"]
    assert guard["unit"] == "contiguous_run"
    assert guard["min_episodes"] == 5
    assert guard["marginal_band"] == [3, 4]
    assert guard["below_marginal_action"] == "untestable_by_construction"
    assert "측정 0회" in guard["measurement"]["timing"]
    assert "측정 후 선택" in guard["measurement"]["disclosure_rule"]


def test_contract_names_no_unimplemented_tools() -> None:
    text = CONTRACT.read_text(encoding="utf-8").lower()
    for name in UNIMPLEMENTED_TOOL_NAMES:
        assert name not in text, name
    assert _contract()["gate"]["only_implemented_tools"] is True


def test_candidate_store_is_not_ingested_and_pending_licenses_block_payload() -> None:
    blocks = _contract()["candidate_blocks"]
    assert blocks["pool_fixed_before_results"] is True
    store = blocks["v14_specific_diagnostic_only_store"]
    assert store["ingestion_status"] == "not_ingested"
    assert store["may_enter_family"] is False
    assert store["OFR_FSI_subindices"]["license"]["display"] == "forbidden_until_confirmed"
    inherited = blocks["inherited_from_rung7_prereg"]
    assert inherited["calendar"]["primary"] == "E1_fomc_in_window"
    assert inherited["positioning"]["primary"] == "P1_vix_lev_net_oi"
    assert inherited["regime_memory"]["primary"] == "D1_log_sessions_since_event"
    diagnostics = ROOT / inherited["unconditional_diagnostics_reference"]
    assert diagnostics.is_file()
    assert json.loads(diagnostics.read_text(encoding="utf-8"))["label_free"] is True


def test_decisions_are_all_pending_and_templates_follow_blueprint_format() -> None:
    contract = _contract()
    assert contract["amendments_applied"] == {}
    assert contract["decisions_resolved"] == {}
    pending = contract["decisions_pending"]
    for decision in ("V14-D0", "V14-D1", "V14-D2", "V14-D3", "V14-D4", "V14-D5",
                     "V14-D6", "V14-D7", "V14-D8", "V14-D9"):
        assert decision in pending, decision
    assert pending["V14-D3"]["independent"] is True
    templates = contract["approvals"]["templates"]
    assert templates["V14-D0"] == "V14-D0 A2 승인"
    for decision, text in templates.items():
        assert text.startswith(decision) and text.endswith("승인"), decision


def test_prereg_document_exists_and_discloses_discipline() -> None:
    text = PREREG_DOC.read_text(encoding="utf-8")
    assert "검정 0회" in text and "라벨 계산 0회" in text
    assert "계약 자체가 승인이 아니다" in text
    assert "contaminated_by_construction" in text
    assert "[추정]" in text
    assert "V14-D0 A2 승인" in text
    assert "max(5" in text
