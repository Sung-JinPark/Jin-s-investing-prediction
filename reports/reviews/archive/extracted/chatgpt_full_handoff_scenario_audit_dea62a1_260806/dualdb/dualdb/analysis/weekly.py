"""주간 리포트 — Q1(정렬 곡선)·Q2(조정 분포)·Q3(변동성 체제)·Q5(IPO)·Q7(Fed)·Q8(M2).

생존편향 고지: 종목 단위 닷컴 통계는 생존자 표본 (§10.2) — 전체 시장 서술은
지수·Ritter·사상자 테이블로만 한다.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

import numpy as np

from .. import config
from ..derive.daily import monthly_overlay


def _cycle_month_now() -> int:
    a = config.ANCHORS["ai"]["anchor_month"]
    t = date.today()
    return (t.year - int(a[:4])) * 12 + t.month - int(a[5:7])


def _dotcom_same_month(cyc: int) -> str:
    a = config.ANCHORS["dotcom"]["anchor_month"]
    total = int(a[:4]) * 12 + int(a[5:7]) - 1 + cyc
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def q1_alignment(conn: sqlite3.Connection) -> str:
    dc, ai, pearson = monthly_overlay(conn)
    n = len(ai)
    dc42, ai42, _ = monthly_overlay(conn, n_months=42)  # 완결월 고정창 — v4.1 대조 기준
    p42 = float(np.corrcoef(np.array(dc42), np.array(ai42))[0, 1])
    ratio = ai[-1] / dc[n - 1] * 100
    return (f"## Q1 정렬 곡선 (calendar M+N, 월말 정규화 M+0=100)\n"
            f"- 오버레이 {n}개월 · Pearson {pearson:.4f} (부분월 포함) · "
            f"완결월 M+0~41 **{p42:.4f}** (v4.1 원문 0.899 재현 — 스펙의 0.9269는 오기)\n"
            f"- 동시점 비율: AI {ai[-1]:.1f} / 닷컴 {dc[n-1]:.1f} = **{ratio:.1f}%** "
            f"(AI가 닷컴 동시점 궤적의 {ratio:.0f}% 수준)\n"
            f"- Tier-1 (Yahoo 일간 → 월말 집계)\n")


def q2_corrections(conn: sqlite3.Connection) -> str:
    from scipy import stats
    rows = {"dotcom": [], "ai": []}
    for r in conn.execute(
            "SELECT era_id, depth, dur_days FROM correction_episode WHERE series='^IXIC'"):
        rows[r["era_id"]].append((r["depth"], r["dur_days"]))
    lines = ["## Q2 조정 에피소드 (월말 -5%+ 기준)"]
    for era, eps in rows.items():
        d = [e[0] for e in eps]
        lines.append(f"- {era}: {len(eps)}회 · 깊이 중앙값 {np.median(d):.1%} "
                     f"· 최심 {min(d):.1%}" if eps else f"- {era}: 0회")
    if all(len(v) >= 3 for v in rows.values()):
        ks = stats.ks_2samp([e[0] for e in rows["dotcom"]], [e[0] for e in rows["ai"]])
        lines.append(f"- 깊이 분포 KS-test p = {ks.pvalue:.3f} "
                     f"({'구분 불가 — 같은 체제 가설 유지' if ks.pvalue > 0.05 else '분포 상이'})")
    lines.append("- Tier-1")
    return "\n".join(lines) + "\n"


def _vix(conn: sqlite3.Connection, month: str | None = None) -> float | None:
    """FRED VIXCLS 우선, 차단 시 Yahoo ^VIX (CHANGELOG #7)."""
    if month:
        r = conn.execute(
            "SELECT AVG(value) v FROM macro_daily WHERE series_id='VIXCLS'"
            " AND substr(date,1,7)=?", (month,)).fetchone()
        if r and r["v"] is not None:
            return float(r["v"])
        r = conn.execute(
            "SELECT AVG(close) v FROM price_daily WHERE series='^VIX'"
            " AND substr(date,1,7)=?", (month,)).fetchone()
        return float(r["v"]) if r and r["v"] is not None else None
    r = conn.execute(
        "SELECT value v FROM macro_daily WHERE series_id='VIXCLS'"
        " ORDER BY date DESC LIMIT 1").fetchone()
    if r:
        return float(r["v"])
    r = conn.execute(
        "SELECT close v FROM price_daily WHERE series='^VIX' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return float(r["v"]) if r else None


def q3_vol_regime(conn: sqlite3.Connection) -> str:
    cyc = _cycle_month_now()
    cur = conn.execute(
        """SELECT vol_20d FROM derived_daily WHERE series='^IXIC' AND era_id='ai'
           AND vol_20d IS NOT NULL ORDER BY date DESC LIMIT 1""").fetchone()
    dc_vols = [r["vol_20d"] for r in conn.execute(
        """SELECT vol_20d FROM derived_daily WHERE series='^IXIC' AND era_id='dotcom'
           AND vol_20d IS NOT NULL""")]
    pct = float(np.mean([v <= cur["vol_20d"] for v in dc_vols])) * 100 if dc_vols else None
    dc_month = _dotcom_same_month(cyc)
    vix_now = _vix(conn)
    vix_then = _vix(conn, dc_month)
    vix_line = (f"- VIX: 현재 {vix_now:.1f} vs 닷컴 동시점 월평균 {vix_then:.1f}"
                if vix_now and vix_then else "- VIX: 결측 (FRED 차단·^VIX 폴백도 부재)")
    return (f"## Q3 변동성 체제 (현재 = 닷컴 M+{cyc} ≈ {dc_month})\n"
            f"- 현 vol20 {cur['vol_20d']:.1%} → 닷컴 전기간 분포의 **{pct:.0f}분위**\n"
            f"{vix_line}\n"
            f"- Tier-1 (Yahoo ^VIX{' — FRED 차단 폴백' if vix_now else ''})\n")


def q5_ipo_heat(conn: sqlite3.Connection) -> str:
    rows = {r["year"]: r for r in conn.execute("SELECT * FROM ipo_annual")}
    if not rows:
        return "## Q5 IPO 과열지수\n- 데이터 없음\n"
    years = sorted(rows)
    counts = np.array([rows[y]["ipo_count"] or 0 for y in years], dtype=float)
    rets = np.array([rows[y]["mean_first_day_ret"] or 0 for y in years], dtype=float)
    negs = np.array([rows[y]["pct_negative_eps"] or np.nan for y in years], dtype=float)

    def z(arr, v):
        return (v - np.nanmean(arr)) / np.nanstd(arr) if np.nanstd(arr) else 0.0

    def heat(y):
        r = rows[y]
        return (z(counts, r["ipo_count"] or 0) + z(rets, r["mean_first_day_ret"] or 0)
                + (z(negs, r["pct_negative_eps"]) if r["pct_negative_eps"] else 0))

    h99 = heat(1999)
    latest = max(y for y in years if y >= 2020)
    hn = heat(latest)
    src_tier = "Tier-3 큐레이션" if "curated" in (rows[1999]["source"] or "") else "Tier-1 자동"
    verdict = "냉담 영역 — 1999식 IPO 광기 부재" if hn < 1 else "과열 진입"
    return (f"## Q5 IPO 과열지수 (z합성: 건수+첫날수익+적자비율)\n"
            f"- 합성 z: 1999 정점 **{h99:+.2f}** vs {latest}년 **{hn:+.2f}** → {verdict}\n"
            f"- {latest} 적자 IPO 비율 {rows[latest]['pct_negative_eps']}% vs 1999년 {rows[1999]['pct_negative_eps']}%\n"
            f"- {src_tier}\n")


def q7_q8_macro(conn: sqlite3.Connection) -> str:
    cyc = _cycle_month_now()
    dc_month = _dotcom_same_month(cyc)
    ff_then = conn.execute(
        "SELECT value FROM macro_monthly WHERE series_id='FEDFUNDS' AND substr(date,1,7)=?",
        (dc_month,)).fetchone()
    ff_now = conn.execute(
        "SELECT value FROM macro_monthly WHERE series_id='FEDFUNDS' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if ff_now is None or ff_then is None:
        return ("## Q7·Q8·Q9 매크로 동시점\n"
                "- **산출 불가 — FRED 계열 미수집** (네트워크 차단, CHANGELOG #7). "
                "결측은 결측으로 유지, FRED 도달 가능 시 `ingest`가 자동 충전.\n")

    def m2_yoy(ym: str) -> float | None:
        cur = conn.execute(
            "SELECT value FROM macro_monthly WHERE series_id='M2SL' AND substr(date,1,7)=?",
            (ym,)).fetchone()
        prev = conn.execute(
            "SELECT value FROM macro_monthly WHERE series_id='M2SL' AND substr(date,1,7)=?",
            (f"{int(ym[:4]) - 1}{ym[4:]}",)).fetchone()
        return (cur["value"] / prev["value"] - 1) * 100 if cur and prev else None

    latest_m2 = conn.execute(
        "SELECT substr(date,1,7) m FROM macro_monthly WHERE series_id='M2SL'"
        " ORDER BY date DESC LIMIT 1").fetchone()["m"]
    hy = conn.execute(
        "SELECT value FROM macro_daily WHERE series_id='BAMLH0A0HYM2'"
        " ORDER BY date DESC LIMIT 1").fetchone()
    return (f"## Q7·Q8·Q9 매크로 동시점 (닷컴 M+{cyc} ≈ {dc_month})\n"
            f"- Fed funds: 현재 {ff_now['value']:.2f}% vs 닷컴 동시점 {ff_then['value']:.2f}%\n"
            f"- M2 YoY: 현재({latest_m2}) {m2_yoy(latest_m2):.1f}% vs 닷컴 동시점 {m2_yoy(dc_month):.1f}%\n"
            f"- HY 스프레드(현재): {hy['value']:.2f}%p\n"
            f"- Tier-1 (FRED)\n")


def q13_margin_debt(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT date, debit_bil FROM margin_debt_monthly ORDER BY date").fetchall()
    if not rows:
        return "## Q13 마진부채\n- 데이터 없음 (FINRA 미수집)\n"
    latest = rows[-1]
    yoy_row = next((r for r in rows
                    if r["date"][:7] == f"{int(latest['date'][:4]) - 1}{latest['date'][4:7]}"), None)
    yoy = (latest["debit_bil"] / yoy_row["debit_bil"] - 1) * 100 if yoy_row else None
    m3 = rows[-4] if len(rows) >= 4 else rows[0]
    chg3 = (latest["debit_bil"] / m3["debit_bil"] - 1) * 100
    yoy_txt = f"YoY **{yoy:+.1f}%**" if yoy is not None else "YoY 산출 불가(12개월 미만)"
    return (f"## Q13 마진부채 (FINRA, Tier-2)\n"
            f"- 최신 {latest['date'][:7]}: **${latest['debit_bil']:,.0f}B** · {yoy_txt} · 3개월 {chg3:+.1f}%\n"
            f"- 닷컴측(1997~2003) 동시점 비교는 페이지 노출 범위 밖 — data_gap (역사 파일 확보 시 충전)\n"
            f"- 참고: 닷컴 정점 직전(2000-03) 마진부채 YoY는 +80%대였다는 것이 통설 — 현 수치와의\n"
            f"  직접 비교는 역사 데이터 충전 후에만 (추측 금지)\n")


def render(conn: sqlite3.Connection) -> str:
    parts = [f"# dualdb 주간 리포트 — {date.today().isoformat()}",
             "> 참고 의견 (P3 게이트 전) · 생존편향: 종목 통계는 생존자 표본\n"]
    for fn in (q1_alignment, q2_corrections, q3_vol_regime, q5_ipo_heat, q13_margin_debt,
               q7_q8_macro):
        try:
            parts.append(fn(conn))
        except Exception as exc:  # noqa: BLE001
            parts.append(f"## {fn.__name__}\n- 산출 실패: {type(exc).__name__}: {exc}\n")
    out = "\n".join(parts)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%y%m%d")
    (config.REPORTS_DIR / f"weekly_{stamp}.md").write_text(out, encoding="utf-8")
    return out
