"""Canonical, versioned XNAS session cutoffs.

Session rows are authoritative calendar inputs.  Cutoffs are derived only from
the session date and explicit local close time, never from observation receipt
or target availability timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo


_XNAS_ZONE = ZoneInfo("America/New_York")
_ALLOWED_MODES = frozenset({"training", "backtest", "live"})


@dataclass(frozen=True, slots=True)
class XnasSession:
    session_date: date
    cutoff_utc: datetime
    calendar_version: str

    @property
    def identity(self) -> str:
        return f"XNAS:{self.session_date.isoformat()}@{self.calendar_version}"


class XnasSessionCalendar:
    """Immutable view of one explicitly versioned XNAS calendar."""

    def __init__(self, *, version: str, sessions: Iterable[XnasSession]) -> None:
        if not version or not version.strip():
            raise ValueError("calendar version is required")
        ordered = sorted(sessions, key=lambda item: item.session_date)
        if any(item.calendar_version != version for item in ordered):
            raise ValueError("session calendar version mismatch")
        if len({item.session_date for item in ordered}) != len(ordered):
            raise ValueError("duplicate XNAS session_date")
        self.version = version
        self._sessions = tuple(ordered)
        self._by_date = {item.session_date: item for item in ordered}

    @classmethod
    def from_rows(
        cls, *, version: str, rows: Iterable[Mapping[str, object]]
    ) -> "XnasSessionCalendar":
        if not version or not version.strip():
            raise ValueError("calendar version is required")
        sessions: list[XnasSession] = []
        for row in rows:
            if "session_date" not in row:
                raise ValueError("session_date is required")
            if "close_time" not in row:
                raise ValueError("close_time is required")
            session_date = date.fromisoformat(str(row["session_date"]))
            close_time = time.fromisoformat(str(row["close_time"]))
            if close_time.tzinfo is not None:
                raise ValueError("close_time must be local XNAS wall time")
            local_close = datetime.combine(session_date, close_time, _XNAS_ZONE)
            sessions.append(
                XnasSession(
                    session_date=session_date,
                    cutoff_utc=local_close.astimezone(timezone.utc),
                    calendar_version=version,
                )
            )
        return cls(version=version, sessions=sessions)

    def session(self, session_date: date | str) -> XnasSession:
        key = date.fromisoformat(session_date) if isinstance(session_date, str) else session_date
        try:
            return self._by_date[key]
        except KeyError as exc:
            raise LookupError(f"no XNAS session for {key.isoformat()}") from exc

    def latest_completed(self, as_of: datetime) -> XnasSession:
        instant = _as_utc(as_of, field="as_of")
        for session in reversed(self._sessions):
            if session.cutoff_utc <= instant:
                return session
        raise LookupError("no completed XNAS session at as_of")


def resolve_origin_session(
    calendar: XnasSessionCalendar,
    *,
    as_of: datetime,
    mode: str = "live",
    target_available_at: datetime | None = None,
) -> XnasSession:
    """Resolve the common origin session used by every execution mode.

    ``target_available_at`` is accepted so callers can pass their PIT research
    coordinate, but it intentionally cannot influence the origin cutoff.
    """
    if mode not in _ALLOWED_MODES:
        raise ValueError(f"unsupported session mode: {mode}")
    if target_available_at is not None:
        _as_utc(target_available_at, field="target_available_at")
    return calendar.latest_completed(as_of)


def _as_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)
