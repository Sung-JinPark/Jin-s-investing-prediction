"""Canonical session-indexed direct-horizon labels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence


HORIZONS = (1, 5, 21, 63)


@dataclass(frozen=True)
class LabelInterval:
    origin_session: date
    label_start_session: date
    label_end_session: date
    mature_at: datetime
    horizon_sessions: int
    value: float | None = None


def label_interval(sessions: Sequence[date], origin_index: int, horizon: int, *, mature_at: datetime, value: float | None = None) -> LabelInterval:
    if horizon not in HORIZONS:
        raise ValueError("unsupported direct horizon")
    if origin_index < 0 or origin_index + horizon >= len(sessions):
        raise IndexError("label interval exceeds session calendar")
    if any(left >= right for left, right in zip(sessions, sessions[1:])):
        raise ValueError("sessions must be strictly increasing")
    return LabelInterval(sessions[origin_index], sessions[origin_index + 1], sessions[origin_index + horizon], mature_at, horizon, value)
