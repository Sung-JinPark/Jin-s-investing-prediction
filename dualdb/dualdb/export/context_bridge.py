"""dualdb → ai_fc ml_history 'context' 브리지 (정합도 배선 — Phase 1-D, 급소).

자동 예측 프롬프트 주입(ai_fc base_rates.ml_digest)이 읽는
data/ml_history/YYYY.jsonl 에 kind:"context" run 1건을 append 한다. 내용:
- analog: 다중 시대 k-NN 최근접 사이클·이후 3/6/12M 수익률 분포·유사 조정 깊이
- factor_tilt: 팩터 기울기 z (가치 HML·모멘텀 Mom·사이즈 SMB, 최근 12M vs 장기)
- regime: 금리커브(T10Y2Y)·HY 스프레드(pctile)·CAPE(빈티지) — 기존 FRED 사용

정직성 (헌법):
- **질문 매핑 확률 없음** (R-4·base_rates.py L3-6). 전방수익률은 시장 전체 base rate
  이지 질문별 확률이 아니며, F1/F3 지평과 겹치므로 준-앵커 주의 라벨을 단다.
- 학습·가중치 갱신 없음 — 결정론 집계·추론 전용 (원칙 5·8-6, ML 게이트 비저촉).
- append-only(파일이 진실). ml_history DB 파생은 sync --rebuild로 재구축.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np

from .. import config
from ..models import knn_analog

NOTE = "과거 유사 시대 base rate — 질문 매핑 확률 아님(R-4, 준-앵커 주의)"


def _analog(conn: sqlite3.Connection) -> dict | None:
    """다중 시대 k-NN 최근접 사이클 + 전방수익률 분포 + 유사 조정 깊이 중앙값."""
    try:
        r = knn_analog.run(conn, record=False)   # model_run 무오염
    except Exception:  # noqa: BLE001 — derive 전이면 아날로그 생략(fail-soft)
        return None
    nbs = r["neighbors"]
    if not nbs:
        return None
    m = r["median_fwd"]
    # 선택된 시대들의 조정 에피소드 깊이 중앙값 (base rate: "이 아날로그들의 조정 깊이")
    sel = r.get("selected_eras", [])
    depth_med = None
    if sel:
        ph = ",".join("?" * len(sel))
        depths = [row["depth"] for row in conn.execute(
            f"SELECT depth FROM correction_episode WHERE era_id IN ({ph}) AND depth IS NOT NULL",
            sel)]
        if depths:
            depth_med = round(float(np.median(depths)), 4)
    return {
        "closest_era": nbs[0]["era"],
        "distance": nbs[0]["distance"],
        "fwd_return_dist": {
            "m3": m["fwd_3m"]["median"], "m6": m["fwd_6m"]["median"],
            "m12": m["fwd_12m"]["median"],
            "n": m["fwd_12m"]["n"],
        },
        "correction_depth_median": depth_med,
        "n_eras": r["n_eras"],
        "pool_eras": r["pool_eras"],
        "selected_eras": sel,
        "asof": r["asof"],
    }


def _factor_z(conn: sqlite3.Connection, col: str, window: int = 12) -> float | None:
    """최근 window개월 팩터 평균의 z — 장기 롤링 window평균 분포 대비 (기울기 국면)."""
    vals = [r[col] for r in conn.execute(
        f"SELECT {col} FROM factor_monthly WHERE {col} IS NOT NULL ORDER BY date")]
    arr = np.array(vals, dtype=float)
    if len(arr) < window * 2:
        return None
    roll = np.convolve(arr, np.ones(window) / window, mode="valid")  # window월 이동평균
    sd = roll.std(ddof=1)
    if sd == 0:
        return None
    return round(float((roll[-1] - roll.mean()) / sd), 2)


def _factor_tilt(conn: sqlite3.Connection) -> dict:
    return {
        "value_z": _factor_z(conn, "hml"),
        "momentum_z": _factor_z(conn, "mom"),
        "size_z": _factor_z(conn, "smb"),
        "vintage": (conn.execute(
            "SELECT MAX(date) d FROM factor_monthly WHERE hml IS NOT NULL").fetchone()
            or {"d": None})["d"],
    }


def _latest_macro(conn: sqlite3.Connection, series_id: str) -> tuple[str, float] | None:
    row = conn.execute(
        "SELECT date, value FROM macro_daily WHERE series_id=? AND value IS NOT NULL"
        " ORDER BY date DESC LIMIT 1", (series_id,)).fetchone()
    return (row["date"], row["value"]) if row else None


def _pctile(conn: sqlite3.Connection, series_id: str, value: float) -> tuple[float, int]:
    vals = [r["value"] for r in conn.execute(
        "SELECT value FROM macro_daily WHERE series_id=? AND value IS NOT NULL", (series_id,))]
    arr = np.array(vals, dtype=float)
    return round(float((arr <= value).mean() * 100), 1), len(arr)


def _regime(conn: sqlite3.Connection) -> dict:
    out: dict = {}
    yc = _latest_macro(conn, "T10Y2Y")
    if yc:
        out["yield_curve_10y2y"] = round(yc[1], 2)
        out["yield_curve_inverted"] = yc[1] < 0
        out["yield_curve_date"] = yc[0]
    hy = _latest_macro(conn, "BAMLH0A0HYM2")
    if hy:
        pct, n = _pctile(conn, "BAMLH0A0HYM2", hy[1])
        out["hy_spread_pct"] = round(hy[1], 2)
        out["hy_spread_pctile"] = pct
        out["hy_spread_n"] = n            # 표본 크기(2023+ 한정) 병기 — 정직성
        out["hy_spread_date"] = hy[0]
    cape_row = conn.execute(
        "SELECT date, cape FROM valuation_monthly WHERE cape IS NOT NULL"
        " ORDER BY date DESC LIMIT 1").fetchone()
    if cape_row:
        capes = [r["cape"] for r in conn.execute(
            "SELECT cape FROM valuation_monthly WHERE cape IS NOT NULL")]
        arr = np.array(capes, dtype=float)
        out["cape_latest"] = round(cape_row["cape"], 1)
        out["cape_pctile"] = round(float((arr <= cape_row["cape"]).mean() * 100), 1)
        out["cape_vintage"] = cape_row["date"]   # 빈티지 명기 (구형일 수 있음)
    # recession_flag: USREC 미수집(Phase 2) — 금리커브 역전 프록시로 대체·명기
    out["recession_flag_proxy"] = out.get("yield_curve_inverted")
    return out


def build_payload(conn: sqlite3.Connection) -> dict:
    return {
        "run_ts": datetime.now().isoformat(timespec="seconds"),
        "kind": "context",
        "source": "dualdb",
        "analog": _analog(conn),
        "factor_tilt": _factor_tilt(conn),
        "regime": _regime(conn),
        "note": NOTE,
    }


def _append(payload: dict) -> Path:
    d = config.REPO_ROOT / "data" / "ml_history"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{payload['run_ts'][:4]}.jsonl"
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    # newline="" 로 LF 고정 — .gitattributes가 data/ml_history/** 를 -text(바이트 보존)로
    # 두므로 Windows 텍스트모드 CRLF는 기존 LF run들과 뒤섞여 EOL 드리프트를 낸다.
    with out.open("a", encoding="utf-8", newline="") as f:
        f.write(line)
    return out


def run(conn: sqlite3.Connection) -> tuple[Path, dict]:
    """payload 1회 산출 → append. (경로, payload) 반환 (콘솔 미리보기 겸용)."""
    payload = build_payload(conn)
    return _append(payload), payload


def export(conn: sqlite3.Connection) -> Path:
    """kind:'context' run을 ai_fc data/ml_history/YYYY.jsonl 에 append (append-only)."""
    return run(conn)[0]
