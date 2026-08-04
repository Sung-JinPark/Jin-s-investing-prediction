"""NASDAQ 시장 맵 시나리오 — 공개 종가에서 재생성 가능한 버전형 스냅샷.

기존 2026-07-14 수동 시나리오는 감사 가능한 fallback vintage로 보존한다.
현재 시나리오는 Yahoo ^IXIC 확정 일봉과 고정 seed GBM으로 생성하며, LLM 질문
확률과 섞지 않는다. 이 계층은 경로 비교용 모델 시나리오이지 투자 조언이 아니다.
"""

from __future__ import annotations

import csv
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .quant import feed, mc
from .market_session import completed_market_cutoff

SCHEMA_VERSION = 2
LATEST_RELATIVE_PATH = Path("data") / "scenarios" / "nasdaq_latest.json"
ARCHIVE_RELATIVE_DIR = Path("data") / "scenarios" / "archive"
CALENDAR_RELATIVE_PATH = Path("data") / "contracts" / "nyse_holidays.yaml"
BAND_CALIBRATION_PATH = Path("data") / "scenarios" / "band_calibration.csv"
REFERENCE_PRICE = 26206.89  # F3 불변 기준가: 2026-07-09 ^IXIC 종가
LOOKBACK_DAYS = 252
FORECAST_HORIZON = 252
N_PATHS = 20_000
SEED = 42

BAND_CALIBRATION_FIELDS = [
    "asof", "origin_asof", "origin_snapshot_id", "actual_close", "p10", "p25",
    "p50", "p75", "p90", "inside_p10_p90", "p50_error_pct", "probability_space",
]

# 2026년 확정 일정. 향후 연도는 별도 캘린더 공급자로 교체하되, 미확정 일정을
# 자동 추정해 넣지 않는다.
EVENTS_2026: tuple[tuple[date, str], ...] = (
    (date(2026, 8, 7), "8/7 고용"),
    (date(2026, 8, 26), "8/26 NVDA"),
    (date(2026, 9, 16), "9/15–16 FOMC"),
    (date(2026, 9, 29), "9/29 미드텀 저점 중위"),
    (date(2026, 10, 28), "10/27–28 FOMC"),
    (date(2026, 11, 3), "11/3 중간선거"),
    (date(2026, 12, 9), "12/8–9 FOMC·산타랠리"),
)

# 7/14 수동 시나리오의 닷컴 참조선 모양만 정규화해 최신 앵커에 재기준화한다.
_ANALOG_VALUES = np.asarray([
    26107, 26918, 25300, 24794, 23943, 24787, 24886, 25925, 26717,
    27130, 26966, 25752, 25718, 27125, 25671, 26467, 27876, 29152,
    30269, 31661, 32399, 33083, 34019, 35267, 37301, 38239,
], dtype=float)
_ANALOG_RATIOS = _ANALOG_VALUES / _ANALOG_VALUES[0]


class ScenarioError(ValueError):
    """시나리오 입력 또는 스키마가 안전 기준을 충족하지 않음."""


def load_calendar_contract(root: Path) -> dict[str, Any]:
    """Load the pre-registered NYSE holiday rules used for future date labels."""
    path = root / CALENDAR_RELATIVE_PATH
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioError(f"NYSE calendar contract unavailable: {path}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ScenarioError("unsupported NYSE calendar contract")
    if payload.get("calendar") != "NYSE" or not isinstance(payload.get("rules"), list):
        raise ScenarioError("invalid NYSE calendar contract")
    return payload


def _observed_fixed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    cursor = date(year, month, 1)
    offset = (weekday - cursor.weekday()) % 7
    return cursor + timedelta(days=offset + 7 * (ordinal - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    """Gregorian computus; NYSE Good Friday is Easter Sunday minus two days."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _holiday_for_rule(year: int, rule: dict[str, Any]) -> date | None:
    if year < int(rule.get("start_year", 1)):
        return None
    kind = rule.get("type")
    if kind == "fixed":
        day = date(year, int(rule["month"]), int(rule["day"]))
        return _observed_fixed(day) if rule.get("observed") == "nearest_weekday" else day
    if kind == "nth_weekday":
        return _nth_weekday(
            year, int(rule["month"]), int(rule["weekday"]), int(rule["ordinal"]))
    if kind == "last_weekday":
        return _last_weekday(year, int(rule["month"]), int(rule["weekday"]))
    if kind == "easter_offset":
        return _easter_sunday(year) + timedelta(days=int(rule["offset_days"]))
    raise ScenarioError(f"unsupported NYSE holiday rule: {kind!r}")


def future_trading_days(asof: date, count: int, calendar: dict[str, Any]) -> list[date]:
    """Return deterministic future NYSE labels without an external calendar API."""
    if count < 1:
        return []
    holidays: set[date] = set()
    for year in range(asof.year, asof.year + 3):
        for rule in calendar["rules"]:
            holiday = _holiday_for_rule(year, rule)
            if holiday is not None:
                holidays.add(holiday)
    for raw in calendar.get("one_off_closures") or []:
        holidays.add(_iso_day(str(raw)))
    out: list[date] = []
    cursor = asof
    while len(out) < count:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5 and cursor not in holidays:
            out.append(cursor)
    return out


def _iso_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ScenarioError(f"invalid scenario asof: {value!r}") from exc


_QUANTILE_KEYS = ("p05", "p10", "p25", "p50", "p75", "p90", "p95")


def _blocked_quantile_table(asof: str, reason: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": reason,
        "probability_space": "scenario_conditional",
        "basis": "lookup unavailable for legacy manual vintage",
        "asof": asof,
        "trading_days": [],
        "quantiles": {key: [] for key in _QUANTILE_KEYS},
        "prob_above_anchor": [],
        "prob_above_ath": [],
        "probability_label": "model_conditional",
        "per_scenario_p50": {key: [] for key in ("S1", "S2", "S3")},
    }


def _validate_quantile_table(table: Any, asof: date) -> None:
    if not isinstance(table, dict):
        raise ScenarioError("scenario quantile_table must be an object")
    if table.get("probability_space") != "scenario_conditional":
        raise ScenarioError("quantile_table probability_space must be scenario_conditional")
    if table.get("probability_label") != "model_conditional":
        raise ScenarioError("quantile_table probabilities must be labelled model_conditional")
    if table.get("status") == "blocked":
        if table.get("trading_days") != []:
            raise ScenarioError("blocked quantile_table must not contain trading days")
        return
    days = table.get("trading_days")
    quantiles = table.get("quantiles")
    if not isinstance(days, list) or len(days) != FORECAST_HORIZON:
        raise ScenarioError("quantile_table must contain 252 trading days")
    parsed = [_iso_day(value) for value in days]
    if parsed[0] <= asof or any(right <= left for left, right in zip(parsed, parsed[1:])):
        raise ScenarioError("quantile_table trading_days must be strictly increasing after asof")
    if not isinstance(quantiles, dict) or set(quantiles) != set(_QUANTILE_KEYS):
        raise ScenarioError("quantile_table quantiles must be p05/p10/p25/p50/p75/p90/p95")
    series = [quantiles[key] for key in _QUANTILE_KEYS]
    arrays = series + [table.get("prob_above_anchor"), table.get("prob_above_ath")]
    per_scenario = table.get("per_scenario_p50")
    if not isinstance(per_scenario, dict) or set(per_scenario) != {"S1", "S2", "S3"}:
        raise ScenarioError("quantile_table per_scenario_p50 must be S1/S2/S3")
    arrays.extend(per_scenario.values())
    if any(not isinstance(values, list) or len(values) != len(days) for values in arrays):
        raise ScenarioError("quantile_table series length mismatch")
    for index in range(len(days)):
        values = [row[index] for row in series]
        if any(not isinstance(value, (int, float)) for value in values):
            raise ScenarioError("quantile_table values must be numeric")
        if any(right < left for left, right in zip(values, values[1:])):
            raise ScenarioError("quantile_table quantiles must be monotonic")
    for key in ("prob_above_anchor", "prob_above_ath"):
        if any(not isinstance(value, int) or not 0 <= value <= 100 for value in table[key]):
            raise ScenarioError(f"quantile_table {key} must be integer percent")


def validate_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    """대시보드가 신뢰할 수 있는 최소 시나리오 계약을 검증한다."""
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioError("unsupported scenario schema_version")
    asof = _iso_day(payload.get("asof", ""))
    if not all(isinstance(payload.get(k), (int, float)) and payload[k] > 0
               for k in ("anchor", "ath", "corr10")):
        raise ScenarioError("scenario anchor/ath/corr10 must be positive")
    weeks = payload.get("weeks")
    paths = payload.get("paths")
    risk = payload.get("risk")
    if not isinstance(weeks, list) or len(weeks) < 2:
        raise ScenarioError("scenario weeks must contain at least two points")
    if not isinstance(paths, dict) or set(paths) != {"S1", "S2", "S3"}:
        raise ScenarioError("scenario paths must be S1/S2/S3")
    if sum(int(paths[k].get("prob", -1)) for k in ("S1", "S2", "S3")) != 100:
        raise ScenarioError("scenario path probabilities must sum to 100")
    for key in ("S1", "S2", "S3"):
        values = paths[key].get("values")
        if not isinstance(values, list) or len(values) != len(weeks):
            raise ScenarioError(f"scenario {key} values length mismatch")
    if not isinstance(risk, list) or len(risk) != len(weeks):
        raise ScenarioError("scenario risk length mismatch")
    _validate_quantile_table(payload.get("quantile_table"), asof)
    return payload


def load_latest_scenario(root: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    """최신 스냅샷을 읽고, 부재·손상 시 archive → legacy 순서로 fail-safe."""
    path = root / LATEST_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return validate_scenario(payload)
    except (OSError, json.JSONDecodeError, ScenarioError):
        pass
    archive_dir = root / ARCHIVE_RELATIVE_DIR
    if archive_dir.exists():
        for archive in sorted(archive_dir.glob("*.json"), reverse=True):
            try:
                recovered = validate_scenario(json.loads(archive.read_text(encoding="utf-8")))
                recovered = deepcopy(recovered)
                recovered["recovered_from_archive"] = True
                return recovered
            except (OSError, json.JSONDecodeError, ScenarioError):
                continue
    legacy = deepcopy(fallback)
    legacy.setdefault("schema_version", SCHEMA_VERSION)
    legacy.setdefault("generated_at", "2026-07-15T00:00:00+00:00")
    legacy.setdefault("method", "manual-audited-vintage")
    legacy.setdefault("source", "reports/md/nasdaq_weekly_scenario_v3_1_1_260715.md")
    legacy.setdefault(
        "quantile_table",
        _blocked_quantile_table(legacy["asof"], "legacy vintage has no retained daily paths"),
    )
    legacy["fallback"] = True
    return validate_scenario(legacy)


def summarize_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    """정적 대시보드용 압축 요약 — 전체 주간 경로와 이벤트는 반복하지 않는다."""
    valid = validate_scenario(payload)
    return {
        "asof": valid["asof"],
        "generated_at": valid.get("generated_at"),
        "anchor": valid["anchor"],
        "bands": deepcopy(valid.get("bands", {})),
        "paths": {
            key: {
                "prob": valid["paths"][key]["prob"],
                "end": valid["paths"][key]["end"],
            }
            for key in ("S1", "S2", "S3")
        },
        "method": valid.get("method", "unknown"),
    }


def load_scenario_history(root: Path, latest: dict[str, Any], *,
                          limit: int = 12) -> list[dict[str, Any]]:
    """날짜별 아카이브에서 최신 N개 압축 요약을 읽는다.

    손상 파일은 해당 날짜만 건너뛰고 latest는 항상 후보에 포함한다. 반환 순서는
    오래된 날짜에서 최신 날짜 순이다.
    """
    if limit < 1:
        return []
    by_day: dict[str, dict[str, Any]] = {}
    archive_dir = root / ARCHIVE_RELATIVE_DIR
    if archive_dir.exists():
        for path in sorted(archive_dir.glob("*.json"), reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                summary = summarize_scenario(payload)
            except (OSError, json.JSONDecodeError, ScenarioError, KeyError, TypeError):
                continue
            by_day[summary["asof"]] = summary
            if len(by_day) >= limit:
                break
    try:
        current = summarize_scenario(latest)
        by_day[current["asof"]] = current
    except (ScenarioError, KeyError, TypeError):
        pass
    return [by_day[day] for day in sorted(by_day)[-limit:]]


def _week_dates(asof: date, end: date) -> list[date]:
    out = [asof]
    cursor = asof
    while cursor < end:
        cursor = min(end, cursor + timedelta(days=7))
        if cursor != out[-1]:
            out.append(cursor)
    return out


def _future_index(asof: date, target: date, horizon: int) -> int:
    if target <= asof:
        return -1
    first = asof + timedelta(days=1)
    idx = int(np.busday_count(first, target + timedelta(days=1))) - 1
    return max(0, min(horizon - 1, idx))


def _partition_probabilities(masks: tuple[np.ndarray, np.ndarray, np.ndarray]
                             ) -> tuple[int, int, int]:
    raw = [float(mask.mean() * 100) for mask in masks]
    rounded = [int(round(value)) for value in raw]
    rounded[int(np.argmax(raw))] += 100 - sum(rounded)
    return tuple(max(0, value) for value in rounded)  # type: ignore[return-value]


def _representative(sampled: np.ndarray, mask: np.ndarray,
                    fallback_percentile: float) -> np.ndarray:
    if bool(mask.any()):
        values = np.median(sampled[mask], axis=0)
    else:
        values = np.percentile(sampled, fallback_percentile, axis=0)
    values[0] = sampled[0, 0]
    return values


def build_scenario(dates: list[date], closes: list[float], *,
                   generated_at: datetime | None = None,
                   n_paths: int = N_PATHS, seed: int = SEED,
                   calendar: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the year-end partition and a 252-session lookup from one GBM draw."""
    if len(dates) != len(closes) or len(closes) < LOOKBACK_DAYS + 1:
        raise ScenarioError("at least 253 aligned daily closes are required")
    if any(b <= a for a, b in zip(dates, dates[1:])):
        raise ScenarioError("scenario dates must be strictly increasing")
    if not all(np.isfinite(closes)) or min(closes) <= 0:
        raise ScenarioError("scenario closes must be finite and positive")

    asof = dates[-1]
    year_end = date(asof.year, 12, 31)
    if asof >= year_end:
        raise ScenarioError("year-end scenario requires an asof before December 31")
    calendar = calendar or load_calendar_contract(Path(__file__).resolve().parents[2])
    trading_days = future_trading_days(asof, FORECAST_HORIZON, calendar)
    year_end_indexes = [index for index, day in enumerate(trading_days) if day <= year_end]
    if len(year_end_indexes) < 2:
        raise ScenarioError("scenario year-end partition horizon is too short")
    year_end_index = year_end_indexes[-1]

    anchor = float(closes[-1])
    ath = float(max(closes))
    corr10 = ath * 0.9
    # This is the only simulation call. Every weekly line and lookup statistic below
    # is derived from the same paths, preserving fixed-seed determinism.
    future = mc.gbm_paths(
        closes, lookback=min(LOOKBACK_DAYS, len(closes) - 1),
        horizon=FORECAST_HORIZON, n=n_paths, seed=seed)

    graph_indexes = list(range(4, FORECAST_HORIZON, 5))
    if graph_indexes[-1] != FORECAST_HORIZON - 1:
        graph_indexes.append(FORECAST_HORIZON - 1)
    week_dates = [asof] + [trading_days[index] for index in graph_indexes]
    sampled = np.empty((n_paths, len(week_dates)), dtype=float)
    sampled[:, 0] = anchor
    for column, index in enumerate(graph_indexes, start=1):
        sampled[:, column] = future[:, index]

    classification = future[:, :year_end_index + 1]
    hit_ath = (classification > ath).any(axis=1)
    end_above_reference = classification[:, -1] > REFERENCE_PRICE
    s1 = hit_ath
    s2 = ~hit_ath & end_above_reference
    s3 = ~(s1 | s2)
    masks = {"S1": s1, "S2": s2, "S3": s3}
    p1, p2, p3 = _partition_probabilities((s1, s2, s3))

    representative = {
        "S1": _representative(sampled, s1, 75),
        "S2": _representative(sampled, s2, 50),
        "S3": _representative(sampled, s3, 25),
    }
    labels = {
        "S1": "상승·ATH 돌파",
        "S2": "상승·ATH 미달",
        "S3": "조정·횡보",
    }
    colors = {"S1": "#ff4f17", "S2": "#ff9d19", "S3": "#c9002d"}
    probs = {"S1": p1, "S2": p2, "S3": p3}

    risk: list[str] = []
    for column, target in enumerate(week_dates):
        index = -1 if column == 0 else graph_indexes[column - 1]
        breach = 0.0 if index < 0 else float((future[:, :index + 1] <= corr10).any(axis=1).mean())
        risk.append("고" if breach >= 0.35 else ("중" if breach >= 0.15 else "저"))

    events = []
    for row, (event_date, label) in enumerate(EVENTS_2026):
        if asof <= event_date <= trading_days[-1]:
            nearest = min(range(len(week_dates)), key=lambda index: abs((week_dates[index] - event_date).days))
            events.append([nearest, label, row % 2])

    analog = np.interp(
        np.linspace(0, len(_ANALOG_RATIOS) - 1, len(week_dates)),
        np.arange(len(_ANALOG_RATIOS)), _ANALOG_RATIOS) * anchor
    terminal = classification[:, -1]
    made_at = generated_at or datetime.now(timezone.utc)

    def round_index(values: np.ndarray) -> list[int]:
        return [int(round(float(value) / 10) * 10) for value in values]

    daily_quantiles = np.percentile(future, (5, 10, 25, 50, 75, 90, 95), axis=0)
    fallback_percentiles = {"S1": 75, "S2": 50, "S3": 25}
    conditional_medians = {
        key: np.median(future[mask], axis=0) if bool(mask.any())
        else np.percentile(future, fallback_percentiles[key], axis=0)
        for key, mask in masks.items()
    }
    quantile_table = {
        "status": "ok",
        "probability_space": "scenario_conditional",
        "basis": (
            f"GBM daily 252d · {n_paths:,} paths · seed {seed} · asof close anchor; "
            "probabilities are model-conditional, not event probabilities"
        ),
        "asof": asof.isoformat(),
        "calendar": "NYSE pre-registered fixed holiday rules; emergency closures corrected next refresh",
        "sampling": "daily D+1..D+252; no interpolation",
        "trading_days": [day.isoformat() for day in trading_days],
        "quantiles": {
            key: round_index(daily_quantiles[index])
            for index, key in enumerate(_QUANTILE_KEYS)
        },
        "prob_above_anchor": [
            int(round(float(value) * 100)) for value in (future > anchor).mean(axis=0)
        ],
        "prob_above_ath": [
            int(round(float(value) * 100)) for value in (future > ath).mean(axis=0)
        ],
        "probability_label": "model_conditional",
        "per_scenario_p50": {
            key: round_index(values) for key, values in conditional_medians.items()
        },
        "per_scenario_counts": {key: int(mask.sum()) for key, mask in masks.items()},
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "asof": asof.isoformat(),
        "generated_at": made_at.isoformat(timespec="seconds"),
        "method": "gbm-daily-252d-v2-lookup",
        "source": "Yahoo Finance chart API · ^IXIC 확정 일봉",
        "anchor": round(anchor, 2),
        "ath": round(ath, 2),
        "corr10": round(corr10, 2),
        "reference_price": REFERENCE_PRICE,
        "bands": {
            "eoy_median": int(round(float(np.median(terminal)))),
            "eoy_50": [int(round(float(np.percentile(terminal, 25)))),
                       int(round(float(np.percentile(terminal, 75))))],
            "eoy_80": [int(round(float(np.percentile(terminal, 10)))),
                       int(round(float(np.percentile(terminal, 90))))],
        },
        "fan": {
            "probability_space": "scenario_conditional",
            "quantiles": {
                f"p{quantile}": [
                    int(round(float(value)))
                    for value in np.percentile(sampled, quantile, axis=0)
                ]
                for quantile in (5, 10, 25, 50, 75, 90, 95)
            },
            "monitoring": "daily-discrete",
            "baseline_method": "gbm-daily-252d-v2-lookup",
        },
        "quantile_table": quantile_table,
        "weeks": [f"{day.month}/{day.day}" for day in week_dates],
        "week_dates": [day.isoformat() for day in week_dates],
        "paths": {
            key: {
                "label": labels[key],
                "prob": probs[key],
                "color": colors[key],
                "end": int(round(float(representative[key][-1]))),
                "values": [int(round(float(value))) for value in representative[key]],
            }
            for key in ("S1", "S2", "S3")
        },
        "analog": {
            "label": "닷컴 아날로그 (참조선 — 시나리오 아님)",
            "color": "#706f68",
            "clip": int(round(anchor * 1.25)),
            "values": [int(round(float(value))) for value in analog],
        },
        "risk": risk,
        "events": events,
        "model": {
            "lookback_days": min(LOOKBACK_DAYS, len(closes) - 1),
            "horizon_business_days": FORECAST_HORIZON,
            "classification_date": trading_days[year_end_index].isoformat(),
            "n_paths": n_paths,
            "seed": seed,
            "partition": {
                "S1": "연말까지 현재 cycle ATH 신규 돌파",
                "S2": "ATH 미돌파 AND 연말 종가 > 2026-07-09 고정 기준가",
                "S3": "나머지 조정·횡보",
            },
            "probability_space": "scenario_conditional",
            "promotion_state": "champion-baseline; v2 alternatives remain shadow",
        },
        "note": (
            "확정 일봉 252거래일의 수익률로 생성한 고정 seed GBM 조건부 분포. "
            "fat tail·정책 이벤트·실적 서프라이즈를 직접 모형화하지 않으며 질문별 "
            "physical_event 확률과 합산하지 않는다. 목표가·사건확률·투자자문이 아니다."
        ),
    }
    return validate_scenario(payload)


def _comparison_text(payload: dict[str, Any]) -> str:
    comparable = deepcopy(payload)
    for field in ("generated_at", "snapshot_id", "revision", "correction_id", "supersedes"):
        comparable.pop(field, None)
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _approved_correction_id(root: Path, asof: str) -> str | None:
    ledger = root / "calibration" / "corrections.csv"
    if not ledger.exists():
        return None
    with ledger.open(encoding="utf-8", newline="") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if row.get("target_table") == "scenario_snapshots"
            and row.get("target_key") == asof
            and row.get("status") == "approved"
        ]
    return rows[-1].get("correction_id") if rows else None


def _persist_scenario(root: Path, payload: dict[str, Any]) -> tuple[Path, dict[str, Any], bool]:
    """Persist a same-asof model change as an approved revision, never an overwrite."""
    latest = root / LATEST_RELATIVE_PATH
    archive_dir = root / ARCHIVE_RELATIVE_DIR
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    asof = payload["asof"]
    candidates = sorted(archive_dir.glob(f"{asof}*.json"))
    target = _comparison_text(payload)
    for archive in candidates:
        try:
            raw = archive.read_text(encoding="utf-8")
            existing = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            continue
        if _comparison_text(existing) == target:
            changed = not latest.exists() or latest.read_text(encoding="utf-8") != raw
            if changed:
                latest.write_text(raw, encoding="utf-8", newline="\n")
            return latest, existing, changed
    persisted = deepcopy(payload)
    if candidates:
        correction_id = _approved_correction_id(root, asof)
        if not correction_id:
            raise ScenarioError(
                f"immutable scenario archive conflict for {asof}; approved correction required")
        revisions = []
        for path in candidates:
            try:
                revisions.append(int(json.loads(path.read_text(encoding="utf-8")).get("revision") or 1))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        revision = max(revisions or [1]) + 1
        persisted.update({
            "snapshot_id": f"nasdaq-scenario:{asof}:r{revision}",
            "revision": revision,
            "correction_id": correction_id,
            "supersedes": f"nasdaq-scenario:{asof}:r{revision - 1}",
        })
        archive = archive_dir / f"{asof}_{correction_id}.json"
    else:
        persisted.update({"snapshot_id": f"nasdaq-scenario:{asof}:r1", "revision": 1})
        archive = archive_dir / f"{asof}.json"
    serialized = json.dumps(persisted, ensure_ascii=False, indent=2) + "\n"
    if archive.exists():
        existing = json.loads(archive.read_text(encoding="utf-8"))
        if _comparison_text(existing) != _comparison_text(persisted):
            raise ScenarioError(f"immutable scenario revision conflict: {archive}")
        return latest, existing, False
    archive.write_text(serialized, encoding="utf-8", newline="\n")
    latest.write_text(serialized, encoding="utf-8", newline="\n")
    return latest, persisted, True


def append_band_calibration(root: Path, *, asof: date, actual_close: float) -> bool:
    """Score the close against a prior immutable fan band without backfilling UI claims."""
    candidates: list[dict[str, Any]] = []
    archive_dir = root / ARCHIVE_RELATIVE_DIR
    if archive_dir.exists():
        for path in archive_dir.glob("*.json"):
            try:
                payload = validate_scenario(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, ScenarioError):
                continue
            if (
                payload["asof"] < asof.isoformat()
                and asof.isoformat() in (payload.get("quantile_table") or {}).get(
                    "trading_days", [])
            ):
                candidates.append(payload)
    if not candidates:
        return False
    origin = max(candidates, key=lambda item: (item["asof"], int(item.get("revision") or 1)))
    table = origin["quantile_table"]
    index = table["trading_days"].index(asof.isoformat())
    values = {key: table["quantiles"][key][index] for key in ("p10", "p25", "p50", "p75", "p90")}
    row: dict[str, Any] = {
        "asof": asof.isoformat(), "origin_asof": origin["asof"],
        "origin_snapshot_id": origin.get("snapshot_id") or f"nasdaq-scenario:{origin['asof']}:r1",
        "actual_close": round(float(actual_close), 2), **values,
        "inside_p10_p90": str(values["p10"] <= actual_close <= values["p90"]).lower(),
        "p50_error_pct": round((actual_close / values["p50"] - 1) * 100, 3),
        "probability_space": "scenario_conditional",
    }
    path = root / BAND_CALIBRATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != BAND_CALIBRATION_FIELDS:
                raise ScenarioError("band_calibration schema drift")
            existing = {(item["asof"], item["origin_snapshot_id"]): item for item in reader}
    key = (row["asof"], row["origin_snapshot_id"])
    text_row = {field: str(row[field]) for field in BAND_CALIBRATION_FIELDS}
    if key in existing:
        if existing[key] != text_row:
            raise ScenarioError(f"append-only band calibration conflict for {key}")
        return False
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BAND_CALIBRATION_FIELDS, lineterminator="\n")
        if path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(row)
    return True


def refresh_scenario(root: Path, *, asof: date | None = None,
                     force: bool = False, now: datetime | None = None
                     ) -> tuple[Path, dict[str, Any], bool]:
    """Yahoo 확정 일봉을 수집해 latest와 날짜별 archive를 갱신한다."""
    today = date.today()
    cutoff = completed_market_cutoff(asof or today, now=now)
    dates, closes = feed.yahoo_series(
        "^IXIC", date(2023, 1, 1), cutoff + timedelta(days=1), "1d")
    aligned = [(day, close) for day, close in zip(dates, closes) if day <= cutoff]
    if not aligned:
        raise ScenarioError("Yahoo returned no completed ^IXIC closes")
    dates = [item[0] for item in aligned]
    closes = [item[1] for item in aligned]
    payload = build_scenario(
        dates, closes, calendar=load_calendar_contract(root))

    latest = root / LATEST_RELATIVE_PATH
    if latest.exists() and not force:
        try:
            current = validate_scenario(json.loads(latest.read_text(encoding="utf-8")))
            if current["asof"] == payload["asof"]:
                append_band_calibration(root, asof=dates[-1], actual_close=closes[-1])
                return latest, current, False
        except (OSError, json.JSONDecodeError, ScenarioError):
            pass

    result = _persist_scenario(root, payload)
    append_band_calibration(root, asof=dates[-1], actual_close=closes[-1])
    return result
