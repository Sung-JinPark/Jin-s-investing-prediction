"""Bi-temporal append-only observation revision chains."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class ObservationRevision:
    revision_id: str
    observation_key_id: str
    revision_seq: int
    value: float | str
    observation_time: datetime
    available_at: datetime
    ingested_at: datetime
    valid_from: datetime
    valid_to: datetime | None
    parser_version: str
    source_hash: str
    supersedes_revision_id: str | None = None

    def __post_init__(self) -> None:
        if self.revision_seq < 0:
            raise ValueError("revision_seq must be non-negative")
        if self.available_at > self.ingested_at:
            raise ValueError("ingested_at cannot precede available_at")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("invalid validity interval")


def validate_revision_chain(rows: Iterable[ObservationRevision]) -> tuple[ObservationRevision, ...]:
    values = tuple(sorted(rows, key=lambda row: row.revision_seq))
    if not values:
        return values
    if len({row.observation_key_id for row in values}) != 1:
        raise ValueError("revision chain mixes observation keys")
    if [row.revision_seq for row in values] != list(range(len(values))):
        raise ValueError("revision sequence must be contiguous from zero")
    for index, row in enumerate(values):
        expected = None if index == 0 else values[index - 1].revision_id
        if row.supersedes_revision_id != expected:
            raise ValueError("supersedes chain is broken")
        if index and row.available_at < values[index - 1].available_at:
            raise ValueError("available_at must be monotonic")
    return values


def reconstruct_as_of(rows: Iterable[ObservationRevision], cutoff: datetime) -> ObservationRevision | None:
    chain = validate_revision_chain(rows)
    eligible = [row for row in chain if row.available_at <= cutoff and row.valid_from <= cutoff and (row.valid_to is None or cutoff < row.valid_to)]
    return max(eligible, key=lambda row: (row.available_at, row.revision_seq), default=None)
