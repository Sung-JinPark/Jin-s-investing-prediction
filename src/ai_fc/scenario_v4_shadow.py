"""Compatibility boundary for the retired PR2 Scenario V4 candidate.

PR2 published a legacy GBM wrapper under an RCFHS identity.  The original
artifact is preserved byte-for-byte in the shadow audit archive, but this
module intentionally exposes no active candidate and performs no writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .scenario_shadow.contracts import (
    ScenarioShadowContractError,
    validate_candidate_payload,
)
from .scenario_shadow.persistence import load_candidate


RETIRED_CANDIDATE_ID = "rcfhs-sb-v1"
RETIRED_REASON = "model_identity_mismatch_not_actual_rcfhs"
RETIRED_ARCHIVE_RELATIVE_PATH = (
    Path("data")
    / "scenarios"
    / "shadow"
    / "archive"
    / "rcfhs_sb_v1_misidentified_20260807_cd2bb86b.json"
)


class ScenarioV4ShadowError(ScenarioShadowContractError):
    """Backward-compatible contract error name."""


def build_shadow_payload(source: dict[str, Any]) -> dict[str, Any]:
    """Reject attempts to rebuild the retired, misidentified PR2 candidate."""
    del source
    raise ScenarioV4ShadowError(
        f"{RETIRED_CANDIDATE_ID} was retired: {RETIRED_REASON}"
    )


def validate_shadow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate only the current generic shadow contract.

    The legacy function name remains for read-model compatibility.  A PR2
    payload fails because its RCFHS identity has no required capabilities or
    evidence.
    """
    try:
        return validate_candidate_payload(payload)
    except ScenarioShadowContractError as exc:
        raise ScenarioV4ShadowError(str(exc)) from exc


def load_shadow(root: Path) -> dict[str, Any] | None:
    """Return only a valid, fresh schema-v2 legacy diagnostic candidate."""
    result = load_candidate(root)
    return result.payload if result.display_allowed else None


def load_shadow_state(root: Path) -> dict[str, Any]:
    """Return a non-price status summary for dashboard warning controls."""
    result = load_candidate(root)
    payload = result.payload or {}
    return {
        "status": result.status,
        "display_allowed": result.display_allowed,
        "reason": result.reason,
        "candidate_id": payload.get("candidate_id"),
    }


def refresh_shadow(root: Path) -> tuple[Path, dict[str, Any], bool]:
    """Reject the deprecated command without creating or changing an artifact."""
    del root
    raise ScenarioV4ShadowError(
        f"{RETIRED_CANDIDATE_ID} was retired: {RETIRED_REASON}; no artifact written"
    )
