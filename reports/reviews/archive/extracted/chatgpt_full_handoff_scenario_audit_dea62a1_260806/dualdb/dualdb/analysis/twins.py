"""Q14 — 트윈 종목 대조: 닷컴 정점 전후 24개월 vs AI 최근 24개월.

두 시대를 모두 생존한 트윈 종목(entity.is_twin=1, era_id='dotcom')에 대해
(a) 닷컴 지수 정점(2000-03-10) 기준 -24개월~정점, (b) AI측 최신일 기준
-24개월~최신의 총수익률·최대낙폭(MDD)·연환산 변동성을 대조하고,
정점 후 사후(정점~+24개월 총수익률 = 붕괴 크기)와 자체 고점 대비
최대낙폭(dotcom_collapse 창 = 정점−24개월 ~ 2003-12-31, 그 창 내 자체 고점
기준)을 base rate로 산출한다.

종가는 adj_close 우선(배당 재투자 조정 — 배당 왜곡 방지), 없으면 close.
어느 쪽을 썼는지 트윈별로 출력(price_basis)에 명기한다.

한계 (정직 고지 — 출력에도 동일 문구 포함):
- **생존편향**: 이 표본은 두 시대 모두 생존한 승자 12종 — 닷컴 전체의 대표가 아님.
  당시 사망·초토화 종목(dotcom_casualty 25+)이 빠져 있어 붕괴 base rate의
  **낙관적 하한**으로만 읽을 것.
- 사이클 표본 n=1 대 n=1 — 분포 비교는 참조선이지 예측 보증이 아님.
- adj_close는 현재 기준 소급 조정치 — 당시 체감 가격 경로와 다를 수 있다.
- 산출물은 base rate 참조용 (P3 게이트 전 '참고 의견') — 매매 신호가 아니다.
"""

from __future__ import annotations

import calendar
import json
import sqlite3
from datetime import datetime

import numpy as np

from .. import config
from ..derive.daily import ERA_WINDOWS

WINDOW_MONTHS = 24
MODEL_NAME = "twins_q14"
SURVIVORSHIP_NOTE = ("이 표본은 두 시대 모두 생존한 승자 12종 — 닷컴 전체의 대표가 아님 "
                     "(사망 종목은 dotcom_casualty 테이블 참조, 붕괴 base rate의 낙관적 하한)")
LIMITATIONS = [
    SURVIVORSHIP_NOTE,
    "사이클 표본 n=1 대 n=1 — 분포 비교는 참조선이지 예측 보증이 아님",
    "adj_close는 현재 기준 소급 조정(배당 재투자 가정) — 당시 체감 가격과 상이 가능",
    "P3 게이트 전 참고 의견 — 매매 신호 아님",
]


def _add_months(d: str, months: int) -> str:
    """YYYY-MM-DD 문자열에 개월 가감 — 말일 초과는 해당 월 말일로 절사."""
    y, m, day = int(d[:4]), int(d[5:7]), int(d[8:10])
    total = y * 12 + (m - 1) + months
    y2, m2 = divmod(total, 12)
    day2 = min(day, calendar.monthrange(y2, m2 + 1)[1])
    return f"{y2:04d}-{m2 + 1:02d}-{day2:02d}"


def _price_basis(conn: sqlite3.Connection, series: str) -> str:
    """adj_close 전량 존재 → 'adj_close', 전량 결측 → 'close', 혼재 → coalesce."""
    r = conn.execute(
        "SELECT COUNT(*) n, SUM(adj_close IS NULL) nn FROM price_daily WHERE series=?",
        (series,)).fetchone()
    if not r["n"]:
        return "none"
    if not r["nn"]:
        return "adj_close"
    if r["nn"] == r["n"]:
        return "close"
    return "coalesce(adj_close,close)"


def _prices(conn: sqlite3.Connection, series: str, d0: str, d1: str,
            basis: str) -> np.ndarray:
    col = basis if basis in ("adj_close", "close") else "COALESCE(adj_close, close)"
    rows = conn.execute(
        f"SELECT {col} px FROM price_daily WHERE series=? AND date BETWEEN ? AND ?"
        f" AND {col} IS NOT NULL ORDER BY date", (series, d0, d1)).fetchall()
    return np.array([r["px"] for r in rows], dtype=float)


def _metrics(px: np.ndarray) -> dict | None:
    """총수익률·최대낙폭·연환산 vol (√252, 로그수익 ddof=1). 표본 2 미만이면 None."""
    if len(px) < 2:
        return None
    mdd = float((px / np.maximum.accumulate(px) - 1.0).min())
    rets = np.diff(np.log(px))
    vol = float(np.std(rets, ddof=1) * np.sqrt(252)) if len(rets) >= 2 else None
    return {"tot_ret": round(float(px[-1] / px[0] - 1.0), 4),
            "mdd": round(mdd, 4),
            "ann_vol": round(vol, 4) if vol is not None else None}


def _median(vals: list[float]) -> float | None:
    return round(float(np.median(vals)), 4) if vals else None


def run(conn: sqlite3.Connection, record: bool = True) -> dict:
    """트윈별 두 창 비교 + 요약 산출. record=True면 model_run에 1행 기록."""
    peak = config.ANCHORS["dotcom"]["peak_date"]          # 2000-03-10
    dc_end = ERA_WINDOWS["dotcom"][1]                      # 2003-12-31
    twins = [(r["ticker"], r["data_ticker"] or r["ticker"], r["role_code"])
             for r in conn.execute(
                 "SELECT ticker, data_ticker, role_code FROM entity"
                 " WHERE is_twin=1 AND era_id='dotcom' ORDER BY ticker")]
    if not twins:
        raise ValueError("entity에 is_twin=1 (era_id='dotcom') 종목이 없음 — seed 적재 필요")
    placeholders = ",".join("?" * len(twins))
    asof = conn.execute(
        f"SELECT MAX(date) d FROM price_daily WHERE series IN ({placeholders})",
        [t[1] for t in twins]).fetchone()["d"]
    if asof is None:
        raise ValueError("트윈 종목의 price_daily 데이터 없음 — ingest 필요")

    windows = {
        "dotcom_pre": (_add_months(peak, -WINDOW_MONTHS), peak),
        "dotcom_post": (peak, _add_months(peak, WINDOW_MONTHS)),
        "dotcom_collapse": (_add_months(peak, -WINDOW_MONTHS), dc_end),
        "ai": (_add_months(asof, -WINDOW_MONTHS), asof),
    }

    rows = []
    for ticker, data_ticker, role in twins:
        basis = _price_basis(conn, data_ticker)
        pre = _metrics(_prices(conn, data_ticker, *windows["dotcom_pre"], basis))
        post_px = _prices(conn, data_ticker, *windows["dotcom_post"], basis)
        post_ret = (round(float(post_px[-1] / post_px[0] - 1.0), 4)
                    if len(post_px) >= 2 else None)
        collapse = _metrics(_prices(conn, data_ticker, *windows["dotcom_collapse"], basis))
        ai = _metrics(_prices(conn, data_ticker, *windows["ai"], basis))
        rows.append({"ticker": ticker, "role": role, "price_basis": basis,
                     "dotcom_pre": pre, "dotcom_post24m_ret": post_ret,
                     "dotcom_collapse_dd": collapse["mdd"] if collapse else None,
                     "ai": ai})

    mu = next((r for r in rows if r["ticker"] == "MU"), None)
    summary = {
        "median_dotcom_pre24m_ret": _median(
            [r["dotcom_pre"]["tot_ret"] for r in rows if r["dotcom_pre"]]),
        "median_ai_recent24m_ret": _median(
            [r["ai"]["tot_ret"] for r in rows if r["ai"]]),
        "median_dotcom_post24m_ret": _median(
            [r["dotcom_post24m_ret"] for r in rows if r["dotcom_post24m_ret"] is not None]),
        "median_dotcom_collapse_dd": _median(
            [r["dotcom_collapse_dd"] for r in rows if r["dotcom_collapse_dd"] is not None]),
        "mu_highlight": ({"dotcom_post24m_ret": mu["dotcom_post24m_ret"],
                          "dotcom_collapse_dd": mu["dotcom_collapse_dd"],
                          "ai_recent24m_ret": mu["ai"]["tot_ret"] if mu["ai"] else None}
                         if mu else None),
    }

    result = {"question": "Q14_twins", "asof": asof,
              "window_months": WINDOW_MONTHS,
              "windows": {k: list(v) for k, v in windows.items()},
              "twins": rows, "summary": summary,
              "survivorship_note": SURVIVORSHIP_NOTE,
              "limitations": LIMITATIONS}
    if record:
        cur = conn.execute(
            "INSERT INTO model_run(model, asof, params_json, output_json, created_at)"
            " VALUES (?,?,?,?,?)",
            (MODEL_NAME, asof,
             json.dumps({"window_months": WINDOW_MONTHS, "peak_date": peak,
                         "dotcom_collapse_end": dc_end,
                         "price_basis_policy": "adj_close 우선, 없으면 close"},
                        ensure_ascii=False),
             json.dumps(result, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        result["run_id"] = cur.lastrowid
    return result


def _pct(v: float | None) -> str:
    return f"{v:+.1%}" if v is not None else "—"


def render_md(res: dict) -> str:
    """run() 결과 dict → 마크다운 (표 + 요약 + 생존편향·한계 고지)."""
    w = res["windows"]
    s = res["summary"]
    lines = [
        f"## Q14 트윈 종목 대조 — 닷컴 정점 전후 vs AI 최근 {res['window_months']}개월 "
        f"(asof {res['asof']})",
        f"> **생존편향 경고: {res['survivorship_note']}**",
        "",
        f"닷컴 창: {w['dotcom_pre'][0]} ~ 정점({w['dotcom_pre'][1]}) ~ {w['dotcom_post'][1]} · "
        f"AI 창: {w['ai'][0]} ~ {w['ai'][1]} · 자체고점 낙폭은 ~{w['dotcom_collapse'][1]}",
        "",
        "| 티커 | 역할 | 기준가 | 닷컴 -24M 수익 | MDD | 연vol "
        "| 정점후 +24M 수익 | 자체고점 최대낙폭 | AI -24M 수익 | MDD | 연vol |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in res["twins"]:
        pre, ai = t["dotcom_pre"], t["ai"]
        lines.append(
            f"| {t['ticker']} | {t['role']} | {t['price_basis']} "
            f"| {_pct(pre['tot_ret']) if pre else '—'} "
            f"| {_pct(pre['mdd']) if pre else '—'} "
            f"| {_pct(pre['ann_vol']) if pre and pre['ann_vol'] is not None else '—'} "
            f"| {_pct(t['dotcom_post24m_ret'])} "
            f"| {_pct(t['dotcom_collapse_dd'])} "
            f"| {_pct(ai['tot_ret']) if ai else '—'} "
            f"| {_pct(ai['mdd']) if ai else '—'} "
            f"| {_pct(ai['ann_vol']) if ai and ai['ann_vol'] is not None else '—'} |")
    lines += [
        "",
        "### 요약 (중앙값 비교)",
        f"- 닷컴 정점 전 24개월 수익 중앙값 **{_pct(s['median_dotcom_pre24m_ret'])}** vs "
        f"AI 최근 24개월 중앙값 **{_pct(s['median_ai_recent24m_ret'])}**",
        f"- 닷컴 정점 후 24개월 수익 중앙값 **{_pct(s['median_dotcom_post24m_ret'])}** · "
        f"자체고점 최대낙폭 중앙값 **{_pct(s['median_dotcom_collapse_dd'])}** "
        "(붕괴 크기 base rate — 생존자 하한)",
    ]
    if s["mu_highlight"]:
        mu = s["mu_highlight"]
        lines.append(
            f"- **MU 별도 강조**: 닷컴 정점 후 +24M {_pct(mu['dotcom_post24m_ret'])}, "
            f"자체고점 최대낙폭 **{_pct(mu['dotcom_collapse_dd'])}** — 메모리 사이클 질문군의 "
            f"최우선 base rate (AI 최근 24M {_pct(mu['ai_recent24m_ret'])})")
    lines += ["", "### 한계 (정직 고지)"]
    lines += [f"- {lim}" for lim in res["limitations"]]
    lines += ["- Tier-1 (Yahoo 일간, adj_close 우선)"]
    return "\n".join(lines) + "\n"
