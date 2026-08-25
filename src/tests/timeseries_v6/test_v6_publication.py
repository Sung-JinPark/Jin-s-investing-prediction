from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ai_fc.timeseries_v6.publication import (
    PromotionError,
    publication_policy_manifest,
    unsigned_decision_payload,
    validate_promotion_decision,
)


ROOT = Path(__file__).resolve().parents[3]


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _decision() -> dict[str, object]:
    decision: dict[str, object] = {
        "schema_version": 1,
        "decision_id": "v6-owner-decision-test",
        "decision_status": "approved",
        "scope": "limited_research_display",
        "owner_id": "owner:test",
        "owner_approval": True,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "contract_hash": "a" * 64,
        "candidate_bundle_hash": "b" * 64,
        "gate_decision_hash": "c" * 64,
        "gate_results": {
            "integrity_gate": True,
            "research_gate": True,
            "operational_gate": True,
        },
        "automatic_action": False,
    }
    decision["detached_signature_receipt"] = {
        "method": "github_environment_attestation",
        "signer": "owner:test",
        "signed_payload_sha256": _hash(unsigned_decision_payload(decision)),
        "signature_sha256": "d" * 64,
        "verified_by": "github-environment",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "protected_environment": "timeseries-v6-production-approval",
    }
    return decision


def _validate(decision: dict[str, object]) -> dict[str, object]:
    return validate_promotion_decision(
        decision,
        expected_contract_hash="a" * 64,
        expected_candidate_bundle_hash="b" * 64,
        expected_gate_decision_hash="c" * 64,
        trusted_owner_ids={"owner:test"},
    )


def test_complete_manual_decision_validates_but_does_not_execute() -> None:
    receipt = _validate(_decision())
    assert receipt["publication_authorized"] is True
    assert receipt["automatic_action"] is False


@pytest.mark.parametrize("gate", ["integrity_gate", "research_gate", "operational_gate"])
def test_any_failed_gate_blocks_manual_decision(gate: str) -> None:
    decision = _decision()
    decision["gate_results"][gate] = False  # type: ignore[index]
    with pytest.raises(PromotionError, match="all V6 Gates"):
        _validate(decision)


def test_missing_owner_or_bad_signature_receipt_blocks() -> None:
    decision = _decision()
    decision["owner_approval"] = False
    with pytest.raises(PromotionError, match="owner"):
        _validate(decision)
    decision = _decision()
    decision["detached_signature_receipt"]["signed_payload_sha256"] = "0" * 64  # type: ignore[index]
    with pytest.raises(PromotionError, match="payload hash"):
        _validate(decision)


def test_manual_workflow_has_no_schedule_write_or_deploy_path() -> None:
    workflow_path = ROOT / ".github/workflows/timeseries-v6-manual-promotion.yml"
    text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow.get("on") if "on" in workflow else workflow.get(True)
    assert set(triggers) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    lowered = text.lower()
    for forbidden in ("git push", "gh pr", "deploy-pages", "pages: write", "contents: write", "--auto-merge"):
        assert forbidden not in lowered
    assert "persist-credentials: false" in lowered


def test_policy_manifest_is_manual_only() -> None:
    policy = publication_policy_manifest()
    assert all(
        policy[key] is False
        for key in (
            "automatic_commit", "automatic_push", "automatic_pr",
            "automatic_merge", "automatic_pages_deploy", "automatic_customer_numbers",
        )
    )
    assert policy["signed_decision_required"] is True
