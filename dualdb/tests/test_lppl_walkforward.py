"""LPPL 워크포워드 테스트 — 합성 신호 로직 검증(수렴·형상·불변식) + 실DB 스모크.

합성 데이터는 임시(throwaway) DB에만 기록 — 실DB 원천 테이블 무접촉 (§10).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from dualdb import db
from dualdb.models.lppl_walkforward import (
    STABLE_TOL,
    TC_HORIZON,
    _ym_add,
    _ym_diff,
    fit_ai_live,
    fit_lppl,
    render_md,
    run,
    summarize,
    walkforward,
    walkforward_dotcom,
)

# ── 합성 LPPL 신호 (알려진 tc) ───────────────────────

TC_TRUE = 62.0  # base 1995-01 기준 → 2000-03
LPPL_PARAMS = dict(beta=0.35, omega=6.5, phi=1.0, A=7.0, B=-0.8, C=0.06)


def _lppl_curve(n: int, tc: float = TC_TRUE, noise: float = 0.005, seed: int = 0
                ) -> np.ndarray:
    p = LPPL_PARAMS
    t = np.arange(n, dtype=float)
    dt = np.maximum(tc - t, 1e-9)
    lp = (p["A"] + p["B"] * dt ** p["beta"]
          + p["C"] * dt ** p["beta"] * np.cos(p["omega"] * np.log(dt) - p["phi"]))
    rng = np.random.default_rng(seed)
    return np.exp(lp + rng.normal(0, noise, n))


def _month_series(n: int, base: str = "1995-01", **kw) -> list[tuple[str, float]]:
    closes = _lppl_curve(n, **kw)
    return [(_ym_add(base, i), float(c)) for i, c in enumerate(closes)]


# ── 로직 검증 (DB 무접촉) ────────────────────────────


def test_synthetic_tc_recovery():
    """알려진 tc=62에서 t=0..50 적합 → ±3개월 내 회복 (스펙 요구)."""
    closes = list(_lppl_curve(51))
    fit = fit_lppl(closes, seed=42, maxiter=200)
    assert abs(fit.tc - TC_TRUE) <= 3.0, f"tc {fit.tc:.2f} vs 진값 {TC_TRUE}"
    assert fit.r2 > 0.95
    assert not fit.boundary_hit


def test_fit_reproducible_and_bounded():
    """seed 고정 재현성 + tc가 탐색 구간 (n+0.5, n+36) 안."""
    closes = list(_lppl_curve(48))
    f1 = fit_lppl(closes, seed=42, maxiter=120)
    f2 = fit_lppl(closes, seed=42, maxiter=120)
    assert f1.tc == f2.tc and f1.beta == f2.beta and f1.omega == f2.omega
    n = len(closes)
    assert n + 0.5 <= f1.tc <= n + TC_HORIZON
    assert 0.1 <= f1.beta <= 0.9 and 4.0 <= f1.omega <= 25.0


def test_walkforward_shape_and_invariants():
    """합성 신호 워크포워드 — 행수·단조 asof·리드 정의·수렴 요약 불변식."""
    series = _month_series(66)  # 1995-01..2000-06
    rows = walkforward(series, "1999-10", "2000-02", "2000-03", seed=42, maxiter=120)
    assert len(rows) == 5
    assert [r["asof_month"] for r in rows] == [
        "1999-10", "1999-11", "1999-12", "2000-01", "2000-02"]
    for r in rows:
        assert r["n_obs"] == _ym_diff(r["asof_month"], "1995-01") + 1
        assert r["n_obs"] + 0.5 <= r["tc_est"] <= r["n_obs"] + TC_HORIZON
        assert r["lead_months"] == pytest.approx(r["tc_est"] - 62, abs=0.011)
        assert np.isfinite(r["r2"])
    # 합성 진신호 → 정점 근방에서 |리드| 작아야 함
    assert abs(np.median([r["lead_months"] for r in rows])) <= STABLE_TOL
    s = summarize(rows, "2000-03", "1995-01")
    assert s["lead_q25"] <= s["lead_median"] <= s["lead_q75"]
    assert s["n_fits"] == 5
    if s["stable"] is not None:
        assert 1 <= s["stable"]["months_before_peak"] <= 62
        assert s["stable"]["n_points"] <= 5


def test_walkforward_rejects_gapped_months():
    series = _month_series(60)
    del series[30]  # 결측월 → t 인덱스 왜곡이므로 거부해야 함
    with pytest.raises(ValueError, match="결측"):
        walkforward(series, "1999-10", "1999-12", "2000-03", seed=42, maxiter=60)


# ── 임시 DB end-to-end (model_run 기록·render) ──────


def test_run_end_to_end_temp_db(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    rows = []
    for m, c in _month_series(66, base="1995-01"):          # 닷컴 창
        rows.append(("^IXIC", f"{m}-28", c))
    for m, c in _month_series(48, base="2022-01", tc=80.0):  # AI 창 (완결월만)
        rows.append(("^IXIC", f"{m}-28", c))
    conn.executemany(
        "INSERT INTO price_daily (series, date, close, source, ingested_at)"
        " VALUES (?,?,?,'synthetic_test','2026-01-01')", rows)
    conn.commit()
    result = run(conn, start_asof="1999-11", end_asof="2000-02", seed=1,
                 maxiter=80, record=True)
    assert result["dotcom"]["base_month"] == "1995-01"
    assert len(result["dotcom"]["rows"]) == 4
    assert result["ai"]["n_obs"] == 48
    # 보정 산식: tc_corrected = tc_raw − lead_median
    s = result["dotcom"]["summary"]
    assert result["ai"]["tc_corrected"] == pytest.approx(
        result["ai"]["tc_raw"] - s["lead_median"], abs=0.011)
    # model_run에 1행, output_json 재파싱 일치
    mr = conn.execute(
        "SELECT * FROM model_run WHERE model='lppl_walkforward'").fetchall()
    assert len(mr) == 1
    stored = json.loads(mr[0]["output_json"])
    assert stored["ai"]["tc_raw"] == result["ai"]["tc_raw"]
    # 원천 테이블 무접촉 확인 (모듈이 price_daily에 아무것도 안 씀)
    n_px = conn.execute("SELECT COUNT(*) c FROM price_daily").fetchone()["c"]
    assert n_px == len(rows)
    md = render_md(result)
    assert "리드 중앙값" in md and "한계" in md and "버블" in md


# ── 실DB 스모크 (존재 시 실행 — skip 아님, 기록은 하지 않음) ──


@pytest.fixture(scope="module")
def real_conn():
    c = db.connect()
    if not c.execute(
            "SELECT 1 FROM price_daily WHERE series='^IXIC' LIMIT 1").fetchone():
        pytest.skip("price_daily 비어 있음 — ingest 후 실행")
    return c


def test_real_db_walkforward_smoke(real_conn):
    """실DB 닷컴 꼬리 3개월 축약 워크포워드 — 형상·범위만 확인 (기록 없음)."""
    rows = walkforward_dotcom(real_conn, start_asof="1999-12", end_asof="2000-02",
                              seed=42, maxiter=120)
    assert len(rows) == 3
    for r in rows:
        assert abs(r["lead_months"]) < TC_HORIZON
        assert r["r2"] > 0.9
    # 정점 직전월(2000-02)에서는 오차가 크지 않아야 함 (사후검증 관측치)
    assert abs(rows[-1]["lead_months"]) <= 12


def test_real_db_ai_live_smoke(real_conn):
    ai = fit_ai_live(real_conn, seed=42, maxiter=120)
    assert ai["base_month"] == "2022-01"
    assert ai["n_obs"] >= 48
    assert ai["n_obs"] + 0.5 <= ai["tc_raw"] <= ai["n_obs"] + TC_HORIZON
    assert np.isfinite(ai["fit"]["r2"])
