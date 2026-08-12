from __future__ import annotations

import json
from pathlib import Path

import yaml

from ai_fc import config
from ai_fc.display_promotion import load_display_promotion


SEMANTIC_REFERENCE = {
    "candidate_id": "scenario_v5_2_scenario_clustered_db_v4",
    "model_version": "complete_separation_empirical_episode_databases_v6",
    "rules_version": "weights-v3+complete-separation-v1",
}


def _candidate() -> dict:
    return {
        "status": "degraded",
        "semantic_reference": SEMANTIC_REFERENCE,
        "runtime_gate": {"display_eligible": True},
    }


def _root(tmp_path: Path) -> tuple[Path, dict]:
    contract = yaml.safe_load(
        (config.ROOT / "data/contracts/display_promotion.yaml")
        .read_text(encoding="utf-8")
    )
    decision = contract["active_decision"]
    decision["operator_approval_receipt_id"] = "display-approval:test:r1"
    decision["render_proof_path"] = "evidence/render_proof.json"
    path = tmp_path / "data/contracts/display_promotion.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(contract, allow_unicode=True), encoding="utf-8")
    method_path = tmp_path / "data/method_changes.jsonl"
    method_path.parent.mkdir(parents=True, exist_ok=True)
    method_path.write_text(json.dumps({
        "event_id": decision["method_disclosure_event_id"],
    }) + "\n", encoding="utf-8")
    return tmp_path, decision


def test_missing_contract_fails_closed_to_champion(tmp_path: Path) -> None:
    result = load_display_promotion(tmp_path, _candidate())
    assert result["gate_pass"] is False
    assert result["default_route"] == "champion"
    assert result["gates"] == {"display_promotion_contract_available": False}


def test_approval_and_render_proof_are_both_required(tmp_path: Path) -> None:
    root, decision = _root(tmp_path)
    pending = load_display_promotion(root, _candidate())
    assert pending["gate_pass"] is False
    assert pending["gates"]["operator_approval_receipt"] is False
    assert pending["gates"]["render_proof_for_desktop_and_mobile"] is False

    receipt_path = root / "data/display_promotions/approval_receipts.jsonl"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps({
        "receipt_id": decision["operator_approval_receipt_id"],
        "decision_id": decision["decision_id"],
        "approval_text": "explicit test approval",
        "semantic_reference": SEMANTIC_REFERENCE,
    }) + "\n", encoding="utf-8")
    proof_path = root / decision["render_proof_path"]
    proof_path.parent.mkdir(parents=True)
    proof_path.write_text(json.dumps({
        "persistent_banner_visible": True,
        "viewports": ["1280", "390"],
        "semantic_reference": SEMANTIC_REFERENCE,
    }), encoding="utf-8")

    active = load_display_promotion(root, _candidate())
    assert active["gate_pass"] is True
    assert active["default_route"] == "research_candidate"


def test_semantic_reference_mismatch_withdraws_display_promotion(
    tmp_path: Path,
) -> None:
    root, decision = _root(tmp_path)
    receipt_path = root / "data/display_promotions/approval_receipts.jsonl"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps({
        "receipt_id": decision["operator_approval_receipt_id"],
        "decision_id": decision["decision_id"],
        "approval_text": "explicit test approval",
        "semantic_reference": SEMANTIC_REFERENCE,
    }) + "\n", encoding="utf-8")
    proof_path = root / decision["render_proof_path"]
    proof_path.parent.mkdir(parents=True)
    proof_path.write_text(json.dumps({
        "persistent_banner_visible": True,
        "viewports": ["1280", "390"],
        "semantic_reference": SEMANTIC_REFERENCE,
    }), encoding="utf-8")
    candidate = _candidate()
    candidate["semantic_reference"] = {
        **SEMANTIC_REFERENCE,
        "rules_version": "unexpected-refresh-rule",
    }
    result = load_display_promotion(root, candidate)
    assert result["gate_pass"] is False
    assert result["gates"]["semantic_reference_match"] is False
    assert result["default_route"] == "champion"
