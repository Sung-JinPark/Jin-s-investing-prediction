"""resolver._ml_ref_before 신선도 상한 — forecast_ts − run_ts ≤ ML_REF_MAX_AGE_DAYS (합성 sqlite).

룩어헤드 차단(run_ts ≤ forecast_ts)은 test_ws2_benchmark 가 본다. 여기서는 반대쪽 경계:
수개월 전 run 과 짝짓지 않는다 — 부재는 NULL (소급 조회 금지).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ai_fc import config
from ai_fc.db import ingest
from ai_fc.resolver import _ml_ref_before

QID = "fixture-ml-fresh"
FORECAST_TS = "2099-06-10T09:00:00"


def _conn(tmp_path: Path):
    return ingest.connect(tmp_path / "db" / "index.db")


def _insert(conn, run_ts: str, prob: float) -> None:
    conn.execute(
        "INSERT INTO ml_forecasts (run_ts, question_id, model, kind, prob) VALUES (?,?,?,?,?)",
        (run_ts, QID, "ensemble", "terminal", prob))
    conn.commit()


def _ts(days_before_forecast: float) -> str:
    return (datetime.fromisoformat(FORECAST_TS)
            - timedelta(days=days_before_forecast)).isoformat(timespec="seconds")


def test_within_max_age_is_used(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _insert(conn, _ts(3), 0.42)                      # 3일 전 — 상한(7일) 이내
    ref = _ml_ref_before(conn, QID, FORECAST_TS)
    assert ref is not None
    assert ref[0] == 0.42 and ref[1] == _ts(3)


def test_older_than_max_age_is_null(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _insert(conn, _ts(config.ML_REF_MAX_AGE_DAYS + 30), 0.9)   # 수개월 전 run 만 존재
    assert _ml_ref_before(conn, QID, FORECAST_TS) is None       # 소급 조회 금지 — NULL


def test_fresh_beats_stale_and_boundary_is_inclusive(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _insert(conn, _ts(config.ML_REF_MAX_AGE_DAYS + 1), 0.9)    # 상한 바깥 — 후보 아님
    _insert(conn, _ts(config.ML_REF_MAX_AGE_DAYS), 0.33)       # 정확히 상한 — 포함(≤)
    ref = _ml_ref_before(conn, QID, FORECAST_TS)
    assert ref is not None and ref[0] == 0.33

    _insert(conn, _ts(1), 0.55)                                 # 더 최신이 있으면 그것
    ref = _ml_ref_before(conn, QID, FORECAST_TS)
    assert ref is not None and ref[0] == 0.55


def test_unparseable_forecast_ts_is_null(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _insert(conn, _ts(1), 0.5)
    assert _ml_ref_before(conn, QID, "not-a-timestamp") is None
    assert _ml_ref_before(conn, QID, "") is None
