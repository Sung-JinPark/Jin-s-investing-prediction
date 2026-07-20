"""Q14 트윈 대조 테스트 — 합성 데이터로 로직(수익률·MDD·vol·기준가 폴백·불변식) 검증
+ 실DB 스모크(데이터 존재 시 실행, record=False로 model_run 오염 없음)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from dualdb import db
from dualdb.analysis import twins

PEAK = "2000-03-10"           # config.ANCHORS['dotcom']['peak_date']
POST_END = "2002-03-10"
AI_END = "2026-07-10"         # 합성 asof — 최신일


def _insert_daily(conn, series, d0, d1, price_fn, with_adj=True):
    """d0~d1 매일 price_fn(경과일, 총일수) 가격 삽입. with_adj=False → adj_close NULL."""
    start, end = date.fromisoformat(d0), date.fromisoformat(d1)
    n = (end - start).days
    rows = []
    for i in range(n + 1):
        d = start + timedelta(days=i)
        p = price_fn(i, n)
        rows.append((series, d.isoformat(), p, p if with_adj else None))
    conn.executemany(
        "INSERT OR REPLACE INTO price_daily(series,date,close,adj_close,source,ingested_at)"
        " VALUES (?,?,?,?,'synthetic','test')", rows)


@pytest.fixture()
def syn_conn(tmp_path):
    conn = db.connect(tmp_path / "twins_test.sqlite")
    conn.executemany(
        "INSERT INTO entity(era_id,ticker,name,role_code,status,data_ticker,is_twin)"
        " VALUES (?,?,?,?,?,?,?)",
        [("dotcom", "TWA", "TwinA", "platform", "alive", "TWA", 1),
         ("dotcom", "TWB", "TwinB", "memory", "alive", "TWB", 1),
         ("dotcom", "NOTW", "NotTwin", "app", "alive", "NOTW", 0),      # is_twin=0 제외
         ("ai", "TWAI", "AiOnly", "platform", "alive", "TWAI", 1)])     # era 필터 제외
    # TWA: 정점 전 100→400 (+300%), 정점 후 400→80 (-80%), AI 창 50 유지 + -20% 딥
    _insert_daily(conn, "TWA", "1998-03-10", PEAK,
                  lambda i, n: 100.0 * 4.0 ** (i / n))
    _insert_daily(conn, "TWA", "2000-03-11", POST_END,
                  lambda i, n: 400.0 * 0.2 ** ((i + 1) / (n + 1)))
    _insert_daily(conn, "TWA", "2024-01-01", AI_END,
                  lambda i, n: 40.0 if 380 <= i <= 410 else 50.0)  # 딥은 창 내부(2025-01경)
    # TWB: adj_close 없음(close 폴백), 정점 전 +100%, 정점 후 -50%, AI 창 상수
    _insert_daily(conn, "TWB", "1998-03-10", PEAK,
                  lambda i, n: 100.0 * 2.0 ** (i / n), with_adj=False)
    _insert_daily(conn, "TWB", "2000-03-11", POST_END,
                  lambda i, n: 200.0 * 0.5 ** ((i + 1) / (n + 1)), with_adj=False)
    _insert_daily(conn, "TWB", "2024-01-01", AI_END,
                  lambda i, n: 10.0, with_adj=False)
    conn.commit()
    return conn


def test_add_months_edges():
    assert twins._add_months("2000-03-31", -1) == "2000-02-29"   # 말일 절사(윤년)
    assert twins._add_months("1999-01-31", 1) == "1999-02-28"
    assert twins._add_months("2026-07-13", -24) == "2024-07-13"
    assert twins._add_months(PEAK, 24) == POST_END


def test_synthetic_metrics_and_shape(syn_conn):
    res = twins.run(syn_conn, record=True)
    assert [t["ticker"] for t in res["twins"]] == ["TWA", "TWB"]  # 필터·정렬
    assert res["asof"] == AI_END
    assert res["windows"]["ai"] == ["2024-07-10", AI_END]

    twa = res["twins"][0]
    assert twa["price_basis"] == "adj_close"
    assert twa["dotcom_pre"]["tot_ret"] == pytest.approx(3.0, abs=1e-9)
    assert twa["dotcom_pre"]["mdd"] == pytest.approx(0.0, abs=1e-9)     # 단조 상승
    assert twa["dotcom_pre"]["ann_vol"] == pytest.approx(0.0, abs=1e-6)  # 등비 경로
    assert twa["dotcom_post24m_ret"] == pytest.approx(-0.8, abs=1e-9)
    assert twa["dotcom_collapse_dd"] == pytest.approx(-0.8, abs=1e-9)
    assert twa["ai"]["tot_ret"] == pytest.approx(0.0, abs=1e-9)
    assert twa["ai"]["mdd"] == pytest.approx(-0.2, abs=1e-9)

    twb = res["twins"][1]
    assert twb["price_basis"] == "close"                                 # adj_close 폴백
    assert twb["dotcom_pre"]["tot_ret"] == pytest.approx(1.0, abs=1e-9)
    assert twb["dotcom_post24m_ret"] == pytest.approx(-0.5, abs=1e-9)

    s = res["summary"]
    assert s["median_dotcom_pre24m_ret"] == pytest.approx(2.0, abs=1e-9)
    assert s["median_dotcom_post24m_ret"] == pytest.approx(-0.65, abs=1e-9)
    assert s["median_ai_recent24m_ret"] == pytest.approx(0.0, abs=1e-9)
    assert s["mu_highlight"] is None                                     # MU 부재
    assert "생존" in res["survivorship_note"]


def test_synthetic_model_run_and_render(syn_conn):
    res = twins.run(syn_conn, record=True)
    row = syn_conn.execute(
        "SELECT * FROM model_run WHERE run_id=?", (res["run_id"],)).fetchone()
    assert row["model"] == "twins_q14" and row["asof"] == AI_END
    out = json.loads(row["output_json"])
    assert out["question"] == "Q14_twins" and len(out["twins"]) == 2
    assert out["survivorship_note"] == twins.SURVIVORSHIP_NOTE

    n_before = syn_conn.execute("SELECT COUNT(*) c FROM model_run").fetchone()["c"]
    twins.run(syn_conn, record=False)                                    # 무기록 모드
    assert syn_conn.execute(
        "SELECT COUNT(*) c FROM model_run").fetchone()["c"] == n_before

    md = twins.render_md(res)
    assert "생존편향 경고" in md and "| TWA |" in md and "adj_close" in md
    assert "한계" in md and "Tier-1" in md


# ── 실DB 스모크 — 데이터가 있으면 반드시 실행 (record=False, 원장 무오염) ──

@pytest.fixture(scope="module")
def real_conn():
    c = db.connect()
    if not c.execute(
            "SELECT 1 FROM price_daily WHERE series='MSFT' LIMIT 1").fetchone():
        pytest.skip("실DB 트윈 가격 없음 — ingest 후 실행")
    return c


def test_real_db_smoke(real_conn):
    res = twins.run(real_conn, record=False)
    assert len(res["twins"]) == 12, "트윈 12종 전부 산출되어야 함"
    assert all(t["price_basis"] in ("adj_close", "close") for t in res["twins"])
    assert all(t["dotcom_pre"] and t["dotcom_pre"]["mdd"] <= 0 for t in res["twins"])
    # 닷컴 과거 창은 고정 역사 — 사전 검증값 재현 (배당 소급조정은 창 내 비율 불변)
    assert res["summary"]["median_dotcom_pre24m_ret"] == pytest.approx(4.22, abs=0.10)
    assert res["summary"]["median_dotcom_post24m_ret"] < -0.3
    mu = next(t for t in res["twins"] if t["ticker"] == "MU")
    assert mu["dotcom_collapse_dd"] <= -0.85, "MU 닷컴 붕괴 -90%대 base rate 재현 실패"
    md = twins.render_md(res)
    assert "MU 별도 강조" in md and "생존편향 경고" in md
