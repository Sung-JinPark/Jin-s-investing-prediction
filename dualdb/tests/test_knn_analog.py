"""Q15 k-NN 아날로그 테스트 — 합성 데이터 로직 검증 + 실DB 스모크.

합성 파트는 tmp DB에 시드 고정 랜덤워크 가격을 넣고 실제 derive 파이프라인
(build_derived_daily)을 돌려 상태벡터를 만든다 — 파생 스키마와의 정합성 겸검증.
실DB 스모크는 derived_daily가 채워져 있으면 실행 (비어 있을 때만 skip) —
record=False로 실DB model_run 원장을 오염시키지 않는다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pytest

from dualdb import db
from dualdb.derive.daily import build_derived_daily
from dualdb.models import knn_analog


def _bdays(d0: str, d1: str) -> list[str]:
    a, b = date.fromisoformat(d0), date.fromisoformat(d1)
    return [(a + timedelta(days=i)).isoformat()
            for i in range((b - a).days + 1)
            if (a + timedelta(days=i)).weekday() < 5]


def _seed_prices(conn) -> None:
    """닷컴(1995~2003)·AI(2022~2026) 창을 덮는 시드 고정 랜덤워크 종가."""
    rng = np.random.default_rng(42)
    dates = _bdays("1995-01-02", "2003-12-31") + _bdays("2022-01-03", "2026-07-14")
    logp = np.cumsum(rng.normal(0.0004, 0.015, len(dates))) + np.log(1000.0)
    rows = [(knn_analog.SERIES, d, float(np.exp(p)), "test", "2026-07-15")
            for d, p in zip(dates, logp)]
    conn.executemany(
        "INSERT OR REPLACE INTO price_daily (series,date,close,source,ingested_at)"
        " VALUES (?,?,?,?,?)", rows)
    conn.commit()


@pytest.fixture(scope="module")
def synth_conn(tmp_path_factory):
    conn = db.connect(tmp_path_factory.mktemp("knn") / "synth.sqlite")
    _seed_prices(conn)
    build_derived_daily(conn)
    return conn


# ── 단위: 이웃 선택 greedy + 90일 간격 ──────────────────────────


def test_greedy_min_gap():
    dates = ["2000-01-31", "2000-02-29", "2000-06-30", "2001-01-31", "2001-02-28"]
    dist = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    # 0 채택 → 1은 29일 간격 탈락 → 2 채택 → 3 채택 → 4는 3과 28일 간격 탈락
    assert knn_analog._greedy_select(dates, dist, k=3, min_gap_days=90) == [0, 2, 3]
    # 간격 조건을 못 채우면 k 미만이라도 있는 만큼만 반환
    assert knn_analog._greedy_select(dates[:2], dist[:2], k=2, min_gap_days=90) == [0]


# ── 단위: 전방 수익률 + 외삽 금지 None ──────────────────────────


def test_forward_returns_and_no_extrapolation():
    dates = _bdays("2003-01-01", "2003-12-31")
    closes = np.array([100.0 + i for i in range(len(dates))])
    nb = dates[-30]  # 잔여 29 거래일: +1m(21)만 산출 가능
    out = knn_analog._forward_returns(dates, closes, nb)
    c0 = closes[-30]
    assert out["fwd_1m"] == pytest.approx((c0 + 21) / c0 - 1, abs=1e-4)
    assert out["fwd_3m"] is None and out["fwd_6m"] is None and out["fwd_12m"] is None
    with pytest.raises(ValueError):
        knn_analog._forward_returns(dates, closes, "1999-01-04")  # 범위 밖 시점


# ── 단위: z 모수는 닷컴 표본에서만 (누출 방지) ──────────────────


def test_z_params_dotcom_only(synth_conn):
    dc_dates, X = knn_analog._dotcom_month_end_vectors(synth_conn)
    assert all(d <= "2003-12-31" for d in dc_dates)
    mu, sd = knn_analog._zfit(X)
    assert np.allclose(mu, X.mean(axis=0)) and np.allclose(sd, X.std(axis=0, ddof=1))
    assert (sd > 0).all()
    # 상수 피처 가드: sd=0 → 1
    _, sd0 = knn_analog._zfit(np.ones((10, 5)))
    assert (sd0 == 1.0).all()


# ── 통합: 합성 DB 전체 실행 — 형상·불변식·기록 ──────────────────


def test_run_shape_invariants_and_model_run(synth_conn):
    n_px_before = synth_conn.execute(
        "SELECT COUNT(*) c FROM price_daily").fetchone()["c"]
    res = knn_analog.run(synth_conn)
    assert set(res) >= {"asof", "neighbors", "median_fwd", "feature_vector",
                        "caveats", "run_id"}
    nbs = res["neighbors"]
    assert len(nbs) == knn_analog.K_DEFAULT
    # 거리 오름차순 (greedy는 거리순으로 채택)
    d = [n["distance"] for n in nbs]
    assert d == sorted(d) and all(x >= 0 for x in d)
    # 이웃 모두 닷컴 창 내부 + 상호 90일 이상 간격
    ds = [date.fromisoformat(n["date"]) for n in nbs]
    assert all("1995-01-01" <= n["date"] <= "2003-12-31" for n in nbs)
    assert all(abs((a - b).days) >= 90 for i, a in enumerate(ds) for b in ds[:i])
    # 중앙값 = 개별값의 중앙값 (None 제외) + 유효 표본수 n 병기
    for h in knn_analog.HORIZONS_TD:
        vals = [n[h] for n in nbs if n[h] is not None]
        expect = round(float(np.median(vals)), 4) if vals else None
        assert res["median_fwd"][h]["median"] == expect
        assert res["median_fwd"][h]["n"] == len(vals)
    # model_run에 기록됨 + params에 z 모수 저장(재현성)
    row = synth_conn.execute(
        "SELECT * FROM model_run WHERE model='knn_analog' AND run_id=?",
        (res["run_id"],)).fetchone()
    assert row is not None and row["asof"] == res["asof"]
    params = json.loads(row["params_json"])
    assert params["k"] == 5 and len(params["z_mu"]) == 5
    out = json.loads(row["output_json"])
    assert out["neighbors"] == nbs
    # 원천(raw) 계층 무접촉 — price_daily 행 수 불변
    # (test_lppl_walkforward.py의 원천 무접촉 확인과 동일 패턴)
    n_px_after = synth_conn.execute(
        "SELECT COUNT(*) c FROM price_daily").fetchone()["c"]
    assert n_px_after == n_px_before


def test_record_false_and_k_short_warning(synth_conn):
    """record=False → model_run 무기록·run_id 없음; 간격 제약 k 미달 → warning."""
    n_runs = synth_conn.execute("SELECT COUNT(*) c FROM model_run").fetchone()["c"]
    res = knn_analog.run(synth_conn, min_gap_days=10 ** 6, record=False)
    assert synth_conn.execute(
        "SELECT COUNT(*) c FROM model_run").fetchone()["c"] == n_runs
    assert "run_id" not in res
    assert len(res["neighbors"]) == 1          # 초대형 간격 → 최근접 1개만
    assert "warning" in res and "1/5" in res["warning"]
    for h in knn_analog.HORIZONS_TD:
        assert res["median_fwd"][h]["n"] <= 1
    assert "⚠" in knn_analog.render_md(res)


def test_render_md(synth_conn):
    res = knn_analog.run(synth_conn)
    md = knn_analog.render_md(res)
    assert f"asof {res['asof']}" in md
    assert "표본 n=1" in md          # 정직성 고지 필수
    assert "참고 의견" in md
    for n in res["neighbors"]:
        assert n["date"] in md
    # None 지평은 '—'로 렌더 (외삽 금지 표기)
    if any(v is None for n in res["neighbors"] for v in
           (n["fwd_1m"], n["fwd_3m"], n["fwd_6m"], n["fwd_12m"])):
        assert "—" in md


# ── 실DB 스모크 (존재 시 실행 — 비어 있을 때만 skip) ─────────────


@pytest.fixture(scope="module")
def real_conn():
    c = db.connect()
    if not c.execute(
            "SELECT 1 FROM derived_daily WHERE era_id='ai' LIMIT 1").fetchone():
        pytest.skip("derived 비어 있음 — P2 derive 후 실행")
    return c


def test_real_db_smoke(real_conn):
    # record=False — 실DB model_run 원장 무오염 (test_twins.py 실DB 스모크와 동일)
    n_runs = real_conn.execute("SELECT COUNT(*) c FROM model_run").fetchone()["c"]
    res = knn_analog.run(real_conn, record=False)
    assert real_conn.execute(
        "SELECT COUNT(*) c FROM model_run").fetchone()["c"] == n_runs
    assert res["asof"] >= "2026-01-01"          # AI 시대 최신 시점
    assert len(res["neighbors"]) == 5
    assert res["n_pool_samples"] >= 90          # 아날로그 풀 월말 표본 충분
    # 다중 시대 풀 활성 — dotcom 외 아날로그 시대 최소 1개 포함 (Phase 1-B)
    assert res["n_eras"] >= 2, f"풀 시대 {res['pool_eras']} — 다중화 실패 의심"
    assert "dotcom" in res["pool_eras"]
    assert all(n.get("era") in knn_analog.ANALOG_ERAS for n in res["neighbors"])
    assert all(np.isfinite(n["distance"]) for n in res["neighbors"])
    md = knn_analog.render_md(res)
    assert "한계" in md and "표본 n=" in md and "다중 아날로그" in md
