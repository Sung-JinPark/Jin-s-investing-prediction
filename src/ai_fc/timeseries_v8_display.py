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
from pathlib import Path
from typing import Any

from .timeseries_v8.contracts import MODEL_ID, MODEL_VERSION, canonical_hash

LATEST_RELATIVE = Path("data/timeseries_v8/multivariate_v8_latest.json")
SEALED_LEDGER_RELATIVE = Path("data/timeseries_v8/ledgers/sealed_evaluations.jsonl")
FORWARD_LEDGER_RELATIVE = Path("data/timeseries_v8/ledgers/shadow_resolutions.jsonl")
# 실측 순위 칸 = 이미 공개된 5개 절단점이 수직선을 6칸으로 나눈 것.
# 완전 보정 시 기대 비율은 10/15/25/25/15/10% (JS 상수와 같은 순서).
RANK_CUTS = ("p10", "p25", "median", "p75", "p90")
# 게이트 사유 문자열이 참조하는 고정 국면 순서 — 정렬로 뒤바뀌면 안 된다.
REGIME_ORDER = ("great_financial_crisis_2008", "pandemic_2020", "tightening_2022")
PROBABILITY_SPACE = "research_timeseries_v8_conditional"
TARGET_SERIES = "NASDAQCOM"
HORIZONS = ("1", "5", "21", "63")
QUANTILES = ("p10", "p25", "p50", "p75", "p90")


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


def load_projection(root: Path) -> dict[str, Any] | None:
    """Return the visible V8 projection, or None so the surface falls back.

    None covers both "no pointer yet" and an operational HOLD: in either case
    the predecessor governance (V5/V2 validation-pending card) already renders
    the honest state, so V8 adds nothing until its gates hold.
    """
    path = root / LATEST_RELATIVE
    if not path.is_file():
        return None
    latest = json.loads(path.read_text(encoding="utf-8"))
    validate_latest(latest)
    if latest.get("publication", {}).get("customer_numbers_visible") is not True:
        return None
    sealed_row = _sealed_row(root, str(latest["gate"]["sealed_run_id"]))
    anchor_value, history = _anchor_and_history(
        root, str(latest["as_of"]), str(latest["knowledge_cutoff"]))
    realized = _realized_after_origin(
        root, str(latest["as_of"]), str(latest["knowledge_cutoff"]))
    policy = _origin_age_policy(root)
    hold_after = policy.get("hold_after_sessions")
    origin_age = min(len(realized.get("dates") or []), len(realized.get("index") or []))
    if hold_after is not None and origin_age >= int(hold_after):
        # 계약 origin_age_policy(사용자 결정 2026-09-07): 주간 주기 2회를 놓친 원점은
        # 열린 전망이 아니다 — 수치를 숨기고 validation_pending 표면으로 페일클로즈.
        return None
    return build_projection(
        latest, anchor_value=anchor_value, sealed_row=sealed_row, history=history,
        resolutions=_forward_resolutions(root), realized=realized,
        origin_age_policy=policy)
