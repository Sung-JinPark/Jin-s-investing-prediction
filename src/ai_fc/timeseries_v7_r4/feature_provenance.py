"""Fail-closed provenance for every active origin-feature value."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class FeatureValueProvenance:
    """One immutable, active origin×feature value and its complete lineage."""

    origin_id: str
    origin_session: date
    origin_cutoff_at: datetime
    feature_id: str
    feature_value: object
    source_observation_ids: tuple[str, ...]
    source_revision_ids: tuple[str, ...]
    source_available_at: tuple[datetime, ...]
    max_available_at: datetime
    transformation_hash: str
    age_seconds: float
    missing_policy: str
    data_grade: str
    date_only_vintage_dates: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        if not self.origin_id or not self.feature_id:
            raise ValueError("origin_id and feature_id are required")
        if not isinstance(self.origin_session, date) or isinstance(self.origin_session, datetime):
            raise ValueError("origin_session must be a date")
        if not self.source_observation_ids:
            raise ValueError("source_observation_ids are required")
        if not self.source_revision_ids:
            raise ValueError("source_revision_ids are required")
        count = len(self.source_observation_ids)
        if len(self.source_revision_ids) != count or len(self.source_available_at) != count:
            raise ValueError("source provenance fields must have the same length")
        if self.date_only_vintage_dates and len(self.date_only_vintage_dates) != count:
            raise ValueError("date_only_vintage_dates must have the same length as sources")
        cutoff = _utc(self.origin_cutoff_at, "origin_cutoff_at")
        available = tuple(_utc(item, "source_available_at") for item in self.source_available_at)
        maximum = _utc(self.max_available_at, "max_available_at")
        if maximum != max(available):
            raise ValueError("max_available_at must equal the maximum source_available_at")
        if maximum > cutoff:
            raise ValueError("PIT invariant failed: max_available_at exceeds origin_cutoff_at")
        if any(vintage >= self.origin_session for vintage in self.date_only_vintage_dates):
            raise ValueError("date-only vintage is unavailable until the next eligible session")
        if len(self.transformation_hash) != 64:
            raise ValueError("transformation_hash must be a 64-character digest")
        if self.age_seconds < 0:
            raise ValueError("age_seconds cannot be negative")
        if not self.missing_policy or not self.data_grade:
            raise ValueError("missing_policy and data_grade are required")


class FeatureProvenanceMatrix:
    """Validated active feature values keyed by their frozen research coordinates."""

    def __init__(self, rows: Iterable[FeatureValueProvenance]) -> None:
        indexed: dict[tuple[str, str], FeatureValueProvenance] = {}
        for row in rows:
            if not isinstance(row, FeatureValueProvenance):
                raise TypeError("matrix rows must be FeatureValueProvenance")
            key = (row.origin_id, row.feature_id)
            if key in indexed:
                raise ValueError(f"duplicate active origin-feature coordinate: {key!r}")
            indexed[key] = row
        self._rows = tuple(indexed.values())

    @property
    def rows(self) -> tuple[FeatureValueProvenance, ...]:
        return self._rows

    def validate_active(self) -> dict[str, int | float]:
        """Return an exhaustive PIT result; invalid rows fail during construction."""
        count = len(self._rows)
        return {
            "active_features": count,
            "pit_passed": count,
            "pit_pass_rate": 1.0 if count else 0.0,
        }
