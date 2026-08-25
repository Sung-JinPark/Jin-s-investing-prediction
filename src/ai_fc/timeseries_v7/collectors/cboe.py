"""Cboe volatility close and term-surface normalization."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


SYMBOLS = {"VIX", "VIX9D", "VIX3M", "VVIX", "SKEW"}


def after_close_available_at(session: date) -> datetime:
    local = datetime.combine(session, time(16, 15), ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc)


def normalize_close(symbol: str, session: date, value: float, *, fetched_at: datetime) -> dict[str, object]:
    if symbol not in SYMBOLS:
        raise ValueError("unsupported Cboe symbol")
    available = after_close_available_at(session)
    if fetched_at < available:
        raise ValueError("close value fetched before declared availability")
    return {"symbol": symbol, "session": session, "value": float(value), "available_at": available, "data_grade": "reconstructed_official_archive"}
