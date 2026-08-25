"""Prevalidated atomic observation batches for high-volume V6 ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Iterable


class BulkIngestionError(RuntimeError):
    """Raised before any durable write when a batch is ambiguous or unsafe."""


@dataclass(frozen=True)
class ObservationBatchRow:
    observation_key_id: str
    observation_version_id: str
    receipt_id: str
    source_id: str
    series_id: str
    observation_time: datetime
    unit: str
    semantic_type: str
    revision_seq: int
    value_numeric: float | None
    value_text: str | None
    available_at: datetime
    vintage_start: date | None
    vintage_end: date | None
    raw_object_sha256: str
    supersedes_observation_version_id: str | None
    status: str = "active"
    relation: str = "parsed_from"


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BulkIngestionError(f"{name} must be timezone-aware")


def validate_observation_batch(
    rows: Iterable[ObservationBatchRow], *, knowledge_cutoff: datetime,
) -> tuple[ObservationBatchRow, ...]:
    _aware(knowledge_cutoff, "knowledge_cutoff")
    batch = tuple(rows)
    if not batch:
        raise BulkIngestionError("observation batch must not be empty")
    key_ids: set[str] = set()
    version_ids: set[str] = set()
    semantic_keys: set[tuple[str, str, datetime, str, str]] = set()
    for row in batch:
        _aware(row.observation_time, "observation_time")
        _aware(row.available_at, "available_at")
        if row.available_at.astimezone(timezone.utc) > knowledge_cutoff.astimezone(timezone.utc):
            raise BulkIngestionError("future-available observation in batch")
        if (row.value_numeric is None) == (row.value_text is None):
            raise BulkIngestionError("exactly one observation value must be populated")
        if row.value_numeric is not None and not isfinite(row.value_numeric):
            raise BulkIngestionError("numeric observation must be finite")
        if row.revision_seq < 0:
            raise BulkIngestionError("revision sequence must be nonnegative")
        if (row.revision_seq == 0) != (row.supersedes_observation_version_id is None):
            raise BulkIngestionError("revision supersedes relationship is inconsistent")
        if row.vintage_start and row.vintage_end and row.vintage_end < row.vintage_start:
            raise BulkIngestionError("vintage interval is inverted")
        if row.status not in {"active", "superseded", "quarantined"}:
            raise BulkIngestionError("invalid observation status")
        if row.relation not in {"parsed_from", "revision_evidence", "cross_check"}:
            raise BulkIngestionError("invalid receipt relation")
        if len(row.raw_object_sha256) != 64:
            raise BulkIngestionError("invalid raw object SHA")
        semantic = (row.source_id, row.series_id, row.observation_time, row.unit, row.semantic_type)
        if row.observation_key_id in key_ids or row.observation_version_id in version_ids or semantic in semantic_keys:
            raise BulkIngestionError("duplicate identity inside observation batch")
        key_ids.add(row.observation_key_id)
        version_ids.add(row.observation_version_id)
        semantic_keys.add(semantic)
    return batch
