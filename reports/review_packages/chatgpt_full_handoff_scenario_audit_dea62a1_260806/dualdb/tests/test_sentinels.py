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
    # 다중 시대 아날로그 정점 (Phase 1-A — 독립 검증 가능한 유명값)
    ("^N225", "1989-12-29"): (38915.87, 1.0),   # 닛케이 사상 최고(2024년 전까지)
    ("^SPX", "1972-12-11"): (119.12, 0.5),      # Nifty Fifty 정점
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


def test_dow1929_monthly_tier(conn):
    """Phase 2: dow1929 월간 tier — 대공황 조정이 정확히 잡히고 일간 경로에서 제외.

    센티널: 1929-09→1932-06 월평균 지수 깊이 ≈ -87% (일중 극값 -89%보다 완만 — 원천
    해상도 한계 명기). k-NN 풀·일간 파생에는 절대 포함되지 않아야 한다 (가짜 일간
    피처 금지).
    """
    row = conn.execute(
        "SELECT peak_date, trough_date, depth FROM correction_episode"
        " WHERE era_id='dow1929' ORDER BY depth ASC LIMIT 1").fetchone()
    if row is None:
        pytest.skip("dow1929 미수집 (FRED M1109BUSM293NNBR) — ingest 후 실행")
    assert row["peak_date"] == "1929-09" and row["trough_date"] == "1932-06"
    assert row["depth"] == pytest.approx(-0.871, abs=0.02)
    # 일간 경로 제외 보증
    from dualdb.derive.daily import ERA_MONTHLY, ERA_WINDOWS
    from dualdb.models.knn_analog import ANALOG_ERAS
    assert "dow1929" in ERA_MONTHLY
    assert "dow1929" not in ERA_WINDOWS and "dow1929" not in ANALOG_ERAS
    n = conn.execute(
        "SELECT COUNT(*) n FROM derived_daily WHERE era_id='dow1929'").fetchone()["n"]
    assert n == 0, f"dow1929 일간 파생 {n}행 — 월간 tier가 일간 경로에 누출"


def test_usrec_recession_series(conn):
    """Phase 2: NBER USREC(0/1, 1854+) — regime.recession_flag 실측 원천."""
    r = conn.execute(
        "SELECT COUNT(*) n, MIN(date) d0, MAX(date) d1 FROM macro_monthly"
        " WHERE series_id='USREC'").fetchone()
    if r["n"] == 0:
        pytest.skip("USREC 미수집 — ingest 후 실행")
    assert r["n"] > 2000 and r["d0"] <= "1860-01-01"
    vals = {row["value"] for row in conn.execute(
        "SELECT DISTINCT value FROM macro_monthly WHERE series_id='USREC'")}
    assert vals <= {0.0, 1.0}


def test_ixic_fred_promotion(conn):
    """DECISIONS 9-5: ^IXIC 1995~2004 종가 정본 = FRED NASDAQCOM (2,519행).

    yahoo 재수집이 close를 raw로 되돌리면 교차검증이 3.11%로 회귀 —
    promote_ixic_close가 ingest_indices 말미에서 항상 재적용됨을 보장한다.
    """
    row = conn.execute(
        """SELECT COUNT(*) n FROM price_daily WHERE series='^IXIC'
           AND date BETWEEN '1995-01-01' AND '2004-12-31'
           AND source='fred-close+yahoo-ohlcv'""").fetchone()
    assert row["n"] == 2519, f"9-5 승격 {row['n']}행 (기대 2519) — 재수집이 되돌렸을 수 있음"


def test_multi_era_derived_coverage(conn):
    """다중 시대 파생 커버리지 — derived_daily PK가 (series,date,era_id)임을 보증.

    era_id 없는 PK면 겹침 창(dotcom 1995~2003 ∩ japan1989 1984~2003)의 ^IXIC 행이
    나중 era에 덮여 dotcom 파생이 0으로 소실된다 (Phase 1-A 회귀). 각 아날로그 지수가
    자기 시대의 파생을 보유하는지 확인한다.
    """
    if not conn.execute("SELECT 1 FROM derived_daily LIMIT 1").fetchone():
        pytest.skip("derived_daily 비어 있음 — derive 후 실행")
    # ^IXIC는 dotcom·ai 두 시대에 각각 파생 보유 (겹침 소실 방지 회귀 가드)
    dot = conn.execute(
        "SELECT COUNT(*) n FROM derived_daily WHERE series='^IXIC' AND era_id='dotcom'").fetchone()["n"]
    ai = conn.execute(
        "SELECT COUNT(*) n FROM derived_daily WHERE series='^IXIC' AND era_id='ai'").fetchone()["n"]
    assert dot > 2000, f"^IXIC dotcom 파생 {dot}행 (기대 >2000) — PK 겹침 소실 의심"
    assert ai > 500, f"^IXIC ai 파생 {ai}행"
    # 신규 아날로그 지수가 자기 시대 파생 보유
    for era, series in [("japan1989", "^N225"), ("crypto2021", "BTC-USD"),
                        ("biotech2015", "IBB"), ("niftyfifty1972", "^SPX")]:
        n = conn.execute(
            "SELECT COUNT(*) n FROM derived_daily WHERE era_id=? AND series=?",
            (era, series)).fetchone()["n"]
        assert n > 500, f"{era}/{series} 파생 {n}행 (기대 >500)"
