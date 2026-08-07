"""Fama-French 팩터 파싱 + factor_monthly 적재 테스트.

단위 파트는 합성 CSV 문자열로 _parse_monthly/_f 로직을 검증(네트워크 무관).
실DB 스모크는 factor_monthly가 채워져 있으면 실행 — 센티널·시대 커버리지.
"""

from __future__ import annotations

import pytest

from dualdb import db
from dualdb.ingest import french

# 헤더 junk + 5팩터 헤더 + 월간 3행 + 연간 경계 (실제 포맷 축약)
_SYNTH_FIVE = """This file was created using the 202605 CRSP database.

,Mkt-RF,SMB,HML,RMW,CMA,RF
196307,   -0.39,   -0.48,   -0.81,    0.64,   -1.15,    0.27
196308,    5.07,   -0.83,    1.65,    0.36,   -0.40,    0.25
202605,    4.90,   -2.77,   -2.15,   -8.42,   -1.39,    0.31

  Annual Factors: January-December

1964,   12.59,    0.40,    9.82,   -2.59,    6.64,    3.54
"""

_SYNTH_MOM = """  This file ... momentum factor ...

,Mom
192701,   0.57
196307,   -0.42
202605,   -1.10

1927,  24.52
"""


def test_missing_sentinel_to_none():
    assert french._f("-99.99") is None
    assert french._f("-999") is None
    assert french._f("  ") is None
    assert french._f("2.89") == 2.89
    assert french._f("-0.39") == -0.39


def test_parse_monthly_five_factor():
    out = french._parse_monthly(_SYNTH_FIVE)
    assert set(out) == {"196307", "196308", "202605"}   # 연간 1964 제외
    r = out["196307"]
    assert r["mkt_rf"] == -0.39 and r["cma"] == -1.15 and r["rf"] == 0.27
    assert r["smb"] == -0.48 and r["hml"] == -0.81 and r["rmw"] == 0.64
    assert "mom" not in r                                # 5팩터엔 모멘텀 없음


def test_parse_monthly_momentum():
    out = french._parse_monthly(_SYNTH_MOM)
    assert set(out) == {"192701", "196307", "202605"}
    assert out["192701"]["mom"] == 0.57
    assert list(out["196307"]) == ["mom"]               # 모멘텀 단일 컬럼


# ── 실DB 스모크 ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def conn():
    c = db.connect()
    if not c.execute("SELECT 1 FROM factor_monthly LIMIT 1").fetchone():
        pytest.skip("factor_monthly 비어 있음 — ingest 후 실행")
    return c


def test_factor_monthly_coverage(conn):
    r = conn.execute("SELECT COUNT(*) n, MIN(date) d0, MAX(date) d1 FROM factor_monthly").fetchone()
    assert r["n"] > 700
    assert r["d0"] <= "1927-01-01"                       # 모멘텀 1927+
    assert r["d1"] >= "2026-01-01"                        # 최신 (~2개월 지연)


def test_factor_sentinels(conn):
    # Ken French 공표값 (독립 검증 가능)
    for date, col, exp in [("1927-01-01", "mom", 0.57), ("1963-07-01", "mkt_rf", -0.39),
                           ("1963-07-01", "cma", -1.15)]:
        r = conn.execute(f"SELECT {col} v FROM factor_monthly WHERE date=?", (date,)).fetchone()
        assert r is not None and r["v"] == pytest.approx(exp, abs=0.01), f"{date} {col}"


def test_five_factor_covers_all_eras(conn):
    """모든 아날로그 시대 창(1970+)이 5팩터를 보유 — factor tilt 산출 가능."""
    for w0, w1 in [("1970-01-01", "1976-12-31"), ("1995-01-01", "2003-12-31"),
                   ("2012-01-01", "2017-12-31"), ("2022-01-01", "2026-05-01")]:
        n = conn.execute(
            "SELECT COUNT(*) n FROM factor_monthly WHERE rmw IS NOT NULL AND date BETWEEN ? AND ?",
            (w0, w1)).fetchone()["n"]
        assert n > 40, f"{w0}~{w1} 5팩터 {n}개월 (부족)"
