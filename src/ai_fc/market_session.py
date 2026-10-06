"""Shared completed U.S. market-day cutoff.

Yahoo can expose a still-forming daily bar before the regular U.S. session has
settled.  Scenario and cross-asset snapshots must therefore share one cutoff
rule instead of independently accepting ``day <= requested``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
# A short settlement buffer avoids treating the 16:00 ET auction print as a
# completed provider bar before Yahoo has finalized it.
SESSION_FINAL_AT = time(16, 15)


def completed_market_cutoff(requested: date, *, now: datetime | None = None) -> date:
    """Return the latest date allowed to contain a finalized U.S. daily bar.

    Historical requested dates pass through.  Today/future requests are capped
    at the current New York date, and before 16:15 ET the current date is
    excluded.  Weekend/holiday resolution remains the price series' job: the
    caller selects the last observation not later than this safe cutoff.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    ny = current.astimezone(NEW_YORK)
    safe = min(requested, ny.date())
    if safe == ny.date() and ny.time().replace(tzinfo=None) < SESSION_FINAL_AT:
        safe -= timedelta(days=1)
    return safe


# ── 아침 8시 최신성 규칙 (2026-10-07) ─────────────────────────────
# 표시 표면(공포·탐욕 · VIX · NASDAQ)이 "마감된 미국 정규장"만 기록하도록 거는 공용 가드.
# 정규장 시각과 휴장일은 저장소에 이미 등록된 NYSE 휴장 계약(data/contracts/nyse_holidays.yaml)
# 을 재사용한다. 계약을 못 읽으면 주말만 거른다 — 그때는 원천이 스스로 보고한 마지막
# 거래일을 받는다(휴장일에 원천이 새 거래일을 만들어 내지는 않는다).
SESSION_OPEN_AT = time(9, 30)


def _now_ny(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(NEW_YORK)


@lru_cache(maxsize=32)
def _holidays(year: int, root=None) -> frozenset[date]:
    try:
        from pathlib import Path

        from .scenario import _holiday_for_rule, load_calendar_contract
        from . import config

        calendar = load_calendar_contract(Path(root) if root is not None else config.ROOT)
    except Exception:  # noqa: BLE001 — 달력이 없으면 주말만 거른다
        return frozenset()
    out: set[date] = set()
    for rule in calendar.get("rules") or []:
        try:
            holiday = _holiday_for_rule(year, rule)
        except Exception:  # noqa: BLE001
            continue
        if holiday is not None:
            out.add(holiday)
    for raw in calendar.get("one_off_closures") or []:
        try:
            out.add(date.fromisoformat(str(raw)))
        except ValueError:
            continue
    return frozenset(out)


def is_trading_day(day: date, *, root=None) -> bool:
    """NYSE 정규 거래일인가 (주말·등록 휴장일 제외)."""
    if day.weekday() >= 5:
        return False
    key = None if root is None else str(root)
    # 1/1 이 토요일이면 대체 휴장일이 전년 12/31 이다 — 다음 해 규칙도 함께 본다.
    return day not in (_holidays(day.year, key) | _holidays(day.year + 1, key))


def session_closed(day: date, *, now: datetime | None = None) -> bool:
    """그 날짜의 정규장이 마감(16:15 ET 정착 버퍼 포함)됐는가."""
    ny = _now_ny(now)
    if day < ny.date():
        return True
    return day == ny.date() and ny.time().replace(tzinfo=None) >= SESSION_FINAL_AT


def is_regular_session_open(now: datetime | None = None, *, root=None) -> bool:
    """지금 미국 정규장이 열려 있는가 (09:30~16:15 ET, 거래일). 장중 값은 기록하지 않는다."""
    ny = _now_ny(now)
    clock = ny.time().replace(tzinfo=None)
    return (is_trading_day(ny.date(), root=root)
            and SESSION_OPEN_AT <= clock < SESSION_FINAL_AT)


def expected_latest_session(now: datetime | None = None, *, root=None) -> date:
    """now 시점에 종가가 확정된 마지막 미국 거래일."""
    ny = _now_ny(now)
    cursor = completed_market_cutoff(ny.date(), now=ny)
    for _ in range(15):
        if is_trading_day(cursor, root=root):
            return cursor
        cursor -= timedelta(days=1)
    return cursor


def session_reflected_by(observed: date, *, root=None) -> date:
    """KST 관측일의 값이 반영하는 미국 거래일 — 관측일보다 **엄격히 앞선** 마지막 거래일.

    fear_greed._daily_tail 과 같은 규칙이다: KST 아침에 읽은 값은 직전 미국 마감을 반영한다.
    """
    cursor = observed - timedelta(days=1)
    for _ in range(15):
        if is_trading_day(cursor, root=root):
            return cursor
        cursor -= timedelta(days=1)
    return cursor


def target_session(now: datetime | None = None, *, root=None) -> date:
    """이번 실행이 기다릴 세션 — 오늘(ET)이 거래일이면 오늘, 아니면 마지막 마감 세션.

    오늘 세션이 이미 마감됐으면 expected_latest_session 과 같다.
    """
    ny = _now_ny(now)
    if is_trading_day(ny.date(), root=root):
        return ny.date()
    return expected_latest_session(ny, root=root)
