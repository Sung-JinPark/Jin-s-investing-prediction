"""Point-in-time macro features defined on releases, not daily carry-forward rows."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable


FEATURE_SCHEMA = {
    "schema_version": 1,
    "unit": "source_series_unit",
    "features": [
        "first_release_value", "latest_known_at_origin", "revision_amount",
        "revision_count", "revision_volatility", "change_since_previous_release",
        "release_surprise", "release_age_seconds", "revision_age_seconds",
        "filtered_factor_innovation",
    ],
    "identity": ["series_id", "release_observation_date", "source_revision_ids"],
}

TRANSFORM_SPEC = {
    "transform_version": 1,
    "release_identity": "distinct observation_date",
    "pit_filter": "available_at <= origin_cutoff_at",
    "revision_amount": "latest_value - first_release_value",
    "revision_count": "revisions_after_first",
    "revision_volatility": "root_mean_square(consecutive_revision_changes)",
    "change_since_previous_release": "current_first_release - previous_latest_at_origin",
    "release_surprise": "current_first_release - explicit_expected_release_value",
    "filtered_factor_innovation": "change_since_previous_release - factor_loading * factor_innovation",
}


def _hash(spec: object) -> str:
    encoded = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


FEATURE_SCHEMA_HASH = _hash(FEATURE_SCHEMA)
TRANSFORM_HASH = _hash(TRANSFORM_SPEC)


@dataclass(frozen=True, slots=True)
class MacroRevision:
    series_id: str
    observation_date: date
    revision_id: str
    value: float
    available_at: datetime

    def __post_init__(self) -> None:
        if not self.series_id or not self.revision_id:
            raise ValueError("series_id and revision_id are required")
        if not isinstance(self.observation_date, date) or isinstance(self.observation_date, datetime):
            raise ValueError("observation_date must be a date")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        if not math.isfinite(self.value):
            raise ValueError("revision value must be finite")


@dataclass(frozen=True, slots=True)
class ReleaseNativeFeatures:
    series_id: str
    release_observation_date: date
    release_count: int
    first_release_value: float
    latest_known_at_origin: float
    revision_amount: float
    revision_count: int
    revision_volatility: float
    change_since_previous_release: float | None
    release_surprise: float | None
    release_age_seconds: float
    revision_age_seconds: float
    filtered_factor_innovation: float | None
    source_revision_ids: tuple[str, ...]
    max_available_at: datetime
    feature_schema_hash: str = FEATURE_SCHEMA_HASH
    transformation_hash: str = TRANSFORM_HASH


def build_release_native_features(
    revisions: Iterable[MacroRevision], *, origin_cutoff_at: datetime,
    expected_release_value: float | None = None,
    factor_loading: float | None = None,
    factor_innovation: float | None = None,
) -> ReleaseNativeFeatures:
    """Build the latest release state visible at ``origin_cutoff_at``.

    A later origin changes ages only until a genuinely new observation period is
    published. Expectations are never inferred from magnitude or future rows.
    """
    if origin_cutoff_at.tzinfo is None or origin_cutoff_at.utcoffset() is None:
        raise ValueError("origin_cutoff_at must be timezone-aware")
    cutoff = origin_cutoff_at.astimezone(timezone.utc)
    visible = [row for row in revisions if row.available_at.astimezone(timezone.utc) <= cutoff]
    if not visible:
        raise ValueError("no release is available at origin_cutoff_at")
    series = {row.series_id for row in visible}
    if len(series) != 1:
        raise ValueError("revisions must belong to exactly one series")
    ids = [row.revision_id for row in visible]
    if len(ids) != len(set(ids)):
        raise ValueError("revision_id must be unique")

    grouped: dict[date, list[MacroRevision]] = {}
    for row in visible:
        grouped.setdefault(row.observation_date, []).append(row)
    ordered = sorted(
        ((min(rows, key=lambda row: row.available_at).available_at, period, rows)
         for period, rows in grouped.items()),
        key=lambda item: (item[0], item[1]),
    )
    _, period, current_rows = ordered[-1]
    current = sorted(current_rows, key=lambda row: (row.available_at, row.revision_id))
    first, latest = current[0], current[-1]
    revision_changes = [right.value - left.value for left, right in zip(current, current[1:])]
    volatility = math.sqrt(sum(value * value for value in revision_changes) / len(revision_changes)) \
        if revision_changes else 0.0

    previous_latest = None
    if len(ordered) > 1:
        prior_rows = sorted(ordered[-2][2], key=lambda row: (row.available_at, row.revision_id))
        previous_latest = prior_rows[-1].value
    change = None if previous_latest is None else first.value - previous_latest
    surprise = None if expected_release_value is None else first.value - expected_release_value
    if (factor_loading is None) != (factor_innovation is None):
        raise ValueError("factor_loading and factor_innovation must be provided together")
    filtered = None
    if factor_loading is not None and change is not None:
        filtered = change - factor_loading * factor_innovation

    return ReleaseNativeFeatures(
        series_id=first.series_id,
        release_observation_date=period,
        release_count=len(ordered),
        first_release_value=first.value,
        latest_known_at_origin=latest.value,
        revision_amount=latest.value - first.value,
        revision_count=len(current) - 1,
        revision_volatility=volatility,
        change_since_previous_release=change,
        release_surprise=surprise,
        release_age_seconds=(cutoff - first.available_at.astimezone(timezone.utc)).total_seconds(),
        revision_age_seconds=(cutoff - latest.available_at.astimezone(timezone.utc)).total_seconds(),
        filtered_factor_innovation=filtered,
        source_revision_ids=tuple(row.revision_id for row in current),
        max_available_at=latest.available_at.astimezone(timezone.utc),
    )
