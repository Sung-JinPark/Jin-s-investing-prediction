"""V14 조건부 전이 트랙 — 사전등록(prereg) 계약 불변식 (2026-10-22 track_open 뒤).

고정하는 것: ① 파싱·정체성·status prereg ② track_open true · ledgers_created true · 원장 4종 실재 + 레지스트리 등록
③ 영수증 D0..D9 각 1행(receipt_id 형식 · literal_template_match false) ↔ decisions_resolved 대응 · pending 은 D10 뿐
④ gates.armed false · 예산 4 · prereg_commit null 또는 hex ⑤ 자동화 부재(verb·워크플로·패키지 0) ⑥ θ 동결값
⑦ V13 prohibitions 전부 승계 + V14 3건 ⑧ seed 20261021 · 홀드아웃 재사용 불허 ⑨ P0 진단 JSON 라벨 미접촉·평가 0
⑩ 서술 문서의 개명 주 ⑪ 미구현 도구 이름 미기재
⑫ rung-1 사전등록이 P0 산출물에 고정됨 — 등록 블록 = P0 registration · P0 제안 제외(R3·guard untestable) ⊆ excluded_cells ·
   planned_tests = (ok + episode_thin) × 블록 · diagnostics_content_hash = P0 content_hash · 라벨 원장 미기재 · uncertainty = gate
⑬ 공시 — bootstrap 실제 import 경로(v13_vol_run.block_boot_ci · _boot_lower_fast) · 구현 도구 2종 · numbers_newly_computed_at_draft.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v14_conditional.yaml"
PARENT = ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml"
PARENT_COEFFICIENTS = ROOT / "data/timeseries_v13/vol/champion_coefficients.json"
LEDGER_REGISTRY = ROOT / "data/contracts/ledger_registry.yaml"
PREREG_DOC = ROOT / "docs/design/v14_conditional_transition_prereg_draft_261021.md"
P0_DIAGNOSTICS = ROOT / "data/timeseries_v14/prereg/p0_conditional_diagnostics.json"
CLI = ROOT / "src/ai_fc/cli.py"
WORKFLOWS = ROOT / ".github/workflows"
RUNG1 = "rung1_conditional_blocks"

DECISIONS = tuple(f"V14-D{i}" for i in range(10))
LEDGER_IDS = {"experiment_ledger": "timeseries_v14_experiments", "approvals_ledger": "timeseries_v14_approvals",
              "live_ledger": "timeseries_v14_live", "live_resolutions_ledger": "timeseries_v14_live_resolutions"}
V14_NEW_PROHIBITIONS = ("anchoring_mapped_probability_into_llm_digest", "holdout_reuse_of_v13_window",
                        "post_hoc_conditioning_threshold_change")
# 블루프린트 §5.1 — 저장소에 없는 도구. 사전등록에 이름이 나오면 실행 불가능한 약속이 된다.
UNIMPLEMENTED_TOOL_NAMES = ("romano", "benjamini", "holm", "bonferroni", "conformal", "model confidence set", "ladder_mcs")
UNCERTAINTY_KEYS = ("block_length", "replicates", "seed", "interval")


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _parent() -> dict:
    return yaml.safe_load(PARENT.read_text(encoding="utf-8"))


def _p0() -> dict:
    return json.loads(P0_DIAGNOSTICS.read_text(encoding="utf-8"))


def _ledger_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _registry_rows() -> list[dict]:
    payload = yaml.safe_load(LEDGER_REGISTRY.read_text(encoding="utf-8"))
    rows: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if "id" in node and "path" in node:
                rows.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(payload)
    return rows


def test_contract_parses_and_carries_prereg_identity() -> None:
    contract = _contract()
    assert contract["schema_version"] == 1
    assert contract["contract_id"] == "timeseries_v14_conditional"
    assert contract["model_id"] == "event_probability.volatility_v14_conditional"
    assert contract["model_version"] == 14
    assert contract["status"] == "prereg"
    assert contract["lineage"]["parent"] == "timeseries_v13_vol"
    assert contract["lineage"]["parent_untouched"] is True
    assert not (ROOT / "data/contracts/multivariate_timeseries_v14_conditional.draft.yaml").exists(), "개명 뒤 .draft 가 남아 있다"


def test_track_is_open_and_ledgers_exist_and_are_registered() -> None:
    contract = _contract()
    protocol = contract["development_protocol"]
    assert protocol["track_open"] is True
    assert protocol["ledgers_created"] is True
    assert protocol["ledger_append_only"] is True
    assert protocol["preregistered_before_results"] is True
    registry = {row["id"]: row for row in _registry_rows()}
    for key, ledger_id in LEDGER_IDS.items():
        path = protocol[key]
        assert path.startswith("data/timeseries_v14/ledgers/"), key
        assert (ROOT / path).is_file(), f"{key} 원장이 없다: {path}"
        assert ledger_id in registry, f"{ledger_id} 가 ledger_registry 에 없다"
        assert registry[ledger_id]["path"] == path, ledger_id


def test_approvals_ledger_has_one_receipt_per_decision_and_contract_points_at_them() -> None:
    contract = _contract()
    ledger = ROOT / contract["development_protocol"]["approvals_ledger"]
    rows = _ledger_rows(ledger)
    by_decision: dict[str, list[dict]] = {}
    for row in rows:
        by_decision.setdefault(row["decision_id"], []).append(row)
    assert set(by_decision) == set(DECISIONS), sorted(by_decision)
    resolved = contract["decisions_resolved"]
    for decision in DECISIONS:
        assert len(by_decision[decision]) == 1, decision
        row = by_decision[decision][0]
        receipt = f"v14-approval:{decision}:2026-10-22:r1"
        assert row["receipt_id"] == receipt
        assert row["literal_template_match"] is False
        assert row["approval_form"] == "delegated_bundle_instruction"
        assert receipt in str(resolved[decision]), decision
    # D10(champion·verb)은 결과 뒤 정의 · D11(rung-2 집행 여부)은 rung-1 negative_result_protocol 이 만든 결정
    assert set(contract["decisions_pending"]) <= {"V14-D10", "V14-D11"} and "V14-D10" in contract["decisions_pending"]
    assert not set(contract["decisions_pending"]) & set(DECISIONS), "해소된 D0..D9 가 대기 목록에 남아 있다"
    assert "delegated_bundle_instruction" in contract["approvals"]["receipt_form_2026_10_22"]
    assert contract["approvals"]["approval_text_rule"]
    templates = contract["approvals"]["templates"]
    for decision, text in templates.items():
        assert text.startswith(decision) and text.endswith("승인"), decision
    receipts = contract["amendments_applied"]["V14-A1"]["approval_receipts"]
    assert sorted(receipts) == sorted(f"v14-approval:{d}:2026-10-22:r1" for d in DECISIONS)


def test_gates_disarmed_and_budget_and_prereg_commit_shape() -> None:
    contract = _contract()
    assert contract["gates"]["armed"] is False
    assert contract["gates"]["evaluated_candidates"] == 0
    protocol = contract["development_protocol"]
    assert protocol["maximum_development_evaluations"] == 4
    assert 0 <= protocol["evaluations_spent"] <= protocol["maximum_development_evaluations"]
    assert protocol["budget_does_not_carry_from_v13"] is True
    commit = contract["metadata"]["prereg_commit"]
    assert commit is None or re.fullmatch(r"[0-9a-f]{8,40}", str(commit)), commit
    metadata = contract["metadata"]
    assert "numbers_newly_computed" not in metadata, "초안 시점 키는 _at_draft 로 개명됐다 — P0 수치는 더 이상 0 이 아니다"
    assert metadata["numbers_newly_computed_at_draft"] == 0
    assert metadata["p0_numbers_disclosed_in"] == ["episode_guard.measurement.result", f"{RUNG1}.selection_rules_applied"]
    assert contract["episode_guard"]["measurement"]["result"] and contract[RUNG1]["selection_rules_applied"]["result"]
    resources = contract["irreversible"]["resources_consumed_by_this_draft"]
    assert resources == {"holdout": 0, "sealed": 0, "evaluations": 0, "usd": 0}


def test_no_automation_exists_for_v14() -> None:
    # ★ 정지점: 라이브 verb·워크플로·패키지는 V14-D10(설계창 결과 뒤 사용자 결정) 전에는 없다.
    cli_text = CLI.read_text(encoding="utf-8")
    assert "timeseries-v14" not in cli_text
    assert "timeseries_v14" not in cli_text
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        assert "timeseries-v14" not in text and "timeseries_v14" not in text, workflow.name
    assert not (ROOT / "src/ai_fc/timeseries_v14").exists()
    assert not (ROOT / "src/ai_fc/timeseries_v14.py").exists()
    contract = _contract()
    assert contract["live_forward_gate"]["execution_path"] == "absent_by_construction"
    assert contract["irreversible"]["auto_execution_path"] == "absent_by_construction"
    assert contract["irreversible"]["user_approval_text_required"] is True
    assert contract["stopping_points"]["sealed"]["execution_path"] == "absent_by_construction"


def test_v13_holdout_window_is_contaminated_and_not_reusable() -> None:
    contract = _contract()
    holdout = contract["window"]["holdout"]
    assert holdout["window"] == ["2015-01-01", "2018-12-31"]
    assert holdout["status"] == "contaminated_by_construction"
    assert holdout["reuse_allowed"] is False
    assert contract["stopping_points"]["holdout"]["reuse_allowed"] is False
    assert contract["window"]["verdict_window"] == "live_forward"
    assert contract["irreversible"]["holdout_slots"] == 0
    assert contract["prohibitions"]["v14_specific"]["holdout_reuse_of_v13_window"] is True
    parent = _parent()
    assert contract["window"]["design"] == parent["data_policy"]["design_window"]
    assert contract["window"]["split"] == parent["split"]
    assert contract["data_policy"]["source"] == parent["data_policy"]["source"]


def test_theta_is_the_v13_frozen_value() -> None:
    contract, parent = _contract(), _parent()
    theta = contract["targets"]["rv_conditional_transition"]["theta"]
    assert theta == 0.1694207105468098
    assert round(theta, 4) == parent["targets"]["rv_exceedance"]["theta"]
    frozen = json.loads(PARENT_COEFFICIENTS.read_text(encoding="utf-8"))
    assert abs(theta - frozen["rv_nan_fill_median"]) < 1e-12
    assert contract["targets"]["rv_conditional_transition"]["horizons"] == parent["targets"]["rv_exceedance"]["horizons"]


def test_targets_are_six_conditional_cells_with_operational_thresholds() -> None:
    targets = _contract()["targets"]
    vix = targets["vix_conditional_transition"]
    assert vix["K"] == 25 and vix["horizons"] == [5, 21, 63]
    assert "VIX_close_t < 20" in vix["conditioning"]
    assert vix["cells"] == ["cvix25_h5", "cvix25_h21", "cvix25_h63"]
    rv = targets["rv_conditional_transition"]
    assert rv["horizons"] == [5, 21, 63] and "<= theta" in rv["conditioning"]
    assert rv["cells"] == ["crv_h5", "crv_h21", "crv_h63"]
    assert targets["cell_count"] == 6
    assert targets["m1_target_non_overlap"]["status"] == "partial_disclosed"


def test_display_tier_is_internal() -> None:
    publication = _contract()["publication"]
    assert publication["display_tier"] == "t0_internal"
    assert publication["display_tiers_allowed"] == ["t0_internal", "t2_hidden_panel", "t3_live_card"]
    assert publication["holdout_status"] == "not_applicable_live_forward"
    assert publication["reference_opinion_only"] is True
    assert publication["wiring_eligible_cells"] == []


def test_prohibitions_superset_v13_plus_three_new() -> None:
    contract, parent = _contract(), _parent()
    inherited = contract["prohibitions"]["inherited_from_v13"]
    for key, value in parent["prohibitions"].items():
        assert inherited.get(key) is value is True, f"V13 prohibition {key} 누락 또는 완화"
    specific = contract["prohibitions"]["v14_specific"]
    for key in V14_NEW_PROHIBITIONS:
        assert specific[key] is True, key


def test_design_gate_seed_and_form() -> None:
    gate = _contract()["gate"]
    assert gate["uncertainty"]["seed"] == 20261021
    assert gate["uncertainty"]["block_length"] == 13 and gate["uncertainty"]["replicates"] == 2000
    assert gate["uncertainty"]["interval"] == [5, 95]
    assert gate["multiplicity"]["method"] == "family_p_binomial"
    assert gate["negative_control"]["p_permutation_forbidden"] is True
    assert gate["mde"]["printed_before_results"] == "required"
    assert gate["only_implemented_tools"] is True
    assert gate["scoring"] == ["brier", "log_score"]
    live = _contract()["live_forward_gate"]
    assert "20261021" in live["uncertainty"]
    assert live["minimum_matured_origins_per_cell"] == 60


def test_episode_guard_form_is_fixed() -> None:
    guard = _contract()["episode_guard"]
    assert guard["unit"] == "contiguous_run"
    assert guard["min_episodes"] == 5 and guard["marginal_band"] == [3, 4]
    assert guard["below_marginal_action"] == "untestable_by_construction"
    assert guard["min_events_per_half_per_class"] == 20
    assert "측정 후 선택" in guard["measurement"]["disclosure_rule"]


def test_p0_diagnostics_exist_and_are_label_free_with_zero_evaluations() -> None:
    assert P0_DIAGNOSTICS.is_file(), "P0 조건부 진단 JSON 이 없다"
    payload = _p0()
    assert payload["schema"] == "v14_cond_p0_diagnostics"
    assert payload["label_free_section_touches_labels"] is False
    assert payload["guard_section_touches_labels"] is True
    assert payload["label_contact_check"]["label_free_function"] == "label_free_report"
    assert payload["evaluations_consumed"] == 0
    assert payload["holdout_read"] is False and payload["sealed_read"] is False
    assert payload["panel"]["design_window"] == ["2007-01-01", "2014-12-31"]
    from ai_fc.timeseries_v13.contracts import canonical_hash
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    assert canonical_hash(body) == payload["content_hash"]
    assert set(payload["label_free"]["cells"]) == {"cvix25_h5", "cvix25_h21", "cvix25_h63", "crv_h5", "crv_h21", "crv_h63"}
    assert set(payload["label_free"]["registration"]["by_class"]) == {"calendar", "positioning", "regime_memory"}
    assert P0_DIAGNOSTICS.read_bytes().count(b"\r\n") == 0, "LF 만"


# ── ⑫ rung-1 사전등록은 P0 산출물에 고정된다 ─────────────────────────────────
def test_rung1_blocks_and_hash_are_pinned_to_the_p0_registration() -> None:
    contract, p0 = _contract(), _p0()
    rung1 = contract[RUNG1]
    registration = p0["label_free"]["registration"]
    assert [b["id"] for b in rung1["blocks"]] == registration["registered_blocks"]
    assert rung1["diagnostics"] == P0_DIAGNOSTICS.relative_to(ROOT).as_posix()
    assert re.fullmatch(r"[0-9a-f]{64}", rung1["diagnostics_content_hash"])
    assert rung1["diagnostics_content_hash"] == p0["content_hash"], "계약이 가리키는 P0 산출물과 파일의 content_hash 가 다르다"
    assert rung1["diagnostics_content_hash"] in contract["episode_guard"]["measurement"]["measured_by"]
    vacant = sorted(k for k, v in registration["by_class"].items() if v["status"] == "vacant_R4")
    assert vacant == ["regime_memory"] and rung1["regime_memory"] == "vacant_R4"
    for block in rung1["blocks"]:
        klass = block["class"]
        assert registration["by_class"][klass]["registered"] == block["id"], klass
        corr = p0["label_free"]["summary"][block["id"]]["max_abs_corr_vs_conditional_champion"]
        assert abs(block["measured_abs_corr_max_conditional"] - round(corr, 3)) < 1e-9, block["id"]


def test_rung1_excluded_cells_cover_every_p0_proposed_exclusion() -> None:
    contract, p0 = _contract(), _p0()
    rung1 = contract[RUNG1]
    blocks = [b["id"] for b in rung1["blocks"]]
    excluded = {(e["cell"], e["block"]) for e in rung1["excluded_cells"]}
    assert len(excluded) == len(rung1["excluded_cells"]), "excluded_cells 중복"
    for e in p0["label_free"]["registration"]["excluded_cells_proposed"]:          # R3 퇴화(그 블록만)
        assert e["block"] in blocks
        assert (e["cell"], e["block"]) in excluded, e
    guard = p0["guard"]
    for cell in guard["cells_untestable"]:                                           # guard untestable(등록 블록 전부)
        for block in blocks:
            assert (cell, block) in excluded, (cell, block)
    # 러너가 쓰기 전에 강제하는 집합 등식 — 사전등록 제외 셀 집합 == P0 untestable 집합
    assert {e["cell"] for e in rung1["excluded_cells"]} == set(guard["cells_untestable"])
    assert all(e["block"] in blocks for e in rung1["excluded_cells"])
    assert rung1["episode_thin_cells"] == guard["cells_episode_thin"]
    for e in rung1["excluded_cells"]:
        if e["cell"] in guard["cells_untestable"]:
            assert "untestable_by_construction" in e["reason"], e


def test_rung1_planned_tests_equal_eligible_cells_times_registered_blocks() -> None:
    contract, p0 = _contract(), _p0()
    rung1 = contract[RUNG1]
    guard = p0["guard"]
    eligible = len(guard["cells_ok"]) + len(guard["cells_episode_thin"])
    assert eligible + len(guard["cells_untestable"]) == 6
    assert rung1["planned_tests"] == eligible * len(rung1["blocks"])
    assert rung1["planned_tests"] == 6 * len(rung1["blocks"]) - len(rung1["excluded_cells"])


def test_rung1_prereg_shape_budget_index_and_uncertainty_coordinates() -> None:
    contract = _contract()
    rung1 = contract[RUNG1]
    commit = rung1["prereg_commit"]
    assert commit is None or re.fullmatch(r"[0-9a-f]{8,40}", str(commit)), commit
    protocol = contract["development_protocol"]
    ledger = ROOT / protocol["experiment_ledger"]
    rows = _ledger_rows(ledger)
    assert rung1["results_path"].startswith("data/timeseries_v14/")
    results = ROOT / rung1["results_path"]
    executed = [r for r in rows if r.get("experiment_label") == rung1["experiment_label"]]
    if not executed:
        # 집행 전 상태 — 결과 파일이 없고 다음 평가 순번이어야 한다
        assert not results.exists(), "결과 전 커밋 전에 결과 파일이 있다"
        spent = max(int(protocol["evaluations_spent"]), len(rows))
        assert rung1["evaluation_index"] == spent + 1 <= protocol["maximum_development_evaluations"]
    else:
        # 집행 후 상태 — 원장 1행, 그 행이 사전등록 커밋·순번·결과 파일 해시를 가리킨다(예산은 원장과 대사)
        assert len(executed) == 1, "평가 예산은 1회용이다 — 같은 라벨이 두 번 원장에 있다"
        row = executed[0]
        assert commit and row["prereg_commit"] == commit
        assert row["evaluation_index"] == rung1["evaluation_index"]
        assert results.is_file()
        assert hashlib.sha256(results.read_bytes()).hexdigest() == row["results_sha256"]
        assert int(protocol["evaluations_spent"]) == len(rows) <= protocol["maximum_development_evaluations"]
    gate_unc = contract["gate"]["uncertainty"]
    for key in UNCERTAINTY_KEYS:
        assert rung1["uncertainty"][key] == gate_unc[key], key
    assert rung1["backtest_windows_opened"] == 0 and rung1["holdout_slot_consumed"] == 0
    assert rung1["window"] == contract["window"]["design"] and rung1["split"] == contract["window"]["split_date"]


# ── ⑬ 공시 — 실제 import 경로 · 구현 도구 ────────────────────────────────────
def test_contract_discloses_actual_bootstrap_paths_and_the_two_implemented_tools() -> None:
    contract = _contract()
    impl = contract["gate"]["uncertainty"]["implementation"]
    assert "tools/v13_vol_run.block_boot_ci" in impl
    assert "tools/v13_vol_rung3_pb.paired_model_ci" in impl
    assert "tools/v13_vol_run._boot_lower_fast" in impl and "b=400" in impl
    assert "src/ai_fc/timeseries_v13/contracts.py" in impl
    assert "src/ai_fc/timeseries_v13/features.py" not in impl, "bootstrap 은 features.py 에 없다 — 옛 문구"
    known = "\n".join(contract["known_limits"])
    assert "tools/v14_cond_diagnostics.py" in known and "tools/v14_cond_run.py" in known
    assert "라이브 verb" in known and "없다" in known
    assert "조건부 PB 적합기·라이브 verb 가 **없다**" not in known, "구현 전 문구가 남아 있다"
    assert (ROOT / "tools/v14_cond_diagnostics.py").is_file() and (ROOT / "tools/v14_cond_run.py").is_file()
    assert "_boot_lower_fast" in (ROOT / "tools/v13_vol_run.py").read_text(encoding="utf-8")


def test_contract_names_no_unimplemented_tools() -> None:
    text = CONTRACT.read_text(encoding="utf-8").lower()
    for name in UNIMPLEMENTED_TOOL_NAMES:
        assert name not in text, name


def test_candidate_store_is_not_ingested_and_pool_is_fixed() -> None:
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
    assert json.loads(diagnostics.read_text(encoding="utf-8"))["label_free"] is True


def test_prereg_document_carries_the_rename_note() -> None:
    text = PREREG_DOC.read_text(encoding="utf-8")
    assert "2026-10-22" in text
    assert "multivariate_timeseries_v14_conditional.yaml" in text
    assert "v14-approval:V14-D0:2026-10-22:r1" in text
    assert "contaminated_by_construction" in text
