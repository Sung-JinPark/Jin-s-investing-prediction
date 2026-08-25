"""Session-based purge and embargo rules."""

from __future__ import annotations

from bisect import bisect_left
from datetime import date
from typing import Iterable, Sequence

from .labels import LabelInterval


def embargo_end(label_end: date, sessions: Sequence[date], embargo_sessions: int) -> date:
    if embargo_sessions < 0:
        raise ValueError("embargo_sessions must be non-negative")
    index = bisect_left(sessions, label_end)
    if index >= len(sessions) or sessions[index] != label_end:
        raise ValueError("label end is not an exchange session")
    target = index + embargo_sessions
    if target >= len(sessions):
        raise IndexError("calendar does not cover embargo")
    return sessions[target]


def eligible_training_labels(labels: Iterable[LabelInterval], validation_origin: date, sessions: Sequence[date], *, embargo_sessions: int = 5) -> list[LabelInterval]:
    return [row for row in labels if embargo_end(row.label_end_session, sessions, embargo_sessions) < validation_origin]
