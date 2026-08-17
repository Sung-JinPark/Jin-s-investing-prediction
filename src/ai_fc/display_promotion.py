"""Read-only display-promotion gate; model/champion promotion remains separate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


CONTRACT_RELATIVE = Path("data/contracts/display_promotion.yaml")
RECEIPTS_RELATIVE = Path("data/display_promotions/approval_receipts.jsonl")


class DisplayPromotionError(ValueError):
    pass


def _customer_unavailable(reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": "display_promotion_v2",
        "decision_id": None,
        "default_route": "unavailable",
        "gate_pass": False,
        "gates": {"display_promotion_contract_available": False},
        "semantic_reference": {},
        "operator_approval_status": "unavailable",
        "persistent_banner_text": None,
        "explicit_research_route_available": False,
        "withdrawal_action": "candidate_unavailable_no_legacy_fallback",
        "reason": reason,
    }


def _receipts(root: Path) -> list[dict[str, Any]]:
    path = root / RECEIPTS_RELATIVE
    if not path.is_file():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise DisplayPromotionError(
                f"invalid display approval receipt at line {line_number}"
            ) from exc
    return rows


def load_display_promotion(root: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    contract_path = root / CONTRACT_RELATIVE
    if not contract_path.is_file():
        return _customer_unavailable("display promotion contract unavailable")
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if contract.get("schema_version") != 1 or contract.get("status") != "active":
        raise DisplayPromotionError("display promotion contract invalid")
    decision = contract.get("active_decision") or {}
    expected = decision.get("candidate") or {}
    actual = candidate.get("semantic_reference") or {}
    semantic_match = all(
        expected.get(key) == actual.get(key)
        for key in ("candidate_id", "model_version", "rules_version")
    )
    method_rows = [
        json.loads(line) for line in (root / "data/method_changes.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    disclosure_present = any(
        row.get("event_id") == decision.get("method_disclosure_event_id")
        for row in method_rows
    )
    receipt_id = decision.get("operator_approval_receipt_id")
    receipt = next(
        (row for row in _receipts(root) if row.get("receipt_id") == receipt_id),
        None,
    ) if receipt_id else None
    receipt_valid = bool(
        receipt
        and receipt.get("decision_id") == decision.get("decision_id")
        and receipt.get("semantic_reference") == expected
        and receipt.get("approval_text")
    )
    proof_path = root / str(decision.get("render_proof_path") or "")
    render_proof = None
    if proof_path.is_file():
        try:
            render_proof = json.loads(proof_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DisplayPromotionError("display promotion render proof invalid") from exc
    render_proof_valid = bool(
        render_proof
        and render_proof.get("three_scenario_chart_visible") is True
        and render_proof.get("internal_gate_copy_absent") is True
        and set(render_proof.get("viewports") or []) >= {"1280", "390"}
        and render_proof.get("semantic_reference") == expected
    )
    runtime_eligible = (
        candidate.get("status") in {"ok", "degraded"}
        and candidate.get("runtime_gate", {}).get("display_eligible") is not False
    )
    gates = {
        "append_only_method_disclosure": disclosure_present,
        "operator_approval_receipt": receipt_valid,
        "render_proof_for_desktop_and_mobile": render_proof_valid,
        "three_scenario_chart_visible": bool(
            render_proof and render_proof.get("three_scenario_chart_visible") is True
        ),
        "internal_gate_copy_absent": bool(
            render_proof and render_proof.get("internal_gate_copy_absent") is True
        ),
        "candidate_runtime_gate_display_eligible": runtime_eligible,
        "semantic_reference_match": semantic_match,
    }
    gate_pass = all(gates.values())
    return {
        "schema_version": 1,
        "contract_id": contract["contract_id"],
        "decision_id": decision.get("decision_id"),
        "default_route": "three_scenario_customer_default" if gate_pass else "unavailable",
        "gate_pass": gate_pass,
        "gates": gates,
        "semantic_reference": expected,
        "operator_approval_status": (
            "approved" if receipt_valid else decision.get("operator_approval_status")
        ),
        "persistent_banner_text": None,
        "explicit_research_route_available": False,
        "withdrawal_action": "candidate_unavailable_no_legacy_fallback",
    }
