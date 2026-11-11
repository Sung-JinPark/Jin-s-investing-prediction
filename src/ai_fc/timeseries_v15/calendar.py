"""V15 XNAS 세션 달력 — kernel 안의 복사본 (exchange_calendars XNAS 가 유일 계산 엔진).

`ai_fc.mts_research.sessions` 의 `_calendar`·`session_table`·`future_sessions`·`session_offset`·
`last_completed_session` 을 그대로 옮겼다(연구 계층 리팩터가 V15 kernel 해시를 흔들지 않게 —
계약 fork.kernel_code_hash_definition, 정합은 테스트 F7). 신규 헬퍼는 `sessions_between`·
`open_utc`·`calendar_hash` 다. 네트워크 접근 없음. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from ai_fc.timeseries_v8.contracts import canonical_hash

SESSION_SETTLE_SECONDS = 900  # 공식 종가 확정 버퍼 (16:15 ET 관례)
CALENDAR_START = date(1995, 1, 1)
CALENDAR_HASH_LOOKAHEAD_DAYS = 100  # 행 calendar_hash 구간 = [1995-01-01, origin + 100일]


class V15CalendarError(ValueError):
    """XNAS 달력 계산 실패 — fail-closed (평일 근사로 대체하지 않는다)."""


@dataclass(frozen=True)
class SessionRow:
    session: str  # YYYY-MM-DD
    open_utc: datetime
    close_utc: datetime
    early_close: bool


def _calendar(start: date, end: date):
    try:
        import exchange_calendars as xcals
    except ImportError as exc:  # pragma: no cover
        raise V15CalendarError("exchange_calendars 의존성이 없다 — 평일 근사로 대체하지 않는다") from exc
    return xcals.get_calendar(
        "XNAS",
        start=(start - timedelta(days=7)).isoformat(),
        end=(end + timedelta(days=7)).isoformat(),
    )


@lru_cache(maxsize=64)
def _session_table_cached(start: date, end: date) -> tuple[SessionRow, ...]:
    import pandas as pd
    from zoneinfo import ZoneInfo

    calendar = _calendar(start, end)
    eastern = ZoneInfo("America/New_York")
    rows: list[SessionRow] = []
    for label in calendar.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end)):
        open_value = calendar.session_open(label).to_pydatetime().astimezone(timezone.utc)
        close_value = calendar.session_close(label).to_pydatetime().astimezone(timezone.utc)
        close_et = close_value.astimezone(eastern)
        rows.append(SessionRow(
            session=label.date().isoformat(),
            open_utc=open_value,
            close_utc=close_value,
            early_close=(close_et.hour, close_et.minute) != (16, 0),
        ))
    return tuple(rows)


def session_table(start: date, end: date) -> list[SessionRow]:
    """[start, end] 구간의 XNAS 세션과 UTC open/close, 조기폐장 여부."""
    return list(_session_table_cached(start, end))


def future_sessions(origin_session: date, count: int) -> list[date]:
    """원점 다음 세션부터 count 개의 미래 거래 세션."""
    if count < 1:
        raise V15CalendarError("count 는 1 이상")
    import pandas as pd

    end = origin_session + timedelta(days=int(count * 1.6) + 21)
    calendar = _calendar(origin_session, end)
    if not calendar.is_session(pd.Timestamp(origin_session)):
        raise V15CalendarError(f"원점이 XNAS 세션이 아니다: {origin_session.isoformat()}")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(origin_session + timedelta(days=1)), pd.Timestamp(end)
    )
    dates = [stamp.date() for stamp in sessions]
    if len(dates) < count:
        raise V15CalendarError("달력 창이 부족하다 — 세션 수 미달")
    return dates[:count]


def session_offset(origin_session: date, k: int) -> date:
    """k 번째 미래 세션 (k>=1)."""
    return future_sessions(origin_session, k)[k - 1]


def last_completed_session(now: datetime) -> date:
    """now 기준 마지막으로 완결(close+버퍼 경과)된 XNAS 세션."""
    if now.tzinfo is None:
        raise V15CalendarError("now 는 timezone-aware 여야 한다")
    current = now.astimezone(timezone.utc)
    table = session_table(current.date() - timedelta(days=14), current.date())
    complete = [
        row for row in table
        if row.close_utc + timedelta(seconds=SESSION_SETTLE_SECONDS) <= current
    ]
    if not complete:
        raise V15CalendarError("완결된 XNAS 세션이 없다")
    return date.fromisoformat(complete[-1].session)


# ── 신규 헬퍼 (mts_research.sessions 에 없다) ────────────────────────────────


def sessions_between(start: date, end: date) -> list[date]:
    """[start, end] 의 XNAS 세션 날짜(오름차순)."""
    if end < start:
        return []
    return [date.fromisoformat(row.session) for row in _session_table_cached(start, end)]


def open_utc(session: date) -> datetime:
    """세션 개장 시각(UTC). 세션이 아니면 fail-closed."""
    table = _session_table_cached(session, session)
    if not table or table[0].session != session.isoformat():
        raise V15CalendarError(f"XNAS 세션이 아니다: {session.isoformat()}")
    return table[0].open_utc


def close_utc(session: date) -> datetime:
    """세션 종가 시각(UTC, 조기폐장일은 실제 close)."""
    table = _session_table_cached(session, session)
    if not table or table[0].session != session.isoformat():
        raise V15CalendarError(f"XNAS 세션이 아니다: {session.isoformat()}")
    return table[0].close_utc


def exchange_calendars_version() -> str:
    try:
        import exchange_calendars as xcals
    except ImportError as exc:  # pragma: no cover
        raise V15CalendarError("exchange_calendars 의존성이 없다") from exc
    return str(xcals.__version__)


def calendar_hash(origin: date | str) -> str:
    """행 calendar_hash — XNAS 세션·종가 시각 [1995-01-01, origin + 100일]의 해시."""
    day = date.fromisoformat(origin) if isinstance(origin, str) else origin
    end = day + timedelta(days=CALENDAR_HASH_LOOKAHEAD_DAYS)
    payload = [
        {"session": row.session, "close": row.close_utc.isoformat()}
        for row in _session_table_cached(CALENDAR_START, end)
    ]
    return canonical_hash({"exchange": "XNAS", "window_start": CALENDAR_START.isoformat(),
                           "window_end": end.isoformat(), "sessions": payload})
