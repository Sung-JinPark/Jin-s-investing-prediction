"""Content-addressed generation identity and pre-persistence exposure guards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceRole(StrEnum):
    TUNING = "tuning"
    QUALIFICATION = "qualification"
    PROSPECTIVE = "prospective"


class QualificationAlreadyConsumed(RuntimeError):
    """Raised before a second qualification exposure for one generation."""


class TuningEvidenceRejected(ValueError):
    """Raised when evidence is not eligible for generation tuning."""


@dataclass(frozen=True)
class GenerationIdentity:
    contract_sha256: str
    data_sha256: str
    code_sha256: str
    runtime_sha256: str
    hypothesis_sha256: str

    def __post_init__(self) -> None:
        for name, value in self.coordinates.items():
            if not _SHA256.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")

    @property
    def coordinates(self) -> dict[str, str]:
        return {
            "contract_sha256": self.contract_sha256,
            "data_sha256": self.data_sha256,
            "code_sha256": self.code_sha256,
            "runtime_sha256": self.runtime_sha256,
            "hypothesis_sha256": self.hypothesis_sha256,
        }

    @property
    def generation_id(self) -> str:
        encoded = json.dumps(self.coordinates, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class ExposureBudget:
    """Process-local early guard; PostgreSQL constraints remain authoritative."""

    def __init__(self) -> None:
        self._qualified_generations: set[str] = set()

    def consume_qualification(self, generation_id: str) -> None:
        if generation_id in self._qualified_generations:
            raise QualificationAlreadyConsumed(generation_id)
        self._qualified_generations.add(generation_id)

    def authorize_tuning_evidence(
        self, *, role: EvidenceRole, available_at: datetime, generation_as_of: datetime
    ) -> None:
        if role is not EvidenceRole.TUNING:
            raise TuningEvidenceRejected(f"{role.value} evidence cannot enter tuning")
        if available_at.tzinfo is None or generation_as_of.tzinfo is None:
            raise TuningEvidenceRejected("available_at and generation_as_of must be timezone-aware")
        if available_at > generation_as_of:
            raise TuningEvidenceRejected("evidence available_at exceeds frozen generation as_of")
