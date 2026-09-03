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
    """배포 후 전진(라이브) 실적 — 성숙 원점이 0이면 0이라고 말한다."""
    monitoring = (latest.get("operational") or {}).get("monitoring") or {}
    origins = sorted({str(row.get("origin")) for row in resolutions if row.get("origin")})
    better = sum(
        1 for row in resolutions
        if row.get("model_crps") is not None and row.get("baseline_crps") is not None
        and float(row["model_crps"]) < float(row["baseline_crps"])
    )
    sessions = sorted(str(row.get("resolved_session")) for row in resolutions if row.get("resolved_session"))
    return {
        "matured_origins": int(monitoring.get("matured_shadow_origins") or 0),
        "source": str(monitoring.get("source") or ""),
        "resolved_rows": len(resolutions),
        "model_better_rows": better,
        "origins": origins,
        "last_resolved_session": sessions[-1] if sessions else None,
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
    return disclosure


def build_projection(
    latest: dict[str, Any], *, anchor_value: float, sealed_row: dict[str, Any],
    history: dict[str, list[Any]] | None = None,
    resolutions: list[dict[str, Any]] | None = None,
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
    horizons: dict[str, Any] = {}
    for key in HORIZONS:
        row = latest["horizons"][key]
        log_return = {name: float(row[name]) for name in QUANTILES}
        horizons[key] = {
            "log_return": log_return,
            "point_return": math.expm1(log_return["p50"]),
            "probability_up": float(row["probability_up"]),
            "median_index": anchor_value * math.exp(log_return["p50"]),
            "band_index": {
                name: anchor_value * math.exp(log_return[name])
                for name in ("p10", "p25", "p75", "p90")
            },
        }
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
            }
            for row in (latest.get("operational", {}).get("freshness") or [])
        ],
        # 밴드 차트 좌측 실적선: 최근 63세션 종가 (visible 표면에만 존재).
        "history": history or None,
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
    return build_projection(
        latest, anchor_value=anchor_value, sealed_row=sealed_row, history=history,
        resolutions=_forward_resolutions(root))
