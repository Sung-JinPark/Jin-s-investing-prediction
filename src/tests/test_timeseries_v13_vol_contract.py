"""V13-VOL 계약 불변식 — V13-D2′ 사전등록 개정(2026-09-08) 이후의 정직성 고정.

원문 gate: 블록·표적·분할·홀드아웃 창은 결과 뒤에도 1바이트도 바뀌지 않아야 하고,
champion·finalist·홀드아웃 verb 의 존재는 계약 상태와 원장에 대사되어야 한다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml"
EXPERIMENTS = ROOT / "data/timeseries_v13/ledgers/vol_experiments.jsonl"
APPROVALS = ROOT / "data/timeseries_v13/ledgers/approvals.jsonl"
REGISTRY = ROOT / "data/contracts/ledger_registry.yaml"
CLI = ROOT / "src/ai_fc/cli.py"

# 사전등록 원문 리터럴 — 결과 뒤 완화 금지 (gate_threshold_relaxation).
FROZEN_GATE = {
    "primary": "각 rung(≠기후)이 기후 대비 쌍대 Brier 손실차 CI90 하한 > 0 (엄격부등호)",
    "bidirectional_transfer": "early(2007-2010) <-> late(2011-2014) 두 방향 모두 CI90 하한 > 0",
    "uncertainty": {"bootstrap": "stationary_block", "block_length": 13, "replicates": 2000,
                    "seed": 20260907, "interval": [5, 95]},
    "negative_control_threshold": "통과율 <= 0.10. 초과 시 그 rung 의 채택 무효.",
}
FROZEN_TARGETS = {"K": [25, 30], "horizons": [5, 21, 63], "theta": 0.1694}


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preregistered_gate_form_is_byte_stable() -> None:
    gate = _contract()["gate"]
    assert gate["primary"] == FROZEN_GATE["primary"]
    assert gate["bidirectional_transfer"] == FROZEN_GATE["bidirectional_transfer"]
    assert gate["uncertainty"] == FROZEN_GATE["uncertainty"]
    assert gate["negative_control"]["threshold"] == FROZEN_GATE["negative_control_threshold"]
    targets = _contract()["targets"]
    assert targets["vix_touch"]["K"] == FROZEN_TARGETS["K"]
    assert targets["vix_touch"]["horizons"] == FROZEN_TARGETS["horizons"]
    assert targets["rv_exceedance"]["horizons"] == FROZEN_TARGETS["horizons"]
    assert targets["rv_exceedance"]["theta"] == FROZEN_TARGETS["theta"]
    assert _contract()["split"] == {"early": ["2007-01-01", "2010-12-31"], "late": ["2011-01-01", "2014-12-31"]}
    assert _contract()["stopping_points"]["holdout"]["window"] == ["2015-01-01", "2018-12-31"]
    assert _contract()["data_policy"]["design_window"] == ["2007-01-01", "2014-12-31"]


def test_evaluation_budget_reconciles_with_experiment_ledger() -> None:
    protocol = _contract()["development_protocol"]
    assert protocol["evaluations_spent"] == len(_rows(EXPERIMENTS))
    assert protocol["evaluations_spent"] <= protocol["maximum_development_evaluations"]
    assert protocol["ledger_append_only"] is True
    assert protocol["preregistered_before_results"] is True


def test_holdout_protocol_is_preregistered_and_finalist_bounded() -> None:
    contract = _contract()
    protocol = contract["development_protocol"]
    assert protocol["holdout_maximum_finalists"] == 3
    assert protocol["holdout_finalists_preregistered"] == ["V13VOL_champion"]
    assert protocol["holdout_single_scoring_per_finalist"] is True
    assert protocol["holdout_requires_explicit_user_approval"] is True
    assert protocol["holdout_execution_path"] in {"absent_by_construction", "named_verb_guarded"}
    holdout = contract["stopping_points"]["holdout"]
    assert holdout["requires_explicit_user_approval"] is True
    gate = holdout["gate"]
    for key in ("G1_vs_climatology", "G2_not_inferior_to_pb", "G3_reliability_report",
                "G4_negative_control", "pass_rule"):
        assert key in gate
    assert "0.10" in gate["G4_negative_control"]
    assert "재적합하지 않는다" in holdout["model_source"]
    assert "2018-12-31" in holdout["origins"]


def test_obvious_baseline_rule_and_new_prohibitions_are_armed() -> None:
    contract = _contract()
    prohibitions = contract["prohibitions"]
    for key in ("champion_on_climatology_alone", "holdout_refit", "sealed_bytes_in_holdout_panel",
                "automatic_holdout_consumption", "gate_threshold_relaxation",
                "p_permutation_null_as_negative_control", "mutate_v8_v2"):
        assert prohibitions[key] is True, key
    pb = contract["baselines"]["persistence_pb"]
    assert pb["nested_in"] == "ewma_logit"
    assert pb["registered_before_results"] is True
    rule = contract["gates"]["G2_champion_vs_persistence_pb"]["rule"]
    assert "persistence_pb" in rule and "HOLD" in rule


def test_design_evidence_pins_match_files_and_ledger() -> None:
    contract = _contract()
    experiments = {row["experiment_label"]: row for row in _rows(EXPERIMENTS)}
    evidence = contract["gates"]["design_evidence"]
    for rung, label in (("ewma_logit", "V13VOL_ewma_logit"), ("har_logistic", "V13VOL_har_logit")):
        pin = evidence[rung]
        assert _sha256(ROOT / pin["path"]) == pin["sha256"], rung
        assert experiments[label]["content_hash"] == pin["ledger_content_hash"], rung


def test_champion_state_reconciles_with_rung3_ledger_row() -> None:
    # C-1(rung-3) 전에는 champion null 이고 원장에 PB 행이 없다; 뒤에는 서로 대사되어야 한다.
    contract = _contract()
    champion = contract["gates"]["champion"]
    pb_rows = [row for row in _rows(EXPERIMENTS) if row.get("rung") == "persistence_pb_g2"]
    if champion["finalist_id"] is None:
        assert champion["cells"] == {} and champion["source_content_hash"] is None
        assert pb_rows == []
    else:
        assert len(pb_rows) == 1
        assert pb_rows[0]["content_hash"] == champion["source_content_hash"]
        assert pb_rows[0]["finalist_id"] == champion["finalist_id"]
        assert set(champion["cells"].values()) <= {"ewma_logit", "persistence_pb", "hold"}
        assert any(v != "hold" for v in champion["cells"].values())
        frozen = contract["frozen_coefficients"]
        if frozen["sha256"] is not None:
            assert frozen["finalist_id"] == champion["finalist_id"]
            assert _sha256(ROOT / frozen["path"]) == frozen["sha256"]


def test_display_tier_cannot_outrun_arming_or_holdout_caveat() -> None:
    contract = _contract()
    publication = contract["publication"]
    assert publication["display_tier"] in publication["display_tiers_allowed"]
    assert "t4" not in " ".join(publication["display_tiers_allowed"]).lower()
    assert publication["reference_opinion_only"] is True
    if publication["display_tier"] != "t0_internal":
        assert contract["gates"]["armed"] is True
        assert contract["frozen_coefficients"]["sha256"] is not None
    if publication["display_tier"] == "t3_live_card" and publication["holdout_status"] != "pass":
        assert publication["t3_without_holdout_requires_bold_caveat"] is True


def test_no_holdout_verb_exists_while_execution_path_is_absent() -> None:
    # ★ 정지점: 승인 원문 없이는 verb 자체가 없다 (V9 패턴). 승인 뒤에는 receipt 가 있어야 한다.
    contract = _contract()
    path = contract["development_protocol"]["holdout_execution_path"]
    cli_text = CLI.read_text(encoding="utf-8")
    module = ROOT / "src/ai_fc/timeseries_v13/holdout.py"
    approvals = _rows(APPROVALS)
    if path == "absent_by_construction":
        assert "timeseries-v13-vol-holdout" not in cli_text
        assert not module.exists()
        assert not (ROOT / contract["development_protocol"]["holdout_ledger"]).exists()
    else:
        assert "timeseries-v13-vol-holdout" in cli_text
        assert module.exists()
        assert any(row["decision_id"] == "V13-D3" and row["approval_text"].strip() for row in approvals)
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert not [w for w in workflows if "timeseries-v13-vol-holdout" in w.read_text(encoding="utf-8")]


def test_approvals_ledger_carries_the_amendment_receipt() -> None:
    rows = _rows(APPROVALS)
    required = {"receipt_id", "decision_id", "approved_at", "approver_role", "approval_text",
                "approval_scope", "conditions", "semantic_reference", "source"}
    for row in rows:
        assert required <= set(row), row.get("receipt_id")
        assert row["approver_role"] == "repository_owner_and_operator"
        assert row["approval_text"].strip()
    receipt = _contract()["amendments_applied"]["V13-D2prime"]["approval_receipt"]
    assert any(row["receipt_id"] == receipt and row["decision_id"] == "V13-D2′" for row in rows)
    assert _contract()["amendments_applied"]["V13-D2prime"]["unchanged"]


def test_v13_ledgers_are_registered() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["ledgers"]
    ids = {row["id"]: row for row in registry}
    for ledger_id in ("timeseries_v13_vol_experiments", "timeseries_v13_holdout_scorings",
                      "timeseries_v13_approvals", "timeseries_v13_vol_live",
                      "timeseries_v13_vol_ladder_results"):
        assert ledger_id in ids, ledger_id
    contract = _contract()
    assert ids["timeseries_v13_holdout_scorings"]["path"] == contract["development_protocol"]["holdout_ledger"]
    assert ids["timeseries_v13_approvals"]["path"] == contract["development_protocol"]["approvals_ledger"]
    assert ids["timeseries_v13_vol_live"]["path"] == contract["live_display"]["ledger"]
    assert ids["timeseries_v13_vol_ladder_results"]["kind"] == "immutable_files"
