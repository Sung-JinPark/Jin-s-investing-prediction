"""Version-aware point-in-time joins; observation-date forward fill is forbidden."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


class PitJoinError(RuntimeError):
    pass


@dataclass(frozen=True)
class Origin:
    origin_id: str
    origin_cutoff_at: datetime


@dataclass(frozen=True)
class PitObservation:
    observation_version_id: str
    source_id: str
    series_id: str
    observation_time: datetime
    available_at: datetime
    revision_seq: int
    value: float
    unit: str


@dataclass(frozen=True)
class OriginSeriesValue:
    origin_id: str
    source_id: str
    series_id: str
    value: float
    unit: str
    observation_time: datetime
    available_at: datetime
    observation_version_id: str
    age_seconds: float


@dataclass(frozen=True)
class PitSnapshot:
    values: tuple[OriginSeriesValue, ...]
    missing: tuple[tuple[str, str, str], ...]


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PitJoinError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def point_in_time_join(
    origins: Iterable[Origin],
    observations: Iterable[PitObservation],
    *,
    required_series: Iterable[tuple[str, str]],
) -> PitSnapshot:
    origin_rows = tuple(origins)
    observation_rows = tuple(observations)
    required = tuple(dict.fromkeys(required_series))
    if not origin_rows or not required:
        raise PitJoinError("origins and required series must be nonempty")
    if len({origin.origin_id for origin in origin_rows}) != len(origin_rows):
        raise PitJoinError("origin ids must be unique")
    for observation in observation_rows:
        _utc(observation.observation_time, "observation_time")
        _utc(observation.available_at, "available_at")
        if observation.revision_seq < 0:
            raise PitJoinError("revision sequence must be nonnegative")
    values: list[OriginSeriesValue] = []
    missing: list[tuple[str, str, str]] = []
    for origin in sorted(origin_rows, key=lambda row: (_utc(row.origin_cutoff_at, "origin cutoff"), row.origin_id)):
        cutoff = _utc(origin.origin_cutoff_at, "origin cutoff")
        for source_id, series_id in required:
            eligible = [
                row for row in observation_rows
                if row.source_id == source_id
                and row.series_id == series_id
                and _utc(row.available_at, "available_at") <= cutoff
                and _utc(row.observation_time, "observation_time") <= cutoff
            ]
            if not eligible:
                missing.append((origin.origin_id, source_id, series_id))
                continue
            chosen = max(
                eligible,
                key=lambda row: (
                    _utc(row.observation_time, "observation_time"),
                    _utc(row.available_at, "available_at"),
                    row.revision_seq,
                    row.observation_version_id,
                ),
            )
            available = _utc(chosen.available_at, "available_at")
            values.append(
                OriginSeriesValue(
                    origin_id=origin.origin_id,
                    source_id=source_id,
                    series_id=series_id,
                    value=chosen.value,
                    unit=chosen.unit,
                    observation_time=_utc(chosen.observation_time, "observation_time"),
                    available_at=available,
                    observation_version_id=chosen.observation_version_id,
                    age_seconds=(cutoff - available).total_seconds(),
                )
            )
    return PitSnapshot(tuple(values), tuple(missing))
