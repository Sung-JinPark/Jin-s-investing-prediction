"""Manual-only V6 promotion boundary.

Research workers can propose a Gate decision but cannot approve, publish, or
change Git state.  A detached approval receipt is validated only in a protected
manual environment.  This module never performs commit, push, merge, Pages
deployment, or customer-data mutation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class PromotionError(RuntimeError):
    """Raised when a manual promotion decision is absent or inconsistent."""


ALLOWED_SCOPE = "limited_research_display"
REQUIRED_GATE_NAMES = ("integrity_gate", "research_gate", "operational_gate")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def unsigned_decision_payload(decision: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in decision.items() if key != "detached_signature_receipt"}


def validate_promotion_decision(
    decision: Mapping[str, Any],
    *,
    expected_contract_hash: str,
    expected_candidate_bundle_hash: str,
    expected_gate_decision_hash: str,
    trusted_owner_ids: set[str],
) -> dict[str, Any]:
    """Validate an externally approved, detached-signature receipt fail closed."""

    required = {
        "schema_version", "decision_id", "decision_status", "scope",
        "owner_id", "owner_approval", "approved_at", "contract_hash",
        "candidate_bundle_hash", "gate_decision_hash", "gate_results",
        "automatic_action", "detached_signature_receipt",
    }
    missing = sorted(required - set(decision))
    if missing:
        raise PromotionError(f"promotion decision fields missing: {missing}")
    if decision["schema_version"] != 1:
        raise PromotionError("unsupported promotion decision schema")
    if decision["decision_status"] != "approved" or decision["owner_approval"] is not True:
        raise PromotionError("explicit owner approval is required")
    if decision["scope"] != ALLOWED_SCOPE:
        raise PromotionError("promotion scope is not customer-safe limited research display")
    if decision["owner_id"] not in trusted_owner_ids:
        raise PromotionError("promotion owner is not trusted")
    if decision["automatic_action"] is not False:
        raise PromotionError("automatic promotion/publication is prohibited")
    if decision["contract_hash"] != expected_contract_hash:
        raise PromotionError("promotion contract hash mismatch")
    if decision["candidate_bundle_hash"] != expected_candidate_bundle_hash:
        raise PromotionError("promotion candidate bundle hash mismatch")
    if decision["gate_decision_hash"] != expected_gate_decision_hash:
        raise PromotionError("promotion Gate decision hash mismatch")
    gates = decision["gate_results"]
    if not isinstance(gates, dict) or any(gates.get(name) is not True for name in REQUIRED_GATE_NAMES):
        raise PromotionError("all V6 Gates must pass before a promotion decision")
    try:
        approved = datetime.fromisoformat(str(decision["approved_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionError("approved_at is not RFC3339") from exc
    if approved.tzinfo is None or approved > datetime.now(timezone.utc):
        raise PromotionError("approved_at must be an aware, non-future timestamp")
    signature = decision["detached_signature_receipt"]
    signature_required = {
        "method", "signer", "signed_payload_sha256", "signature_sha256",
        "verified_by", "verified_at", "protected_environment",
    }
    if not isinstance(signature, dict) or signature_required - set(signature):
        raise PromotionError("complete detached signature verification receipt required")
    if signature["method"] not in {"gpg_detached", "sigstore_bundle", "github_environment_attestation"}:
        raise PromotionError("unapproved detached signature method")
    if signature["signer"] != decision["owner_id"]:
        raise PromotionError("signature signer does not match approved owner")
    if signature["protected_environment"] != "timeseries-v6-production-approval":
        raise PromotionError("signature was not verified in the protected environment")
    if signature["signed_payload_sha256"] != _sha256(unsigned_decision_payload(decision)):
        raise PromotionError("detached signature payload hash mismatch")
    if not isinstance(signature["signature_sha256"], str) or len(signature["signature_sha256"]) != 64:
        raise PromotionError("detached signature artifact hash is invalid")
    return {
        "schema_version": 1,
        "decision_id": decision["decision_id"],
        "decision_hash": _sha256(decision),
        "scope": decision["scope"],
        "owner_id": decision["owner_id"],
        "gates_pass": True,
        "signature_receipt_pass": True,
        "publication_authorized": True,
        "automatic_action": False,
    }


def load_and_validate_decision(
    path: Path,
    *,
    expected_contract_hash: str,
    expected_candidate_bundle_hash: str,
    expected_gate_decision_hash: str,
    trusted_owner_ids: set[str],
) -> dict[str, Any]:
    if not path.is_file():
        raise PromotionError(f"promotion decision does not exist: {path}")
    decision = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decision, dict):
        raise PromotionError("promotion decision must be a JSON object")
    return validate_promotion_decision(
        decision,
        expected_contract_hash=expected_contract_hash,
        expected_candidate_bundle_hash=expected_candidate_bundle_hash,
        expected_gate_decision_hash=expected_gate_decision_hash,
        trusted_owner_ids=trusted_owner_ids,
    )


def publication_policy_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "automatic_commit": False,
        "automatic_push": False,
        "automatic_pr": False,
        "automatic_merge": False,
        "automatic_pages_deploy": False,
        "automatic_customer_numbers": False,
        "manual_workflow": ".github/workflows/timeseries-v6-manual-promotion.yml",
        "protected_environment": "timeseries-v6-production-approval",
        "required_gates": list(REQUIRED_GATE_NAMES),
        "required_scope": ALLOWED_SCOPE,
        "signed_decision_required": True,
    }
