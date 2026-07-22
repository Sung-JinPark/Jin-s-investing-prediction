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
    # recession_flag: NBER USREC 실측 (Phase 2). 미수집이면 금리커브 역전 프록시로 폴백.
    rec = conn.execute(
        "SELECT date, value FROM macro_monthly WHERE series_id='USREC'"
        " ORDER BY date DESC LIMIT 1").fetchone()
    if rec:
        out["recession_flag"] = bool(rec["value"])
        out["recession_date"] = rec["date"]
    else:
        out["recession_flag_proxy"] = out.get("yield_curve_inverted")
    return out


def _breadth(conn: sqlite3.Connection) -> dict | None:
    """시장 폭 프록시 — 추적 종목(config yahoo_daily) 중 200DMA 상회 비율.

    한계(정직성): 시총가중 HHI·Mag7 비중은 주식수 이력 부재로 산출 불가 —
    등가중 추적 유니버스(~24종, AAPL·TSLA 미포함)의 가격 폭 프록시일 뿐이다.
    """
    tickers = list(config.YAHOO_DAILY)
    ph = ",".join("?" * len(tickers))
    rows = conn.execute(
        f"""SELECT d.series, d.date, d.dist_200dma FROM derived_daily d
            JOIN (SELECT series, MAX(date) md FROM derived_daily
                  WHERE era_id='ai' AND series IN ({ph}) GROUP BY series) t
              ON d.series=t.series AND d.date=t.md
            WHERE d.era_id='ai' AND d.dist_200dma IS NOT NULL""", tickers).fetchall()
    if not rows:
        return None
    above = sum(1 for r in rows if r["dist_200dma"] > 0)
    return {
        "pct_above_200dma": round(above / len(rows) * 100, 1),
        "n": len(rows),
        "asof": max(r["date"] for r in rows),
        "note": "등가중 추적 유니버스 프록시 — 시총가중 HHI 아님(주식수 이력 부재)",
    }


def _concentration(conn: sqlite3.Connection) -> dict | None:
    """대형주 집중 프록시 — ^NDX(나스닥100)/^IXIC(컴포지트) 가격 비율.

    한계(정직성): 시총 비중·HHI가 아니라 지수 가격 비율의 상대 추세다. 두 지수의
    기준점 차이로 절대 수준은 무의미 — 백분위(1995+)·1년 변화만 의미를 갖는다.
    """
    rows = conn.execute(
        """SELECT a.date d, a.close / b.close r FROM price_daily a
           JOIN price_daily b ON b.date = a.date AND b.series = '^IXIC'
           WHERE a.series = '^NDX' AND a.date >= '1995-01-01' ORDER BY a.date""").fetchall()
    if len(rows) < 300:
        return None
    ratios = np.array([r["r"] for r in rows], dtype=float)
    latest = ratios[-1]
    yr_ago = ratios[-253] if len(ratios) > 253 else ratios[0]
    return {
        "ratio_pctile": round(float((ratios <= latest).mean() * 100), 1),
        "chg_1y_pct": round(float(latest / yr_ago - 1) * 100, 1),
        "asof": rows[-1]["d"],
        "note": "NDX/IXIC 가격 비율 프록시 — 시총가중 HHI 아님",
    }


def _overlay(conn: sqlite3.Connection) -> dict:
    """시대별 월말 norm_m0 배열 (M+0=100) — 대시보드 다중 시대 오버레이용.

    일간 tier는 derived_daily 월말 norm_m0, 월간 tier(dow1929)는 macro_monthly를
    앵커월=100으로 정규화. 값은 소수 1자리 (payload 크기 절제).
    """
    from ..derive.daily import ERA_MONTHLY, ERA_WINDOWS, ERA_INDEX
    out: dict[str, list] = {}
    for era_id in ERA_WINDOWS:
        series = ERA_INDEX[era_id]
        anchor = config.ANCHORS[era_id]["anchor_month"]
        rows = conn.execute(
            """SELECT substr(d.date,1,7) m, d.norm_m0 v FROM derived_daily d
               JOIN (SELECT MAX(date) md FROM derived_daily
                     WHERE series=? AND era_id=? GROUP BY substr(date,1,7)) t
                 ON d.date = t.md
               WHERE d.series=? AND d.era_id=? AND d.norm_m0 IS NOT NULL
               ORDER BY d.date""", (series, era_id, series, era_id)).fetchall()
        a = int(anchor[:4]) * 12 + int(anchor[5:7])
        vals = [(int(r["m"][:4]) * 12 + int(r["m"][5:7]) - a, r["v"]) for r in rows]
        vals = [(k, v) for k, v in vals if k >= 0]
        if vals:
            out[era_id] = [round(v, 1) for _, v in vals]
    for era_id, (sid, (w0, w1)) in ERA_MONTHLY.items():
        anchor = config.ANCHORS[era_id]["anchor_month"]
        base = conn.execute(
            "SELECT value FROM macro_monthly WHERE series_id=? AND substr(date,1,7)=?",
            (sid, anchor)).fetchone()
        if not base:
            continue
        rows = conn.execute(
            """SELECT value v FROM macro_monthly WHERE series_id=?
               AND substr(date,1,7) >= ? AND date <= ? ORDER BY date""",
            (sid, anchor, w1)).fetchall()
        out[era_id] = [round(r["v"] / base["value"] * 100, 1) for r in rows]
    return out


def _deep_history(conn: sqlite3.Connection) -> list[dict]:
    """월간 tier 시대(dow1929 등)의 최심 조정 — 심층 역사 base rate."""
    from ..derive.daily import ERA_MONTHLY
    out = []
    for era_id in ERA_MONTHLY:
        row = conn.execute(
            """SELECT peak_date, trough_date, depth FROM correction_episode
               WHERE era_id=? ORDER BY depth ASC LIMIT 1""", (era_id,)).fetchone()
        if row:
            out.append({"era": era_id, "peak": row["peak_date"],
                        "trough": row["trough_date"], "depth": row["depth"],
                        "note": "월평균 지수 기준 — 일중 극값 대비 완만"})
    return out


def build_payload(conn: sqlite3.Connection) -> dict:
    return {
        "run_ts": datetime.now().isoformat(timespec="seconds"),
        "kind": "context",
        "source": "dualdb",
        "analog": _analog(conn),
        "factor_tilt": _factor_tilt(conn),
        "regime": _regime(conn),
        "breadth": _breadth(conn),
        "concentration": _concentration(conn),
        "overlay": _overlay(conn),           # 대시보드 오버레이용 — 프롬프트 미주입
        "deep_history": _deep_history(conn),
        # Perez 국면은 config 정본(anchors.perez) — 추정 라벨 포함 문자열 그대로
        "perez_ai": config.ANCHORS.get("ai", {}).get("perez"),
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
