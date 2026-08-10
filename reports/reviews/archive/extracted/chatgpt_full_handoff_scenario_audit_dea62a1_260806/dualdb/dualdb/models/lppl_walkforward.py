"""LPPL 워크포워드 사후검증 — 닷컴 사이클로 tc 리드/래그를 재고 AI 사이클에 병기.

ln(p(t)) = A + B·(tc−t)^β + C·(tc−t)^β·cos(ω·ln(tc−t) − φ)   (Sornette LPPL)

2단계 적합: 비선형 파라미터(tc, β, ω, φ)는 differential_evolution(seed 고정)으로
탐색하고 선형 파라미터(A, B, C)는 각 후보에서 최소자승으로 푼다
(src/ai_fc/quant/lppl.py의 절차를 dualdb용으로 복제·적응 — ai_fc 임포트 없음).

워크포워드: 닷컴 ^IXIC 월말 종가(1995-01 시작)에서 적합 종료점을 1998-06부터
2000-02까지 월 단위로 이동, 각 시점에서 '그 시점까지 데이터만으로' tc를 추정해
실제 정점(2000-03) 대비 오차(개월)를 기록한다. 동일 파이프라인으로 AI ^IXIC
월말(2022-01~최근 완결월)을 1회 적합해 raw tc와 워크포워드 리드 중앙값으로
보정한 tc를 병기한다.

백테스트 금지 원칙의 예외 근거: 사용자 제공 dualdb 스펙 v1.0 §8 —
"수치 모델은 닷컴 백테스트가 유효하다 — LLM 판단과 달리 사전지식 오염이 없다.
이 구분을 README에 명기." (산출물은 base rate 참조용.) 단 하이퍼파라미터
(탐색 경계·기간 선택)가 정점 지식을 간접 내포할 수 있음은 caveat로 남는다.

한계 (정직성 §10 — 출력 caveats에도 동일 명기):
- 표본 n=1 사이클(닷컴)로 잰 편향 보정 — 통계적 신뢰구간을 부여할 수 없다.
- LPPL은 '버블 존재'를 전제한다 — AI 사이클이 초지수 버블이 아니면 tc는 무의미.
- tc 탐색 하한이 표본 끝+0.5개월이라 정점 직전 시점의 리드는 우측 절단된다
  (음의 큰 리드가 구조적으로 불가능) — 편향 통계 해석 시 주의.
- 탐색 상한(TC_HORIZON) 고정 구간에서는 tc가 경계에 붙어 리드가 상한
  파라미터의 결정론적 함수가 되는 아티팩트 — 경계히트 비율 > 0.5면 보정 tc를
  비활성화하고 raw tc + 사분위만 병기한다.
- 하이퍼파라미터(탐색 경계·워크포워드 기간 선택)가 닷컴 정점 시점 지식을
  간접 내포할 수 있다 (수치 모델 예외 조항의 잔여 오염 경로).
- ^IXIC은 생존한 지수 — 생존편향 내재.
- differential_evolution은 다봉 목적함수의 국소해 위험 — seed 고정은 재현성만
  보장하고 전역 최적을 보장하지 않는다.
- 산출은 base rate 참조용이며 매매 신호가 아니다 (P3 게이트 전 '참고 의견').
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime

import numpy as np
from scipy.optimize import differential_evolution

from .. import config
from ..derive.daily import ERA_WINDOWS

MODEL_NAME = "lppl_walkforward"
SERIES = "^IXIC"
WF_START = "1998-06"          # 워크포워드 적합 종료점 시작
WF_END = "2000-02"            # 정점(2000-03) 직전월까지
TC_HORIZON = 36.0             # tc 탐색 상한: 표본 끝 + 36개월
STABLE_TOL = 6.0              # '수렴' 판정: |오차| ≤ 6개월
BOUNDARY_RATIO_MAX = 0.5      # 워크포워드 경계히트 비율 초과 시 보정 tc 비활성화
CAVEATS = [
    "표본 n=1 사이클(닷컴) 기반 편향 보정 — 신뢰구간 부여 불가",
    "LPPL은 버블 존재를 전제 — AI 사이클이 버블이 아니면 tc 무의미",
    "tc 하한 = 표본 끝 + 0.5개월 → 정점 직전 리드는 우측 절단(음의 리드 하한 절단)",
    "탐색 상한(TC_HORIZON) 고정 구간에서 tc가 상한 경계에 붙으면 리드가 상한 "
    "파라미터의 결정론적 함수가 되는 아티팩트 — 경계히트 비율 > 0.5면 보정 tc 비활성화",
    "하이퍼파라미터(탐색 경계·워크포워드 기간 선택)가 닷컴 정점 지식을 간접 내포 가능 "
    "(스펙 v1.0 §8 수치 모델 예외의 잔여 오염 경로)",
    "^IXIC 생존 지수 — 생존편향 내재",
    "differential_evolution 국소해 위험 — seed 고정은 재현성만 보장",
    "base rate 참조용 — 매매 신호 아님 (P3 게이트 전 참고 의견)",
]


# ── 월 연산 유틸 ─────────────────────────────────────


def _ym_total(ym: str) -> int:
    return int(ym[:4]) * 12 + int(ym[5:7]) - 1


def _ym_add(ym: str, k: int) -> str:
    total = _ym_total(ym) + k
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _ym_diff(a: str, b: str) -> int:
    """a − b (개월)."""
    return _ym_total(a) - _ym_total(b)


def _month_ends(conn: sqlite3.Connection, series: str, d0: str, d1: str
                ) -> list[tuple[str, float]]:
    """월말 종가 (derive.daily와 동일 정의 — 월내 최종 거래일)."""
    return [(r["m"], r["c"]) for r in conn.execute(
        """SELECT substr(date,1,7) m, close c, MAX(date) FROM price_daily
           WHERE series=? AND date BETWEEN ? AND ? GROUP BY substr(date,1,7)
           ORDER BY m""", (series, d0, d1))]


# ── 2단계 LPPL 적합 (ai_fc/quant/lppl.py 포팅) ───────


@dataclass
class LpplFit:
    tc: float          # 표본 시작월 기준 개월 인덱스 (t=0 = 첫 월말)
    beta: float
    omega: float
    phi: float
    r2: float
    converged: bool    # differential_evolution success
    boundary_hit: bool  # tc가 탐색 경계에 붙음 → 추정 불신 신호


def _design(t: np.ndarray, tc: float, beta: float, omega: float, phi: float) -> np.ndarray:
    dt = np.maximum(tc - t, 1e-9)
    f = dt ** beta
    g = f * np.cos(omega * np.log(dt) - phi)
    return np.column_stack([np.ones_like(t), f, g])


def fit_lppl(closes: list[float], seed: int = 42, maxiter: int = 300) -> LpplFit:
    """월말 종가열에 LPPL 적합 — tc는 '첫 관측월 = 0' 기준 개월."""
    p = np.log(np.asarray(closes, dtype=float))
    t = np.arange(len(p), dtype=float)
    n = len(p)

    def sse(params: np.ndarray) -> float:
        tc, beta, omega, phi = params
        X = _design(t, tc, beta, omega, phi)
        coef, *_ = np.linalg.lstsq(X, p, rcond=None)
        resid = p - X @ coef
        return float(resid @ resid)

    lo, hi = n + 0.5, n + TC_HORIZON
    bounds = [(lo, hi),            # tc: 표본 끝 이후 0.5~36개월
              (0.1, 0.9),          # β
              (4.0, 25.0),         # ω
              (0.0, 2 * np.pi)]    # φ
    result = differential_evolution(sse, bounds, seed=seed, maxiter=maxiter,
                                    tol=1e-10, polish=True)
    tc, beta, omega, phi = result.x
    X = _design(t, tc, beta, omega, phi)
    coef, *_ = np.linalg.lstsq(X, p, rcond=None)
    pred = X @ coef
    ss_res = float(np.sum((p - pred) ** 2))
    ss_tot = float(np.sum((p - p.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return LpplFit(float(tc), float(beta), float(omega), float(phi), r2,
                   bool(result.success), bool(min(tc - lo, hi - tc) < 0.05))


# ── 워크포워드 (순수 함수 — DB 무접촉, 합성 데이터 테스트 가능) ──


def walkforward(month_closes: list[tuple[str, float]], start_asof: str, end_asof: str,
                actual_peak_month: str, *, seed: int = 42, maxiter: int = 300
                ) -> list[dict]:
    """적합 종료점(asof)을 월 단위로 이동하며 tc 추정 → 실제 정점 대비 오차 기록.

    lead_months = tc 추정월 − 실제 정점월 (음수 = 조기 예측, 양수 = 지연 예측
    — ai_fc backcalibrate_dotcom의 bias 부호 규약과 동일).
    """
    months = [m for m, _ in month_closes]
    closes = [c for _, c in month_closes]
    base = months[0]
    # 연속 월 격자 검증 — 결측월이 있으면 t 인덱스가 왜곡된다
    for i, m in enumerate(months):
        if _ym_diff(m, base) != i:
            raise ValueError(f"월말열 결측: {base}+{i} 기대, {m} 발견")
    peak_idx = _ym_diff(actual_peak_month, base)
    rows = []
    asof = start_asof
    while _ym_diff(asof, end_asof) <= 0:
        if asof not in months:
            raise ValueError(f"asof {asof} 월말 데이터 없음")
        i = months.index(asof)
        fit = fit_lppl(closes[:i + 1], seed=seed, maxiter=maxiter)
        lead = fit.tc - peak_idx
        rows.append({
            "asof_month": asof,
            "n_obs": i + 1,
            "tc_est": round(fit.tc, 2),
            "tc_est_month": _ym_add(base, int(round(fit.tc))),
            "lead_months": round(lead, 2),
            "r2": round(fit.r2, 4),
            "converged": fit.converged,
            "boundary_hit": fit.boundary_hit,
        })
        asof = _ym_add(asof, 1)
    return rows


def summarize(rows: list[dict], actual_peak_month: str, base_month: str,
              stable_tol: float = STABLE_TOL) -> dict:
    """리드 중앙값/사분위 + '정점 N개월 전부터 |오차| ≤ tol 유지' 수렴 요약."""
    leads = np.array([r["lead_months"] for r in rows], dtype=float)
    free = [r["lead_months"] for r in rows if not r["boundary_hit"]]
    peak_idx = _ym_diff(actual_peak_month, base_month)
    # 뒤에서부터 |lead| ≤ tol이 끊기지 않는 가장 긴 접미 구간
    k = len(rows)
    for i in range(len(rows) - 1, -1, -1):
        if abs(rows[i]["lead_months"]) <= stable_tol:
            k = i
        else:
            break
    stable = None
    if k < len(rows):
        first = rows[k]
        stable = {
            "from_asof": first["asof_month"],
            "months_before_peak": peak_idx - _ym_diff(first["asof_month"], base_month),
            "n_points": len(rows) - k,
        }
    return {
        "n_fits": len(rows),
        "lead_median": round(float(np.median(leads)), 2),
        "lead_q25": round(float(np.percentile(leads, 25)), 2),
        "lead_q75": round(float(np.percentile(leads, 75)), 2),
        "lead_median_nonboundary": (round(float(np.median(free)), 2) if free else None),
        "n_boundary_hits": int(sum(r["boundary_hit"] for r in rows)),
        "stable_tol": stable_tol,
        "stable": stable,  # None = end_asof 시점까지도 미수렴
    }


# ── DB 결합 계층 ─────────────────────────────────────


def walkforward_dotcom(conn: sqlite3.Connection, *, start_asof: str = WF_START,
                       end_asof: str = WF_END, seed: int = 42, maxiter: int = 300
                       ) -> list[dict]:
    """닷컴 ^IXIC 월말(1995-01~)로 워크포워드 — 정점월은 config.ANCHORS 기준."""
    w0, _ = ERA_WINDOWS["dotcom"]
    peak_month = config.ANCHORS["dotcom"]["peak_date"][:7]
    me = _month_ends(conn, SERIES, w0, "2000-06-30")
    if not me:
        raise ValueError("닷컴 ^IXIC 월말 데이터 없음 — ingest 필요")
    return walkforward(me, start_asof, end_asof, peak_month, seed=seed, maxiter=maxiter)


def fit_ai_live(conn: sqlite3.Connection, *, seed: int = 42, maxiter: int = 300) -> dict:
    """AI ^IXIC 월말(2022-01~최근 완결월) 라이브 적합 1회 — 진행 중 월은 제외."""
    w0, _ = ERA_WINDOWS["ai"]
    me = _month_ends(conn, SERIES, w0, date.today().isoformat())
    me = [(m, c) for m, c in me if m != date.today().isoformat()[:7]]  # 부분월 제외
    # 불완전 월 가드 (stale DB 방어): 마지막 월의 MAX(date)가 그 월 25일 이후가
    # 아니면 미완결 월로 간주하고 제외 — 캘린더상 지난 달이라도 ingest가 밀려
    # 월 중반까지만 있으면 '월말 종가'가 아니어서 적합을 왜곡한다.
    if me:
        last_max = conn.execute(
            "SELECT MAX(date) d FROM price_daily WHERE series=? AND substr(date,1,7)=?",
            (SERIES, me[-1][0])).fetchone()["d"]
        if int(last_max[8:10]) < 25:
            me = me[:-1]
    if len(me) < 24:
        raise ValueError(f"AI 월말 표본 부족: {len(me)} (< 24)")
    fit = fit_lppl([c for _, c in me], seed=seed, maxiter=maxiter)
    base = me[0][0]
    return {
        "base_month": base,
        "last_month": me[-1][0],
        "n_obs": len(me),
        "fit": {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in asdict(fit).items()},
        "tc_raw": round(fit.tc, 2),
        "tc_raw_month": _ym_add(base, int(round(fit.tc))),
    }


def run(conn: sqlite3.Connection, *, start_asof: str = WF_START, end_asof: str = WF_END,
        seed: int = 42, maxiter: int = 300, record: bool = True) -> dict:
    """워크포워드 + AI 라이브 적합 + (record 시) model_run 기록. 원천 테이블 무접촉."""
    rows = walkforward_dotcom(conn, start_asof=start_asof, end_asof=end_asof,
                              seed=seed, maxiter=maxiter)
    peak_month = config.ANCHORS["dotcom"]["peak_date"][:7]
    base_dc = _ym_add(start_asof, -(rows[0]["n_obs"] - 1))
    summary = summarize(rows, peak_month, base_dc)
    ai = fit_ai_live(conn, seed=seed, maxiter=maxiter)
    boundary_ratio = summary["n_boundary_hits"] / summary["n_fits"]
    ai["boundary_hit_ratio"] = round(boundary_ratio, 3)
    if boundary_ratio > BOUNDARY_RATIO_MAX:
        # 경계히트 지배 표본에서 리드 통계는 탐색 상한(TC_HORIZON)의 결정론적
        # 함수 — 편향 측정이 아니라 하이퍼파라미터 아티팩트이므로 보정 비활성화.
        # raw tc + 리드 사분위만 유효, 비경계 중앙값은 '참고'로만 병기.
        ai["correction_disabled"] = True
        ai["correction_disabled_reason"] = (
            f"워크포워드 경계히트 {summary['n_boundary_hits']}/{summary['n_fits']} "
            f"(비율 {boundary_ratio:.2f} > {BOUNDARY_RATIO_MAX}) — 리드가 탐색 상한 "
            f"TC_HORIZON={TC_HORIZON:.0f}개월의 결정론적 함수가 되는 아티팩트. "
            "보정 tc 비활성화, raw tc와 리드 사분위만 유효 "
            "(비경계 중앙값은 참고용 병기)")
        ai["lead_correction_applied"] = None
        ai["tc_corrected"] = None
        ai["tc_corrected_month"] = None
        ai["tc_corrected_range_months"] = None
        ai["tc_corrected_in_past"] = None
        ai["lead_median_nonboundary_ref"] = summary["lead_median_nonboundary"]  # 참고
    else:
        ai["correction_disabled"] = False
        # 1차 편향 보정: 워크포워드 리드 중앙값을 뺀다 (사분위로 범위 병기)
        ai["lead_correction_applied"] = summary["lead_median"]
        ai["tc_corrected"] = round(ai["tc_raw"] - summary["lead_median"], 2)
        ai["tc_corrected_month"] = _ym_add(ai["base_month"],
                                           int(round(ai["tc_corrected"])))
        ai["tc_corrected_range_months"] = [  # [q75 보정, q25 보정] = 이른쪽~늦은쪽
            _ym_add(ai["base_month"], int(round(ai["tc_raw"] - summary["lead_q75"]))),
            _ym_add(ai["base_month"], int(round(ai["tc_raw"] - summary["lead_q25"]))),
        ]
        # 보정 tc가 이미 지난 달이면 보정 자체가 무의미할 가능성 — 자체 플래그
        ai["tc_corrected_in_past"] = (
            _ym_diff(ai["tc_corrected_month"], ai["last_month"]) <= 0)
    result = {
        "model": MODEL_NAME,
        "series": SERIES,
        "dotcom": {
            "base_month": base_dc,
            "actual_peak_month": peak_month,
            "rows": rows,
            "summary": summary,
        },
        "ai": ai,
        "caveats": CAVEATS,
    }
    if record:
        params = {"series": SERIES, "start_asof": start_asof, "end_asof": end_asof,
                  "seed": seed, "maxiter": maxiter, "tc_horizon": TC_HORIZON,
                  "stable_tol": STABLE_TOL}
        conn.execute(
            """INSERT INTO model_run (model, asof, params_json, output_json, created_at)
               VALUES (?,?,?,?,?)""",
            (MODEL_NAME, date.today().isoformat(), json.dumps(params),
             json.dumps(result, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    return result


def render_md(result: dict) -> str:
    """run() 결과 → 마크다운 (파일 쓰기는 오케스트레이터 몫)."""
    dc, ai, s = result["dotcom"], result["ai"], result["dotcom"]["summary"]
    lines = [
        f"# LPPL 워크포워드 사후검증 — {result['series']} (base rate 참조용)",
        "> 참고 의견 (P3 게이트 전) · 수치 모델 과거 적합 = 백테스트 금지 예외 "
        "(dualdb 스펙 v1.0 §8 — 사전지식 오염 없음, 단 하이퍼파라미터 간접 오염 caveat)\n",
        f"## 닷컴 워크포워드 (정점 {dc['actual_peak_month']}, 적합 시작 {dc['base_month']})",
        "| asof | n | tc 추정월 | 리드(개월) | R² | 경계히트 |",
        "|---|---|---|---|---|---|",
    ]
    for r in dc["rows"]:
        lines.append(f"| {r['asof_month']} | {r['n_obs']} | {r['tc_est_month']} "
                     f"| {r['lead_months']:+.1f} | {r['r2']:.3f} "
                     f"| {'●' if r['boundary_hit'] else ''} |")
    stable = s["stable"]
    stable_line = (f"정점 **{stable['months_before_peak']}개월 전**({stable['from_asof']})부터 "
                   f"|오차| ≤ {s['stable_tol']:.0f}개월 유지 ({stable['n_points']}개 시점)"
                   if stable else
                   f"{WF_END}까지도 |오차| ≤ {s['stable_tol']:.0f}개월 안정 수렴 실패")
    nb = s["lead_median_nonboundary"]
    boundary_dominant = s["n_boundary_hits"] / s["n_fits"] > BOUNDARY_RATIO_MAX
    lines += [
        "",
        f"- 리드 중앙값 **{s['lead_median']:+.1f}개월** "
        f"(Q25 {s['lead_q25']:+.1f} / Q75 {s['lead_q75']:+.1f}, "
        f"음수 = 조기 예측) · 경계히트 {s['n_boundary_hits']}/{s['n_fits']}회"
        + (f" · 비경계 중앙값 {nb:+.1f} (참고용)" if nb is not None else ""),
        f"- 수렴 요약: {stable_line}",
        "",
        f"## AI 라이브 적합 ({ai['base_month']}~{ai['last_month']}, n={ai['n_obs']})",
        f"- raw tc: **{ai['tc_raw_month']}** (tc={ai['tc_raw']}, "
        f"R²={ai['fit']['r2']:.3f}{', 경계히트 — 추정 불신' if ai['fit']['boundary_hit'] else ''})",
    ]
    if ai.get("correction_disabled"):
        lines.append(f"- ⚠ **보정 tc 비활성화** — {ai['correction_disabled_reason']}")
        lines.append(
            f"- 유효 산출은 raw tc **{ai['tc_raw_month']}** + 리드 사분위 "
            f"(Q25 {s['lead_q25']:+.1f} / Q75 {s['lead_q75']:+.1f}개월)뿐"
            + (f" · 비경계 중앙값 {nb:+.1f}개월은 참고로만 병기" if nb is not None else ""))
    else:
        lines.append(
            f"- 리드 중앙값({ai['lead_correction_applied']:+.1f}) 보정 tc: "
            f"**{ai['tc_corrected_month']}** "
            f"(사분위 보정 범위 {ai['tc_corrected_range_months'][0]}~"
            f"{ai['tc_corrected_range_months'][1]})")
        if boundary_dominant:
            # 방어선: 비활성화 로직과 별개로 경계히트>0.5면 경고를 반드시 출력
            lines.append(
                f"- ⚠ 워크포워드 경계히트 {s['n_boundary_hits']}/{s['n_fits']} > 50% — "
                "리드 통계가 탐색 상한(TC_HORIZON) 아티팩트일 수 있어 보정 tc 불신")
        if ai.get("tc_corrected_in_past"):
            lines.append(
                "- ⚠ 보정 tc가 이미 지난 달 — 경계히트 지배 표본(n=1)에서 잰 편향이라 "
                "보정 자체가 무의미하거나, AI 사이클이 닷컴 편향 궤적과 다르다는 신호")
    lines += ["", "## 한계"]
    lines += [f"- {c}" for c in result["caveats"]]
    return "\n".join(lines) + "\n"
