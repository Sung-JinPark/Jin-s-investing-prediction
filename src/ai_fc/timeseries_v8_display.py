"""Fail-closed dashboard projection for the V8 shadow timeseries surface.

This module lives outside ``src/ai_fc/timeseries_v8/`` on purpose: that
package is part of the sealed ``model_code_hash`` dependency set, so display
wiring placed there would silently change the recorded identity of the sealed
model.  Display code may read the sealed artifacts; it may never move them.

The projection is the display-promotion step the latest-pointer publisher
defers to: numbers appear only while the disclosed sealed gate AND the
operational freshness gate both hold, quantiles map from cumulative log
returns to index levels per the contract's ``display_price_unit: index``,
and every payload keeps its 참고 의견 (research reference) status.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from .timeseries_v8.contracts import MODEL_ID, MODEL_VERSION, canonical_hash

LATEST_RELATIVE = Path("data/timeseries_v8/multivariate_v8_latest.json")
# 매일 갱신 표시 포인터(사용자 결정 2026-10-07) — 표시 전용, 채점·성적은 주간 원장이 맡는다.
DAILY_LATEST_RELATIVE = Path("data/timeseries_v8/daily_display_latest.json")
SEALED_LEDGER_RELATIVE = Path("data/timeseries_v8/ledgers/sealed_evaluations.jsonl")
FORWARD_LEDGER_RELATIVE = Path("data/timeseries_v8/ledgers/shadow_resolutions.jsonl")
# 섀도 진행률(표시 전용): 승격 계약의 단위는 '세션'이라 첫 섀도 원점 **다음** XNYS 세션부터
# NYSE 휴장 계약(data/contracts/nyse_holidays.yaml)으로 결정론적으로 센다. 첫 h63 성숙 =
# 첫 원점 + 63 세션. 계약이 요구 세션 수를 말하지 않으면 진행률도 싣지 않는다(지어내지 않는다).
SHADOW_MATURITY_SESSIONS = 63
# 실측 순위 칸 = 이미 공개된 5개 절단점이 수직선을 6칸으로 나눈 것.
# 완전 보정 시 기대 비율은 10/15/25/25/15/10% (JS 상수와 같은 순서).
RANK_CUTS = ("p10", "p25", "median", "p75", "p90")
# 게이트 사유 문자열이 참조하는 고정 국면 순서 — 정렬로 뒤바뀌면 안 된다.
REGIME_ORDER = ("great_financial_crisis_2008", "pandemic_2020", "tightening_2022")
PROBABILITY_SPACE = "research_timeseries_v8_conditional"
TARGET_SERIES = "NASDAQCOM"
HORIZONS = ("1", "5", "21", "63")
QUANTILES = ("p10", "p25", "p50", "p75", "p90")

# ── 표시 공시 상수 (2026-11-11 정합성 감사 P5 — 숫자 불변, 라벨·접기만) ─────────────
# 상수 파일은 data/timeseries_v8/ 밖에 둔다 — V8 해시 범위를 모호하게 만들지 않기 위해서다.
DISPLAY_CONSTANTS_RELATIVE = Path("data/mts_research/contracts/v8_display_constants_v1.json")
SHADOW_FORECAST_LEDGER_RELATIVE = Path("data/timeseries_v8/ledgers/shadow_forecasts.jsonl")
DISCLOSURE_NOTICE = "참고 의견, 매매 신호 아님"
# V8 grid = 5계열 관측일 교집합(dropna). 표시층은 이 교집합과 XNAS 달력의 차로 휴장 라벨을 센다.
GRID_SERIES = ("NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXBGS")
CARRY_SERIES = "DTWEXBGS"
# '사전(prospective)' 지위는 발행 시점에 목표 세션이 대부분 남아 있는 지평에만 붙인다.
PROSPECTIVE_HORIZONS = ("21", "63")
BASE_RATE_HORIZONS = ("21", "63")
ENGINE_HORIZONS = ("1", "5")
# 주간 해소 실행 시각 — .github/workflows/timeseries-v8-shadow.yml 의 cron(UTC) 원문. 테스트가 대조한다.
RESOLVER_CRON_UTC = "10 3 * * 2-6"
HOLD_KIND_LABELS = {
    "calendar_hold": "달력 hold(동결 48h 규칙·주말/휴일)",
    "source_delay": "원천 지연",
}
FRESHNESS_REASON_PREFIX = "필수 시장 입력 신선도 초과:"


class TimeSeriesV8DisplayError(ValueError):
    """The V8 latest pointer or its display preconditions failed closed."""


def validate_latest(value: dict[str, Any]) -> None:
    if value.get("model_id") != MODEL_ID:
        raise TimeSeriesV8DisplayError("V8 model id mismatch")
    if value.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV8DisplayError("V8 model version mismatch")
    if value.get("probability_space") != PROBABILITY_SPACE:
        raise TimeSeriesV8DisplayError("V8 probability space mismatch")
    if value.get("probability_unit") != "fraction":
        raise TimeSeriesV8DisplayError("V8 probability unit mismatch")
    body = dict(value)
    expected = body.pop("content_hash", None)
    if expected != canonical_hash(body):
        raise TimeSeriesV8DisplayError("V8 latest content hash mismatch")
    gate = value.get("gate") or {}
    publication = value.get("publication") or {}
    visible = publication.get("customer_numbers_visible") is True
    gates_pass = (
        gate.get("sealed_gate_pass") is True and gate.get("operational_pass") is True
    )
    if visible is not gates_pass:
        raise TimeSeriesV8DisplayError("V8 visibility must equal both gate decisions")
    if visible is not (value.get("status") == "shadow_live"):
        raise TimeSeriesV8DisplayError("V8 visibility/status mismatch")
    if publication.get("reference_opinion_only") is not True:
        raise TimeSeriesV8DisplayError("V8 must keep reference-opinion-only status")
    if (publication.get("combined_with_official_forecasts") is not False
            or publication.get("combined_with_scenario_v5_2") is not False):
        raise TimeSeriesV8DisplayError("V8 must remain isolated from other surfaces")
    if not visible:
        if value.get("horizons") or value.get("path"):
            raise TimeSeriesV8DisplayError("V8 HOLD surface must hide numerical forecasts")
        return
    horizons = value.get("horizons") or {}
    if set(horizons) != set(HORIZONS):
        raise TimeSeriesV8DisplayError("V8 visible horizon set incomplete")
    for row in horizons.values():
        probability = float(row["probability_up"])
        if not 0.0 <= probability <= 1.0:
            raise TimeSeriesV8DisplayError("V8 probability outside fraction bounds")
        ordered = [float(row[key]) for key in QUANTILES]
        if ordered != sorted(ordered):
            raise TimeSeriesV8DisplayError("V8 quantile crossing")


def _num(value: Any, digits: int = 6) -> float | None:
    """원장 값을 표시 정밀도로만 반올림한다 (없으면 None을 그대로 보존)."""
    if value is None:
        return None
    number = float(value)
    return None if not math.isfinite(number) else round(number, digits)


def _horizon_metrics(block: dict[str, Any], *, with_dm: bool) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for key in HORIZONS:
        row = (block.get("horizons") or {}).get(key)
        if not isinstance(row, dict):
            continue
        entry = {
            "crps_improvement_vs_best": _num(row.get("crps_improvement_vs_best")),
            "coverage_p10_p90": _num(row.get("coverage_p10_p90")),
            "coverage_p25_p75": _num(row.get("coverage_p25_p75")),
            "origins": int(row.get("origins") or 0),
        }
        if with_dm:
            # 비교 기준선은 기간마다 다를 수 있다(봉인창 5거래일은 block_bootstrap).
            entry["best_baseline"] = str(row.get("best_baseline") or "")
            entry["dm_p_value"] = _num((row.get("diebold_mariano") or {}).get("p_value"))
            # 절대 CRPS(모델·최선 기준선) — 공개된 개선율의 분자·분모 그대로다. 로그수익률
            # 단위라 '평균 오차 %p'로 읽힌다(점예측이면 CRPS=MAE). 새 지표 파생이 아니다.
            entry["crps"] = _num(row.get("crps"), 8)
            entry["best_baseline_crps"] = _num(row.get("best_baseline_crps"), 8)
        rows[key] = entry
    return rows


def _rank_bins(scores: list[dict[str, Any]], window_start: str) -> dict[str, Any]:
    """실측값이 다섯 절단점이 만든 여섯 칸 중 어디에 떨어졌는지 센다.

    새 확률을 만들지 않는다 — 이미 공개된 per-origin 점수와 이미 공개된 분위수
    절단점을 결정론적으로 다시 세는 것뿐이며, 가운데 네 칸의 합은 정의상 공표
    적중률(coverage_p10_p90)과 같은 값이 된다.
    """
    bins: dict[str, Any] = {}
    for key in HORIZONS:
        counts = [0] * 6
        total = 0
        for row in scores:
            if str(row.get("horizon")) != key or str(row.get("date", "")) < window_start:
                continue
            actual = row.get("actual_log_return")
            if actual is None:
                continue
            cuts = [row.get(name) for name in RANK_CUTS]
            if any(cut is None for cut in cuts):
                continue
            counts[sum(1 for cut in cuts if float(actual) >= float(cut))] += 1
            total += 1
        if total:
            bins[key] = {"counts": counts, "n": total}
    return bins


def _forward_block(latest: dict[str, Any], resolutions: list[dict[str, Any]]) -> dict[str, Any]:
    """배포 후 전진(라이브) 실적 — 성숙 원점이 0이면 0이라고 말한다.

    확정 행이 있으면 그 결과(기준선 대비·구간 포함·방향)도 그대로 센다. 성숙 원점
    0을 근거로 확정 행의 존재 자체를 부정하면 부정적 증거가 축소된다(검수 2차).
    """
    monitoring = (latest.get("operational") or {}).get("monitoring") or {}
    origins = sorted({str(row.get("origin")) for row in resolutions if row.get("origin")})
    forecasts = sorted({str(row.get("forecast_id")) for row in resolutions if row.get("forecast_id")})
    better = sum(
        1 for row in resolutions
        if row.get("model_crps") is not None and row.get("baseline_crps") is not None
        and float(row["model_crps"]) < float(row["baseline_crps"])
    )
    direction_rows = [row for row in resolutions if row.get("direction_correct") is not None]
    sessions = sorted(str(row.get("resolved_session")) for row in resolutions if row.get("resolved_session"))
    return {
        "matured_origins": int(monitoring.get("matured_shadow_origins") or 0),
        "source": str(monitoring.get("source") or ""),
        "resolved_rows": len(resolutions),
        "unique_forecasts": len(forecasts),
        "model_better_rows": better,
        "covered_p10_p90_rows": sum(1 for row in resolutions if row.get("covered_p10_p90") is True),
        "direction_rows": len(direction_rows),
        "direction_correct_rows": sum(1 for row in direction_rows if bool(row["direction_correct"])),
        # 라이브 기준선은 예측 시점에 저장한 historical_simulation 분위수 그리드 하나로
        # 고정된다(timeseries_v8/backtest.py의 baseline_quantile_grid → pipeline.py 해소).
        # 봉인 성적표의 '기간별 최선 기준선'과 다르므로 이름을 함께 싣는다.
        "baseline": "historical_simulation",
        "origins": origins,
        "last_resolved_session": sessions[-1] if sessions else None,
        # 확정 행별 오차 대조(승패 타일용) — 라이브 원장에 이미 있는 값만 옮긴다.
        "rows": [
            {
                "origin": str(row.get("origin") or ""),
                "horizon": str(row.get("horizon") or ""),
                "model_crps": _num(row.get("model_crps"), 8),
                "baseline_crps": _num(row.get("baseline_crps"), 8),
                "covered_p10_p90": row.get("covered_p10_p90") is True,
            }
            for row in sorted(
                resolutions,
                key=lambda row: (str(row.get("origin") or ""), int(row.get("horizon") or 0)),
            )
            if row.get("model_crps") is not None and row.get("baseline_crps") is not None
        ],
    }


def _sealed_disclosure(
    sealed_row: dict[str, Any], summary: dict[str, Any],
    latest: dict[str, Any], resolutions: list[dict[str, Any]],
) -> dict[str, Any]:
    """R8-D4 승인 범위: 이미 1회 실시된 봉인 평가의 요약값을 더 투영한다.

    봉인창(2019+)이 이 표면의 out-of-sample 기준선이고, 전체창(2007~)은
    개발기간을 포함하므로 반드시 그 사실과 함께만 실린다. 새 필드가 하나라도
    비면 그 블록만 빠지고 기존 표면은 그대로 뜬다 — 사이트 빌드를 세우지 않는다.
    """
    disclosure: dict[str, Any] = {}
    sealed = sealed_row.get("sealed_summary") or {}
    window = [str(value) for value in (sealed_row.get("sealed_window") or [])]
    development = [str(value) for value in (sealed_row.get("development_window") or [])]
    scores = sealed_row.get("scores") or []
    sealed_horizons = _horizon_metrics(sealed, with_dm=True)
    if sealed_horizons and window:
        dates = sorted(
            str(row.get("date")) for row in scores
            if str(row.get("horizon")) == "21" and str(row.get("date", "")) >= window[0]
        )
        disclosure["sealed_window"] = {
            "window": window,
            "origin_count": int(sealed.get("origin_count") or 0),
            "status": str(sealed.get("status") or ""),
            "gate_pass": bool(sealed.get("gate_pass")),
            # 게이트 사유는 원장 문자열 원문 — 번역·요약하지 않는다.
            "reasons": [str(reason) for reason in (sealed.get("reasons") or [])],
            "first_origin": dates[0] if dates else None,
            "last_origin": dates[-1] if dates else None,
            "horizons": sealed_horizons,
        }
    full_horizons = _horizon_metrics(summary, with_dm=False)
    if full_horizons:
        all_dates = sorted(str(row.get("date")) for row in scores if row.get("date"))
        disclosure["full_backtest"] = {
            "origin_count": int(summary.get("origin_count") or 0),
            "window": [all_dates[0], all_dates[-1]] if all_dates else [],
            "development_window": development,
            "includes_development_window": True,
            "status": str(summary.get("status") or ""),
            "gate_pass": bool(summary.get("gate_pass")),
            "horizons": full_horizons,
        }
    regimes = sealed.get("regime_coverage") or {}
    if regimes:
        disclosure["regimes"] = [
            {
                "key": key,
                # 봉인창에 원점이 없는 국면은 0이 아니라 '자료 없음'이다.
                "coverage_p10_p90": _num((regimes.get(key) or {}).get("coverage_p10_p90")),
                "origins": int((regimes.get(key) or {}).get("origins") or 0),
            }
            for key in REGIME_ORDER if key in regimes
        ]
    if window and scores:
        rank_bins = _rank_bins(scores, window[0])
        if rank_bins:
            disclosure["rank_bins"] = rank_bins
    ci90 = sealed.get("long_horizon_loss_difference_ci90") or {}
    if ci90.get("lower") is not None and ci90.get("upper") is not None:
        disclosure["loss_diff_ci90"] = {
            "lower": _num(ci90.get("lower"), 8),
            "upper": _num(ci90.get("upper"), 8),
            "origin_count": int(ci90.get("origin_count") or 0),
            "method": str(ci90.get("method") or ""),
        }
    disclosure["forward"] = _forward_block(latest, resolutions)
    score = score100(disclosure)
    if score is not None:
        disclosure["score100"] = score
        bounds = score100_bounds(score)
        if bounds is not None:
            disclosure["score100_bounds"] = bounds
    return disclosure


# ── 100점 환산 성적 (표시 전용 · 게이트 아님) ──────────────────────────────
# 설계 근거: docs/design/timeseries_score100_261006.md. 벤치마크 —
#  · 기상 검증의 CRPS Skill Score: 1 − CRPS/CRPS_ref, 0 = 기준선과 동급.
#  · M4 대회 OWA: 기준선(Naive2) 오차 = 1 로 정규화한 상대 오차.
#  · 구간 예측의 공칭 적중률(coverage) 대비 편차 — 계약 dev_gate_proxy 허용대역.
#  · 다요인 1~10점 등급(TipRanks Smart Score)의 고정 가중 합산·구간 라벨.
# 모든 입력은 이미 공개된 봉인창·라이브 값이며, 매핑은 고정 규칙이다(학습 아님).
SCORE100_WEIGHTS = {
    "accuracy": 30, "confidence": 10, "calibration": 30, "robustness": 15, "live": 15,
}
# 정확도: 개선율 0% = 50점(기준선과 동급), +10% = 100점, −10% = 0점.
SCORE100_SKILL_FULL = 0.10
# 적중률: 허용대역 끝(80% 구간 ±4pp, 50% 구간 ±5pp) = 75점, 대역의 4배 = 0점.
SCORE100_COVER_TOL_PP = {0.8: 4.0, 0.5: 5.0}
# 위기 국면: 발행 하한 70%(공칭 −10pp) = 75점. 넓게 담은 쪽(보수적)은 벌점 절반.
SCORE100_REGIME_TOL_PP = 10.0
# 라이브: 소표본을 중립(승률 50%·적중 80%)으로 끌어당기는 사전 무게(행 수).
SCORE100_LIVE_PRIOR_ROWS = 10
SCORE100_GRADES = ((80, "A", "우수"), (60, "B", "보통"), (40, "C", "미흡"), (0, "D", "부진"))


def _clamp100(value: float) -> float:
    return max(0.0, min(100.0, value))


def _skill_points(gain: float) -> float:
    return _clamp100(50.0 + 50.0 * gain / SCORE100_SKILL_FULL)


def _cover_points(coverage: float, nominal: float, *, over_factor: float = 1.0,
                  tol_pp: float | None = None) -> float:
    tol = tol_pp if tol_pp is not None else SCORE100_COVER_TOL_PP[nominal]
    dev = (coverage - nominal) * 100.0
    penalty = abs(dev) * (over_factor if dev > 0 else 1.0)
    return _clamp100(100.0 - 25.0 * penalty / tol)


def score100(disclosure: dict[str, Any]) -> dict[str, Any] | None:
    """공개된 봉인·라이브 지표를 100점으로 환산한다 — 표시 전용 요약이다.

    봉인창 블록이 없으면 None(점수 없음) — 전체창(개발기간 포함)으로 대체하지 않는다.
    증거가 없는 항목(예: 2008 원점 0개)은 0점이다: 검증 안 된 것은 점수가 없다.
    """
    window = disclosure.get("sealed_window") or {}
    horizons = window.get("horizons") or {}
    keys = [key for key in HORIZONS if isinstance(horizons.get(key), dict)]
    gains = [float(horizons[k]["crps_improvement_vs_best"]) for k in keys
             if horizons[k].get("crps_improvement_vs_best") is not None]
    if not gains:
        return None
    pillars: dict[str, dict[str, Any]] = {}

    accuracy = sum(_skill_points(gain) for gain in gains) / len(gains)
    pillars["accuracy"] = {"score": accuracy, "detail": {
        "mean_improvement": sum(gains) / len(gains), "horizons": len(gains)}}

    pvalues = [horizons[k].get("dm_p_value") for k in keys]
    pvalues = [float(p) for p in pvalues if p is not None]
    significant = sum(1 for p in pvalues if p < 0.05)
    ci = disclosure.get("loss_diff_ci90") or {}
    ci_clear = ci.get("upper") is not None and float(ci["upper"]) < 0.0
    confidence = 50.0 * (1.0 if ci_clear else 0.0) + 50.0 * (
        significant / len(pvalues) if pvalues else 0.0)
    pillars["confidence"] = {"score": confidence, "detail": {
        "significant_horizons": significant, "tested_horizons": len(pvalues),
        "long_ci90_below_zero": ci_clear}}

    cover_scores = []
    for key in keys:
        row = horizons[key]
        if row.get("coverage_p10_p90") is not None:
            cover_scores.append(_cover_points(float(row["coverage_p10_p90"]), 0.8))
        if row.get("coverage_p25_p75") is not None:
            cover_scores.append(_cover_points(float(row["coverage_p25_p75"]), 0.5))
    calibration = sum(cover_scores) / len(cover_scores) if cover_scores else 0.0
    pillars["calibration"] = {"score": calibration, "detail": {"checks": len(cover_scores)}}

    regimes = disclosure.get("regimes") or []
    regime_scores = []
    untested = []
    for regime in regimes:
        coverage = regime.get("coverage_p10_p90")
        if coverage is None or not int(regime.get("origins") or 0):
            regime_scores.append(0.0)
            untested.append(str(regime.get("key")))
        else:
            regime_scores.append(_cover_points(
                float(coverage), 0.8, over_factor=0.5, tol_pp=SCORE100_REGIME_TOL_PP))
    robustness = sum(regime_scores) / len(regime_scores) if regime_scores else 0.0
    pillars["robustness"] = {"score": robustness, "detail": {
        "regimes": len(regime_scores), "untested": untested}}

    forward = disclosure.get("forward") or {}
    rows = int(forward.get("resolved_rows") or 0)
    better = int(forward.get("model_better_rows") or 0)
    covered = int(forward.get("covered_p10_p90_rows") or 0)
    prior = SCORE100_LIVE_PRIOR_ROWS
    win_rate = (better + prior * 0.5) / (rows + prior)
    cover_rate = (covered + prior * 0.8) / (rows + prior)
    live = (_clamp100(100.0 * win_rate) + _cover_points(cover_rate, 0.8)) / 2.0
    pillars["live"] = {"score": live, "detail": {
        "rows": rows, "model_better_rows": better, "covered_rows": covered,
        "evidence_weight": rows / (rows + prior)}}

    total = 0.0
    for key, weight in SCORE100_WEIGHTS.items():
        pillar = pillars[key]
        pillar["weight"] = weight
        pillar["points"] = round(pillar["score"] * weight / 100.0, 1)
        pillar["score"] = round(pillar["score"], 1)
        total += pillar["score"] * weight / 100.0
    total = round(total)
    grade, label = next((g, l) for floor, g, l in SCORE100_GRADES if total >= floor)
    return {
        "total": total, "grade": grade, "label": label,
        "pillars": pillars, "method": "display_only_fixed_rule_v1",
    }


def _score100_grade(total: float) -> str:
    return next(grade for floor, grade, _ in SCORE100_GRADES if total >= floor)


def score100_bounds(score: dict[str, Any] | None) -> dict[str, Any] | None:
    """현 산식에서 총점이 움직일 수 있는 범위 — 표시 전용 공시, 새 산식이 아니다.

    봉인 4축(정확도·확실성·약속 지킴·위기 대응)은 1회 봉인 평가의 값이라 불변이고,
    실전 축만 라이브 원장이 쌓이며 0~가중(15)점 사이를 오르내린다(가상 10행 수축은
    표본이 늘수록 풀린다). 하한·상한은 score100 과 같은 반올림 규칙으로 계산한다:
    round(Σ round(score,1)·w/100) 에 실전 축 0점·만점을 각각 넣은 값.
    """
    if not score or not isinstance(score.get("pillars"), dict):
        return None
    pillars = score["pillars"]
    fixed = 0.0
    for key, weight in SCORE100_WEIGHTS.items():
        if key == "live":
            continue
        pillar = pillars.get(key)
        if not isinstance(pillar, dict) or pillar.get("score") is None:
            return None
        fixed += float(pillar["score"]) * weight / 100.0
    live = pillars.get("live") if isinstance(pillars.get("live"), dict) else {}
    live_weight = SCORE100_WEIGHTS["live"]
    floor_total = round(fixed)
    ceiling_total = round(fixed + live_weight)
    floor_grade, ceiling_grade = _score100_grade(floor_total), _score100_grade(ceiling_total)
    return {
        "fixed_pillars": [key for key in SCORE100_WEIGHTS if key != "live"],
        "fixed_points": round(fixed, 1),
        "variable_pillar": "live",
        "variable_weight": live_weight,
        "live_points": None if live.get("points") is None else float(live["points"]),
        "floor_total": floor_total,
        "ceiling_total": ceiling_total,
        "floor_grade": floor_grade,
        "ceiling_grade": ceiling_grade,
        "grade_locked": floor_grade == ceiling_grade,
        "method": "display_only_fixed_rule_v1",
    }


def shadow_progress(
    origins: list[str], *, as_of_session: str, calendar: dict[str, Any],
    required_sessions: int, maturity_sessions: int = SHADOW_MATURITY_SESSIONS,
) -> dict[str, Any] | None:
    """섀도 진행률 — 첫 섀도 원점 다음 NYSE 세션부터 센다(표시 전용 순수 함수).

    세션은 거래일 달력(ai_fc.scenario.future_trading_days · NYSE 휴장 계약)으로 결정론적으로
    만든다. 원점이 하나도 없거나 요구 세션 수가 없으면 None — 진행률을 지어내지 않는다.
    승격은 계약(automatic_champion=false · explicit_owner_approval)대로 사람이 결정한다;
    126 도달은 '표본이 찼다'는 뜻이지 승격·판정이 아니다.
    """
    from .scenario import future_trading_days

    known = sorted({str(origin) for origin in origins if origin})
    required = int(required_sessions or 0)
    maturity = int(maturity_sessions or 0)
    if not known or required <= 0 or maturity <= 0:
        return None
    start = date.fromisoformat(known[0])
    cutoff = date.fromisoformat(str(as_of_session)[:10])
    sessions = future_trading_days(start, max(required, maturity), calendar)
    elapsed = sum(1 for session in sessions if session <= cutoff)
    return {
        "first_origin": known[0],
        "latest_origin": known[-1],
        "origins": len(known),
        "as_of_session": cutoff.isoformat(),
        "calendar": str(calendar.get("calendar") or "NYSE"),
        "sessions_elapsed": elapsed,
        "required_sessions": required,
        "sessions_remaining": max(0, required - elapsed),
        "required_session_date": sessions[required - 1].isoformat(),
        "maturity_sessions": maturity,
        "first_h63_maturity_date": sessions[maturity - 1].isoformat(),
        "first_h63_matured": elapsed >= maturity,
        "promotion_automatic": False,
    }


def build_projection(
    latest: dict[str, Any], *, anchor_value: float, sealed_row: dict[str, Any],
    history: dict[str, list[Any]] | None = None,
    resolutions: list[dict[str, Any]] | None = None,
    realized: dict[str, list[Any]] | None = None,
    origin_age_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map the visible latest pointer into the dashboard read-model slot.

    Quantiles arrive as cumulative log returns (fractions); index levels are
    ``anchor × exp(q)`` so the anchor close at the forecast origin is the only
    extra input.  The sealed evaluation's disclosed metrics ride along so the
    surface can show its evidence instead of asserting trust.
    """
    if latest.get("publication", {}).get("customer_numbers_visible") is not True:
        raise TimeSeriesV8DisplayError("projection requested for a HOLD surface")
    if not (isinstance(anchor_value, (int, float)) and math.isfinite(anchor_value)
            and anchor_value > 0):
        raise TimeSeriesV8DisplayError("V8 anchor close must be a positive finite level")
    summary = sealed_row.get("summary") or {}
    if summary.get("gate_pass") is not True:
        raise TimeSeriesV8DisplayError("sealed evaluation row did not pass the gate")
    if sealed_row.get("run_id") != latest.get("gate", {}).get("sealed_run_id"):
        raise TimeSeriesV8DisplayError("sealed run id does not match the latest pointer")
    # 원점 이후 실측(있으면): 빌드 시점에 이미 만기가 지난 지평은 열린 전망이 아니다.
    # 사후 대조는 표시 전용이며 전진 원장(shadow_resolutions)에 기입하지 않는다 —
    # 원장은 별도 성숙 판정 경로가 맡고, 이 값은 base rate 참조일 뿐이다.
    realized_dates = [str(value) for value in ((realized or {}).get("dates") or [])]
    realized_index = [float(value) for value in ((realized or {}).get("index") or [])]
    origin_age_sessions = min(len(realized_dates), len(realized_index))
    horizons: dict[str, Any] = {}
    for key in HORIZONS:
        row = latest["horizons"][key]
        log_return = {name: float(row[name]) for name in QUANTILES}
        band_index = {
            name: anchor_value * math.exp(log_return[name])
            for name in ("p10", "p25", "p75", "p90")
        }
        horizon = {
            "log_return": log_return,
            "point_return": math.expm1(log_return["p50"]),
            "probability_up": float(row["probability_up"]),
            "median_index": anchor_value * math.exp(log_return["p50"]),
            "band_index": band_index,
            "elapsed": False,
        }
        steps = int(key)
        if origin_age_sessions >= steps:
            level = realized_index[steps - 1]
            horizon.update({
                "elapsed": True,
                "realized_date": realized_dates[steps - 1],
                "realized_index": level,
                "realized_return": level / anchor_value - 1.0,
                "realized_inside_p10_p90": bool(band_index["p10"] <= level <= band_index["p90"]),
            })
        horizons[key] = horizon
    sealed_horizons = summary.get("horizons") or {}
    sealed_metrics = {
        key: {
            "crps_improvement_vs_best": float(sealed_horizons[key]["crps_improvement_vs_best"]),
            "coverage_p10_p90": float(sealed_horizons[key]["coverage_p10_p90"]),
        }
        for key in ("21", "63")
        if key in sealed_horizons
    }
    if set(sealed_metrics) != {"21", "63"}:
        raise TimeSeriesV8DisplayError("sealed evaluation metrics incomplete for display")
    return {
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "status": "shadow_live",
        "display_state": "research_reference",
        "numbers_visible": True,
        "probability_space": PROBABILITY_SPACE,
        "probability_unit": "fraction",
        "combined_with_existing_models": False,
        "as_of": latest["as_of"],
        "knowledge_cutoff": latest["knowledge_cutoff"],
        "gate": latest["gate"],
        "publication": latest["publication"],
        "anchor": {"series_id": TARGET_SERIES, "value": float(anchor_value)},
        "horizons": horizons,
        "sealed_metrics": {
            "run_id": sealed_row["run_id"],
            "origin_count": int(summary.get("origin_count") or 0),
            "horizons": sealed_metrics,
            **_sealed_disclosure(sealed_row, summary, latest, resolutions or []),
        },
        # 게이트 위젯용: 신선도 5그룹의 상태 요약 (visible 표면에만 존재).
        "freshness_summary": [
            {
                "group": str(row.get("group")),
                "age_hours": None if row.get("age_hours") is None else float(row["age_hours"]),
                "limit_hours": None if row.get("limit_hours") is None else float(row["limit_hours"]),
                "status": str(row.get("status")),
                # 포인터가 기록한 마지막 관측일 — 나이(age_hours)는 포인터 생성 시각 기준이라
                # 화면은 관측일을 함께 보여 '언제 기준 신선도인지'를 드러낸다.
                "observation_time": None if row.get("observation_time") is None else str(row["observation_time"]),
                **{key: row[key] for key in ("policy_id", "rule", "expected_observation",
                    "publication_deadline", "next_publication_deadline") if key in row},
            }
            for row in (latest.get("operational", {}).get("freshness") or [])
        ],
        # 밴드 차트 좌측 실적선: 최근 63세션 종가 (visible 표면에만 존재).
        "history": history or None,
        # 원점 이후 실측 종가(사후 대조용, visible 표면에만 존재)와 원점 경과 거래일 수.
        "realized": (
            {"dates": realized_dates[:origin_age_sessions], "index": realized_index[:origin_age_sessions]}
            if origin_age_sessions else None
        ),
        "origin_age_sessions": origin_age_sessions,
        # 계약 origin_age_policy(사용자 결정 2026-09-07): 경고·보류 임계를 화면이 함께 말한다.
        "origin_age_policy": (
            {
                "warn_after_sessions": int(origin_age_policy["warn_after_sessions"]),
                "hold_after_sessions": int(origin_age_policy["hold_after_sessions"]),
            }
            if origin_age_policy and origin_age_policy.get("hold_after_sessions") is not None
            else None
        ),
        "footnote": latest["footnote"],
    }


def _sealed_row(root: Path, run_id: str) -> dict[str, Any]:
    path = root / SEALED_LEDGER_RELATIVE
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if path.is_file() else []
    for row in rows:
        if row.get("run_id") == run_id:
            return row
    raise TimeSeriesV8DisplayError(f"sealed evaluation {run_id} missing from the ledger")


def _forward_resolutions(root: Path) -> list[dict[str, Any]]:
    """전진(라이브) 확정 행 — 없으면 빈 목록이며 그 자체가 정직한 상태다."""
    path = root / FORWARD_LEDGER_RELATIVE
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _anchor_and_history(
    root: Path, origin: str, knowledge_cutoff: str, *, sessions: int = 63,
) -> tuple[float, dict[str, list[Any]]]:
    """Anchor close at the origin plus the trailing session history up to it.

    Display-layer join only: the sealed latest pointer never carries these
    numbers (its HOLD surface must stay number-free), so the band chart's
    history line is assembled here from the same read-only market archive that
    already supplies the anchor.
    """
    from .timeseries_v2.market_archive import read_market_observations

    rows = sorted(
        (
            row for row in read_market_observations(root, knowledge_cutoff=knowledge_cutoff)
            if row.series_id == TARGET_SERIES and row.observation_time <= origin
        ),
        key=lambda row: row.observation_time,
    )
    if not rows or rows[-1].observation_time != origin:
        raise TimeSeriesV8DisplayError(
            f"anchor close for {TARGET_SERIES} at {origin} missing from the market archive"
        )
    tail = rows[-sessions:]
    history = {
        "dates": [row.observation_time for row in tail],
        "index": [float(row.value) for row in tail],
    }
    return float(rows[-1].value), history


def _realized_after_origin(
    root: Path, origin: str, knowledge_cutoff: str, *, sessions: int = 63,
) -> dict[str, list[Any]]:
    """Closes observed after the origin, up to the knowledge cutoff.

    Display-layer join like ``_anchor_and_history`` — the same read-only archive
    that supplies the anchor already holds the sessions after it, so horizons
    that have matured by build time can be shown against what really happened.
    A missing or empty archive yields an empty series; it never blocks the build
    (the live ledger is scored by its own maturity path, not here).
    """
    from .timeseries_v2.market_archive import read_market_observations

    try:
        rows = sorted(
            (
                row for row in read_market_observations(root, knowledge_cutoff=knowledge_cutoff)
                if row.series_id == TARGET_SERIES and row.observation_time > origin
            ),
            key=lambda row: row.observation_time,
        )
    except (OSError, ValueError, KeyError):
        rows = []
    head = rows[:sessions]
    return {
        "dates": [row.observation_time for row in head],
        "index": [float(row.value) for row in head],
    }


def _origin_age_policy(root: Path) -> dict[str, Any]:
    """Read the contract's origin_age_policy block; absent file or block means no hold.

    이 섹션은 frozen_coordinates 밖이라 frozen_hash에 영향을 주지 않는다. 계약 전체
    검증(load_contract_v8)은 파이프라인이 맡고, 표시 계층은 이 블록만 읽는다.
    """
    import yaml

    from .timeseries_v8.contracts import CONTRACT_RELATIVE

    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    policy = payload.get("origin_age_policy") if isinstance(payload, dict) else None
    return dict(policy) if isinstance(policy, dict) else {}


def _promotion_policy(root: Path) -> dict[str, Any]:
    """Read the contract's promotion block (minimum_shadow_sessions 등); absent means no label.

    origin_age_policy 와 같은 읽기 전용 접근 — 계약 전체 검증은 파이프라인 몫이고 표시 계층은
    이 블록만 읽는다. 블록이 없으면 진행률 자체를 싣지 않는다(fail-closed).
    """
    import yaml

    from .timeseries_v8.contracts import CONTRACT_RELATIVE

    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    policy = payload.get("promotion") if isinstance(payload, dict) else None
    return dict(policy) if isinstance(policy, dict) else {}


def _shadow_progress_block(
    root: Path, latest: dict[str, Any], sealed_metrics: dict[str, Any],
) -> dict[str, Any] | None:
    """섀도 진행률 블록 — 첫 원점은 전진 해소 원장(이미 계보 등록)에서, 세션은 NYSE 달력에서.

    달력·계약·원점 중 하나라도 없으면 None 을 돌려주고 표면은 그대로 뜬다 — 사이트 빌드를
    세우지 않고 숫자도 지어내지 않는다.
    """
    from .scenario import ScenarioError, load_calendar_contract

    required = (_promotion_policy(root) or {}).get("minimum_shadow_sessions")
    origins = [str(origin) for origin in ((sealed_metrics.get("forward") or {}).get("origins") or [])]
    if required is None or not origins:
        return None
    try:
        calendar = load_calendar_contract(root)
    except (ScenarioError, OSError):
        return None
    # 경과 세션의 기준일 = 포인터가 아는 마지막 NASDAQ 관측 세션(없으면 원점 as_of).
    observed = [
        str(row.get("observation_time"))[:10]
        for row in ((latest.get("operational") or {}).get("freshness") or [])
        if str(row.get("group") or "").startswith(TARGET_SERIES) and row.get("observation_time")
    ]
    as_of_session = max([str(latest.get("as_of") or "")[:10], *observed])
    try:
        return shadow_progress(
            origins, as_of_session=as_of_session, calendar=calendar,
            required_sessions=int(required))
    except (ValueError, TypeError, ScenarioError):
        return None


# ── 표시 공시 (P5 — D2·D3·D7·D15) ───────────────────────────────────────────────
# 이미 공개된 포인터·V8 원장·시장 아카이브와 XNAS 달력만 읽는다. 연구 원장
# (mts_research 계층의 원장)은 읽지 않는다 — production_publish 경계. 어떤 확률·분위수도
# 다시 계산하거나 바꾸지 않고, 그 숫자가 무엇을 센 값인지 라벨만 덧붙인다.

class XnasCalendar:
    """XNAS 세션과 UTC 종가 시각의 읽기 전용 표 (ai_fc.mts_research.sessions.session_table).

    아카이브 관측일을 달력으로 쓰지 않는다. 창 밖 질의는 추정하지 않고 실패한다.
    """

    def __init__(self, start: date, end: date) -> None:
        from .mts_research.sessions import session_table

        table = session_table(start, end)
        self.start, self.end = start, end
        self.sessions = [date.fromisoformat(row.session) for row in table]
        self._close = {date.fromisoformat(row.session): row.close_utc for row in table}
        self._index = {day: index for index, day in enumerate(self.sessions)}

    def is_session(self, day: date) -> bool:
        return day in self._index

    def close_utc(self, day: date) -> datetime:
        if day not in self._close:
            raise TimeSeriesV8DisplayError(f"XNAS 세션이 아니다: {day.isoformat()}")
        return self._close[day]

    def offset(self, origin: date, k: int) -> date:
        """원점 다음 k번째 XNAS 세션 (k>=1)."""
        if origin not in self._index:
            raise TimeSeriesV8DisplayError(f"원점이 XNAS 세션이 아니다: {origin.isoformat()}")
        index = self._index[origin] + int(k)
        if k < 1 or index >= len(self.sessions):
            raise TimeSeriesV8DisplayError(f"XNAS 달력 창 밖: {origin.isoformat()}+{k}")
        return self.sessions[index]

    def between(self, after: date, through: date) -> list[date]:
        """(after, through] 구간의 XNAS 세션."""
        return [day for day in self.sessions if after < day <= through]


def _utc(value: str) -> datetime:
    stamp = datetime.fromisoformat(str(value))
    if stamp.tzinfo is None:
        raise TimeSeriesV8DisplayError(f"시각에 timezone 이 없다: {value}")
    return stamp.astimezone(timezone.utc)


def base_rate_counts(
    archive: Mapping[str, float], horizon: int,
    start: date = date(2007, 1, 1), end: date = date(2025, 12, 31),
    *, cal: XnasCalendar | None = None,
) -> tuple[int, int]:
    """[start, end] 안의 XNAS 원점·목표 쌍 중 목표 종가가 원점 종가보다 높았던 (k, n).

    원점과 목표가 모두 창 안이어야 한다(창 끝을 넘는 목표를 쓰지 않는다 — 고정 창이라 데이터가
    늘어도 상수가 움직이지 않는다). XNAS 세션 종가가 아카이브에 없으면 실패한다.
    """
    if int(horizon) < 1:
        raise TimeSeriesV8DisplayError("horizon 은 1 이상")
    calendar = cal or XnasCalendar(start, end)
    sessions = [day for day in calendar.sessions if start <= day <= end]
    up = total = 0
    for index in range(len(sessions) - int(horizon)):
        origin, target = sessions[index], sessions[index + int(horizon)]
        try:
            before, after = float(archive[origin.isoformat()]), float(archive[target.isoformat()])
        except KeyError as exc:
            raise TimeSeriesV8DisplayError(f"아카이브에 XNAS 세션 종가가 없다: {exc}") from exc
        total += 1
        up += after > before
    if not total:
        raise TimeSeriesV8DisplayError("기저율 창에 원점이 없다")
    return up, total


def base_rate_up(
    archive: Mapping[str, float], horizon: int,
    start: date = date(2007, 1, 1), end: date = date(2025, 12, 31),
) -> float:
    """같은 창(2007+) NASDAQ h세션 상승 빈도 — 표시 라벨용 기저율(학습·보정 아님)."""
    up, total = base_rate_counts(archive, horizon, start, end)
    return up / total


def emit_timing(row: dict[str, Any], cal: XnasCalendar) -> dict[str, Any]:
    """주간 섀도 행의 발행 시점 공시 — 원점 종가 뒤 발행 지연과 지평별 이미 실현된 세션 수.

    발행 시각 = 원장 행의 knowledge_cutoff(실행 시각). 세션은 종가+15분(공식 종가 확정 버퍼)이
    발행 시각 이전이면 '실현'으로 센다. 입력 누수 판정이 아니라 사전(prospective) 지위의 공시다.
    """
    from .mts_research.sessions import SESSION_SETTLE_SECONDS

    origin = date.fromisoformat(str(row["origin"])[:10])
    emitted = _utc(row["knowledge_cutoff"])
    settle = timedelta(seconds=SESSION_SETTLE_SECONDS)
    realized: dict[str, int] = {}
    for key in HORIZONS:
        steps = int(key)
        targets = [cal.offset(origin, step) for step in range(1, steps + 1)]
        realized[key] = sum(1 for day in targets if cal.close_utc(day) + settle <= emitted)
    return {
        "origin": origin.isoformat(),
        "emitted_at": emitted.isoformat(),
        "emit_lag_days": round((emitted - cal.close_utc(origin)).total_seconds() / 86400.0, 4),
        "emitted_after_h1_close": realized["1"] == 1,
        "realized_sessions": realized,
        "realized_fraction": {key: round(realized[key] / int(key), 6) for key in HORIZONS},
    }


def _cron_slot(expression: str) -> tuple[int, int, frozenset[int]]:
    """'M H * * a-b' 형태의 UTC cron 만 해석한다(요일 0=일). 다른 형태는 실패한다."""
    parts = expression.split()
    if len(parts) != 5 or parts[2:4] != ["*", "*"]:
        raise TimeSeriesV8DisplayError(f"지원하지 않는 cron: {expression}")
    first, _, last = parts[4].partition("-")
    days = range(int(first), int(last or first) + 1)
    return int(parts[0]), int(parts[1]), frozenset(day % 7 for day in days)


def ledger_resolution_eta(grid_target: date, cal: XnasCalendar) -> datetime:
    """원장 해소가 가능한 가장 이른 주간 실행 시각(하한).

    resolver 는 5계열 bundle 로 해소하므로 grid 목표 세션이 든 주의 H.10(다음 월요일 또는 다음
    연준 영업일 16:15 ET + 배포 유예)이 나온 뒤 첫 cron 실행에서야 행이 생긴다.
    """
    from .forecast_source_freshness import NEW_YORK, board_business_day, policy

    if not cal.is_session(grid_target):
        raise TimeSeriesV8DisplayError(f"grid 목표가 XNAS 세션이 아니다: {grid_target.isoformat()}")
    section = policy()["weekly_dollar"]
    release = grid_target - timedelta(days=grid_target.weekday()) + timedelta(days=7)
    while not board_business_day(release):
        release += timedelta(days=1)
    release_at = (
        datetime.combine(release, time.fromisoformat(section["release_time"]), NEW_YORK)
        + timedelta(hours=float(section["distribution_grace_hours"]))
    ).astimezone(timezone.utc)
    minute, hour, weekdays = _cron_slot(RESOLVER_CRON_UTC)
    for offset in range(15):
        slot = datetime.combine(
            release_at.date() + timedelta(days=offset), time(hour, minute), timezone.utc)
        if slot >= release_at and slot.isoweekday() % 7 in weekdays:
            return slot
    raise TimeSeriesV8DisplayError("cron 실행 시각을 2주 안에서 찾지 못했다")


def _grid_gap(day: date, grid: set[date], known_through: date) -> bool:
    """grid 에서 빠지는 XNAS 세션인가 — 관측 구간은 실제 교집합, 그 뒤는 연준 휴일로 투영."""
    from .forecast_source_freshness import board_business_day

    if day <= known_through:
        return day not in grid
    return not board_business_day(day)


def _grid_set(grid_dates: Iterable[Any]) -> set[date]:
    grid = {date.fromisoformat(str(value)[:10]) for value in grid_dates}
    if not grid:
        raise TimeSeriesV8DisplayError("V8 grid 관측일이 비어 있다")
    return grid


def holiday_label_exposure(
    origin: date, h: int, grid_dates: Iterable[Any], cal: XnasCalendar,
    *, known_through: date | None = None,
) -> list[date]:
    """원점 뒤 h개 XNAS 세션 창 안에서 grid 라벨이 빠뜨리는(국채 휴장) 세션 목록."""
    grid = _grid_set(grid_dates)
    known = known_through or max(grid)
    target = cal.offset(origin, h)
    return [day for day in cal.between(origin, target) if _grid_gap(day, grid, known)]


def grid_target_session(
    origin: date, h: int, grid_dates: Iterable[Any], cal: XnasCalendar,
    *, known_through: date | None = None,
) -> date:
    """원장 라벨이 쓰는 h번째 grid 세션 (관측 교집합 + 연준 휴일 투영)."""
    grid = _grid_set(grid_dates)
    known = known_through or max(grid)
    count, step = 0, 0
    while count < int(h):
        step += 1
        day = cal.offset(origin, step)
        if not _grid_gap(day, grid, known):
            count += 1
    return day


def hold_reason(gate_detail: dict[str, Any], now: datetime) -> Literal["calendar_hold", "source_delay"]:
    """신선도 보류의 성격 — 각 입력의 실제 관측일을 기대 공표 일정(정책 v1)과 대조한다.

    공표 일정상 이미 나왔어야 할 관측이 없으면 원천 지연, 공표 일정상으론 최신인데 동결 48h
    규칙(주말·휴일)에 걸렸으면 달력 hold 다. 판정할 수 없는 행은 원천 지연으로 둔다(달력으로
    덮지 않는다).
    """
    from .forecast_source_freshness import source_freshness

    stale = [row for row in gate_detail.get("freshness") or [] if str(row.get("status")) != "fresh"]
    if not stale:
        raise TimeSeriesV8DisplayError("신선도 보류가 아니다")
    for row in stale:
        series = str(row.get("series_id") or str(row.get("group") or "").split("_or_")[0])
        observed = row.get("observation_time")
        if not observed:
            return "source_delay"
        try:
            report = source_freshness(series, str(observed)[:10], now)
        except (ValueError, KeyError):
            return "source_delay"
        if report["status"] != "fresh":
            return "source_delay"
    return "calendar_hold"


def _hold_block(pointer: dict[str, Any] | None) -> dict[str, Any] | None:
    """포인터가 신선도 사유로 보류됐을 때만 그 성격 라벨을 싣는다."""
    if pointer is None or (pointer.get("publication") or {}).get("customer_numbers_visible") is True:
        return None
    reasons = [str(reason) for reason in ((pointer.get("gate") or {}).get("reasons") or [])]
    if not any(reason.startswith(FRESHNESS_REASON_PREFIX) for reason in reasons):
        return None
    detail = pointer.get("operational") or {}
    stale = [str(row.get("group")) for row in detail.get("freshness") or []
             if str(row.get("status")) != "fresh"]
    block: dict[str, Any] = {"as_of": pointer.get("as_of"), "groups": stale,
                             "evaluated_at": pointer.get("knowledge_cutoff")}
    try:
        kind = hold_reason(detail, _utc(str(pointer.get("knowledge_cutoff"))))
    except (TimeSeriesV8DisplayError, ValueError, TypeError, OSError) as exc:
        return {**block, "kind": None, "label": None, "status": "unavailable", "error": str(exc)[:200]}
    return {**block, "kind": kind, "label": HOLD_KIND_LABELS[kind], "status": "ok"}


def daily_input_status(info: dict[str, Any] | None) -> dict[str, Any]:
    """일일 행 상태 라벨 — 'confirmed'에 달러 캐리(0변화 이월) 세션 수를 붙인다(carried_forward 길이)."""
    info = info or {}
    origin = str(info.get("origin") or "")
    carried = [
        row for row in info.get("carried_forward") or []
        if str(row.get("series_id")) == CARRY_SERIES
        and (not origin or str(row.get("observation_time")) <= origin)
    ]
    state = str(info.get("input_state") or "")
    sessions = len({str(row.get("observation_time")) for row in carried})
    return {
        "state": state,
        "carry_series": CARRY_SERIES if sessions else None,
        "carry_sessions": sessions,
        "carried_from": max((str(row.get("carried_from")) for row in carried), default=None),
        "label": f"{state}·달러 캐리 {sessions}세션" if sessions else state,
        "final": False,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _display_constants(root: Path) -> tuple[dict[str, Any] | None, str]:
    """표시 상수 파일 — content_hash 가 맞을 때만 쓴다(불일치면 해당 라벨을 싣지 않는다)."""
    path = root / DISPLAY_CONSTANTS_RELATIVE
    if not path.is_file():
        return None, "constants_missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "constants_unreadable"
    body = dict(value)
    expected = body.pop("content_hash", None)
    if expected != canonical_hash(body) or body.get("constants_id") != "v8_display_constants_v1":
        return None, "constants_hash_mismatch"
    return value, "ok"


def _nasdaq_archive(root: Path, knowledge_cutoff: str) -> tuple[dict[str, float], list[str]]:
    """NASDAQ 종가와 V8 grid(5계열 관측일 교집합) — 같은 읽기 전용 아카이브에서."""
    from .timeseries_v2.market_archive import read_market_observations

    series: dict[str, set[str]] = {name: set() for name in GRID_SERIES}
    closes: dict[str, float] = {}
    for row in read_market_observations(root, knowledge_cutoff=knowledge_cutoff):
        if row.series_id in series:
            series[row.series_id].add(str(row.observation_time)[:10])
        if row.series_id == TARGET_SERIES:
            closes[str(row.observation_time)[:10]] = float(row.value)
    grid = sorted(set.intersection(*series.values()))
    return closes, grid


def _contract_operational_gate(root: Path) -> dict[str, Any]:
    """동결 계약 operational_gate 블록(읽기 전용) — 감시 공백 라벨의 분모만 읽는다."""
    import yaml

    from .timeseries_v8.contracts import CONTRACT_RELATIVE

    path = root / CONTRACT_RELATIVE
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    gate = payload.get("operational_gate") if isinstance(payload, dict) else None
    return dict(gate) if isinstance(gate, dict) else {}


def _p_up_disclosure(
    constants: dict[str, Any] | None, constants_status: str, resolutions: list[dict[str, Any]],
) -> dict[str, Any]:
    """① 상승확률 라벨 — h21/h63 은 기저율 구조, h1/h5 는 엔진 조건부(봉인 구간 예측력 미검출)."""
    base = (constants or {}).get("base_rate_up") or {}
    uplift = (constants or {}).get("b4_uplift_pp") or {}
    signal = (constants or {}).get("sealed_location_signal") or {}
    rows: dict[str, Any] = {}
    for key in HORIZONS:
        resolved = [row for row in resolutions if str(row.get("horizon")) == key
                    and row.get("actual_log_return") is not None]
        recent = {
            "k": sum(1 for row in resolved if float(row["actual_log_return"]) > 0),
            "n": len(resolved), "n_origins": len({str(row.get("origin")) for row in resolved}),
            "basis": "ledger_grid_label", "single_episode": True,
        }
        if key in BASE_RATE_HORIZONS:
            rate = (base.get("horizons") or {}).get(key) or {}
            rows[key] = {
                "kind": "base_rate_structural", "label": "기저율 기반 상승확률",
                "base_rate": rate.get("value"), "base_rate_n": rate.get("n"),
                "base_rate_window": base.get("window"),
                "b4_uplift_pp": (uplift.get("horizons") or {}).get(key),
                "b4_uplift_n_origins": uplift.get("n_origins"),
                "state_responsive": False, "recent_up": recent,
            }
        else:
            row = (signal.get("horizons") or {}).get(key) or {}
            rows[key] = {
                "kind": "engine_conditional", "label": "엔진 조건부(봉인 구간 예측력 미검출)",
                "sealed_spearman": row.get("spearman"), "sealed_p_value": row.get("p_value"),
                "sealed_n": signal.get("n"), "recent_up": recent,
            }
    return {"constants_status": constants_status,
            "sigma_now_corr": ((constants or {}).get("state_insensitivity") or {}).get("sigma_now_corr"),
            "horizons": rows}


def _emission_block(forecasts: list[dict[str, Any]], cal: XnasCalendar) -> dict[str, Any]:
    """② 원점별 발행 지연·이미 실현된 세션 수 — '사전' 지위는 h21/h63 에만."""
    rows = [emit_timing(row, cal) for row in sorted(forecasts, key=lambda row: str(row.get("origin")))]
    lags = [row["emit_lag_days"] for row in rows]
    return {
        "n_origins": len(rows),
        "emit_lag_median_days": round(statistics.median(lags), 4) if lags else None,
        "emitted_after_h1_close": sum(1 for row in rows if row["emitted_after_h1_close"]),
        "h5_realized_sessions": [row["realized_sessions"]["5"] for row in rows],
        "realized_fraction_mean": {
            key: round(sum(row["realized_fraction"][key] for row in rows) / len(rows), 6) if rows else None
            for key in HORIZONS
        },
        "prospective_horizons": list(PROSPECTIVE_HORIZONS),
        "single_episode": False,
        "rows": rows,
    }


def _holiday_block(
    forecasts: list[dict[str, Any]], resolutions: list[dict[str, Any]],
    grid: list[str], cal: XnasCalendar,
) -> dict[str, Any]:
    """④ 국채 휴장일 수익 제외 라벨 — 해소 행은 '확정', 미해소 쌍은 '예정'."""
    resolved = {(str(row.get("origin")), str(row.get("horizon"))) for row in resolutions}
    known = max(_grid_set(grid))
    items: list[dict[str, Any]] = []
    pairs = resolved_pairs = 0
    for forecast in sorted(forecasts, key=lambda row: str(row.get("origin"))):
        origin = date.fromisoformat(str(forecast["origin"])[:10])
        for key in HORIZONS:
            pairs += 1
            resolved_pairs += (origin.isoformat(), key) in resolved
            days = holiday_label_exposure(origin, int(key), grid, cal, known_through=known)
            if days:
                items.append({
                    "origin": origin.isoformat(), "horizon": key,
                    "dates": [day.isoformat() for day in days],
                    "status": "confirmed" if (origin.isoformat(), key) in resolved else "expected",
                })
    dates = sorted({value for item in items for value in item["dates"]})
    return {
        "label": "국채 휴장일 수익 제외 라벨",
        "dates": dates,
        "confirmed_rows": sum(1 for item in items if item["status"] == "confirmed"),
        "expected_rows": sum(1 for item in items if item["status"] == "expected"),
        "resolved_pairs": resolved_pairs,
        "unresolved_pairs": pairs - resolved_pairs,
        "n_pairs": pairs,
        "grid_known_through": known.isoformat(),
        "single_episode": len(dates) <= 1,
        "items": items,
    }


def _maturity_block(
    forecasts: list[dict[str, Any]], resolutions: list[dict[str, Any]],
    grid: list[str], cal: XnasCalendar,
) -> dict[str, Any] | None:
    """③ 첫 h63 성숙 이중 표기 — XNAS 63세션 날짜와 원장 해소 예상(grid 세션·H.10 뒤 cron)."""
    origins = sorted(str(row.get("origin"))[:10] for row in forecasts if row.get("origin"))
    if not origins:
        return None
    first = date.fromisoformat(origins[0])
    horizon = int(SHADOW_MATURITY_SESSIONS)
    grid_target = grid_target_session(first, horizon, grid, cal)
    resolved = any(str(row.get("origin")) == origins[0] and str(row.get("horizon")) == str(horizon)
                   for row in resolutions)
    return {
        "first_origin": origins[0],
        "horizon": horizon,
        "xnas_maturity_session": cal.offset(first, horizon).isoformat(),
        "ledger_grid_session": grid_target.isoformat(),
        "ledger_eta_utc": ledger_resolution_eta(grid_target, cal).isoformat(),
        "ledger_eta_is_lower_bound": True,
        "ledger_resolved": resolved,
    }


def _monitoring_gap(latest: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """⑦ 감시 공백 — h63 성숙 원점이 계약 recent_origins 에 닿기 전엔 자동 성적 경보가 없다."""
    required = _contract_operational_gate(root).get("recent_origins")
    if required is None:
        return None
    monitoring = (latest.get("operational") or {}).get("monitoring") or {}
    matured = int(monitoring.get("matured_shadow_origins") or 0)
    return {
        "matured_h63_origins": matured, "required_origins": int(required),
        "auto_alert_active": matured >= int(required),
        "label": f"h63 성숙 원점 {matured}/{int(required)} — 그 전까지 자동 성적 경보 없음",
    }


def _disclosure_part(build) -> Any:
    """공시 블록 하나를 만든다 — 실패하면 그 블록만 '확인 불가'로 남기고 표면은 그대로 뜬다."""
    try:
        return build()
    except (TimeSeriesV8DisplayError, OSError, ValueError, KeyError, TypeError, ImportError,
            RuntimeError) as exc:
        return {"status": "unavailable", "error": str(exc)[:200]}


def _v8_disclosure(
    root: Path, latest: dict[str, Any], weekly: dict[str, Any] | None, *, use_daily: bool,
) -> dict[str, Any]:
    """표시 공시 묶음(display_only) — 숫자를 바꾸지 않고 라벨·접기 근거만 싣는다."""
    resolutions = _forward_resolutions(root)
    forecasts = _read_jsonl(root / SHADOW_FORECAST_LEDGER_RELATIVE)
    constants, constants_status = _display_constants(root)
    disclosure: dict[str, Any] = {
        "display_only": True, "notice": DISCLOSURE_NOTICE,
        "n_origins": len({str(row.get("origin")) for row in forecasts}),
        "single_episode": True,
        "p_up": _p_up_disclosure(constants, constants_status, resolutions),
        "monitoring_gap": _disclosure_part(lambda: _monitoring_gap(latest, root)),
        # ⑥ 일일 표면이 떠 있어도 주간 원점이 보류면 그 성격을 함께 말한다.
        "weekly_hold": _hold_block(weekly) if use_daily else None,
    }
    if use_daily:
        disclosure["input_state"] = daily_input_status(
            {**(latest.get("daily") or {}), "origin": latest.get("as_of")})
    if forecasts:
        origins = sorted(date.fromisoformat(str(row["origin"])[:10]) for row in forecasts)
        cal_box: dict[str, Any] = {}

        def calendar() -> XnasCalendar:
            if "cal" not in cal_box:
                cal_box["cal"] = XnasCalendar(origins[0] - timedelta(days=7),
                                              origins[-1] + timedelta(days=150))
            return cal_box["cal"]

        archive_box: dict[str, Any] = {}

        def grid() -> list[str]:
            if "grid" not in archive_box:
                archive_box["grid"] = _nasdaq_archive(root, str(latest["knowledge_cutoff"]))[1]
            return archive_box["grid"]

        disclosure["emission"] = _disclosure_part(lambda: _emission_block(forecasts, calendar()))
        disclosure["holiday_exposure"] = _disclosure_part(
            lambda: _holiday_block(forecasts, resolutions, grid(), calendar()))
        disclosure["maturity"] = _disclosure_part(
            lambda: _maturity_block(forecasts, resolutions, grid(), calendar()))
    return disclosure


def _daily_anchor_and_history(
    root: Path, origin: str, knowledge_cutoff: str, anchor_value: float, *, sessions: int = 63,
) -> dict[str, list[Any]]:
    """History line for the daily surface: archive closes before the origin + the row's anchor.

    The daily row may sit on a provisional NASDAQ close that the archive has not
    confirmed yet, so the origin point is the anchor the forecast actually used.
    """
    from .timeseries_v2.market_archive import read_market_observations

    rows = sorted(
        (
            row for row in read_market_observations(root, knowledge_cutoff=knowledge_cutoff)
            if row.series_id == TARGET_SERIES and row.observation_time < origin
        ),
        key=lambda row: row.observation_time,
    )[-(sessions - 1):]
    return {
        "dates": [row.observation_time for row in rows] + [origin],
        "index": [float(row.value) for row in rows] + [float(anchor_value)],
    }


def _read_pointer(root: Path, relative: Path) -> dict[str, Any] | None:
    path = root / relative
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_latest(value)
    return value


def _hold_projection(
    latest: dict[str, Any], *, use_daily: bool, weekly: dict[str, Any] | None,
    origin_age_reason: str | None = None,
) -> dict[str, Any]:
    """Keep the selected V8 decision visible without carrying numerical data."""
    gate = latest.get("gate") or {}
    reasons = [str(reason) for reason in (gate.get("reasons") or [])]
    if origin_age_reason is not None:
        reasons.append(origin_age_reason)
    return {
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "status": "shadow_operational_hold" if origin_age_reason is not None else latest["status"],
        "display_state": "validation_pending",
        "numbers_visible": False,
        "probability_space": PROBABILITY_SPACE,
        "probability_unit": "fraction",
        "combined_with_existing_models": False,
        "as_of": latest.get("as_of"),
        "knowledge_cutoff": latest.get("knowledge_cutoff"),
        "gate": {
            "sealed_gate_pass": gate.get("sealed_gate_pass") is True,
            "sealed_run_id": gate.get("sealed_run_id"),
            "operational_pass": False if origin_age_reason is not None else gate.get("operational_pass") is True,
            "reasons": reasons,
        },
        "publication": {
            "customer_numbers_visible": False,
            "combined_with_official_forecasts": False,
            "combined_with_scenario_v5_2": False,
            "reference_opinion_only": True,
        },
        "horizons": {},
        "path": {},
        "cadence": "daily" if use_daily else "weekly",
        "weekly_as_of": None if weekly is None else weekly.get("as_of"),
        "footnote": latest.get("footnote"),
        # ⑥ 보류 성격 라벨(표시 전용) — 숫자 없이 사유의 종류만 말한다.
        "v8_disclosure": {
            "display_only": True, "notice": DISCLOSURE_NOTICE, "single_episode": False,
            "hold": _hold_block(latest),
            "weekly_hold": _hold_block(weekly) if use_daily else None,
        },
    }


def load_projection(root: Path, *, now=None) -> dict[str, Any] | None:
    """Return the selected V8 decision, or None only when no pointer exists.

    HOLD keeps V8's own metadata and reasons on the surface while omitting all
    numerical data; it must not expose an older model's decision as V8's state.

    The daily display pointer (user decision 2026-10-07) owns the surface when it
    is at least as new as the weekly pointer — including its HOLD (fail-closed).
    Scoring blocks (sealed metrics, live forward, score100) always come from the
    weekly shadow ledgers either way.
    """
    weekly = _read_pointer(root, LATEST_RELATIVE)
    daily = _read_pointer(root, DAILY_LATEST_RELATIVE)
    use_daily = daily is not None and (
        weekly is None or (daily.get("as_of") is not None
                           and str(daily["as_of"]) >= str(weekly.get("as_of") or "")))
    latest = daily if use_daily else weekly
    if latest is None:
        return None
    reasons = latest.get("gate", {}).get("reasons") or []
    if (use_daily and latest.get("daily", {}).get("display_id") and reasons
            and all(str(reason).startswith("필수 시장 입력 신선도 초과:") for reason in reasons)):
        # Reevaluate a source-only HOLD against the same published daily row.
        # Sealed gate, CRPS monitor, source validation and origin-age still apply;
        # this read path never trains, appends or replaces a pointer.
        from .timeseries_v8_daily import publish_daily_display_latest
        try:
            current = publish_daily_display_latest(root, now=now, persist=False)
        except (OSError, ValueError, KeyError, RuntimeError, TypeError, ImportError) as exc:
            closed = {**latest, "gate": {**latest["gate"], "reasons": [
                *reasons, "운영 신선도 재검수 실패: " + str(exc)[:256]]}}
            return _hold_projection(closed, use_daily=use_daily, weekly=weekly)
        if (current.get("daily", {}).get("display_id") == latest.get("daily", {}).get("display_id")
                and current.get("as_of") == latest.get("as_of")):
            latest = current
    if latest.get("publication", {}).get("customer_numbers_visible") is not True:
        return _hold_projection(latest, use_daily=use_daily, weekly=weekly)
    realized = _realized_after_origin(
        root, str(latest["as_of"]), str(latest["knowledge_cutoff"]))
    policy = _origin_age_policy(root)
    hold_after = policy.get("hold_after_sessions")
    origin_age = min(len(realized.get("dates") or []), len(realized.get("index") or []))
    if hold_after is not None and origin_age >= int(hold_after):
        # Display-only closure: preserve the pointer's gate and numbers on disk.
        return _hold_projection(
            latest, use_daily=use_daily, weekly=weekly,
            origin_age_reason=f"예측 원점 경과 거래일 {origin_age}: 보류 임계 {int(hold_after)} 도달")
    sealed_row = _sealed_row(root, str(latest["gate"]["sealed_run_id"]))
    if use_daily:
        info = latest.get("daily") or {}
        anchor = info.get("anchor") or {}
        if anchor.get("series_id") != TARGET_SERIES:
            raise TimeSeriesV8DisplayError("daily pointer lacks its NASDAQ anchor")
        anchor_value = float(anchor["value"])
        history = _daily_anchor_and_history(
            root, str(latest["as_of"]), str(latest["knowledge_cutoff"]), anchor_value)
    else:
        anchor_value, history = _anchor_and_history(
            root, str(latest["as_of"]), str(latest["knowledge_cutoff"]))
    projection = build_projection(
        latest, anchor_value=anchor_value, sealed_row=sealed_row, history=history,
        resolutions=_forward_resolutions(root), realized=realized,
        origin_age_policy=policy)
    # 표시 주기: 화면 원점은 매일, 채점·성적은 주간 원점(weekly_as_of)이다.
    projection["cadence"] = "daily" if use_daily else "weekly"
    projection["weekly_as_of"] = None if weekly is None else weekly.get("as_of")
    # 섀도 진행률(표시 전용) — 성적 블록과 같은 자리(sealed_metrics)에 싣는다.
    progress = _shadow_progress_block(root, latest, projection.get("sealed_metrics") or {})
    if progress is not None:
        projection["sealed_metrics"]["shadow_progress"] = progress
    if use_daily:
        info = latest.get("daily") or {}
        projection["input_state"] = str(info.get("input_state") or "")
        projection["provisional_series"] = [str(item) for item in info.get("provisional_series") or []]
        projection["anchor"]["provisional"] = bool((info.get("anchor") or {}).get("provisional"))
    # 표시 공시(P5): 기존 키는 한 바이트도 바꾸지 않고 새 키 하나에만 싣는다.
    projection["v8_disclosure"] = _v8_disclosure(root, latest, weekly, use_daily=use_daily)
    return projection
