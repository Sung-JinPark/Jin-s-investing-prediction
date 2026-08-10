"""DTW 정밀 정렬 — 닷컴↔AI norm_m0 주간 워핑 경로로 '현재의 닷컴 위상' 추정.

절차:
1. derived_daily(^IXIC) norm_m0을 era별 **앵커월 첫 거래일부터** ISO주 마지막
   거래일로 다운샘플 — 닷컴 ~420주 × AI ~190주로 O(n·m) 전체 행렬 감당 가능.
   (닷컴 1995년 프리앵커 구간은 제외: 두 시계열 모두 M+0=100에서 출발해야
   DTW 경계조건(시작점 상호 매핑)이 위상 비교로 성립한다.)
2. 비용 = |ln(norm) 차| (앵커=100 기준 누적 로그수익률 차). 전구간 z-정규화는
   길이·진폭이 다른 두 사이클의 스케일을 다르게 눌러 위상을 왜곡하므로 배제.
3. 표준 DTW 전체 누적행렬(창 제약 없음) + 역추적 워핑 경로.
   단, AI는 진행 중(미완) 사이클이므로 기본은 **open-end(접두) 정렬**:
   닷컴 축 종점 j*를 argmin_j D[n, j+1]/(n+j+1)로 자유화한다. 종점 고정
   closed-end DTW는 닷컴의 잔여 경로(정점→붕괴→바닥)를 AI 마지막 몇 주에
   강제 압축하는 아티팩트가 있어 위상 판독에 부적합 (거리만 참고로 병기).
4. 산출: (a) AI 최신 주가 매핑되는 닷컴 날짜(들)와 위상(개월),
   (b) alignment(method='dtw') — AI 주 인덱스별 (ai_date, 닷컴 매핑 중앙값) —
   파생 계층이므로 DELETE 후 재삽입, (c) 캘린더 정렬(M+N) 대비 위상차(개월).

한계 (정직성 고지 — §10):
- **표본 n=1 사이클 대 n=1 사이클**: DTW는 형태 유사성 측도일 뿐 인과·예측
  보증이 아니다. base rate 참조용 참고 의견 (P3 게이트 전).
- **open-end 접두 정렬의 의미**: "AI가 닷컴 경로의 어느 지점까지 왔나"의 형태
  매핑이며, 닷컴의 잔여 경로가 AI의 미래라는 가정을 부여하지 않는다.
- **생존편향**: ^IXIC 자체가 구성종목 전면 교체를 거친 생존 지수.
- **선택 민감성**: 주간 다운샘플·log 비용함수·종점 정규화 방식에 따라 위상
  추정이 수 주 단위로 움직일 수 있다.
기록: alignment(method='dtw')와 model_run(model='dtw_daily')에만 쓴다 —
원천(raw) 계층 무접촉.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import numpy as np

from .. import config

SERIES = "^IXIC"
DAYS_PER_MONTH = 30.4375          # 365.25 / 12 — 일수→개월 환산
MIN_WEEKS = {"dotcom": 52, "ai": 26}

CAVEATS = [
    "표본 n=1 사이클 — 형태 유사성이지 예측 보증 아님 (P3 게이트 전 참고 의견)",
    "open-end 접두 정렬 — 닷컴 잔여 경로를 AI의 미래로 가정하지 않음",
    "^IXIC는 구성종목 전면 교체를 거친 생존 지수 (생존편향 내재)",
    "주간 다운샘플·log 비용·종점 정규화 선택에 위상 추정 민감 (수 주 단위)",
]


# ── 데이터 준비 ──────────────────────────────────────────

def _weekly_norm(conn: sqlite3.Connection, series: str, era_id: str
                 ) -> tuple[list[str], np.ndarray]:
    """앵커월 이후 norm_m0을 ISO주 마지막 거래일로 다운샘플."""
    anchor = config.ANCHORS[era_id]["anchor_month"]
    rows = conn.execute(
        """SELECT date, norm_m0 FROM derived_daily
           WHERE series=? AND era_id=? AND norm_m0 IS NOT NULL
             AND substr(date,1,7) >= ? ORDER BY date""",
        (series, era_id, anchor)).fetchall()
    dates: list[str] = []
    vals: list[float] = []
    prev_key: tuple[int, int] | None = None
    for r in rows:
        key = date.fromisoformat(r["date"]).isocalendar()[:2]
        if key == prev_key:
            dates[-1], vals[-1] = r["date"], r["norm_m0"]   # 같은 주 → 마지막으로 교체
        else:
            dates.append(r["date"])
            vals.append(r["norm_m0"])
            prev_key = key
    return dates, np.asarray(vals, dtype=float)


# ── DTW 코어 (numpy 직접 구현) ───────────────────────────

def dtw_matrix(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """표준 DTW 누적비용 행렬 (n+1)×(m+1) — 창 제약 없음, 비용 |x_i − y_j|."""
    n, m = len(x), len(y)
    cost = np.abs(x[:, None] - y[None, :])
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        ci = cost[i - 1]
        prev, cur = D[i - 1], D[i]
        for j in range(1, m + 1):
            cur[j] = ci[j - 1] + min(prev[j - 1], prev[j], cur[j - 1])
    return D


def dtw_path(D: np.ndarray, end_j: int | None = None) -> list[tuple[int, int]]:
    """(n−1, end_j)에서 (0, 0)까지 역추적 — 동률이면 대각 우선. 0-based 쌍 반환."""
    i = D.shape[0] - 1
    j = D.shape[1] - 1 if end_j is None else end_j + 1
    path = [(i - 1, j - 1)]
    while i > 1 or j > 1:
        moves = []                          # 대각을 먼저 넣어 동률 시 대각 선택
        if i > 1 and j > 1:
            moves.append((D[i - 1, j - 1], i - 1, j - 1))
        if i > 1:
            moves.append((D[i - 1, j], i - 1, j))
        if j > 1:
            moves.append((D[i, j - 1], i, j - 1))
        _, i, j = min(moves, key=lambda t: t[0])
        path.append((i - 1, j - 1))
    path.reverse()
    return path


def open_end_j(D: np.ndarray) -> int:
    """open-end 종점: argmin_j D[n, j+1]/(n+j+1) — 경로 길이 근사로 정규화."""
    n, m = D.shape[0] - 1, D.shape[1] - 1
    scores = D[n, 1:] / (n + np.arange(1, m + 1))
    return int(np.argmin(scores))


def dtw_align(x: np.ndarray, y: np.ndarray, open_end: bool = True) -> dict:
    """x(질의, AI)를 y(참조, 닷컴)에 정렬 — 경로·거리·종점 반환."""
    n, m = len(x), len(y)
    D = dtw_matrix(x, y)
    j_end = open_end_j(D) if open_end else m - 1
    path = dtw_path(D, j_end)
    raw = float(D[n, j_end + 1])
    return {
        "path": path, "end_j": j_end,
        "raw": raw, "norm": raw / len(path),
        "closed_raw": float(D[n, m]), "closed_norm": float(D[n, m]) / (n + m),
    }


# ── 위상 판독·기록 ───────────────────────────────────────

def _months_between(d0: str, d1: str) -> float:
    return (date.fromisoformat(d1) - date.fromisoformat(d0)).days / DAYS_PER_MONTH


def _calendar_dotcom_month(ai_last: str) -> tuple[str, int]:
    """캘린더 정렬: AI 최신 월의 M+N과 닷컴 동시점 월 (weekly.py와 동일 산식)."""
    a_ai = config.ANCHORS["ai"]["anchor_month"]
    a_dc = config.ANCHORS["dotcom"]["anchor_month"]
    cyc = (int(ai_last[:4]) - int(a_ai[:4])) * 12 + int(ai_last[5:7]) - int(a_ai[5:7])
    total = int(a_dc[:4]) * 12 + int(a_dc[5:7]) - 1 + cyc
    return f"{total // 12:04d}-{total % 12 + 1:02d}", cyc


def _upsert_alignment(conn: sqlite3.Connection, path: list[tuple[int, int]],
                      dc_dates: list[str], ai_dates: list[str]) -> int:
    """method='dtw' 행 DELETE 후 재삽입 — AI 주 i당 (dotcom, ai) era 행 쌍.

    long format: 같은 cycle_index의 era 행들이 한 정렬점 (반환값은 쌍 수 = AI 주 수).
    """
    by_i: dict[int, list[int]] = {}
    for i, j in path:
        by_i.setdefault(i, []).append(j)
    rows = []
    for i, js in sorted(by_i.items()):
        rows.append(("dtw", float(i), "", "dotcom", dc_dates[js[len(js) // 2]]))
        rows.append(("dtw", float(i), "", "ai", ai_dates[i]))
    conn.execute("DELETE FROM alignment WHERE method='dtw'")
    conn.executemany(
        "INSERT INTO alignment (method, cycle_index, event_name, era_id, date)"
        " VALUES (?,?,?,?,?)", rows)
    return len(by_i)


def run(conn: sqlite3.Connection, series: str = SERIES, open_end: bool = True) -> dict:
    """DTW 정렬 실행 + alignment/model_run 기록. 반환 dict는 render_md 입력 겸용."""
    dc_dates, dc_v = _weekly_norm(conn, series, "dotcom")
    ai_dates, ai_v = _weekly_norm(conn, series, "ai")
    if len(dc_dates) < MIN_WEEKS["dotcom"] or len(ai_dates) < MIN_WEEKS["ai"]:
        raise ValueError(
            f"주간 표본 부족 (dotcom {len(dc_dates)}, ai {len(ai_dates)}) — derive 후 실행")

    res = dtw_align(np.log(ai_v), np.log(dc_v), open_end=open_end)
    n_rows = _upsert_alignment(conn, res["path"], dc_dates, ai_dates)

    last_i = len(ai_v) - 1
    last_js = sorted(j for i, j in res["path"] if i == last_i)
    phase_j = res["end_j"]
    phase_date = dc_dates[phase_j]
    phase_m = _months_between(dc_dates[0], phase_date)
    cal_m = _months_between(ai_dates[0], ai_dates[-1])
    cal_month, cal_cyc = _calendar_dotcom_month(ai_dates[-1])

    result = {
        "asof": ai_dates[-1],
        "series": series,
        "weeks": {"dotcom": len(dc_dates), "ai": len(ai_dates)},
        "open_end": open_end,
        "distance_norm": round(res["norm"], 4),
        "distance_closed_norm": round(res["closed_norm"], 4),
        "phase": {
            "dotcom_date": phase_date,                 # AI 최신 주의 닷컴 위상 (종점)
            "run_first": dc_dates[last_js[0]],         # AI 최신 주에 매핑된 닷컴 구간
            "run_last": dc_dates[last_js[-1]],
            "cycle_months_dtw": round(phase_m, 1),
        },
        "calendar": {"cycle_months": round(cal_m, 1), "cycle_m_label": cal_cyc,
                     "dotcom_month": cal_month},
        "phase_gap_months": round(phase_m - cal_m, 1),  # 음수 = 캘린더보다 이른 위상
        "ai_norm_last": round(float(ai_v[-1]), 1),
        "dotcom_norm_at_phase": round(float(dc_v[phase_j]), 1),
        "alignment_rows": n_rows,
        "caveats": list(CAVEATS),
    }
    params = {
        "series": series, "downsample": "isoweek_last",
        "cost": "abs_log_norm_m0_diff", "open_end": open_end,
        "anchor_start": {"dotcom": dc_dates[0], "ai": ai_dates[0]},
        "endpoint_norm": "D[n,j]/(n+j) path-length approx",
    }
    cur = conn.execute(
        "INSERT INTO model_run (model, asof, params_json, output_json, created_at)"
        " VALUES (?,?,?,?,?)",
        ("dtw_daily", ai_dates[-1], json.dumps(params, ensure_ascii=False),
         json.dumps(result, ensure_ascii=False),
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    result["run_id"] = cur.lastrowid
    return result


def render_md(result: dict) -> str:
    """run() 결과 dict → 마크다운 절 (한계 고지 포함 — 없으면 출력 무효)."""
    ph, cal = result["phase"], result["calendar"]
    gap = result["phase_gap_months"]
    verdict = ("캘린더 시간표보다 이른 위상 — AI가 뒤처짐" if gap < 0
               else "캘린더 시간표보다 진행된 위상 — AI가 앞섬")
    run_span = (f"{ph['run_first']}~{ph['run_last']}"
                if ph["run_first"] != ph["run_last"] else ph["run_first"])
    lines = [
        f"## DTW 정밀 정렬 (^IXIC norm_m0 주간, open-end) — asof {result['asof']}",
        "> 참고 의견 (P3 게이트 전) · 표본 n=1 사이클 — 형태 매핑이지 예측 아님",
        "",
        f"- 현재의 닷컴 위상: **{ph['dotcom_date']}** (앵커 후 {ph['cycle_months_dtw']:.1f}개월)"
        f" — AI 최신 주 매핑 닷컴 구간 {run_span}",
        f"- 캘린더 정렬 대비: M+{cal['cycle_m_label']}(≈{cal['dotcom_month']},"
        f" {cal['cycle_months']:.1f}개월) → 위상차 **{gap:+.1f}개월** ({verdict})",
        f"- 정규화 DTW 거리 {result['distance_norm']:.4f}"
        f" (참고: closed-end {result['distance_closed_norm']:.4f} —"
        " 닷컴 잔여 경로 강제 압축 아티팩트 포함)",
        f"- 주간 표본: 닷컴 {result['weeks']['dotcom']}주 × AI {result['weeks']['ai']}주"
        f" · 정렬 값 검증: AI norm {result['ai_norm_last']:.1f}"
        f" ↔ 닷컴 위상시점 norm {result['dotcom_norm_at_phase']:.1f}",
        f"- alignment(method='dtw') {result['alignment_rows']}행 재기록",
        "",
        "### 한계 (정직성 고지)",
    ]
    lines += [f"- {c}" for c in result["caveats"]]
    return "\n".join(lines) + "\n"
