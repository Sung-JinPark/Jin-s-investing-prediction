"""파생 계층 — derived_daily 지표, 조정 에피소드(월말 기준), 이중시계 정렬, v4.1 재현.

전량 재계산 가능 (원천 무접촉). 조정 에피소드는 v4.1·센티널과 동일하게
**월말 종가 기준 -5%+** 로 탐지한다 (일간 기준은 노이즈로 횟수가 부풀어 비교 불능).
"""

from __future__ import annotations

import sqlite3
from datetime import date

import numpy as np

from .. import config

# era 계산 창·아날로그 지수는 config.yaml anchors에서 (하드코딩 제거 — 다중 시대 일반화)
ERA_WINDOWS = {  # era_id: (창 시작, 끝 — 끝 None = 오늘)
    e: (m["window"][0], m["window"][1])
    for e, m in config.ANCHORS.items() if m.get("window")
}
ERA_INDEX = {e: m.get("index", "^IXIC") for e, m in config.ANCHORS.items()}


def _series_closes(conn: sqlite3.Connection, series: str) -> tuple[list[str], np.ndarray]:
    rows = conn.execute(
        "SELECT date, close FROM price_daily WHERE series=? ORDER BY date", (series,)).fetchall()
    return [r["date"] for r in rows], np.array([r["close"] for r in rows], dtype=float)


def _rsi14(closes: np.ndarray) -> np.ndarray:
    delta = np.diff(closes, prepend=closes[0])
    up = np.clip(delta, 0, None)
    dn = np.clip(-delta, 0, None)
    out = np.full(len(closes), np.nan)
    if len(closes) < 15:
        return out
    au, ad = up[1:15].mean(), dn[1:15].mean()
    for i in range(15, len(closes)):
        au = (au * 13 + up[i]) / 14
        ad = (ad * 13 + dn[i]) / 14
        out[i] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def _anchor_first_trading(dates: list[str], anchor_month: str) -> int | None:
    for i, d in enumerate(dates):
        if d[:7] == anchor_month:
            return i
    return None


def build_derived_daily(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM derived_daily")
    n = 0
    series_list = [r["series"] for r in conn.execute(
        "SELECT DISTINCT series FROM price_daily")]
    for series in series_list:
        dates, closes = _series_closes(conn, series)
        if len(closes) < 30:
            continue
        rets = np.diff(np.log(closes), prepend=np.nan)
        rsi = _rsi14(closes)
        # 200일 이평·변동성은 누적 계산
        rows = []
        for era_id, (w0, w1) in ERA_WINDOWS.items():
            anchor = config.ANCHORS[era_id]["anchor_month"]
            a_idx = _anchor_first_trading(dates, anchor)
            if a_idx is None:
                continue
            m0 = closes[a_idx]
            ath = 0.0
            trading_count = 0
            for i, d in enumerate(dates):
                if d < w0 or (w1 and d > w1):
                    continue
                ath = max(ath, closes[i]) if trading_count else closes[i]
                trading_count += 1
                vol20 = (float(np.nanstd(rets[max(0, i - 19):i + 1], ddof=1)) * np.sqrt(252)
                         if i >= 20 else None)
                vol60 = (float(np.nanstd(rets[max(0, i - 59):i + 1], ddof=1)) * np.sqrt(252)
                         if i >= 60 else None)
                dma200 = float(closes[max(0, i - 199):i + 1].mean()) if i >= 199 else None
                rows.append((
                    series, d, era_id, i - a_idx,
                    float(rets[i]) if np.isfinite(rets[i]) else None,
                    vol20, vol60, ath,
                    float(closes[i] / ath - 1) if ath else None,
                    float(closes[i] / dma200 - 1) if dma200 else None,
                    float(rsi[i]) if np.isfinite(rsi[i]) else None,
                    float(closes[i] / m0 * 100)))
        conn.executemany(
            """INSERT OR REPLACE INTO derived_daily
               (series,date,era_id,cycle_day,ret_1d,vol_20d,vol_60d,ath_to_date,
                drawdown,dist_200dma,rsi_14,norm_m0) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows)
        n += len(rows)
    conn.commit()
    return n


def _month_ends(conn: sqlite3.Connection, series: str, d0: str, d1: str
                ) -> list[tuple[str, float]]:
    return [(r["m"], r["c"]) for r in conn.execute(
        """SELECT substr(date,1,7) m, close c, MAX(date) FROM price_daily
           WHERE series=? AND date BETWEEN ? AND ? GROUP BY substr(date,1,7)
           ORDER BY m""", (series, d0, d1))]


def build_correction_episodes(conn: sqlite3.Connection,
                              threshold: float = -0.05) -> int:
    """월말 종가 기준 고점→저점 -5%+ 에피소드 (v4.1·센티널 정의와 동일).

    각 era는 자신의 아날로그 지수(ERA_INDEX)로 계산 — 다중 시대 일반화.
    """
    conn.execute("DELETE FROM correction_episode")  # 전량 재구축
    n = 0
    for era_id, (w0, w1) in ERA_WINDOWS.items():
        series = ERA_INDEX[era_id]
        me = _month_ends(conn, series, w0, w1 or date.today().isoformat())
        if not me:
            continue
        anchor = config.ANCHORS[era_id]["anchor_month"]
        peak_m, peak_v = me[0][0], me[0][1]
        trough_m, trough_v = peak_m, peak_v
        in_dd = False
        for m, v in me[1:]:
            if v > peak_v and not in_dd:
                peak_m, peak_v = m, v
                trough_m, trough_v = m, v
            elif v < trough_v:
                trough_m, trough_v = m, v
                if trough_v / peak_v - 1 <= threshold:
                    in_dd = True
            if in_dd and v > peak_v:  # 회복 완료 → 에피소드 확정
                _insert_episode(conn, series, era_id, anchor,
                                peak_m, peak_v, trough_m, trough_v, m)
                n += 1
                in_dd = False
                peak_m, peak_v = m, v
                trough_m, trough_v = m, v
        if in_dd:  # 미회복 진행형 에피소드
            _insert_episode(conn, series, era_id, anchor,
                            peak_m, peak_v, trough_m, trough_v, None)
            n += 1
    conn.commit()
    return n


def _insert_episode(conn, series, era_id, anchor, peak_m, peak_v,
                    trough_m, trough_v, recover_m) -> None:
    y0, mo0 = int(anchor[:4]), int(anchor[5:7])
    yp, mp = int(peak_m[:4]), int(peak_m[5:7])
    cyc = (yp - y0) * 12 + (mp - mo0)
    dur = ((int(trough_m[:4]) - yp) * 12 + int(trough_m[5:7]) - mp) * 30
    rec = (((int(recover_m[:4]) - int(trough_m[:4])) * 12
            + int(recover_m[5:7]) - int(trough_m[5:7])) * 30) if recover_m else None
    conn.execute(
        """INSERT OR REPLACE INTO correction_episode
           (series, era_id, peak_date, trough_date, recover_date, depth,
            dur_days, recover_days, cycle_month_at_peak) VALUES (?,?,?,?,?,?,?,?,?)""",
        (series, era_id, peak_m, trough_m, recover_m,
         round(trough_v / peak_v - 1, 4), dur, rec, float(cyc)))


def monthly_overlay(conn: sqlite3.Connection, n_months: int = 43
                    ) -> tuple[list[float], list[float], float]:
    """M+0..M+(n-1) 월말 정규화 배열 (dotcom, ai) + Pearson — v4.1 재현 게이트."""
    out = {}
    for era_id in ("dotcom", "ai"):
        anchor = config.ANCHORS[era_id]["anchor_month"]
        w0, w1 = ERA_WINDOWS[era_id]
        me = dict(_month_ends(conn, "^IXIC", w0, w1 or date.today().isoformat()))
        y0, m0 = int(anchor[:4]), int(anchor[5:7])
        vals = []
        for k in range(n_months):
            total = y0 * 12 + (m0 - 1) + k
            ym = f"{total // 12:04d}-{total % 12 + 1:02d}"
            if ym not in me:
                break
            vals.append(me[ym])
        base = vals[0]
        out[era_id] = [v / base * 100 for v in vals]
    n = min(len(out["dotcom"]), len(out["ai"]))
    a = np.array(out["dotcom"][:n])
    b = np.array(out["ai"][:n])
    pearson = float(np.corrcoef(a, b)[0, 1])
    return out["dotcom"][:n], out["ai"][:n], pearson


def fill_event_alignment(conn: sqlite3.Connection) -> None:
    """AI측 crisis_bottom을 데이터에서 확정 (2025-03~06 최저 종가일) — 추정 아닌 실측."""
    row = conn.execute(
        """SELECT date FROM price_daily WHERE series='^IXIC'
           AND date BETWEEN '2025-03-01' AND '2025-06-30' ORDER BY close LIMIT 1""").fetchone()
    if row:
        conn.execute(
            "UPDATE alignment SET ai_date=? WHERE method='event' AND event_name='crisis_bottom'",
            (row["date"],))
        conn.commit()


def run(conn: sqlite3.Connection) -> dict:
    n_daily = build_derived_daily(conn)
    n_ep = build_correction_episodes(conn)
    fill_event_alignment(conn)
    dc, ai, pearson = monthly_overlay(conn)
    n_dc_ep = conn.execute(
        """SELECT COUNT(*) c FROM correction_episode WHERE series='^IXIC'
           AND era_id='dotcom' AND peak_date <= '2000-03'""").fetchone()["c"]
    return {"derived_daily": n_daily, "episodes": n_ep,
            "overlay_months": len(dc), "pearson_m0_42": round(pearson, 4),
            "dotcom_episodes_pre_peak": n_dc_ep,
            "current_ratio_pct": round(ai[-1] / dc[len(ai) - 1] * 100, 1)}
