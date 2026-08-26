"""Governance boundary for research-only open-data challengers.

This module intentionally does not ingest data or write Gate state.  It validates
the immutable registration document that keeps proposed sources at zero weight.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class SourceQualification:
    source_id: str
    pit_grade: str
    license_receipt: str
    terms_receipt: str
    preregistered: bool = False
    validated: bool = False
    weight: float = 0.0
    official_gate_eligible: bool = False

    def __post_init__(self) -> None:
        if not self.source_id or not self.pit_grade:
            raise ValueError("source_id and explicit PIT grade are required")
        if not self.license_receipt or not self.terms_receipt:
            raise ValueError("license and terms receipts are required")
        if self.weight < 0.0:
            raise ValueError("source weight cannot be negative")
        approved = self.preregistered and self.validated
        if self.weight != 0.0 and not approved:
            raise ValueError("non-zero weight requires a separately preregistered and validated source")
        if self.official_gate_eligible and not approved:
            raise ValueError("official Gate eligibility requires preregistration and validation")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceQualification":
        return cls(**value)


@dataclass(frozen=True)
class OpenDataChallengerContract:
    contract_version: str
    lane: str
    frozen_v7_coordinates_unchanged: bool
    v8_proposal_required: bool
    v8_proposal_path: str
    sources: tuple[SourceQualification, ...]

    def __post_init__(self) -> None:
        if self.lane != "research_only":
            raise ValueError("open-data challengers must remain in the research_only lane")
        if not self.frozen_v7_coordinates_unchanged:
            raise ValueError("the challenger contract must not change frozen V7 coordinates")
        if len({source.source_id for source in self.sources}) != len(self.sources):
            raise ValueError("source_id values must be unique")
        if not self.sources:
            raise ValueError("at least one proposed source is required")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OpenDataChallengerContract":
        allowed = {
            "contract_version", "lane", "frozen_v7_coordinates_unchanged",
            "v8_proposal_required", "v8_proposal_path", "sources",
        }
        unexpected = set(value) - allowed
        if unexpected:
            raise ValueError(f"unexpected contract fields: {sorted(unexpected)}")
        return cls(
            contract_version=str(value["contract_version"]),
            lane=str(value["lane"]),
            frozen_v7_coordinates_unchanged=bool(value["frozen_v7_coordinates_unchanged"]),
            v8_proposal_required=bool(value["v8_proposal_required"]),
            v8_proposal_path=str(value["v8_proposal_path"]),
            sources=tuple(SourceQualification.from_mapping(item) for item in value["sources"]),
        )

    @classmethod
    def from_path(cls, path: Path | str) -> "OpenDataChallengerContract":
        return cls.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))
