from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_fc.cli import app
from ai_fc.scenario_shadow.contracts import (
    RCFHS_REQUIRED_CAPABILITIES,
    ScenarioShadowContractError,
    validate_candidate_payload,
    validate_model_identity,
)
from ai_fc.scenario_v4_shadow import load_shadow


ROOT = Path(__file__).resolve().parents[2]
OLD_SHA = "cd2bb86b37b2e9cbe6c5c370e3bbd3cc6f21a8953727732c8b4fc27590ee70ca"


def test_pr2_misidentified_artifact_is_retired_with_hash_preserved() -> None:
    old_latest = ROOT / "data/scenarios/shadow/rcfhs_sb_v1_latest.json"
    archived = (
        ROOT
        / "data/scenarios/shadow/archive"
        / "rcfhs_sb_v1_misidentified_20260807_cd2bb86b.json"
    )
    receipt = json.loads(
        (ROOT / "data/scenarios/shadow/archive/rcfhs_sb_v1_retirement_receipt.json")
        .read_text(encoding="utf-8")
    )

    assert not old_latest.exists()
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == OLD_SHA
    assert receipt["original_sha256"] == OLD_SHA
    assert receipt["official_snapshot_affected"] is False


def test_rcfhs_identity_is_rejected_without_capabilities() -> None:
    payload = {
        "candidate_id": "nasdaq_rcfhs_sb_shadow",
        "status": "shadow_only",
        "promotion_state": "blocked_pending_rolling_origin_validation",
        "model_identity": {
            "family": "rcfhs_sb",
            "is_rcfhs": True,
            "capabilities": {},
        },
    }
    with pytest.raises(ScenarioShadowContractError, match="capability_evidence"):
        validate_model_identity(payload)


def test_rcfhs_identity_requires_evidence_for_every_capability() -> None:
    payload = {
        "candidate_id": "nasdaq_rcfhs_sb_shadow",
        "status": "shadow_only",
        "promotion_state": "blocked_pending_rolling_origin_validation",
        "model_identity": {
            "family": "rcfhs_sb",
            "is_rcfhs": True,
            "capabilities": {key: True for key in RCFHS_REQUIRED_CAPABILITIES},
            "capability_evidence": {
                key: {
                    "implementation_component": "module.symbol",
                    "test_receipt": "test_name",
                    "input_lineage": "source-sha",
                }
                for key in RCFHS_REQUIRED_CAPABILITIES
            },
        },
    }
    payload["model_identity"]["capability_evidence"]["approved_pit_history"].pop(
        "input_lineage"
    )
    with pytest.raises(ScenarioShadowContractError, match="input_lineage"):
        validate_model_identity(payload)


def test_retired_candidate_is_not_exposed() -> None:
    active = load_shadow(ROOT)
    assert active is not None
    assert active["candidate_id"] == "legacy_gbm_actual_member_v1"
    assert "rcfhs" not in active["candidate_id"]


def test_retired_cli_exits_nonzero_and_writes_no_artifact() -> None:
    latest = ROOT / "data/scenarios/shadow/rcfhs_sb_v1_latest.json"
    result = CliRunner().invoke(app, ["scenario-v4-shadow"])

    assert result.exit_code == 2
    assert "was retired" in result.output
    assert "no artifact was written" in result.output
    assert not latest.exists()


def test_active_dashboard_has_no_incorrect_pr2_labels() -> None:
    source = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(
        encoding="utf-8"
    )
    assert "RCFHS-SB v1 official" not in source
    assert "RCFHS-SB v1 shadow" not in source


def test_candidate_contract_rejects_probability_sum_or_status_drift() -> None:
    candidate = json.loads(
        (ROOT / "data/scenarios/shadow/legacy_gbm_actual_member_v1_latest.json")
        .read_text(encoding="utf-8")
    )
    candidate["official_weights"]["values"]["S1"] = 0.82
    with pytest.raises(ScenarioShadowContractError, match="sum to 1"):
        validate_candidate_payload(candidate)

    candidate["official_weights"]["values"]["S1"] = 0.83
    candidate["status"] = "official"
    with pytest.raises(ScenarioShadowContractError, match="stored candidate status"):
        validate_candidate_payload(candidate)


def test_official_snapshot_hash_unchanged() -> None:
    official = ROOT / "data/scenarios/nasdaq_latest.json"
    assert hashlib.sha256(official.read_bytes()).hexdigest() == (
        "7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c"
    )
