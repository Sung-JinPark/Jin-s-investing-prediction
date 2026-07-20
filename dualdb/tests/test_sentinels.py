"""§11 센티널 게이트 — P1 통과 조건. 불일치 시 데이터 재수집, 테스트 수정 금지 (§10.4)."""

from __future__ import annotations

import pytest

from dualdb import db

SENTINELS = {  # (series, date): (expected_close, tol)
    ("^IXIC", "1996-01-31"): (1059.79, 0.5),    # 닷컴 M+0
    ("^IXIC", "2000-03-10"): (5048.62, 0.5),    # 닷컴 정점
    ("^IXIC", "2002-10-09"): (1114.11, 0.5),    # 닷컴 바닥
    ("^IXIC", "2023-01-31"): (11584.55, 1.0),   # AI M+0
    ("^IXIC", "2026-06-02"): (27093.90, 1.0),   # AI ATH
    ("^IXIC", "2026-07-14"): (26107.01, 1.0),   # 최신 앵커
}


@pytest.fixture(scope="module")
def conn():
    c = db.connect()
    if not c.execute("SELECT 1 FROM price_daily LIMIT 1").fetchone():
        pytest.skip("price_daily 비어 있음 — P1 ingest 후 실행")
    return c


@pytest.mark.parametrize("key", list(SENTINELS))
def test_price_sentinel(conn, key):
    series, date = key
    expected, tol = SENTINELS[key]
    row = conn.execute(
        "SELECT close FROM price_daily WHERE series=? AND date=?", (series, date)).fetchone()
    assert row is not None, f"{series} {date} 행 없음"
    assert row["close"] == pytest.approx(expected, abs=tol)


def test_vix_ltcm_fear(conn):
    """LTCM 공포 확인 — FRED VIXCLS 우선, 차단 시 Yahoo ^VIX(동일 지수) 인정 (CHANGELOG #7)."""
    row = conn.execute(
        "SELECT value FROM macro_daily WHERE series_id='VIXCLS' AND date='1998-10-08'"
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT close AS value FROM price_daily WHERE series='^VIX' AND date='1998-10-08'"
        ).fetchone()
    assert row is not None and row["value"] > 40


def test_ritter_1999_negative_eps(conn):
    row = conn.execute("SELECT pct_negative_eps FROM ipo_annual WHERE year=1999").fetchone()
    assert row is not None and row["pct_negative_eps"] > 70


def test_ixic_coverage(conn):
    from datetime import date, timedelta
    r = conn.execute(
        "SELECT COUNT(*) n, MIN(date) d0, MAX(date) d1 FROM price_daily"
        " WHERE series='^IXIC' AND date >= '1995-01-01'").fetchone()
    assert r["n"] > 7000
    assert date.fromisoformat(r["d1"]) >= date.today() - timedelta(days=7)
    d0, d1 = date.fromisoformat(r["d0"]), date.fromisoformat(r["d1"])
    biz = sum(1 for i in range((d1 - d0).days + 1)
              if date.fromordinal(d0.toordinal() + i).weekday() < 5)
    holidays_allowance = 0.045  # 미 공휴일 ~9일/년
    assert 1 - r["n"] / biz < holidays_allowance + 0.005  # 실질 결측 < 0.5%


def test_dual_source_cross_check(conn):
    """FRED NASDAQCOM vs Yahoo ^IXIC 종가 차이 > 0.1% 인 날 비율이 1% 미만.

    FRED가 이 네트워크에서 차단이면 보류(skip) — 통과로 위장하지 않는다 (§10.6).
    """
    rows = conn.execute(
        """SELECT p.close AS yahoo, m.value AS fred FROM price_daily p
           JOIN macro_daily m ON m.series_id='NASDAQCOM' AND m.date=p.date
           WHERE p.series='^IXIC' AND p.date >= '1995-01-01'""").fetchall()
    if not rows:
        pytest.skip("FRED NASDAQCOM 미수집 (네트워크 차단) — 교차검증 보류, DoD 부분통과로 보고")
    assert len(rows) > 5000
    bad = sum(1 for r in rows if abs(r["yahoo"] - r["fred"]) / r["fred"] > 0.001)
    assert bad / len(rows) < 0.01, f"교차검증 불일치 {bad}/{len(rows)}"


def test_seed_minimums(conn):
    assert conn.execute("SELECT COUNT(*) c FROM dotcom_casualty").fetchone()["c"] >= 25
    assert conn.execute(
        "SELECT COUNT(*) c FROM event WHERE era_id='dotcom'").fetchone()["c"] >= 13
    assert conn.execute(
        "SELECT COUNT(*) c FROM event WHERE era_id='ai'").fetchone()["c"] >= 12
