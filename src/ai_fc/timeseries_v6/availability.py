"""Explicit source availability policies and point-in-time eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class AvailabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class AvailabilityPolicy:
    policy_id: str
    data_grade: str
    conservative_delay: timedelta
    unknown_release_action: str

    def available_at(
        self,
        *,
        observation_time: datetime,
        published_at: datetime | None,
        captured_at: datetime,
    ) -> datetime:
        for value in (observation_time, captured_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise AvailabilityError("availability timestamps must be timezone-aware")
        if published_at is not None and (published_at.tzinfo is None or published_at.utcoffset() is None):
            raise AvailabilityError("published_at must be timezone-aware")
        if self.data_grade == "captured_forward":
            return captured_at.astimezone(timezone.utc)
        if published_at is not None:
            return max(published_at, observation_time + self.conservative_delay).astimezone(timezone.utc)
        if self.unknown_release_action != "challenger_or_prospective_only":
            raise AvailabilityError("unknown-release policy must fail closed")
        if self.data_grade == "native_pit":
            raise AvailabilityError("native PIT observations require an explicit publication timestamp")
        return captured_at.astimezone(timezone.utc)


def eligible_at(*, available_at: datetime, origin_cutoff_at: datetime) -> bool:
    if any(value.tzinfo is None or value.utcoffset() is None for value in (available_at, origin_cutoff_at)):
        raise AvailabilityError("PIT comparison timestamps must be timezone-aware")
    return available_at.astimezone(timezone.utc) <= origin_cutoff_at.astimezone(timezone.utc)


def age_since_release(*, available_at: datetime, origin_cutoff_at: datetime) -> timedelta:
    if not eligible_at(available_at=available_at, origin_cutoff_at=origin_cutoff_at):
        raise AvailabilityError("future-available value has no valid release age")
    return origin_cutoff_at.astimezone(timezone.utc) - available_at.astimezone(timezone.utc)
