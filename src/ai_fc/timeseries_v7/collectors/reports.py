"""Analyst/report evidence metadata; text cannot set returns."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReportEvidence:
    source: str
    published_at: datetime
    cutoff: datetime
    horizon: str
    target: str
    revision: str
    catalyst: str
    evidence_hash: str


def evidence_hash(normalized_text: str) -> str:
    return hashlib.sha256(" ".join(normalized_text.casefold().split()).encode()).hexdigest()


def cluster_count(rows: list[ReportEvidence]) -> int:
    return len({row.evidence_hash for row in rows})
