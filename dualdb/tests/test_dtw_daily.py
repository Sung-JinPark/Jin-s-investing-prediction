"""dtw_daily 검증 — 합성 데이터 로직(수렴·형상·불변식) + 실DB 스모크.

실DB 스모크는 backup API로 뜬 임시 사본에 실행 — 원본 DB 무접촉.
DB가 존재하면 skip하지 않는다 (존재 시 반드시 실행).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import numpy as np
import pytest

from dualdb import config, db
from dualdb.models import dtw_daily


def _check_path_invariants(path, n, m, end_j=None):
    """경계조건 + 단조성 + 허용 스텝 {(1,0),(0,1),(1,1)} — DTW 불변식."""
    assert path[0] == (0, 0)
    assert path[-1] == (n - 1, m - 1 if end_j is None else end_j)
    for (i0, j0), (i1, j1) in zip(path, path[1:]):
        assert (i1 - i0, j1 - j0) in {(1, 0), (0, 1), (1, 1)}


# ── 합성: DTW 코어 로직 ─────────────────────────────────

def test_self_dtw_diagonal_zero():
    """동일 시계열 self-DTW → 거리 0 · 대각 경로 · open-end 종점 = 끝."""
    x = np.log(100.0 * np.exp(np.linspace(0, 1.2, 60)) + 3 * np.sin(np.arange(60)))
    res = dtw_daily.dtw_align(x, x, open_end=True)
    assert res["raw"] == pytest.approx(0.0, abs=1e-12)
    assert res["end_j"] == len(x) - 1
    assert res["path"] == [(i, i) for i in range(len(x))]
    res_closed = dtw_daily.dtw_align(x, x, open_end=False)
    assert res_closed["closed_raw"] == pytest.approx(0.0, abs=1e-12)


def test_open_end_prefix_recovery():
    """질의 = 참조의 앞 60% (속도 상이) → open-end 종점이 60% 지점에 수렴."""
    def f(t):
        return 0.9 * t + 0.15 * np.sin(t * 1.7)

    y = f(np.linspace(0.0, 10.0, 200))       # 참조 (닷컴 역할, 전체 경로)
    x = f(np.linspace(0.0, 6.0, 90))         # 질의 (AI 역할, t=6까지만)
    res = dtw_daily.dtw_align(x, y, open_end=True)
    expected_j = round(6.0 / 10.0 * 199)      # t=6 ↔ index ≈ 119
    assert abs(res["end_j"] - expected_j) <= 8
    assert res["norm"] < 0.02
    _check_path_invariants(res["path"], len(x), len(y), res["end_j"])
    # closed-end는 참조 잔여 경로를 강제 매핑 → 거리가 open-end 이상
    assert res["closed_raw"] >= res["raw"]


def test_path_invariants_noisy_pair():
    """무관한 잡음 쌍에서도 경로 불변식·양의 거리 유지 (형상 검증)."""
    rng = np.random.default_rng(7)
    x = np.cumsum(rng.normal(0, 0.02, 80)) + 1.0
    y = np.cumsum(rng.normal(0, 0.02, 150)) + 1.0
    res = dtw_daily.dtw_align(x, y, open_end=False)
    _check_path_invariants(res["path"], len(x), len(y))
    assert res["raw"] > 0
    # 누적행렬 마지막 행은 단조 비감소가 아닐 수 있으나 전부 유한이어야 함
    D = dtw_daily.dtw_matrix(x, y)
    assert np.isfinite(D[1:, 1:]).all()


# ── 합성: DB 파이프라인 (run → alignment/model_run) ──────

def _insert_synthetic_era(conn, era_id, start, n_weeks, speed):
    """주중일만 생성 — 값은 100·exp(0.02·w·speed + 0.2·sin(w·speed/6))."""
    rows, k, d = [], 0, start
    while k < n_weeks * 5:
        if d.weekday() < 5:
            t = (k / 5.0) * speed
            val = 100.0 * float(np.exp(0.02 * t + 0.2 * np.sin(t / 6.0)))
            rows.append(("^IXIC", d.isoformat(), era_id, k, val))
            k += 1
        d += timedelta(days=1)
    conn.executemany(
        "INSERT INTO derived_daily (series, date, era_id, cycle_day, norm_m0)"
        " VALUES (?,?,?,?,?)", rows)
    conn.commit()


@pytest.fixture()
def syn_conn(tmp_path):
    conn = db.connect(tmp_path / "syn.sqlite")
    # 닷컴 420주(속도 1) vs AI 190주(속도 0.5) → AI 최신 ↔ 닷컴 95주 위상
    _insert_synthetic_era(conn, "dotcom", date(1996, 1, 1), 420, 1.0)
    _insert_synthetic_era(conn, "ai", date(2023, 1, 2), 190, 0.5)
    # 타 method 무접촉 검증용 시드 — run()은 method='dtw'만 재기록해야 한다
    conn.executemany(
        "INSERT INTO alignment (method, cycle_index, event_name, era_id, date)"
        " VALUES ('calendar_m', 0.0, '', ?, ?)",
        [("dotcom", "1996-01-31"), ("ai", "2023-01-31")])
    conn.commit()
    yield conn
    conn.close()


def test_run_synthetic_phase_and_records(syn_conn):
    out = dtw_daily.run(syn_conn)
    # 알려진 위상: AI 190주 × 0.5 = 닷컴 95주 ≈ 21.8개월 (±1.5 허용)
    expected_m = 95 * 7 / dtw_daily.DAYS_PER_MONTH
    assert out["phase"]["cycle_months_dtw"] == pytest.approx(expected_m, abs=1.5)
    assert out["phase_gap_months"] == pytest.approx(
        out["phase"]["cycle_months_dtw"] - out["calendar"]["cycle_months"],
        abs=0.11)  # 내부 일관성 (반올림 오차만)
    # alignment (long): AI 주당 (dotcom, ai) era 행 쌍, 닷컴 매핑 단조 비감소
    dc_rows = syn_conn.execute(
        "SELECT cycle_index, date FROM alignment"
        " WHERE method='dtw' AND era_id='dotcom' ORDER BY cycle_index").fetchall()
    ai_rows = syn_conn.execute(
        "SELECT cycle_index, date FROM alignment"
        " WHERE method='dtw' AND era_id='ai' ORDER BY cycle_index").fetchall()
    assert len(dc_rows) == len(ai_rows) == out["alignment_rows"] == out["weeks"]["ai"]
    dc_seq = [r["date"] for r in dc_rows]
    assert dc_seq == sorted(dc_seq)
    assert dc_rows[0]["cycle_index"] == 0.0
    # model_run 기록 + 재실행 멱등(alignment 중복 없음, model_run은 append 로그)
    assert syn_conn.execute(
        "SELECT COUNT(*) c FROM model_run WHERE model='dtw_daily'").fetchone()["c"] == 1
    out2 = dtw_daily.run(syn_conn)
    assert out2["alignment_rows"] == out["alignment_rows"]
    n_align = syn_conn.execute(
        "SELECT COUNT(*) c FROM alignment WHERE method='dtw'").fetchone()["c"]
    assert n_align == out["alignment_rows"] * 2      # era 행 쌍
    assert syn_conn.execute(
        "SELECT COUNT(*) c FROM model_run WHERE model='dtw_daily'").fetchone()["c"] == 2
    # event/calendar 등 타 method 행 무접촉 — fixture가 시드한 calendar_m 행 쌍이
    # run() 2회 후에도 그대로 남아야 한다 (DELETE는 method='dtw'만)
    cal = {r["era_id"]: r["date"] for r in syn_conn.execute(
        "SELECT era_id, date FROM alignment WHERE method='calendar_m'")}
    assert cal == {"dotcom": "1996-01-31", "ai": "2023-01-31"}


def test_run_insufficient_data_raises(tmp_path):
    conn = db.connect(tmp_path / "empty.sqlite")
    with pytest.raises(ValueError, match="주간 표본 부족"):
        dtw_daily.run(conn)
    conn.close()


# ── 실DB 스모크 (backup 사본 — 원본 무접촉, 존재 시 skip 아님) ──

@pytest.fixture()
def real_conn(tmp_path):
    if not config.DB_PATH.exists():
        pytest.skip("실DB 없음 — ingest/derive 후 실행")
    src = sqlite3.connect(config.DB_PATH)
    if not src.execute(
            "SELECT 1 FROM derived_daily WHERE series='^IXIC' LIMIT 1").fetchone():
        src.close()
        pytest.skip("derived_daily 비어 있음 — derive 후 실행")
    dst = sqlite3.connect(tmp_path / "real_copy.sqlite")
    src.backup(dst)
    src.close()
    dst.row_factory = sqlite3.Row
    yield dst
    dst.close()


def test_real_db_smoke(real_conn):
    out = dtw_daily.run(real_conn)
    assert out["weeks"]["dotcom"] > 300 and out["weeks"]["ai"] > 150
    # 위상은 닷컴 창 내부, 앵커(1996-01) 이후여야 함
    assert "1996-06-01" <= out["phase"]["dotcom_date"] <= "2003-12-31"
    assert out["phase"]["run_first"] <= out["phase"]["dotcom_date"]
    n = real_conn.execute(
        "SELECT COUNT(*) c FROM alignment WHERE method='dtw'").fetchone()["c"]
    assert n == out["alignment_rows"] * 2            # long format: era 행 쌍
    assert out["alignment_rows"] == out["weeks"]["ai"]
    assert real_conn.execute(
        "SELECT COUNT(*) c FROM model_run WHERE model='dtw_daily'").fetchone()["c"] >= 1
    # 위상차 sanity: 캘린더 대비 ±24개월 이내 (그 밖이면 데이터·로직 점검 신호)
    assert abs(out["phase_gap_months"]) <= 24
    md = dtw_daily.render_md(out)
    assert "닷컴 위상" in md and out["phase"]["dotcom_date"] in md
    assert "한계" in md  # 정직성 고지 없으면 출력 무효
