from datetime import datetime, timezone
import hashlib

import pytest

from ai_fc.timeseries_v7_r4.generation_freezer import (
    EvidenceRole,
    ExposureBudget,
    GenerationIdentity,
    QualificationAlreadyConsumed,
    TuningEvidenceRejected,
)


HASHES = {
    name: hashlib.sha256(name.encode()).hexdigest()
    for name in ("contract", "data", "code", "runtime", "hypothesis")
}


def test_generation_identity_freezes_all_research_coordinates():
    identity = GenerationIdentity(**{f"{key}_sha256": value for key, value in HASHES.items()})

    assert identity.generation_id == GenerationIdentity(
        **{f"{key}_sha256": value for key, value in HASHES.items()}
    ).generation_id
    assert len(identity.generation_id) == 64
    with pytest.raises(ValueError, match="hypothesis_sha256"):
        GenerationIdentity(**{
            **{f"{key}_sha256": value for key, value in HASHES.items()},
            "hypothesis_sha256": "not-a-hash",
        })


def test_qualification_can_be_consumed_only_once_per_generation():
    budget = ExposureBudget()
    identity = GenerationIdentity(**{f"{key}_sha256": value for key, value in HASHES.items()})

    budget.consume_qualification(identity.generation_id)
    with pytest.raises(QualificationAlreadyConsumed):
        budget.consume_qualification(identity.generation_id)


@pytest.mark.parametrize(
    ("role", "available_at"),
    [
        (EvidenceRole.PROSPECTIVE, datetime(2024, 1, 1, tzinfo=timezone.utc)),
        (EvidenceRole.TUNING, datetime(2024, 1, 3, tzinfo=timezone.utc)),
    ],
)
def test_prospective_or_post_as_of_evidence_cannot_enter_tuning(role, available_at):
    budget = ExposureBudget()

    with pytest.raises(TuningEvidenceRejected):
        budget.authorize_tuning_evidence(
            role=role,
            available_at=available_at,
            generation_as_of=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
