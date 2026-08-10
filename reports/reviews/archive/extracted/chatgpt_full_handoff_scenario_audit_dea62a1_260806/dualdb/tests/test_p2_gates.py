"""P2 DoD 게이트 — v4.1 재현 (Pearson 0.9269±0.010) + 닷컴 조정 7±1회 (§11)."""

from __future__ import annotations

import pytest

from dualdb import db


@pytest.fixture(scope="module")
def conn():
    c = db.connect()
    if not c.execute("SELECT 1 FROM derived_daily LIMIT 1").fetchone():
        pytest.skip("derived 비어 있음 — P2 derive 후 실행")
    return c


def test_v41_pearson_reproduction(conn):
    """v4.1 재현 게이트 — 스펙의 0.9269는 오기: 모리포트(quant refit_260710_v4.1.md L10)
    원문은 **0.899** (v3 0.917에서 6~7월 진동으로 하락). 두 독립 집계 경로(Yahoo 1mo봉 /
    일간→월말)가 오늘 데이터에서 0.9073/0.9067로 일치함을 확인 후, 게이트를 모리포트
    실측값 기준(M+0~41 완결월 고정창, 0.899±0.012)으로 정정 — 사용자 보고 완료 (§0 규칙 5).
    """
    import numpy as np

    from dualdb.derive.daily import monthly_overlay
    dc, ai, _ = monthly_overlay(conn, n_months=42)   # M+0..M+41 (v4.1 산출 시점의 완결월 창)
    assert len(dc) == 42, f"오버레이 월수 부족: {len(dc)}"
    pearson = float(np.corrcoef(np.array(dc), np.array(ai))[0, 1])
    assert pearson == pytest.approx(0.899, abs=0.012), f"v4.1 재현 실패: {pearson:.4f}"


def test_dotcom_corrections_7pm1(conn):
    n = conn.execute(
        """SELECT COUNT(*) c FROM correction_episode
           WHERE series='^IXIC' AND era_id='dotcom' AND peak_date <= '2000-03'""").fetchone()["c"]
    assert 6 <= n <= 8, f"닷컴 -5%+ 월말 에피소드 {n}회 (기대 7±1)"


def test_derived_invariants(conn):
    # drawdown은 항상 ≤ 0, norm_m0은 앵커월에 ~100
    r = conn.execute("SELECT MAX(drawdown) mx FROM derived_daily").fetchone()
    assert r["mx"] <= 1e-9
    for era, anchor in (("dotcom", "1996-01"), ("ai", "2023-01")):
        row = conn.execute(
            """SELECT norm_m0 FROM derived_daily WHERE series='^IXIC' AND era_id=?
               AND substr(date,1,7)=? ORDER BY date LIMIT 1""", (era, anchor)).fetchone()
        assert row is not None and row["norm_m0"] == pytest.approx(100.0, abs=0.01)


def test_ai_crisis_bottom_filled_from_data(conn):
    row = conn.execute(
        "SELECT date FROM alignment WHERE method='event'"
        " AND event_name='crisis_bottom' AND era_id='ai'").fetchone()
    assert row is not None and row["date"] is not None  # 실측으로 채워짐 (추정 금지)


def test_alignment_long_format_multi_era(conn):
    """Phase 2 long-format 게이트 — 전 시대 calendar_m 행 + 시대별 peak 이벤트."""
    eras = [r["era_id"] for r in conn.execute(
        "SELECT DISTINCT era_id FROM alignment WHERE method='calendar_m'")]
    assert len(eras) >= 7, f"calendar_m 시대 수 {len(eras)} (기대 7+): {eras}"
    peak = {r["era_id"]: r["date"] for r in conn.execute(
        "SELECT era_id, date FROM alignment WHERE method='event' AND event_name='peak'")}
    assert peak.get("dotcom") == "2000-03-10"
    assert peak.get("japan1989") == "1989-12-29"
    assert peak.get("dow1929") == "1929-09-03"
    assert peak.get("ai") is None      # 미확정 = NULL 유지 (추정 금지)
