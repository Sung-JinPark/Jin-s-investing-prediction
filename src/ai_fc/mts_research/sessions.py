"""거래 세션 달력 — exchange_calendars XNAS 를 유일 계산 엔진으로 쓴다 (§4.1, T10).

- 거래일은 실제 거래소 달력으로 계산한다. 달력 일수·평일 수로 5·21·63 을 대체하지 않는다.
- DST·휴장·조기폐장은 XNAS 세션 시각에서 나온다 (daily6m 전례: close+900s 완결 버퍼).
- legacy 달력(nyse_holidays.yaml 규칙, V13 관측일 교집합 grid)은 CalendarRef 로
  **표현만** 하고 여기서 재계산하지 않는다 — adapter 가 재생할 때 어떤 달력을 썼는지
  calendar_hash 로 항상 명시된다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict

from ..timeseries_v8.contracts import canonical_hash

SESSION_SETTLE_SECONDS = 900  # 공식 종가 확정 버퍼 (16:15 ET 관례 — market_session.py 와 일치)
NYSE_HOLIDAYS_RELATIVE = Path("data/contracts/nyse_holidays.yaml")


class MtsSessionError(RuntimeError):
    """세션 달력 계산 실패 — fail-closed."""


class CalendarRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    calendar_id: Literal["xnas_exchange_calendars", "nyse_holidays_yaml_v1", "observation_grid"]
    calendar_hash: str
    library_version: str | None
    window_start: str
    window_end: str


class SessionRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session: str  # YYYY-MM-DD
    open_utc: datetime
    close_utc: datetime
    early_close: bool


def _calendar(start: date, end: date):
    try:
        import exchange_calendars as xcals
    except ImportError as exc:  # pragma: no cover
        raise MtsSessionError("exchange_calendars 의존성이 없다 — 평일 근사로 대체하지 않는다") from exc
    return xcals.get_calendar(
        "XNAS",
        start=(start - timedelta(days=7)).isoformat(),
        end=(end + timedelta(days=7)).isoformat(),
    )


def session_table(start: date, end: date) -> list[SessionRow]:
    """[start, end] 구간의 XNAS 세션과 UTC open/close, 조기폐장 여부."""
    import pandas as pd
    from zoneinfo import ZoneInfo

    calendar = _calendar(start, end)
    eastern = ZoneInfo("America/New_York")
    rows: list[SessionRow] = []
    for label in calendar.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end)):
        open_utc = calendar.session_open(label).to_pydatetime().astimezone(timezone.utc)
        close_utc = calendar.session_close(label).to_pydatetime().astimezone(timezone.utc)
        close_et = close_utc.astimezone(eastern)
        rows.append(SessionRow(
            session=label.date().isoformat(),
            open_utc=open_utc,
            close_utc=close_utc,
            early_close=(close_et.hour, close_et.minute) != (16, 0),
        ))
    return rows


def xnas_ref(start: date, end: date) -> CalendarRef:
    import exchange_calendars as xcals

    table = session_table(start, end)
    payload = [
        {"session": row.session, "open": row.open_utc.isoformat(), "close": row.close_utc.isoformat()}
        for row in table
    ]
    return CalendarRef(
        calendar_id="xnas_exchange_calendars",
        calendar_hash=canonical_hash({"exchange": "XNAS", "sessions": payload}),
        library_version=xcals.__version__,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
    )


def legacy_nyse_ref(root: Path) -> CalendarRef:
    """v2/v8/v13 이 쓰는 규칙 달력의 표현 — 재계산 아님."""
    import yaml

    payload = yaml.safe_load((root / NYSE_HOLIDAYS_RELATIVE).read_text(encoding="utf-8"))
    return CalendarRef(
        calendar_id="nyse_holidays_yaml_v1",
        calendar_hash=canonical_hash(payload),
        library_version=None,
        window_start="rule_based",
        window_end="rule_based",
    )


def observation_grid_ref(dates: Sequence[str]) -> CalendarRef:
    """V13 류 관측일 교집합 grid 의 표현 (adapter replay 용)."""
    ordered = list(dates)
    if ordered != sorted(set(ordered)):
        raise MtsSessionError("관측일 grid 는 중복 없는 오름차순이어야 한다")
    return CalendarRef(
        calendar_id="observation_grid",
        calendar_hash=canonical_hash({"grid": ordered}),
        library_version=None,
        window_start=ordered[0] if ordered else "",
        window_end=ordered[-1] if ordered else "",
    )


def future_sessions(origin_session: date, count: int) -> list[date]:
    """원점 다음 세션부터 count 개의 미래 거래 세션."""
    if count < 1:
        raise MtsSessionError("count 는 1 이상")
    import pandas as pd

    # 넉넉한 달력 창: 거래일 count 개 ≤ 달력일 약 count*1.6 + 14
    end = origin_session + timedelta(days=int(count * 1.6) + 21)
    calendar = _calendar(origin_session, end)
    if not calendar.is_session(pd.Timestamp(origin_session)):
        raise MtsSessionError(f"원점이 XNAS 세션이 아니다: {origin_session.isoformat()}")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(origin_session + timedelta(days=1)), pd.Timestamp(end)
    )
    dates = [stamp.date() for stamp in sessions]
    if len(dates) < count:
        raise MtsSessionError("달력 창이 부족하다 — 세션 수 미달")
    return dates[:count]


def session_offset(origin_session: date, k: int) -> date:
    """k 번째 미래 세션 (k>=1)."""
    return future_sessions(origin_session, k)[k - 1]


def information_cutoff_for(session: date, *, policy_id: str = "settle_1615et_v1") -> datetime:
    """세션 종가 확정 시각(UTC) — close + settle 버퍼. 조기폐장일은 실제 close 기준 (T10)."""
    if policy_id != "settle_1615et_v1":
        raise MtsSessionError(f"등록되지 않은 cutoff 정책: {policy_id}")
    table = session_table(session, session)
    if not table or table[0].session != session.isoformat():
        raise MtsSessionError(f"XNAS 세션이 아니다: {session.isoformat()}")
    return table[0].close_utc + timedelta(seconds=SESSION_SETTLE_SECONDS)


def last_completed_session(now: datetime) -> date:
    """now 기준 마지막으로 완결(close+버퍼 경과)된 XNAS 세션 (daily6m 과 같은 규약)."""
    if now.tzinfo is None:
        raise MtsSessionError("now 는 timezone-aware 여야 한다")
    current = now.astimezone(timezone.utc)
    table = session_table(current.date() - timedelta(days=14), current.date())
    complete = [
        row for row in table
        if row.close_utc + timedelta(seconds=SESSION_SETTLE_SECONDS) <= current
    ]
    if not complete:
        raise MtsSessionError("완결된 XNAS 세션이 없다")
    return date.fromisoformat(complete[-1].session)
