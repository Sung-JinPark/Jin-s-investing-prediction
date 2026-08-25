"""XNAS completed-session origins and session-based freshness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import exchange_calendars as xcals


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletedSession:
    session_label: str
    open_at: datetime
    close_at: datetime
    origin_cutoff_at: datetime
    calendar_hash: str


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SessionError("session timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _python_datetime(value: object) -> datetime:
    converted = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if not isinstance(converted, datetime):
        raise SessionError("calendar returned an invalid timestamp")
    return _aware(converted)


def last_completed_xnas_session(as_of: datetime, *, cutoff_delay: timedelta = timedelta(minutes=15)) -> CompletedSession:
    as_of = _aware(as_of)
    calendar = xcals.get_calendar("XNAS")
    labels = calendar.sessions_in_range((as_of - timedelta(days=14)).date(), as_of.date())
    completed: list[tuple[object, datetime, datetime]] = []
    for label in labels:
        opened = _python_datetime(calendar.session_open(label))
        closed = _python_datetime(calendar.session_close(label))
        if closed + cutoff_delay <= as_of:
            completed.append((label, opened, closed))
    if not completed:
        raise SessionError("no completed XNAS session found before cutoff")
    label, opened, closed = completed[-1]
    label_text = str(label.date())
    material = json.dumps(
        {"calendar": "XNAS", "session": label_text, "open": opened.isoformat(), "close": closed.isoformat(), "cutoff_delay_seconds": cutoff_delay.total_seconds()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return CompletedSession(label_text, opened, closed, closed + cutoff_delay, hashlib.sha256(material).hexdigest())


def missing_completed_sessions(*, last_observed_session: str, as_of: datetime) -> int:
    target = last_completed_xnas_session(as_of)
    calendar = xcals.get_calendar("XNAS")
    labels = calendar.sessions_in_range(last_observed_session, target.session_label)
    return sum(1 for label in labels if str(label.date()) > last_observed_session)
