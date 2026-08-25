"""Forward-only consensus and release event snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EventSnapshot:
    event_id: str
    scheduled_at: datetime
    captured_at: datetime
    consensus: float
    dispersion: float | None
    actual: float | None = None
    actual_available_at: datetime | None = None

    @property
    def is_pre_event(self) -> bool:
        return self.captured_at < self.scheduled_at and self.actual is None


def independent_resolved_event_count(rows: list[EventSnapshot], cutoff: datetime) -> int:
    eligible = {
        row.event_id for row in rows
        if row.is_pre_event and any(
            other.event_id == row.event_id and other.actual is not None and other.actual_available_at is not None and other.actual_available_at <= cutoff
            for other in rows
        )
    }
    return len(eligible)
