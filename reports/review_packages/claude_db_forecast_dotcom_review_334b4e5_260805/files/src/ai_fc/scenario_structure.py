"""DB-conditioned path shapes for the NASDAQ scenario chart.

The distribution and scenario weights remain owned by :mod:`ai_fc.scenario`.
This module only replaces the visually misleading cross-sectional median line
with a deterministic structural path.  Its turns come from the committed
innovation-era panel and its correction amplitude is calibrated to the
committed multi-era correction base rate.  A registered physical-event
probability is carried as separate evidence and is never used arithmetically.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import yaml


CONTRACT_PATH = Path("data/contracts/scenario_structural_forecast.yaml")
CONTEXT_DIR = Path("data/ml_history")
BASE_RATE_PATH = Path("data/base_rates/dotcom_analog_auto.md")
AI_REGIME_PATH = Path("data/ai_capital_cycle/ai_regime_latest.json")
TRACKER_PATH = Path("data/signals/scenario_tracker_latest.json")
LIQUIDITY_PATH = Path("data/liquidity/liquidity_latest.json")
QUESTION_ID = "nasdaq-corr10-augoct-2026"


class StructuralForecastError(ValueError):
    """Committed structural inputs or output failed their contract."""


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StructuralForecastError(f"structural forecast contract unavailable: {path}") from exc
    if not isinstance(payload, dict):
        raise StructuralForecastError("structural forecast contract must be an object")
    return payload


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return deepcopy(fallback)
    return payload if isinstance(payload, dict) else deepcopy(fallback)


def _latest_context(root: Path) -> dict[str, Any]:
    latest: dict[str, Any] | None = None
    latest_key = ""
    for path in sorted((root / CONTEXT_DIR).glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for position, line in enumerate(lines):
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if row.get("kind") != "context" or not isinstance(row.get("overlay"), dict):
                continue
            key = f"{row.get('run_ts') or ''}|{path.name}|{position:09d}"
            if key >= latest_key:
                latest, latest_key = row, key
    if latest is None:
        raise StructuralForecastError("committed innovation-cycle context is unavailable")
    return latest


def _episode_base_rates(root: Path) -> dict[str, Any]:
    try:
        text = (root / BASE_RATE_PATH).read_text(encoding="utf-8")
    except OSError as exc:
        raise StructuralForecastError("correction episode base-rate report is unavailable") from exc
    result: dict[str, Any] = {"source": BASE_RATE_PATH.as_posix()}
    for era in ("dotcom", "ai"):
        match = re.search(
            rf"^- {era}:\s*(\d+)회\s*·\s*깊이 중앙값\s*(-?[\d.]+)%",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        if not match:
            raise StructuralForecastError(f"{era} correction base rate is missing")
        result[era] = {
            "episodes": int(match.group(1)),
            "median_depth_pct": float(match.group(2)),
        }
    return result


def _latest_registered_forecast(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    candidates = sorted(
        path for path in (root / "forecasts").glob(f"**/*_{QUESTION_ID}_r*.md")
        if not path.stem.endswith("_evidence")
    )
    if not candidates:
        return {
            "status": "unavailable", "question_id": QUESTION_ID,
            "probability_space": "physical_event", "used_numerically": False,
        }
    path = candidates[-1]
    text = path.read_text(encoding="utf-8")
    blocks = text.split("---", 2)
    try:
        header = yaml.safe_load(blocks[1]) if len(blocks) >= 3 else {}
    except yaml.YAMLError:
        header = {}
    header = header if isinstance(header, dict) else {}
    window = contract["physical_event_reference"]["window"]
    return {
        "status": "registered",
        "question_id": QUESTION_ID,
        "forecast_id": header.get("forecast_id"),
        "probability_pct": header.get("probability"),
        "ci80_pct": header.get("ci80"),
        "window": [str(window[0]), str(window[1])],
        "threshold": header.get("snapshots", {}).get("threshold")
        if isinstance(header.get("snapshots"), dict) else None,
        "probability_space": "physical_event",
        "used_numerically": False,
        "separation_rule": "display in a separate box; never combine with scenario weights",
        "source": path.relative_to(root).as_posix(),
    }


def _interpolate(values: list[Any], phase: float) -> float:
    numeric = [float(value) for value in values]
    low = max(0, min(len(numeric) - 1, int(math.floor(phase))))
    high = min(len(numeric) - 1, low + 1)
    weight = max(0.0, min(1.0, phase - low))
    return numeric[low] * (1.0 - weight) + numeric[high] * weight


def _max_drawdown(values: list[int], dates: list[date], indexes: list[int]) -> dict[str, Any]:
    peak_value = float(values[indexes[0]])
    peak_index = indexes[0]
    trough_index = indexes[0]
    minimum = 0.0
    peak_before_trough = peak_index
    peak_value_before_trough = peak_value
    for index in indexes:
        value = float(values[index])
        if value > peak_value:
            peak_value, peak_index = value, index
        drawdown = value / peak_value - 1.0
        if drawdown < minimum:
            minimum = drawdown
            trough_index = index
            peak_before_trough = peak_index
            peak_value_before_trough = peak_value
    recovery = None
    for index in indexes:
        if index > trough_index and values[index] >= peak_value_before_trough:
            recovery = dates[index].isoformat()
            break
    return {
        "max_drawdown_pct": round(minimum * 100.0, 1),
        "peak_date": dates[peak_before_trough].isoformat(),
        "trough_date": dates[trough_index].isoformat(),
        "recovery_date": recovery,
        "recovery_status": "within_display_year" if recovery else "not_within_display_year",
    }


def _year_residual(raw: list[float], indexes: list[int], index: int) -> float:
    start, end = indexes[0], indexes[-1]
    if start == end:
        return 1.0
    position = (index - start) / (end - start)
    trend = raw[start] * ((raw[end] / raw[start]) ** position)
    return raw[index] / trend


def _structural_paths(
    scenario: dict[str, Any], dates: list[date], raw: list[float], strength: float
) -> dict[str, list[int]]:
    years = sorted({day.year for day in dates})
    output: dict[str, list[int]] = {}
    for key in ("S1", "S2", "S3"):
        source = [float(value) for value in scenario["paths"][key]["values"]]
        values: list[int | None] = [None] * len(dates)
        for year in years:
            indexes = [index for index, day in enumerate(dates) if day.year == year]
            start, end = indexes[0], indexes[-1]
            start_value, end_value = source[start], source[end]
            for position, index in enumerate(indexes):
                progress = position / max(1, len(indexes) - 1)
                baseline = start_value * ((end_value / start_value) ** progress)
                residual = _year_residual(raw, indexes, index)
                values[index] = int(round(baseline * (residual ** strength)))
        output[key] = [int(value) for value in values if value is not None]
    return output


def _calibration_strength(
    scenario: dict[str, Any], dates: list[date], raw: list[float],
    target_year: int, target_depth_pct: float, bounds: list[Any],
) -> float:
    indexes = [index for index, day in enumerate(dates) if day.year == target_year]
    if len(indexes) < 3:
        raise StructuralForecastError("calibration year has fewer than three chart points")
    low, high = float(bounds[0]), float(bounds[1])
    for _ in range(64):
        middle = (low + high) / 2.0
        values = _structural_paths(scenario, dates, raw, middle)["S1"]
        depth = abs(float(_max_drawdown(values, dates, indexes)["max_drawdown_pct"]))
        if depth < target_depth_pct:
            low = middle
        else:
            high = middle
    strength = (low + high) / 2.0
    achieved = abs(float(_max_drawdown(
        _structural_paths(scenario, dates, raw, strength)["S1"], dates, indexes
    )["max_drawdown_pct"]))
    if abs(achieved - target_depth_pct) > 0.2:
        raise StructuralForecastError("innovation correction calibration did not converge")
    return strength


def _analog_window(raw: list[float], dates: list[date], indexes: list[int]) -> dict[str, Any]:
    residuals = [_year_residual(raw, indexes, index) for index in indexes]
    trough_position = min(range(len(residuals)), key=residuals.__getitem__)
    trough = residuals[trough_position]
    threshold = 1.0 - max(0.005, (1.0 - trough) * 0.35)
    active = [position for position, value in enumerate(residuals) if value <= threshold]
    start_position = active[0] if active else trough_position
    end_position = active[-1] if active else trough_position
    return {
        "start": dates[indexes[start_position]].isoformat(),
        "end": dates[indexes[end_position]].isoformat(),
        "center_month": dates[indexes[trough_position]].strftime("%Y-%m"),
        "basis": "selected-era median detrended residual; monthly phase resolution",
        "exact_day_forecast": False,
    }


def build_structural_forecast(root: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, year-segmented path shape from committed DB layers."""
    contract = _read_yaml(root / CONTRACT_PATH)
    if contract.get("version") != "2026-08-05.v1":
        raise StructuralForecastError("unsupported structural forecast contract version")
    context = _latest_context(root)
    analog = context.get("analog") or {}
    overlay = context.get("overlay") or {}
    selected = list(analog.get("selected_eras") or [])
    minimum = int(contract["innovation_cycle"]["minimum_selected_eras"])
    if len(selected) < minimum or any(not isinstance(overlay.get(key), list) for key in selected):
        raise StructuralForecastError("selected innovation-era panel does not meet its gate")
    ai_values = overlay.get("ai")
    if not isinstance(ai_values, list) or len(ai_values) < 2:
        raise StructuralForecastError("AI phase series is unavailable")
    current_phase = len(ai_values) - 1
    dates = [date.fromisoformat(value) for value in scenario["week_dates"]]
    asof = date.fromisoformat(scenario["asof"])
    phase_days = float(contract["innovation_cycle"]["days_per_phase_month"])
    raw = []
    for day in dates:
        phase = current_phase + (day - asof).days / phase_days
        ratios = [
            _interpolate(overlay[key], phase) / float(overlay[key][current_phase])
            for key in selected
        ]
        raw.append(float(statistics.median(ratios)))

    target_depth_pct = abs(float(analog.get("correction_depth_median") or 0.0) * 100.0)
    if not 5.0 <= target_depth_pct <= 30.0:
        raise StructuralForecastError("multi-era correction depth is outside the contract gate")
    strength = _calibration_strength(
        scenario, dates, raw, asof.year, target_depth_pct,
        contract["calibration"]["strength_bounds"],
    )
    paths = _structural_paths(scenario, dates, raw, strength)
    year_rows = []
    for year in sorted({day.year for day in dates}):
        indexes = [index for index, day in enumerate(dates) if day.year == year]
        year_rows.append({
            "year": year,
            "start_index": indexes[0],
            "end_index": indexes[-1],
            "start_date": dates[indexes[0]].isoformat(),
            "end_date": dates[indexes[-1]].isoformat(),
            "coverage": "partial_year" if (
                dates[indexes[0]].month != 1 or dates[indexes[-1]].month != 12
            ) else "full_year",
            "analog_risk_window": _analog_window(raw, dates, indexes),
            "path_diagnostics": {
                key: _max_drawdown(paths[key], dates, indexes)
                for key in ("S1", "S2", "S3")
            },
        })

    ai_regime = _read_json(root / AI_REGIME_PATH, {"status": "unavailable"})
    tracker = _read_json(root / TRACKER_PATH, {"status": "unavailable"})
    liquidity = _read_json(root / LIQUIDITY_PATH, {"status": "unavailable"})
    episode_rates = _episode_base_rates(root)
    physical_event = _latest_registered_forecast(root, contract)
    output = {
        "status": "ok",
        "version": contract["version"],
        "method": "db-conditioned-innovation-ensemble-v1",
        "path_kind": "structural_forecast_not_random_sample",
        "probability_space": "scenario_conditional",
        "dates": [day.isoformat() for day in dates],
        "paths": {
            key: {
                "values": paths[key],
                "terminal_anchor_source": "unchanged scenario-conditional center endpoint",
            }
            for key in ("S1", "S2", "S3")
        },
        "years": year_rows,
        "calibration": {
            "target": "S1 origin-year maximum drawdown",
            "target_depth_pct": round(target_depth_pct, 2),
            "target_source": "latest innovation context correction_depth_median",
            "strength": round(strength, 6),
            "endpoint_rule": "preserve each scenario's existing year-segment endpoints",
        },
        "evidence": {
            "innovation_cycle": {
                "context_asof": analog.get("asof"),
                "available_at": context.get("run_ts"),
                "current_phase": current_phase,
                "selected_eras": selected,
                "selected_era_count": len(selected),
                "pool_era_count": analog.get("n_eras"),
                "correction_depth_median_pct": round(-target_depth_pct, 2),
                "source": "data/ml_history/*.jsonl kind=context",
                "used_for_path_shape": True,
            },
            "correction_episodes": episode_rates,
            "physical_event": physical_event,
            "scenario_tracker": {
                "asof": tracker.get("asof"), "status": tracker.get("status"),
                "counts": (tracker.get("summary") or {}).get("counts"),
                "probability_space": tracker.get("probability_space", "reference_only"),
                "used_numerically": False,
            },
            "liquidity": {
                "asof": liquidity.get("asof"), "status": liquidity.get("status"),
                "zone": liquidity.get("zone"), "zone_metric": liquidity.get("zone_metric"),
                "probability_space": liquidity.get("probability_space", "reference_only"),
                "used_numerically": False,
            },
            "ai_regime": {
                "asof": ai_regime.get("asof"), "status": ai_regime.get("status"),
                "coverage": ai_regime.get("coverage"),
                "coverage_threshold": ai_regime.get("coverage_threshold"),
                "used_numerically": False,
            },
        },
        "guardrails": {
            "probability_combination": "prohibited",
            "exact_correction_date_claim": "prohibited",
            "bubble_burst_date_claim": "prohibited",
            "simulation_sample_used_as_display_path": False,
            "fan_distribution_unchanged": True,
        },
        "limitations": [
            "선택 시대는 결과를 아는 소표본 역사 자료이며 독립 표본이 아니다.",
            "경로의 굴곡은 월 단위 위험창이지 특정 거래일 사건 예측이 아니다.",
            "조건부 분포의 확률·분위수와 physical_event 확률은 산술 결합하지 않는다.",
            "AI 자본사이클 레짐은 coverage 게이트가 닫혀 있어 수치 입력에서 제외했다.",
        ],
    }
    return validate_structural_forecast(output, len(dates))


def validate_structural_forecast(payload: Any, expected_length: int) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise StructuralForecastError("structural forecast must be an ok object")
    if payload.get("probability_space") != "scenario_conditional":
        raise StructuralForecastError("structural forecast probability space drifted")
    if payload.get("path_kind") != "structural_forecast_not_random_sample":
        raise StructuralForecastError("structural forecast path semantics drifted")
    dates = payload.get("dates")
    if not isinstance(dates, list) or len(dates) != expected_length:
        raise StructuralForecastError("structural forecast dates length mismatch")
    paths = payload.get("paths")
    if not isinstance(paths, dict) or set(paths) != {"S1", "S2", "S3"}:
        raise StructuralForecastError("structural forecast paths must be S1/S2/S3")
    for row in paths.values():
        values = row.get("values") if isinstance(row, dict) else None
        if (
            not isinstance(values, list) or len(values) != expected_length
            or any(not isinstance(value, int) or value <= 0 for value in values)
        ):
            raise StructuralForecastError("structural forecast path values are invalid")
    years = payload.get("years")
    if not isinstance(years, list) or len(years) < 1:
        raise StructuralForecastError("structural forecast year partitions are missing")
    previous_end = -1
    for row in years:
        start, end = row.get("start_index"), row.get("end_index")
        if not isinstance(start, int) or not isinstance(end, int) or start != previous_end + 1 or end < start:
            raise StructuralForecastError("structural forecast year partitions must be contiguous")
        previous_end = end
    if previous_end != expected_length - 1:
        raise StructuralForecastError("structural forecast year partitions do not cover the path")
    evidence = payload.get("evidence") or {}
    event = evidence.get("physical_event") or {}
    regime = evidence.get("ai_regime") or {}
    if event.get("used_numerically") is not False:
        raise StructuralForecastError("physical_event probability cannot enter structural arithmetic")
    if regime.get("status") == "blocked" and regime.get("used_numerically") is not False:
        raise StructuralForecastError("blocked AI regime cannot enter structural arithmetic")
    if (payload.get("guardrails") or {}).get("simulation_sample_used_as_display_path") is not False:
        raise StructuralForecastError("simulation samples cannot be the structural display path")
    return payload
