"""SEC accepted-at filing ledger and as-of eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FilingFact:
    accession: str
    cik: str
    accepted_at: datetime
    fiscal_period: str
    concept: str
    value: float
    restates_accession: str | None = None


def facts_as_of(rows: list[FilingFact], cutoff: datetime) -> list[FilingFact]:
    return [row for row in rows if row.accepted_at <= cutoff]
