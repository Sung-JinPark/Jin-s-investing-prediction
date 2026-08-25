"""Official macro release and revision identities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OfficialRelease:
    source: str
    series_id: str
    period: str
    release_id: str
    published_at: datetime
    value: float
    revision_seq: int
    supersedes: str | None = None


def validate_releases(rows: list[OfficialRelease]) -> None:
    by_period: dict[tuple[str, str, str], list[OfficialRelease]] = {}
    for row in rows:
        by_period.setdefault((row.source, row.series_id, row.period), []).append(row)
    for values in by_period.values():
        ordered = sorted(values, key=lambda row: row.revision_seq)
        if [row.revision_seq for row in ordered] != list(range(len(ordered))):
            raise ValueError("revision sequence gap")
        for index, row in enumerate(ordered):
            if index and (row.published_at < ordered[index - 1].published_at or row.supersedes != ordered[index - 1].release_id):
                raise ValueError("invalid official revision chain")
