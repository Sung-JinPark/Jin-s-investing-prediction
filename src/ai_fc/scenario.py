"""NASDAQ 시장 맵 시나리오 — 공개 종가에서 재생성 가능한 버전형 스냅샷.

기존 2026-07-14 수동 시나리오는 감사 가능한 fallback vintage로 보존한다.
현재 시나리오는 Yahoo ^IXIC 확정 일봉과 고정 seed GBM으로 생성하며, LLM 질문
확률과 섞지 않는다. 이 계층은 경로 비교용 모델 시나리오이지 투자 조언이 아니다.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .quant import feed, mc

SCHEMA_VERSION = 1
LATEST_RELATIVE_PATH = Path("data") / "scenarios" / "nasdaq_latest.json"
ARCHIVE_RELATIVE_DIR = Path("data") / "scenarios" / "archive"
REFERENCE_PRICE = 26206.89  # F3 불변 기준가: 2026-07-09 ^IXIC 종가
LOOKBACK_DAYS = 252
N_PATHS = 20_000
SEED = 42

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


def _iso_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ScenarioError(f"invalid scenario asof: {value!r}") from exc


def validate_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    """대시보드가 신뢰할 수 있는 최소 시나리오 계약을 검증한다."""
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioError("unsupported scenario schema_version")
    _iso_day(payload.get("asof", ""))
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
                   n_paths: int = N_PATHS, seed: int = SEED) -> dict[str, Any]:
    """확정 일봉으로 연말까지 세 개의 상호배타 경로를 생성한다.

    S1 = 연말까지 현재 cycle ATH를 새로 돌파한 경로
    S2 = ATH 미돌파이면서 연말 종가가 F3 고정 기준가를 상회한 경로
    S3 = 나머지 조정·횡보 경로
    """
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
    first_future = asof + timedelta(days=1)
    horizon = int(np.busday_count(first_future, year_end + timedelta(days=1)))
    if horizon < 2:
        raise ScenarioError("scenario horizon is too short")

    anchor = float(closes[-1])
    ath = float(max(closes))
    corr10 = ath * 0.9
    future = mc.gbm_paths(
        closes, lookback=min(LOOKBACK_DAYS, len(closes) - 1),
        horizon=horizon, n=n_paths, seed=seed)
    week_dates = _week_dates(asof, year_end)
    sampled = np.empty((n_paths, len(week_dates)), dtype=float)
    sampled[:, 0] = anchor
    for column, target in enumerate(week_dates[1:], start=1):
        sampled[:, column] = future[:, _future_index(asof, target, horizon)]

    hit_ath = (future > ath).any(axis=1)
    end_above_reference = future[:, -1] > REFERENCE_PRICE
    s1 = hit_ath
    s2 = ~hit_ath & end_above_reference
    s3 = ~(s1 | s2)
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
    for target in week_dates:
        idx = _future_index(asof, target, horizon)
        breach = 0.0 if idx < 0 else float((future[:, :idx + 1] <= corr10).any(axis=1).mean())
        risk.append("고" if breach >= 0.35 else ("중" if breach >= 0.15 else "저"))

    events = []
    for row, (event_date, label) in enumerate(EVENTS_2026):
        if asof <= event_date <= year_end:
            events.append([
                round(min(len(week_dates) - 1, (event_date - asof).days / 7), 2),
                label, row % 2,
            ])

    analog = np.interp(
        np.linspace(0, len(_ANALOG_RATIOS) - 1, len(week_dates)),
        np.arange(len(_ANALOG_RATIOS)), _ANALOG_RATIOS) * anchor
    terminal = future[:, -1]
    made_at = generated_at or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "asof": asof.isoformat(),
        "generated_at": made_at.isoformat(timespec="seconds"),
        "method": "gbm-daily-252d-v1",
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
                for quantile in (5, 25, 50, 75, 95)
            },
            "monitoring": "daily-discrete",
            "baseline_method": "gbm-daily-252d-v1",
        },
        "weeks": [f"{day.month}/{day.day}" for day in week_dates],
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
            "horizon_business_days": horizon,
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
            "확정 일봉 252거래일의 수익률로 생성한 고정 seed GBM 조건부 중앙 경로. "
            "fat tail·정책 이벤트·실적 서프라이즈를 직접 모형화하지 않으며 질문별 "
            "LLM 확률과 합산하지 않는다. 참고 의견 — 투자 자문 아님."
        ),
    }
    return validate_scenario(payload)


def refresh_scenario(root: Path, *, asof: date | None = None,
                     force: bool = False) -> tuple[Path, dict[str, Any], bool]:
    """Yahoo 확정 일봉을 수집해 latest와 날짜별 archive를 갱신한다."""
    today = date.today()
    cutoff = asof or today
    dates, closes = feed.yahoo_series(
        "^IXIC", date(2023, 1, 1), cutoff + timedelta(days=1), "1d")
    aligned = [(day, close) for day, close in zip(dates, closes) if day <= cutoff]
    if not aligned:
        raise ScenarioError("Yahoo returned no completed ^IXIC closes")
    dates = [item[0] for item in aligned]
    closes = [item[1] for item in aligned]
    payload = build_scenario(dates, closes)

    latest = root / LATEST_RELATIVE_PATH
    if latest.exists() and not force:
        try:
            current = validate_scenario(json.loads(latest.read_text(encoding="utf-8")))
            if current["asof"] == payload["asof"]:
                return latest, current, False
        except (OSError, json.JSONDecodeError, ScenarioError):
            pass

    latest.parent.mkdir(parents=True, exist_ok=True)
    archive = root / ARCHIVE_RELATIVE_DIR / f"{payload['asof']}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    latest.write_text(text, encoding="utf-8")
    archive.write_text(text, encoding="utf-8")
    return latest, payload, True
