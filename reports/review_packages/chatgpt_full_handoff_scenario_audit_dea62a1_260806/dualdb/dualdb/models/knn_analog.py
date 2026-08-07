"""k-NN 아날로그 (Q15) — 다중 아날로그 시대 상태공간에서 현재 AI 국면의 최근접 이웃.

절차:
1. 각 아날로그 시대(dotcom·japan1989·niftyfifty1972·crypto2021·biotech2015)의
   자기 지수(ERA_INDEX) 월말(마지막 거래일) 5차원 상태벡터
   [vol_20d, vol_60d, drawdown, dist_200dma, rsi_14]를 풀로 수집 (derived_daily).
   5차원은 모두 척도무관(연율 변동성·비율·RSI) → 서로 다른 지수 간 비교 가능.
2. **풀 전체(과거 시대만)** 로 z-표준화 모수 산출 — AI 질의 데이터는 모수에서 제외
   (누출 방지). 현재 AI 최신 벡터를 같은 모수로 변환.
3. 유클리드 거리 k=5 최근접 시점 선택. **같은 시대 내에서만** 최소 90일 간격 강제
   (다른 시대 이웃은 달력이 겹쳐도 독립 시장 — 간격 미적용).
4. 각 이웃의 이후 1/3/6/12개월(21/63/126/252 거래일) 수익률을 **그 시대의 지수·창**
   안에서 산출. 이웃+지평이 시대 창을 넘으면 None — 외삽 금지.

한계 (정직성 고지 — §10):
- **사이클당 관측 소수**: n=1(닷컴)에서 다중 시대로 확장했으나 각 시대 자체가 한
  사이클이라 검정력은 여전히 제한 — 확률이 아니라 아날로그 참조(base rate 입력).
- **시대 간 시장 미시구조 상이**: crypto(BTC)는 7일 주간 → 21거래일 지평이 주식의
  ~30% 짧은 달력폭(변동성·전방수익률 지평이 시대 간 비대칭); 지수 구성·유동성·
  회계 관행도 상이. 각 이웃의 era를 병기해 추적 가능하게 한다.
- **상태벡터 불완전**: 가격 파생 5차원만. 밸류에이션(CAPE)·크레딧(HY)은 교차 시대
  데이터 부재(HY 1996~·CAPE 2023-09 종료·美 특화)로 k-NN 차원 불가 — 현재 레짐
  컨텍스트로 별도 제공(context digest). 심리(AAII)도 결측.
- **자기상관·백색화 미적용**: 동일 사이클 내 이웃은 독립 아님(90일 간격으로 완화).
  피처 간 상호상관 미백색화 — 유효 차원 < 5 (R-4).
기록: model_run 테이블에만 INSERT (model='knn_analog') — 원천 계층 무접촉.
"""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_left
from datetime import date, datetime

import numpy as np

from ..derive.daily import ERA_INDEX, ERA_WINDOWS

FEATURES = ("vol_20d", "vol_60d", "drawdown", "dist_200dma", "rsi_14")
HORIZONS_TD = {"fwd_1m": 21, "fwd_3m": 63, "fwd_6m": 126, "fwd_12m": 252}
K_DEFAULT = 5
MIN_GAP_DAYS = 90

QUERY_ERA = "ai"                    # 질의(현재) 시대 — 이웃 풀에서 제외
QUERY_SERIES = ERA_INDEX[QUERY_ERA]
# 아날로그 이웃 풀: AI를 제외한 모든 파생 창 보유 시대
ANALOG_ERAS = [e for e in ERA_WINDOWS if e != QUERY_ERA]
SERIES = QUERY_SERIES              # 하위호환(테스트·외부 참조) — 질의 지수

STRUCTURAL_CAVEATS = [
    "시대 간 시장 미시구조 상이 — crypto(BTC) 7일 주간은 21거래일 지평이 주식의 ~30%"
    " 짧은 달력폭; 지수 구성·유동성도 상이 (각 이웃 era 병기로 추적)",
    "상태벡터는 가격 파생 5차원만 — 밸류에이션(CAPE)·크레딧(HY)은 교차 시대 데이터"
    " 부재로 k-NN 차원 불가, 현재 레짐 컨텍스트로 별도 제공. 심리(AAII) 결측",
    "피처 간 상호 상관 미백색화(vol20↔vol60, drawdown↔dist_200dma) — 유효 차원 < 5"
    " (R-4; Mahalanobis/PCA 백색화는 이웃 집합을 실질 변경하므로 별도 검증 라운드)",
    "동일 사이클 내 이웃은 자기상관 — 90일 간격 강제로 완화하나 독립 표본 아님",
    "이웃+지평이 시대 창을 넘으면 None — 외삽 금지",
    "지수 구성종목 전면 교체(시대 내·간) — 지수 수준 생존편향 유사 왜곡 가능",
    "전방수익률 표는 **질문 매핑 확률이 아님 — 참조 base rate** (F1/F3 지평과 겹치므로"
    " 프롬프트 주입 시 준-앵커 주의, R-4)",
]


def _era_month_end_vectors(conn: sqlite3.Connection, era_id: str
                           ) -> tuple[list[str], np.ndarray]:
    """한 시대의 각 월말(마지막 거래일) 5차원 상태벡터 — 전 피처 non-NULL만."""
    series = ERA_INDEX[era_id]
    cols = ", ".join(f"d.{f}" for f in FEATURES)
    cond = " AND ".join(f"d.{f} IS NOT NULL" for f in FEATURES)
    rows = conn.execute(
        f"""SELECT d.date, {cols} FROM derived_daily d
            JOIN (SELECT MAX(date) md FROM derived_daily
                  WHERE series=? AND era_id=? GROUP BY substr(date,1,7)) me
              ON d.date = me.md
            WHERE d.series=? AND d.era_id=? AND {cond}
            ORDER BY d.date""", (series, era_id, series, era_id)).fetchall()
    dates = [r["date"] for r in rows]
    X = np.array([[r[f] for f in FEATURES] for r in rows], dtype=float)
    return dates, X


def _analog_pool_vectors(conn: sqlite3.Connection
                         ) -> tuple[list[str], list[str], np.ndarray]:
    """전 아날로그 시대의 월말 벡터 풀 — (era 라벨, 날짜, X). 데이터 없는 시대는 생략."""
    eras: list[str] = []
    dates: list[str] = []
    mats: list[np.ndarray] = []
    for era_id in ANALOG_ERAS:
        d, X = _era_month_end_vectors(conn, era_id)
        if len(d) == 0:
            continue
        eras.extend([era_id] * len(d))
        dates.extend(d)
        mats.append(X)
    X_all = np.vstack(mats) if mats else np.empty((0, len(FEATURES)))
    return eras, dates, X_all


# 하위호환 별칭 — 닷컴 단일 시대 벡터 (기존 테스트·직접 호출용)
def _dotcom_month_end_vectors(conn: sqlite3.Connection
                              ) -> tuple[list[str], np.ndarray]:
    return _era_month_end_vectors(conn, "dotcom")


def _query_latest_vector(conn: sqlite3.Connection) -> tuple[str, np.ndarray]:
    """질의(AI) 시대 최신 시점의 상태벡터 (전 피처 non-NULL인 가장 최근 행)."""
    cols = ", ".join(FEATURES)
    cond = " AND ".join(f"{f} IS NOT NULL" for f in FEATURES)
    row = conn.execute(
        f"""SELECT date, {cols} FROM derived_daily
            WHERE series=? AND era_id=? AND {cond}
            ORDER BY date DESC LIMIT 1""", (QUERY_SERIES, QUERY_ERA)).fetchone()
    if row is None:
        raise ValueError("질의(AI) 시대 완전 상태벡터 없음 — derive 후 실행")
    return row["date"], np.array([row[f] for f in FEATURES], dtype=float)


_ai_latest_vector = _query_latest_vector  # 하위호환 별칭


def _zfit(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """풀 표본만으로 z 모수 산출 (질의 데이터 제외 — 누출 방지). 상수 피처는 sd=1 가드."""
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=1)
    sd = np.where(sd > 0, sd, 1.0)
    return mu, sd


def _greedy_select(dates: list[str], dist: np.ndarray, k: int,
                   min_gap_days: int, eras: list[str] | None = None) -> list[int]:
    """거리 오름차순 greedy — 기선택 이웃과 min_gap_days 미만이면 건너뜀.

    eras가 주어지면 **같은 시대 이웃끼리만** 간격을 강제(다른 시대는 달력 겹쳐도 독립).
    eras=None이면 전부 동일 시대로 간주 — 기존 단일 시대 동작(달력 간격) 유지.
    """
    chosen: list[int] = []
    for idx in np.argsort(dist, kind="stable"):
        d = date.fromisoformat(dates[idx])
        ok = True
        for j in chosen:
            if eras is not None and eras[idx] != eras[j]:
                continue  # 다른 시대 — 간격 미적용
            if abs((d - date.fromisoformat(dates[j])).days) < min_gap_days:
                ok = False
                break
        if ok:
            chosen.append(int(idx))
        if len(chosen) == k:
            break
    return chosen


def _forward_returns(price_dates: list[str], closes: np.ndarray,
                     neighbor_date: str) -> dict[str, float | None]:
    """이웃 시점 이후 21/63/126/252 거래일 수익률 — 배열 범위 밖이면 None.

    price_dates/closes는 해당 시대 창까지로 잘려 들어와야 한다 —
    범위 초과가 곧 외삽 금지 None이 되는 구조.
    """
    i = bisect_left(price_dates, neighbor_date)
    if i >= len(price_dates) or price_dates[i] != neighbor_date:
        raise ValueError(f"price_daily에 이웃 시점 {neighbor_date} 없음 — DB 불일치")
    c0 = closes[i]
    out: dict[str, float | None] = {}
    for name, td in HORIZONS_TD.items():
        j = i + td
        out[name] = round(float(closes[j] / c0 - 1), 4) if j < len(closes) else None
    return out


def _era_prices(conn: sqlite3.Connection, era_id: str
                ) -> tuple[list[str], np.ndarray]:
    """한 시대의 지수 종가(창 내) — 전방수익률 계산용. 창 초과가 외삽 금지 None으로."""
    series = ERA_INDEX[era_id]
    w0, w1 = ERA_WINDOWS[era_id]
    w1 = w1 or date.today().isoformat()
    rows = conn.execute(
        "SELECT date, close FROM price_daily WHERE series=? AND date BETWEEN ? AND ?"
        " ORDER BY date", (series, w0, w1)).fetchall()
    return [r["date"] for r in rows], np.array([r["close"] for r in rows], dtype=float)


def _dotcom_prices(conn: sqlite3.Connection) -> tuple[list[str], np.ndarray]:
    return _era_prices(conn, "dotcom")  # 하위호환 별칭


def run(conn: sqlite3.Connection, k: int = K_DEFAULT,
        min_gap_days: int = MIN_GAP_DAYS, record: bool = True) -> dict:
    """k-NN 아날로그 실행. record=True면 model_run에 1행 기록 (twins.run과 동일 API).

    반환 dict는 render_md 입력 겸용 — run_id는 record=True일 때만 포함.
    """
    eras, pool_dates, X = _analog_pool_vectors(conn)
    if len(pool_dates) < k:
        raise ValueError(f"아날로그 월말 표본 {len(pool_dates)}개 < k={k} — derive 후 실행")
    asof, v = _query_latest_vector(conn)

    mu, sd = _zfit(X)                      # 풀(과거 시대)만 — 누출 방지
    Z = (X - mu) / sd
    z = (v - mu) / sd
    dist = np.sqrt(((Z - z) ** 2).sum(axis=1))
    chosen = _greedy_select(pool_dates, dist, k, min_gap_days, eras=eras)

    price_cache: dict[str, tuple[list[str], np.ndarray]] = {}
    neighbors = []
    for idx in chosen:
        e = eras[idx]
        if e not in price_cache:
            price_cache[e] = _era_prices(conn, e)
        pds, cls = price_cache[e]
        rec: dict = {"era": e, "date": pool_dates[idx],
                     "distance": round(float(dist[idx]), 4)}
        rec.update(_forward_returns(pds, cls, pool_dates[idx]))
        neighbors.append(rec)

    # 각 지평의 중앙값에 유효 표본수 n 병기 — None(외삽 금지) 제외 후 남는 표본
    median_fwd: dict[str, dict] = {}
    for h in HORIZONS_TD:
        vals = [n[h] for n in neighbors if n[h] is not None]
        median_fwd[h] = {
            "median": round(float(np.median(vals)), 4) if vals else None,
            "n": len(vals),
        }

    pool_eras = sorted(set(eras))
    n_eras = len(pool_eras)
    sel_eras = sorted(set(n["era"] for n in neighbors))
    caveats = [
        (f"표본 n={n_eras} 사이클(다중 아날로그: {', '.join(pool_eras)}) — n=1(닷컴)에서"
         " 확장, 그러나 사이클당 관측 소수로 검정력 제한, 확률 아님 참조"
         if n_eras > 1 else
         "표본 n=1 사이클(닷컴) — 통계적 검정력 없음, base rate 참조용 참고 의견"),
        *STRUCTURAL_CAVEATS,
    ]
    result = {
        "asof": asof,
        "n_pool_samples": len(pool_dates),
        "n_eras": n_eras,
        "pool_eras": pool_eras,
        "selected_eras": sel_eras,
        "feature_vector": {
            "raw": {f: round(float(v[i]), 6) for i, f in enumerate(FEATURES)},
            "z": {f: round(float(z[i]), 3) for i, f in enumerate(FEATURES)},
        },
        "neighbors": neighbors,
        "median_fwd": median_fwd,
        "caveats": caveats,
    }
    if len(chosen) < k:
        result["warning"] = (
            f"이웃 {len(chosen)}/{k}개만 선택 — min_gap_days={min_gap_days} 간격 "
            "제약으로 k 미달 (중앙값 표본 축소, 해석 주의)")
    params = {
        "k": k, "min_gap_days": min_gap_days, "query_series": QUERY_SERIES,
        "analog_eras": ANALOG_ERAS, "pool_eras": pool_eras,
        "features": list(FEATURES), "horizons_trading_days": HORIZONS_TD,
        "standardize": "pool-only z (과거 시대만 — 누출 방지)",
        "z_mu": [round(float(x), 6) for x in mu],
        "z_sd": [round(float(x), 6) for x in sd],
    }
    if record:
        cur = conn.execute(
            "INSERT INTO model_run (model, asof, params_json, output_json, created_at)"
            " VALUES (?,?,?,?,?)",
            ("knn_analog", asof, json.dumps(params, ensure_ascii=False),
             json.dumps(result, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        result["run_id"] = cur.lastrowid
    return result


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:+.1%}"


def render_md(result: dict) -> str:
    """run() 결과 dict → 마크다운 (한계 고지 포함 — 없으면 출력 무효)."""
    fv = result["feature_vector"]
    pool = ", ".join(result.get("pool_eras", []))
    n_pool = result.get("n_pool_samples", result.get("n_dotcom_samples", 0))
    lines = [
        f"# k-NN 아날로그 (Q15) — asof {result['asof']}",
        f"> 참고 의견 (P3 게이트 전) · 표본 n={result.get('n_eras', 1)} 사이클"
        f"({pool}) — 확률 아님, 아날로그 참조",
        "",
        f"## 현재 상태벡터 (^IXIC AI 시대, 아날로그 풀 월말 {n_pool}개 기준 z)",
        "| feature | raw | z |",
        "|---|---|---|",
    ]
    for f in FEATURES:
        lines.append(f"| {f} | {fv['raw'][f]:.4f} | {fv['z'][f]:+.2f} |")
    k = len(result["neighbors"])
    lines += [
        "",
        f"## 최근접 아날로그 이웃 k={k} (유클리드, 동일 시대 내 90일+ 간격)",
        "| # | 시대 | 시점 | 거리 | +1m | +3m | +6m | +12m |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, n in enumerate(result["neighbors"], 1):
        lines.append(
            f"| {i} | {n.get('era', '—')} | {n['date']} | {n['distance']:.3f} |"
            f" {_pct(n['fwd_1m'])} | {_pct(n['fwd_3m'])} |"
            f" {_pct(n['fwd_6m'])} | {_pct(n['fwd_12m'])} |")
    m = result["median_fwd"]
    lines.append(
        "| **중앙값 (n)** | | | | "
        + " | ".join(f"**{_pct(m[h]['median'])}** (n={m[h]['n']})"
                     for h in ("fwd_1m", "fwd_3m", "fwd_6m", "fwd_12m"))
        + " |")
    if result.get("warning"):
        lines += ["", f"> ⚠ {result['warning']}"]
    lines += ["", "## 한계 (정직성 고지)"]
    lines += [f"- {c}" for c in result["caveats"]]
    return "\n".join(lines) + "\n"
