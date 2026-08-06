"""quant 실행기 — 피드 → 전 도구 재계산 → base_rates 자동 갱신 + 콘솔 요약.

산출 파일 data/base_rates/quant_auto.md는 '자동 생성·재생성 가능' 파일이다
(불변 규약 대상 아님 — 예측 기록과 달리 갱신이 정상).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import numpy as np

from . import feed, lppl, mc, overlay, seasonality, stats

V3_REFERENCE = {  # v3 리포트(2026-05-27) 적합값 — 비교용
    "pearson": 0.9173, "spearman": 0.9104, "hurst_ai": 0.699, "hurst_dc": 0.633,
    "beta_ai": 0.249, "beta_dc": 0.244, "lppl_tc_m": 49.4, "shift": 5,
}


def m_to_calendar(m: float, anchor: str = overlay.AI_ANCHOR) -> str:
    ay, am = int(anchor[:4]), int(anchor[5:7])
    total = am - 1 + int(round(m))
    return f"{ay + total // 12:04d}-{total % 12 + 1:02d}"


def run_all() -> tuple[dict, str]:
    today = date.today()

    # ── 피드 ──
    dc_labels, dc_closes = feed.monthly_closes("^IXIC", date(1995, 12, 1), date(2000, 5, 1))
    ai_labels, ai_closes = feed.monthly_closes("^IXIC", date(2022, 12, 1), today)
    try:
        m2 = feed.fred_m2()
    except Exception:  # noqa: BLE001 — FRED 실패 시 M2 항목만 생략 (우아한 강등)
        m2 = None
    daily_dates, daily_closes = feed.yahoo_series("^IXIC", date(2023, 1, 1), today, "1d")
    spx_dates, spx_closes = feed.yahoo_series("^GSPC", date(1993, 1, 1), today, "1d")

    # ── 오버레이 ──
    dc_idx = overlay.normalize(dc_labels, dc_closes, overlay.DOTCOM_ANCHOR)
    ai_idx = overlay.normalize(ai_labels, ai_closes, overlay.AI_ANCHOR)
    ai_m_labels = {overlay.month_offset(overlay.AI_ANCHOR, lb): lb for lb in ai_labels}
    dc_m_labels = {overlay.month_offset(overlay.DOTCOM_ANCHOR, lb): lb for lb in dc_labels}
    if m2 is not None:
        ai_m2adj = overlay.m2_normalize(ai_idx, ai_m_labels, m2, overlay.AI_ANCHOR)
        dc_m2adj = overlay.m2_normalize(dc_idx, dc_m_labels, m2, overlay.DOTCOM_ANCHOR)
    else:
        ai_m2adj, dc_m2adj = None, None
    latest_m = max(ai_idx)
    dd = overlay.max_drawdown([d.isoformat() for d in daily_dates], daily_closes)
    ath_i = int(np.argmax(daily_closes))

    # ── 통계 재적합 ──
    r, r_p = stats.pearson(ai_idx, dc_idx)
    rho, _ = stats.spearman(ai_idx, dc_idx)
    dc_upto = [dc_idx[m] for m in sorted(dc_idx) if m <= latest_m]
    ai_series = [ai_idx[m] for m in sorted(ai_idx)]
    hurst_ai = stats.hurst_rs(ai_series)
    hurst_dc = stats.hurst_rs(dc_upto)
    beta_ai = stats.power_law_beta(ai_series)
    beta_dc = stats.power_law_beta(dc_upto)
    shift, shift_d = stats.best_shift(ai_idx, dc_idx)
    ret_a, sig_a, sharpe_a = stats.sharpe_annualized(ai_series)
    ret_d, sig_d, sharpe_d = stats.sharpe_annualized(dc_upto)

    # ── LPPL: 닷컴 백캘리브레이션 → AI 적합 → 편향 보정 ──
    dc_full = [dc_idx[m] for m in sorted(dc_idx)]
    dc_fit, bias = lppl.backcalibrate_dotcom(dc_full, fit_upto=min(41, len(dc_full)))
    ai_fit = lppl.fit_lppl(ai_series)
    tc_corrected = ai_fit.tc - bias  # 편향 보정 (bias 음수 = 일찍 예측 → 뒤로 밀기)

    # ── GBM ──
    gbm = mc.gbm_simulate(ai_series)

    # ── 미드텀 (S&P 일봉 직접 계산) ──
    cases = seasonality.midterm_stats(spx_dates, spx_closes)
    mid = seasonality.summarize(cases)

    results = {
        "asof": today.isoformat(), "latest_m": latest_m,
        "ai_idx_latest": ai_idx[latest_m], "ath": max(daily_closes),
        "ath_date": daily_dates[ath_i].isoformat(),
        "dd_cycle": dd.mdd, "pearson": r, "pearson_p": r_p, "spearman": rho,
        "hurst_ai": hurst_ai, "hurst_dc": hurst_dc,
        "beta_ai": beta_ai, "beta_dc": beta_dc,
        "shift": shift, "sharpe_ai": sharpe_a, "sharpe_dc": sharpe_d,
        "lppl_tc": ai_fit.tc, "lppl_tc_cal": m_to_calendar(ai_fit.tc),
        "lppl_beta": ai_fit.beta, "lppl_omega": ai_fit.omega, "lppl_r2": ai_fit.r2,
        "lppl_bias": bias, "lppl_tc_corrected": tc_corrected,
        "lppl_tc_corrected_cal": m_to_calendar(tc_corrected),
        "gbm": gbm, "midterm": mid,
        "ai_m2adj_latest": ai_m2adj[latest_m] if ai_m2adj else None,
        "dc_m2adj_peak": dc_m2adj.get(overlay.DOTCOM_PEAK_M) if dc_m2adj else None,
    }
    return results, render_md(results, cases)


def render_md(x: dict, cases) -> str:
    g = x["gbm"]
    m = x["midterm"]
    v3 = V3_REFERENCE
    case_rows = "\n".join(
        f"| {c.election} | {c.pre_window_dd:+.1%} | {c.to_year_end:+.1%} | {c.plus_12m:+.1%} |"
        for c in cases)
    if x["dc_m2adj_peak"] and x["ai_m2adj_latest"]:
        room = x["dc_m2adj_peak"] / x["ai_m2adj_latest"] - 1
        m2_line = (f"- M2 정규화: AI 현재 {x['ai_m2adj_latest']:.1f} vs 닷컴 정점 "
                   f"{x['dc_m2adj_peak']:.1f} → 여력 {room:+.0%}")
    else:
        m2_line = "- M2 정규화: FRED 응답 실패로 이번 실행에서 생략 (재실행 시 갱신)"
    return f"""# Base Rates — quant 자동 산출 (재생성 가능 파일)

> `python -m ai_fc quant`가 원시 데이터(Yahoo ^IXIC/^GSPC, FRED M2SL)에서 직접 재계산.
> 생성: {x["asof"]} · AI 사이클 M+{x["latest_m"]} · v3 리포트(2026-05-27) 대비 병기.
> 이 파일은 자동 생성본 — 수기 편집 금지 (불변 규약 대상은 아니며 재실행 시 갱신됨).

## 오버레이 좌표
- AI 지수(M+{x["latest_m"]}, 월말): {x["ai_idx_latest"]:.1f} / 사이클 ATH {x["ath"]:,.2f} ({x["ath_date"]})
- 사이클 최대 낙폭(일간): {x["dd_cycle"]:.2%}
{m2_line}

## 시계열 동학 재적합 (v3 값 병기)
| 도구 | v4 재적합 | v3 (5/27) |
|---|---|---|
| Pearson r | {x["pearson"]:.4f} (p={x["pearson_p"]:.1e}) | {v3["pearson"]} |
| Spearman ρ | {x["spearman"]:.4f} | {v3["spearman"]} |
| Hurst H (AI / 닷컴 동기간) | {x["hurst_ai"]:.3f} / {x["hurst_dc"]:.3f} | {v3["hurst_ai"]} / {v3["hurst_dc"]} |
| Power law β (AI / 닷컴) | {x["beta_ai"]:.3f} / {x["beta_dc"]:.3f} | {v3["beta_ai"]} / {v3["beta_dc"]} |
| 최적 시프트 (개월) | {x["shift"]:+d} | +{v3["shift"]} |
| Sharpe (AI / 닷컴) | {x["sharpe_ai"]:.2f} / {x["sharpe_dc"]:.2f} | 1.65 / 1.05 |

## LPPL 재적합
- AI t_c = M+{x["lppl_tc"]:.1f} → **{x["lppl_tc_cal"]}** (β={x["lppl_beta"]:.3f}, ω={x["lppl_omega"]:.2f}, R²={x["lppl_r2"]:.3f})
- 닷컴 백캘리브레이션 편향: {x["lppl_bias"]:+.1f}개월 → 보정 t_c = M+{x["lppl_tc_corrected"]:.1f} = {x["lppl_tc_corrected_cal"]}
  **[비활성화 — DECISIONS 8-7]**: dualdb 워크포워드 실측(경계히트 17/21 = 탐색상한
  아티팩트, 정점 1개월 전에야 수렴)으로 편향 보정은 무의미 판정 — 이 보정값은
  참고 표기일 뿐 어떤 리스크 판단에도 사용 금지. 정본은 raw + 워크포워드 리드 IQR.
- **정본 규칙 (D-9·8-7)**: 하류 문서는 raw를 명시 라벨과 함께 인용하고, 보정값 인용 시
  반드시 위 비활성화 단서를 병기할 것. 편향 상수는 닷컴 1사이클 역산값(순환성).
- 주의: LPPL은 적합 불안정성이 큼 + 조기경보 도구로 강등됨(8-7) — 시드·경계 민감도는 v4.1 부록

## GBM 6개월 시뮬레이션 (최근 12개월 파라미터, n=10,000)
- μ={g.mu_monthly:+.2%}/월, σ={g.sigma_monthly:.2%}/월 → 6M 중앙값 {g.median_pct:+.1%}, 95% CI [{g.ci95_lo_pct:+.1%}, {g.ci95_hi_pct:+.1%}], 상승확률 {g.prob_up:.0%}
- 한계: 정규분포 가정 — fat tail·체제전환 미포착 (v3 관찰 14 동일)

## 중간선거 시즌성 (S&P 500 일봉 직접 계산, 1994~)
| 선거일 | 선거 전(8/1~) 최대낙폭 | 선거→연말 | +12개월 |
|---|---|---|---|
{case_rows}
- 평균: 선거 전 낙폭 {m["avg_pre_dd"]:+.1%} / 선거→연말 {m["avg_to_ye"]:+.1%} / +12개월 {m["avg_12m"]:+.1%} (승률 {m["win_12m"]:.0%}, n={m["n"]:.0f})
- **사용 질문**: nasdaq-ath-eoy-2026, nasdaq-corr10-augoct-2026, nasdaq-eoy-above-jul9-2026, soxx-eoy-down15
"""


def write_base_rates(root: Path, md: str) -> Path:
    out = root / "data" / "base_rates" / "quant_auto.md"
    out.write_text(md, encoding="utf-8")
    return out
