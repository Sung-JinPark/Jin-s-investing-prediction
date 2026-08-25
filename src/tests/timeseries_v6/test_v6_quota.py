import pytest

from ai_fc.timeseries_v6.quota import (
    LegalDeletionRequest,
    QuotaState,
    RetentionPolicyError,
    authorize_evidence_deletion,
    decide_collection,
    reject_quota_cleanup,
)


def test_quota_holds_at_projected_eighty_percent_without_deletion() -> None:
    assert decide_collection(QuotaState(79, 100)).allow_collection is True
    decision = decide_collection(QuotaState(79, 100, 1))
    assert decision.allow_collection is False
    assert decision.state == "hold"
    with pytest.raises(RetentionPolicyError, match="prohibited"):
        reject_quota_cleanup()


def test_only_approved_legal_deletion_can_be_authorized() -> None:
    request = LegalDeletionRequest(
        object_sha256="a" * 64,
        legal_basis="license_revocation",
        approval_receipt_sha256="b" * 64,
        approved_by_role="data_governance_owner",
    )
    assert authorize_evidence_deletion(request)["decision_type"] == "legal_delete_authorized"
    with pytest.raises(RetentionPolicyError, match="legal basis"):
        authorize_evidence_deletion(LegalDeletionRequest("a" * 64, "free_space", "b" * 64, "data_governance_owner"))
    with pytest.raises(RetentionPolicyError, match="approval"):
        authorize_evidence_deletion(LegalDeletionRequest("a" * 64, "court_order", "b" * 64, "trainer"))


def test_invalid_quota_counts_fail_closed() -> None:
    with pytest.raises(RetentionPolicyError, match="invalid"):
        decide_collection(QuotaState(1, 0))
