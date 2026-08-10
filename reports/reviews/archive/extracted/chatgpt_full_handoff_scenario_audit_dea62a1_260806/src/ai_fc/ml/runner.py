"""ml 실행기 — 오픈웨이트 추론 → 질문 매핑 확률 → 이력 기록(JSONL+DB) + base_rates 렌더.

핵심 산출: 오픈웨이트 모델의 분포를 시스템 등록 질문(mapping.QUESTION_MAPS)의
임계값에 매핑해, LLM 추론(rN 확률)과 나란히 비교 가능한 참조 확률을 만든다.
괴리 15%p+는 due의 divergence 표시로 이어진다 (표시만 — 자동 재예측 없음).

모델 결합은 고정 규칙(중앙값)만 사용한다 — ML 게이트(가중 학습 금지) 준수.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

import numpy as np

from .. import config
from ..quant import feed, mc
from . import chronos_fc, sentiment
from .history import append_run
from .mapping import QUESTION_MAPS, QuestionMap

T5_NUM_SAMPLES = 256  # CPU 실측 후 하향(128) 가능


def weekly_closes(symbol: str, start: date, end: date) -> list[float]:
    _, closes = feed.yahoo_series(symbol, start, end, "1wk")
    return closes


def _window_steps(asof: date, window: tuple[str, str] | None,
                  horizon: int) -> tuple[int, int] | None:
    """판정 윈도우(ISO 날짜쌍) → 주간 스텝 인덱스 폐구간. 전체 지평이면 None."""
    if window is None:
        return None
    ws = date.fromisoformat(window[0])
    we = date.fromisoformat(window[1])
    s0 = max(0, (ws - asof).days // 7)
    s1 = min(horizon - 1, -(-(we - asof).days // 7))  # ceil
    return (s0, s1)


def _window_steps_daily(asof: date, window: tuple[str, str] | None,
                        horizon_days: int | None) -> tuple[int, int] | None:
    """판정 윈도우 → 일간(거래일) 스텝 인덱스 폐구간 (WS3 GBM 일간화 — ±1일 근사)."""
    if window is None or horizon_days is None:
        return None
    ws = date.fromisoformat(window[0])
    we = date.fromisoformat(window[1])
    s0 = max(0, int(np.busday_count(asof, ws)))
    s1 = min(horizon_days - 1, int(np.busday_count(asof, we)))
    if s0 > s1:
        return (0, 0)
    return (s0, s1)


def _model_probs(qm: QuestionMap, fcs: dict[str, chronos_fc.QuantileForecast],
                 combined: chronos_fc.QuantileForecast,
                 paths: dict[str, "object"], asof: date) -> tuple[dict[str, float], dict]:
    """질문 1개의 모델별 확률.

    종점 질문: 분위수 모델(bolt·c2) 각각 + GBM 종점.
    경로 질문: T5 샘플·GBM 배리어 터치(정공법) — 분위수 종점 확률(중앙값 결합)은
    하한 참고치로 detail에만 남긴다.
    """
    detail: dict = {}
    gbm = paths.get("gbm")
    t5 = paths.get("t5")

    if qm.mode in ("above_terminal", "below_terminal"):
        above = qm.mode == "above_terminal"
        models = {name: (p if above else 1.0 - p)
                  for name, fc in fcs.items()
                  for p in [fc.prob_above(qm.threshold)]}
        if gbm is not None:
            p_gbm = float((gbm[:, -1] >= qm.threshold).mean())
            models["gbm"] = p_gbm if above else 1.0 - p_gbm
        return models, detail

    # 경로 질문 — 배리어 터치 확률. WS3(T-11 상환): 공식 참조값은 보정값
    # (t5 = 브라운 브리지, gbm = 일간 스텝), 주간 raw는 detail에 병기.
    direction = "above" if qm.mode == "above_path" else "below"
    step_range = _window_steps(asof, qm.window, combined.horizon)
    p_term = combined.prob_above(qm.threshold)
    detail["quantile_terminal_bound"] = round(
        p_term if direction == "above" else 1.0 - p_term, 4)
    if step_range is not None:
        detail["window_steps"] = list(step_range)
    models: dict[str, float] = {}
    raw: dict[str, float] = {}
    if t5 is not None:
        raw["t5"] = mc.barrier_prob(t5, qm.threshold, direction, step_range)
        models["t5"] = chronos_fc.bridge_touch_prob(
            t5, qm.threshold, direction, step_range)
    gbm_daily = paths.get("gbm_daily")
    horizon_days = paths.get("horizon_days")
    if gbm_daily is not None:
        daily_range = _window_steps_daily(asof, qm.window, horizon_days)
        models["gbm"] = mc.barrier_prob(gbm_daily, qm.threshold, direction, daily_range)
        if gbm is not None:
            raw["gbm"] = mc.barrier_prob(gbm, qm.threshold, direction, step_range)
    elif gbm is not None:  # 일간 데이터 실패 시 주간 폴백 (fail-soft — raw 그대로)
        models["gbm"] = mc.barrier_prob(gbm, qm.threshold, direction, step_range)
        detail["gbm_fallback_weekly"] = True
    if raw:
        detail["raw_weekly"] = {k: round(v, 4) for k, v in raw.items()}
        detail["correction"] = {"t5": "brown-bridge(log, sigma_w 경로 내 추정)",
                                "gbm": "daily-steps"}
    if not models:  # 경로 모델 부재 시 하한으로 폴백 (정직 고지 유지)
        detail["terminal_bound"] = "lower"
        models = {"quantile": detail["quantile_terminal_bound"]}
    return models, detail


def _question_probs(series_models: dict[str, dict[str, chronos_fc.QuantileForecast]],
                    series_combined: dict[str, chronos_fc.QuantileForecast],
                    paths_by_series: dict[str, dict], asof: date) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for qm in QUESTION_MAPS:
        combined = series_combined.get(qm.series_key)
        if combined is None:
            continue
        models, detail = _model_probs(
            qm, series_models[qm.series_key], combined,
            paths_by_series.get(qm.series_key, {}), asof)
        ens = float(median(list(models.values())))
        spread = chronos_fc.disagreement(models)
        detail["disagreement"] = round(spread, 4)
        if spread > config.ML_DISAGREEMENT_PP / 100:
            detail["low_confidence"] = True  # divergence 트리거에서 제외 (고정 규칙)
        out[qm.question_id] = {
            "label": qm.label, "threshold": qm.threshold, "mode": qm.mode,
            "horizon_weeks": combined.horizon, "models": models, "ensemble": ens,
            "detail": detail,
        }
    return out


def run_all() -> tuple[dict, str]:
    """추론만 수행 (파일·DB 무접촉). (results, md) 반환."""
    today = date.today()
    start = date(2023, 1, 1)
    horizon = max(4, min(60, (date(today.year, 12, 31) - today).days // 7))

    closes = {
        "q_ixic": weekly_closes("^IXIC", start, today),
        "q_soxx": weekly_closes("SOXX", start, today),
        "q_vix": weekly_closes("^VIX", start, today),
    }
    horizons = {"q_ixic": horizon, "q_soxx": horizon, "q_vix": min(horizon, 13)}
    symbols = {"q_ixic": "^IXIC", "q_soxx": "SOXX", "q_vix": "^VIX"}

    # 공변량: 같은 Yahoo 주간 그리드의 ^TNX(10y 금리)·^VIX — 정렬 문제 원천 제거.
    # past-only (미래 공변량 없음 — 미래 값을 아는 척하지 않는다).
    tnx = weekly_closes("^TNX", start, today)
    covariates = {"q_ixic": {"vix": closes["q_vix"], "tnx": tnx},
                  "q_soxx": {"vix": closes["q_vix"], "tnx": tnx},
                  "q_vix": None}

    series_models: dict[str, dict[str, chronos_fc.QuantileForecast]] = {}
    c2_error: str | None = None
    for k in closes:
        models = {"bolt": chronos_fc.forecast_quantiles(symbols[k], closes[k], horizons[k])}
        try:
            models["c2"] = chronos_fc.forecast_quantiles_c2(
                symbols[k], closes[k], horizons[k], past_covariates=covariates[k])
        except Exception as exc:  # noqa: BLE001 — c2 실패 시 bolt 단독으로 계속 (fail-soft)
            c2_error = f"{type(exc).__name__}: {exc}"[:200]
        series_models[k] = models
    series_combined = {k: chronos_fc.combine_median(list(m.values()))
                       for k, m in series_models.items()}

    # 경로 확률용 샘플 경로: GBM은 전 시리즈(저비용), T5는 경로 질문 있는 시리즈만(CPU 수 분).
    # WS3: 경로 시리즈는 GBM을 일간 스텝으로 추가 생성 (주간 이산 과소추정 T-11의 근본 해결).
    path_series = {qm.series_key for qm in QUESTION_MAPS if qm.mode.endswith("_path")}
    paths_by_series: dict[str, dict] = {}
    for k in closes:
        p: dict = {"gbm": mc.gbm_paths(closes[k], lookback=52, horizon=horizons[k])}
        if k in path_series:
            p["t5"] = chronos_fc.sample_paths(closes[k], horizons[k],
                                              num_samples=T5_NUM_SAMPLES)
            try:
                end_date = today + timedelta(weeks=horizons[k])
                horizon_days = max(5, int(np.busday_count(today, end_date)))
                _, dclose = feed.yahoo_series(symbols[k], date(2024, 1, 1), today, "1d")
                if len(dclose) >= 260:
                    p["gbm_daily"] = mc.gbm_paths(dclose, lookback=252,
                                                  horizon=horizon_days)
                    p["horizon_days"] = horizon_days
            except Exception:  # noqa: BLE001 — 일간 수집 실패 시 주간 폴백 (fail-soft)
                pass
        paths_by_series[k] = p

    feeds = sentiment.run_all_feeds()
    overall = (sum(f.score * f.n_headlines for f in feeds)
               / max(sum(f.n_headlines for f in feeds), 1))

    # 시리즈 밴드 요약 — base_rates 다이제스트(프롬프트 주입)의 원재료.
    # 질문별 매핑 확률은 넣지 않는다 (앵커링 방지 — base_rates.py 참조)
    series_bands: dict[str, dict] = {}
    for k, fc in series_combined.items():
        rets = np.diff(np.log(np.asarray(closes[k][-53:], dtype=float)))
        series_bands[k] = {
            "symbol": symbols[k], "horizon_weeks": horizons[k],
            "last_value": fc.last_value,
            "terminal": {q: fc.terminal(q) for q in ("q10", "q25", "q50", "q75", "q90")},
            "median_pct": fc.terminal_pct("q50"),
            "gbm": {"mu_w": float(rets.mean()), "sigma_w": float(rets.std(ddof=1))},
        }

    results = {
        "asof": today.isoformat(), "horizon_weeks": horizon,
        "series": series_combined, "series_models": series_models,
        "series_bands": series_bands, "c2_error": c2_error,
        "question_probs": _question_probs(series_models, series_combined,
                                          paths_by_series, today),
        "feeds": feeds, "sentiment_overall": overall,
    }
    return results, render_md(results)


def run_and_record(root: Path, conn: sqlite3.Connection) -> tuple[dict, str]:
    """추론 → data/ml_history JSONL append → DB sync → md 반환."""
    from ..db import ingest

    results, md = run_all()
    run_ts = datetime.now().isoformat(timespec="seconds")

    forecasts = []
    for qid, qp in results["question_probs"].items():
        kind = "path_touch" if qp["mode"].endswith("_path") else "terminal"
        for model, prob in qp["models"].items():
            forecasts.append({"question_id": qid, "model": model, "kind": kind,
                              "prob": round(prob, 4), "threshold": qp["threshold"],
                              "horizon_weeks": qp["horizon_weeks"], "detail": qp["detail"]})
        forecasts.append({"question_id": qid, "model": "ensemble", "kind": kind,
                          "prob": round(qp["ensemble"], 4), "threshold": qp["threshold"],
                          "horizon_weeks": qp["horizon_weeks"], "detail": qp["detail"]})

    append_run(root, {
        "run_ts": run_ts, "kind": "ml",
        "forecasts": forecasts,
        "sentiment": [{"feed": f.feed, "n_headlines": f.n_headlines,
                       "score": round(f.score, 4)} for f in results["feeds"]],
        "series_bands": results["series_bands"],
        "sentiment_overall": round(results["sentiment_overall"], 4),
    })
    ingest.sync(conn, root)

    # 감성 Δ7d는 DB 이력이 있어야 계산 가능 — sync 후 붙여서 재렌더
    from ..db import queries
    results["sentiment_deltas"] = {
        f.feed: queries.sentiment_delta(conn, f.feed) for f in results["feeds"]}
    return results, render_md(results)


def _mapping_rows(x: dict) -> str:
    rows = []
    for qp in x["question_probs"].values():
        models = " · ".join(f"{m} {p:.0%}" for m, p in qp["models"].items())
        d = qp["detail"]
        if d.get("terminal_bound"):
            note = " (경로 터치의 하한 — 종점 근사)"
        elif d.get("raw_weekly"):
            raws = " · ".join(f"{m} {v:.0%}" for m, v in d["raw_weekly"].items())
            note = (f" (보정값 — raw 주간: {raws} · 보정: t5 브리지·gbm 일간, "
                    f"분위수 종점 {d['quantile_terminal_bound']:.0%}는 하한)")
        elif "quantile_terminal_bound" in d:
            note = f" (경로 터치 정공법 · 분위수 종점 {d['quantile_terminal_bound']:.0%}는 하한)"
        else:
            note = ""
        lc = " ⚠불일치" if d.get("low_confidence") else ""
        rows.append(f"| {qp['label']} | {qp['threshold']:,.2f} | "
                    f"**{qp['ensemble']:.0%}**{lc} | {models}{note} |")
    return "\n".join(rows)


def _c2_line(x: dict) -> str:
    if x.get("c2_error"):
        return f"- ⚠ Chronos-2 로드 실패 — Bolt 단독 실행: `{x['c2_error']}`"
    covs = "^IXIC·SOXX에 past-only 공변량(VIX·TNX) 적용"
    return f"- Chronos-2(120M) 공변량 조건부 + Bolt 결합 — {covs}, 미래 공변량 미사용"


def render_md(x: dict) -> str:
    qi: chronos_fc.QuantileForecast = x["series"]["q_ixic"]
    qs: chronos_fc.QuantileForecast = x["series"]["q_soxx"]
    qv: chronos_fc.QuantileForecast = x["series"]["q_vix"]
    feeds: list[sentiment.FeedSentiment] = x["feeds"]

    deltas = x.get("sentiment_deltas", {})

    def _delta(feed: str) -> str:
        d = deltas.get(feed)
        return f"{d:+.3f}" if d is not None else "—"

    feed_rows = "\n".join(
        f"| {f.feed} | {f.n_headlines} | {f.score:+.3f} | {_delta(f.feed)} |" for f in feeds)
    negs = [t for f in feeds for t in f.top_negative][:4]
    neg_block = "\n".join(f"- {t}" for t in negs) or "- (강한 부정 헤드라인 없음)"

    def band(fc: chronos_fc.QuantileForecast) -> str:
        return (f"중앙값 {fc.terminal('q50'):,.0f} ({fc.terminal_pct('q50'):+.1%}) · "
                f"50% 밴드 [{fc.terminal('q25'):,.0f}, {fc.terminal('q75'):,.0f}] · "
                f"80% 밴드 [{fc.terminal('q10'):,.0f}, {fc.terminal('q90'):,.0f}]")

    return f"""# Base Rates — 오픈웨이트 ML 자동 산출 (추론 전용, 재생성 가능)

> `python -m ai_fc ml` — Chronos(시계열)·FinBERT(감성), 전부 로컬 CPU 추론.
> 생성: {x["asof"]} · 예측 지평 {x["horizon_weeks"]}주(연말) · **학습 없음 — ML 게이트 준수**.
> 모델 결합은 고정 중앙값 (가중 학습 아님 — **모델 2개 구간에서는 평균과 동일**하며
> 중앙값의 이상치 방어는 3개 이상부터 유효, AUDIT-260715 D-8). zero-shot 분포는
> 이벤트 캘린더를 모르는 무조건부 추정 — 참조선일 뿐.

## Chronos 연말 분위수 예측 — Bolt·Chronos-2 중앙값 결합 (컨텍스트 {qi.context_len}주)
- **^IXIC**: {band(qi)}
- **SOXX**: {band(qs)}
- **^VIX** (13주 지평): {band(qv)}
{_c2_line(x)}

## 시스템 질문 임계값 매핑 (오픈웨이트 vs LLM 추론 비교용)
| 질문 | 임계값 | 앙상블 | 모델별 |
|---|---|---|---|
{_mapping_rows(x)}

- 사용법: 앙상블 참조 확률과 시스템 rN 확률의 괴리 {config.ML_DIVERGENCE_PP}%p+ 는
  `due`에 divergence로 표시된다 (재예측 후보 — 자동 실행 없음, 판단은 사람).

## FinBERT 헤드라인 감성 (Google News RSS, 무료)
| 피드 | 헤드라인 수 | 감성 지수 [-1,+1] | Δ7d |
|---|---|---|---|
{feed_rows}
- **종합**: {x["sentiment_overall"]:+.3f} (0 = 중립)
- 최근 부정 헤드라인 샘플:
{neg_block}

## 한계 (정직 고지)
- Chronos는 계절성·자기상관만 학습한 무조건부 모델 — FOMC·미드텀 같은 이벤트 구조를 모름.
  시나리오 분석(v4·주간 차트)의 이벤트 조건부 경로와 '보완' 관계이지 대체가 아님.
- 경로 터치 확률은 보정값 기준 (T-11 상환, v2 WS3): GBM은 일간 스텝 재추정(근본 해결),
  T5는 주간 경로에 브라운 브리지 보정 — p=exp(−2·d0·d1/σ_w²), σ_w는 경로 내 추정 근사.
  raw 주간값 병기 (추적성). divergence 판정도 보정값 기준 (DECISIONS 기록).
  GBM(모수·정규수익률)과 T5(비모수·경험분포)는 추정 대상 분포의 정의가 달라
  결합값은 이질 모델 평균임.
- VIX에 대한 GBM은 평균회귀 특성을 무시한 참조치 — T5 경로와 병기해 상호 점검.
- FinBERT 감성은 동행~후행 지표 — 방향 예측이 아니라 현재 분위기의 정량화.
- 본 파일은 자동 생성본. 어떤 가중치도 갱신되지 않았음 (추론 전용).
  이력 원본: data/ml_history/*.jsonl (append-only).
"""


def write_base_rates(root: Path, md: str) -> Path:
    out = root / "data" / "base_rates" / "ml_auto.md"
    out.write_text(md, encoding="utf-8")
    return out
