"""Quota and retention policy that never deletes evidence to make room."""

from __future__ import annotations

from dataclasses import dataclass


class RetentionPolicyError(RuntimeError):
    """Raised when collection or deletion violates the evidence-retention contract."""


@dataclass(frozen=True)
class QuotaState:
    used_bytes: int
    quota_bytes: int
    pending_bytes: int = 0

    def projected_fraction(self) -> float:
        if self.quota_bytes <= 0 or self.used_bytes < 0 or self.pending_bytes < 0:
            raise RetentionPolicyError("quota byte counts are invalid")
        return (self.used_bytes + self.pending_bytes) / self.quota_bytes


@dataclass(frozen=True)
class QuotaDecision:
    allow_collection: bool
    state: str
    projected_fraction: float
    reason_code: str


def decide_collection(state: QuotaState, *, hold_fraction: float = 0.80) -> QuotaDecision:
    if not 0 < hold_fraction <= 1:
        raise RetentionPolicyError("hold fraction must be in (0,1]")
    projected = state.projected_fraction()
    if projected >= hold_fraction:
        return QuotaDecision(False, "hold", projected, "managed_free_tier_80_percent")
    return QuotaDecision(True, "allowed", projected, "within_quota_budget")


@dataclass(frozen=True)
class LegalDeletionRequest:
    object_sha256: str
    legal_basis: str
    approval_receipt_sha256: str
    approved_by_role: str


def authorize_evidence_deletion(request: LegalDeletionRequest) -> dict[str, str]:
    """Validate an exceptional legal deletion; ordinary quota cleanup is never allowed."""

    for name in ("object_sha256", "approval_receipt_sha256"):
        value = getattr(request, name)
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise RetentionPolicyError(f"invalid {name}")
    if request.legal_basis not in {"court_order", "privacy_erasure", "license_revocation"}:
        raise RetentionPolicyError("evidence deletion requires an enumerated legal basis")
    if request.approved_by_role != "data_governance_owner":
        raise RetentionPolicyError("evidence deletion requires data-governance approval")
    return {
        "decision_type": "legal_delete_authorized",
        "object_sha256": request.object_sha256,
        "approval_receipt_sha256": request.approval_receipt_sha256,
        "reason_code": request.legal_basis,
    }


def reject_quota_cleanup() -> None:
    raise RetentionPolicyError("quota pressure must HOLD collection; evidence deletion is prohibited")
