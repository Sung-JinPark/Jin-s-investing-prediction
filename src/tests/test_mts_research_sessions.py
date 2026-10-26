"""세션 달력 테스트 — T10 (DST·휴장·조기폐장·UTC 변환) + CalendarRef.

오라클은 하드코딩된 실제 XNAS 세션 시각이다 (2026-03 DST 전환 주간, 2026-07-03 조기폐장).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ai_fc.mts_research.sessions import (
    MtsSessionError,
    future_sessions,
    information_cutoff_for,
    last_completed_session,
    observation_grid_ref,
    session_offset,
    session_table,
    xnas_ref,
)
from mts_research_fixtures import utc


def test_t10_dst_transition_close_times():
    """2026-03-06(EST, UTC-5) 종가 21:00Z → 2026-03-09(EDT, UTC-4) 종가 20:00Z (T10)."""
    table = {row.session: row for row in session_table(date(2026, 3, 5), date(2026, 3, 10))}
    assert table["2026-03-06"].close_utc == utc(2026, 3, 6, 21, 0)
    assert table["2026-03-09"].close_utc == utc(2026, 3, 9, 20, 0)
    assert not table["2026-03-06"].early_close and not table["2026-03-09"].early_close


def test_t10_early_close_and_holiday():
    """2025-07-03 조기폐장(13:00 ET=17:00Z), 2025-07-04(금) 휴장 처리 (T10).

    참고: 2026 년은 7/4 가 토요일이라 7/3 자체가 휴장이다 — 그 경우도 아래에서 검증.
    """
    table = {row.session: row for row in session_table(date(2025, 7, 1), date(2025, 7, 8))}
    assert "2025-07-04" not in table  # 금요일 휴장
    assert table["2025-07-02"].early_close is False
    early = table["2025-07-03"]
    assert early.early_close is True
    assert early.close_utc == utc(2025, 7, 3, 17, 0)
    # cutoff 정책은 실제 close 기준 (조기폐장일은 17:00Z + 15분)
    assert information_cutoff_for(date(2025, 7, 3)) == utc(2025, 7, 3, 17, 15)
    assert information_cutoff_for(date(2025, 7, 2)) == utc(2025, 7, 2, 20, 15)
    # 2026: 7/4 토요일 → 7/3(금) 전일 휴장 — 세션이 아니다
    table_2026 = {row.session for row in session_table(date(2026, 7, 1), date(2026, 7, 7))}
    assert "2026-07-03" not in table_2026 and "2026-07-04" not in table_2026


def test_t10_horizon_counts_sessions_not_weekdays():
    """지평은 거래 세션 수 — 휴장·주말을 건너뛴다 (T10).

    2025-07-02 의 다음 세션은 7/3(조기폐장), 그다음은 7/7(월) — 7/4 휴장 + 주말 스킵.
    """
    sessions = future_sessions(date(2025, 7, 2), 2)
    assert [d.isoformat() for d in sessions] == ["2025-07-03", "2025-07-07"]
    assert session_offset(date(2025, 7, 2), 2).isoformat() == "2025-07-07"


def test_non_session_origin_rejected():
    with pytest.raises(MtsSessionError):
        future_sessions(date(2026, 7, 4), 1)  # 토요일
    with pytest.raises(MtsSessionError):
        information_cutoff_for(date(2026, 7, 3))  # 2026 관측 휴장일


def test_last_completed_session_settle_buffer():
    """close+15분 전에는 그 세션이 완결로 집계되지 않는다."""
    close = utc(2025, 7, 2, 20, 0)
    assert last_completed_session(close + timedelta(minutes=10)).isoformat() == "2025-07-01"
    assert last_completed_session(close + timedelta(minutes=20)).isoformat() == "2025-07-02"


def test_calendar_refs_stable_and_distinct():
    ref1 = xnas_ref(date(2026, 7, 1), date(2026, 7, 7))
    ref2 = xnas_ref(date(2026, 7, 1), date(2026, 7, 7))
    assert ref1.calendar_hash == ref2.calendar_hash
    assert ref1.library_version is not None
    grid = observation_grid_ref(["2026-07-01", "2026-07-02"])
    assert grid.calendar_hash != ref1.calendar_hash
    with pytest.raises(MtsSessionError):
        observation_grid_ref(["2026-07-02", "2026-07-01"])  # 비정렬 grid 거부
