"""거래일 달력 신선도 — '마지막 완료 세션' 기준 누락 거래일 수. 주말·연휴·화~토 refresh 지연을 정직하게 처리한다.

missing_sessions = #{NYSE 거래일 d : as_of < d <= last_completed_session(now)}
fresh ⇔ missing_sessions <= max_missing_sessions (계약 live_display.freshness, 기본 1).
발행(라이브 CLI)과 빌드(표시 모듈) 두 시점에 각각 평가한다. stdlib + 달력 계약만 (pandas 없음).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..market_session import completed_market_cutoff
from ..scenario import future_trading_days, load_calendar_contract


def last_completed_session(root: Path, now: datetime) -> date:
    """now 시점에 종가가 확정된 마지막 NYSE 거래일 (16:15 ET 이전이면 전일)."""
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    cutoff = completed_market_cutoff(current.date(), now=current)
    calendar = load_calendar_contract(root)
    start = cutoff - timedelta(days=40)
    valid = [d for d in future_trading_days(start, 40, calendar) if d <= cutoff]
    return valid[-1] if valid else cutoff


def missing_sessions(root: Path, as_of: date, now: datetime) -> tuple[int, date]:
    last = last_completed_session(root, now)
    if as_of >= last:
        return 0, last
    calendar = load_calendar_contract(root)
    span = (last - as_of).days + 5
    gaps = [d for d in future_trading_days(as_of, max(span, 1), calendar) if d <= last]
    return len(gaps), last


def freshness_report(root: Path, as_of: str | None, now: datetime, *, max_missing_sessions: int = 1) -> dict[str, Any]:
    if not as_of:
        return {"rule": "nyse_trading_calendar", "as_of": None, "last_completed_session": None,
                "missing_sessions": None, "max_missing_sessions": max_missing_sessions, "status": "no_observation"}
    missing, last = missing_sessions(root, date.fromisoformat(as_of[:10]), now)
    return {"rule": "nyse_trading_calendar", "as_of": as_of[:10], "last_completed_session": last.isoformat(),
            "missing_sessions": missing, "max_missing_sessions": max_missing_sessions,
            "evaluated_at": (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds"),
            "status": "fresh" if missing <= max_missing_sessions else "stale"}
