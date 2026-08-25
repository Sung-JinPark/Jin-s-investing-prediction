"""Canonical XNAS session timestamps and label-session arithmetic."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from .identifiers import content_hash, stable_id


@lru_cache(maxsize=8)
def xnas_schedule(start: str, end: str):
    try:
        import exchange_calendars as xcals  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("install ai-fc[timeseries-v5] for the canonical XNAS calendar") from exc
    calendar = xcals.get_calendar("XNAS")
    schedule = calendar.schedule.loc[start:end].copy()
    schedule.index = schedule.index.tz_localize(None)
    return schedule


def session_records(start: str, end: str) -> list[dict]:
    schedule = xnas_schedule(start, end); calendar_hash = content_hash([(str(day.date()), row["open"], row["close"]) for day, row in schedule.iterrows()])
    output = []
    for day, row in schedule.iterrows():
        date_value = day.date().isoformat(); opened = row["open"].to_pydatetime().astimezone(timezone.utc); closed = row["close"].to_pydatetime().astimezone(timezone.utc)
        output.append({"session_id": stable_id("xnas", date_value), "exchange": "XNAS", "session_date": date_value, "open_at": opened.isoformat(), "close_at": closed.isoformat(), "calendar_hash": calendar_hash})
    return output


def cutoff_for_session(session: dict) -> datetime:
    value = datetime.fromisoformat(str(session["close_at"])); return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def market_feature_is_eligible(available_at: str | datetime, cutoff_at: str | datetime) -> bool:
    available = datetime.fromisoformat(available_at) if isinstance(available_at, str) else available_at
    cutoff = datetime.fromisoformat(cutoff_at) if isinstance(cutoff_at, str) else cutoff_at
    if available.tzinfo is None or cutoff.tzinfo is None: raise ValueError("PIT comparison requires timezone-aware timestamps")
    return available <= cutoff


def missing_completed_sessions(last_observation_session: str, *, through_session: str) -> int:
    schedule = xnas_schedule(last_observation_session, through_session)
    dates = [day.date().isoformat() for day in schedule.index]
    if not dates or last_observation_session not in dates: return len(dates)
    return max(0, len(dates) - dates.index(last_observation_session) - 1)


def future_sessions(after_session: str, count: int) -> list[str]:
    """Return the next XNAS session labels without manufacturing weekdays."""
    try:
        import exchange_calendars as xcals  # type: ignore
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("install ai-fc[timeseries-v5] for the canonical XNAS calendar") from exc
    calendar = xcals.get_calendar("XNAS")
    start = pd.Timestamp(after_session) + pd.Timedelta(days=1)
    sessions = calendar.sessions_in_range(start, start + pd.Timedelta(days=max(120, count * 3)))
    if len(sessions) < count:
        raise RuntimeError("XNAS calendar did not supply enough future sessions")
    return [value.date().isoformat() for value in sessions[:count]]
