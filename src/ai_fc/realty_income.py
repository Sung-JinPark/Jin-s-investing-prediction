"""Auditable Realty Income rate/credit sensitivity and event-study layers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

from .quant import feed

MACRO_ASSUMPTIONS = Path("data/contracts/cross_asset_macro_assumptions.yaml")
RATE_EVENT_REGISTRY = Path("data/rate_events/registry.yaml")
DIVIDENDS = Path("data/realty_income/dividends.csv")
DIVIDEND_REFERENCE = Path("data/realty_income/sec_annual_dividend_reference.yaml")
SENSITIVITY_LATEST = Path("data/realty_income/rate_sensitivity_latest.json")
SENSITIVITY_ARCHIVE = Path("data/realty_income/rate_sensitivity_archive")
EVENT_STUDY_LATEST = Path("data/rate_events/event_study_latest.json")
EVENT_STUDY_ARCHIVE = Path("data/rate_events/archive")

SCENARIO_IDS = {
    "deleveraging", "easing_rotation", "soft_landing", "rates_stay_high",
}
REQUIRED_MONTHS = {0, 3, 6, 12, 24, 36, 48, 60}
MIN_WEEKS = 156
BOOTSTRAP_REPETITIONS = 1_000
BOOTSTRAP_BLOCK_WEEKS = 4
BOOTSTRAP_SEED = 20260804
HY_LEGACY_CAPTURE_URL = (
    "https://raw.githubusercontent.com/maaurocp/Trading_Protocol/"
    "bf64e83fa4c2a6e72c37d3883476dc81bd9d2e31/data/raw/fred_BAMLH0A0HYM2.csv"
)


class RealtyIncomeError(ValueError):
    """Contract, source, or append-only persistence violation."""


@dataclass(frozen=True)
class FredSeries:
    series_id: str
    dates: list[date]
    values: list[float]
    receipt: dict[str, Any]


def fetch_fred_series(
    series_id: str, start: date, *, fetch_text: Callable[..., str] = feed.get_with_curl_fallback,
) -> FredSeries:
    url = (
        "https://fred.stlouisfed.org/graph/fredgraph.csv?"
        f"id={series_id}&cosd={start.isoformat()}"
    )
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw = fetch_text(url, timeout=30)
    reader = csv.reader(io.StringIO(raw))
    header = next(reader, [])
    if len(header) < 2 or header[1] != series_id:
        raise RealtyIncomeError(f"FRED {series_id} schema mismatch")
    rows: list[tuple[date, float]] = []
    for row in reader:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            rows.append((date.fromisoformat(row[0]), float(row[1])))
        except ValueError:
            continue
    if not rows:
        raise RealtyIncomeError(f"FRED {series_id} returned no observations")
    return FredSeries(
        series_id, [row[0] for row in rows], [row[1] for row in rows],
        {
            "source": "fred_market_signals", "series_id": series_id,
            "request_url": url,
            "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "fetched_at": fetched_at, "revision_vintage": "captured_current",
        },
    )


def fetch_hy_event_history(
    start: date = date(1996, 1, 1), *,
    fetch_text: Callable[..., str] = feed.get_with_curl_fallback,
) -> FredSeries:
    """Fetch HY OAS for event studies, with a pinned legacy FRED capture fallback.

    FRED's public graph endpoint was reduced to a rolling three-year window in
    April 2026. The fallback is used only to calculate derived event diagnostics;
    raw observations are not persisted or redistributed by this repository.
    """
    current = (
        fetch_fred_series("BAMLH0A0HYM2", start)
        if fetch_text is feed.get_with_curl_fallback
        else fetch_fred_series("BAMLH0A0HYM2", start, fetch_text=fetch_text)
    )
    coverage_start = min(current.dates)
    receipt = deepcopy(current.receipt)
    receipt.update({
        "source": "fred_historical_event_study",
        "primary_request_url": receipt.pop("request_url"),
        "primary_response_sha256": receipt.pop("response_sha256"),
        "primary_coverage_start": coverage_start.isoformat(),
        "redistribution_policy": "derived_event_diagnostics_only",
    })
    if str(receipt["primary_request_url"]).startswith("mock://"):
        receipt["history_status"] = "test_fixture"
        receipt["request_url"] = receipt["primary_request_url"]
        receipt["response_sha256"] = receipt["primary_response_sha256"]
        return FredSeries(current.series_id, current.dates, current.values, receipt)
    if coverage_start <= date(2001, 1, 3):
        receipt["history_status"] = "available_from_primary"
        receipt["request_url"] = receipt["primary_request_url"]
        receipt["response_sha256"] = receipt["primary_response_sha256"]
        return FredSeries(current.series_id, current.dates, current.values, receipt)

    raw = fetch_text(HY_LEGACY_CAPTURE_URL, timeout=30)
    legacy: dict[date, float] = {}
    for row in csv.DictReader(io.StringIO(raw)):
        value = row.get("BAMLH0A0HYM2")
        if value in (None, "", "."):
            continue
        try:
            legacy[date.fromisoformat(str(row.get("date") or row.get("DATE")))] = float(value)
        except (TypeError, ValueError):
            continue
    if not legacy or min(legacy) > date(2001, 1, 3):
        raise RealtyIncomeError("legacy HY capture does not cover the preregistered events")
    merged = dict(legacy)
    merged.update(zip(current.dates, current.values, strict=True))
    rows = sorted((day, value) for day, value in merged.items() if day >= start)
    receipt.update({
        "history_status": "legacy_public_fred_capture_plus_current",
        "fallback_request_url": HY_LEGACY_CAPTURE_URL,
        "fallback_response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "fallback_coverage_start": rows[0][0].isoformat(),
        "request_url": HY_LEGACY_CAPTURE_URL,
        "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "limitation": (
            "The current official FRED graph feed exposes only three years; older "
            "observations come from a commit-pinned public capture of the FRED series."
        ),
    })
    return FredSeries(
        "BAMLH0A0HYM2", [row[0] for row in rows], [row[1] for row in rows], receipt)


def validate_macro_assumptions(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("probability_space") != "scenario_conditional":
        raise RealtyIncomeError("macro assumptions probability_space drifted")
    if set(payload.get("scenarios") or {}) != SCENARIO_IDS:
        raise RealtyIncomeError("macro assumptions require exactly four scenarios")
    if set(payload.get("required_months") or []) != REQUIRED_MONTHS:
        raise RealtyIncomeError("macro assumption required_months drifted")
    for scenario_id, scenario in payload["scenarios"].items():
        for key in ("delta_10y_bp", "delta_hy_bp"):
            curve = scenario.get(key) or {}
            if set(curve) != REQUIRED_MONTHS or float(curve[0]) != 0:
                raise RealtyIncomeError(
                    f"{scenario_id}.{key} must contain M0/M3/M6/M12/M24/M36/M48/M60 "
                    "and anchor at zero")
            if not all(math.isfinite(float(value)) for value in curve.values()):
                raise RealtyIncomeError(f"{scenario_id}.{key} contains a non-finite value")
    if float(payload.get("realty_income_price_carry_pct", 0)) != 0:
        raise RealtyIncomeError("Realty Income price-path carry must remain zero in v2")
    return payload


def load_macro_assumptions(root: Path) -> dict[str, Any]:
    path = root / MACRO_ASSUMPTIONS
    if not path.exists():
        raise RealtyIncomeError(f"missing preregistered macro assumptions: {path}")
    return validate_macro_assumptions(
        yaml.safe_load(path.read_text(encoding="utf-8")))


def load_event_registry(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / RATE_EVENT_REGISTRY).read_text(encoding="utf-8"))
    events = payload.get("events") or []
    ids = [item.get("event_id") for item in events]
    expected = [
        "dotcom_easing", "tightening_2004_2006", "taper_2013",
        "hikes_2015_2018", "acute_crisis_2020", "hikes_2022_2023",
    ]
    if ids != expected or len(set(ids)) != len(ids):
        raise RealtyIncomeError("rate-event registry must preserve the six preregistered events")
    for item in events:
        if date.fromisoformat(str(item["start"])) >= date.fromisoformat(str(item["end"])):
            raise RealtyIncomeError(f"invalid event window: {item['event_id']}")
    return payload


def load_tracker_hypothesis(root: Path) -> dict[str, Any]:
    """Read the single computed C1-C4 summary; never recompute it in the UI layer."""
    path = root / "data" / "signals" / "scenario_tracker_latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = payload["realty_income_hypothesis"]
        if summary.get("conditions_total") != 4 or len(summary.get("conditions") or []) != 4:
            raise ValueError("C1-C4 summary is incomplete")
        return deepcopy(summary)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {
            "status": "source_unavailable", "conditions_met": None,
            "conditions_total": 4, "conditions": [
                {"id": condition_id, "signal": signal_id, "met": False,
                 "signal_state": "source_unavailable", "status": "source_unavailable",
                 "metrics": {}, "as_of": None}
                for condition_id, signal_id in (
                    ("C1", "S1"), ("C2", "S8"), ("C3", "S2"), ("C4", "S9"))
            ],
            "text": f"C1-C4 tracker summary unavailable: {type(exc).__name__}",
        }


def load_dividend_reference(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / DIVIDEND_REFERENCE).read_text(encoding="utf-8"))
    annual = payload.get("annual") or {}
    if list(annual) != [2001, 2002, 2003, 2004, 2005]:
        raise RealtyIncomeError("SEC dividend reference must preserve 2001-2005 order")
    if not all(float(value) > 0 for value in annual.values()):
        raise RealtyIncomeError("SEC dividend reference contains invalid values")
    if not str(payload.get("source_url") or "").startswith("https://www.realtyincome.com/"):
        raise RealtyIncomeError("SEC dividend reference requires the official company source")
    return payload


def dividend_rows(
    result: feed.YahooDividendResult, *, asof: date,
) -> list[dict[str, Any]]:
    captured = str(result.receipt.get("fetched_at") or "")
    return [
        {
            "ex_date": day.isoformat(), "amount": round(float(amount), 6),
            "declared_at": captured, "available_at": captured,
            "source": "yahoo-chart-dividend-events",
            "source_url": str(result.receipt.get("request_url") or ""),
            "source_fingerprint": str(result.receipt.get("response_sha256") or ""),
            "revision_vintage": "captured_current",
            "availability_semantics": "first_repository_capture_not_corporate_declaration",
        }
        for day, amount in zip(result.dates, result.amounts, strict=True)
        if day <= asof and amount > 0
    ]


def append_dividends(root: Path, rows: list[dict[str, Any]]) -> tuple[Path, bool]:
    path = root / DIVIDENDS
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "ex_date", "amount", "declared_at", "available_at", "source", "source_url",
        "source_fingerprint", "revision_vintage", "availability_semantics",
    ]
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            existing = list(csv.DictReader(handle))
    by_date = {row["ex_date"]: row for row in existing}
    latest = max(by_date, default="")
    pending = []
    for row in sorted(rows, key=lambda item: item["ex_date"]):
        current = by_date.get(row["ex_date"])
        if current:
            if float(current["amount"]) != float(row["amount"]):
                raise RealtyIncomeError(
                    f"append-only dividend conflict for {row['ex_date']}; correction required")
            continue
        if latest and row["ex_date"] < latest:
            raise RealtyIncomeError(
                f"historical dividend insertion {row['ex_date']} requires a correction")
        pending.append(row)
    if not pending:
        return path, False
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        if path.stat().st_size == 0:
            writer.writeheader()
        writer.writerows({field: row[field] for field in fields} for row in pending)
    return path, True


def build_dividend_monitor(rows: list[dict[str, Any]], *, asof: date) -> dict[str, Any]:
    eligible = sorted(
        (row for row in rows if date.fromisoformat(row["ex_date"]) <= asof),
        key=lambda row: row["ex_date"],
    )
    recent = eligible[-12:]
    cuts = sum(float(right["amount"]) < float(left["amount"]) for left, right in zip(recent, recent[1:]))
    latest_change = None
    if len(recent) >= 2:
        latest_change = round(float(recent[-1]["amount"]) - float(recent[-2]["amount"]), 6)
    maintained = bool(recent) and cuts == 0
    return {
        "status": "maintained_or_increased" if maintained else "weakened_or_unavailable",
        "c4_met": maintained,
        "latest_ex_date": recent[-1]["ex_date"] if recent else None,
        "latest_amount": recent[-1]["amount"] if recent else None,
        "latest_change": latest_change,
        "cuts_last_12_events": cuts,
        "observations": len(recent),
        "semantics": "ex-date cash events; available_at is first repository capture",
    }


def build_dividend_crosscheck(
    rows: list[dict[str, Any]], reference: dict[str, Any],
) -> dict[str, Any]:
    yahoo_by_year: dict[int, float] = {}
    for row in rows:
        year = date.fromisoformat(row["ex_date"]).year
        if year in reference["annual"]:
            yahoo_by_year[year] = yahoo_by_year.get(year, 0.0) + float(row["amount"])
    years = list(reference["annual"])
    official = [float(reference["annual"][year]) for year in years]
    yahoo = [yahoo_by_year.get(year) for year in years]
    official_increasing = all(right > left for left, right in zip(official, official[1:]))
    yahoo_increasing = all(
        left is not None and right is not None and right > left
        for left, right in zip(yahoo, yahoo[1:])
    )
    return {
        "status": "direction_confirmed" if official_increasing and yahoo_increasing
        else "direction_mismatch_or_incomplete",
        "basis": {
            "official": "dividends paid per common share",
            "yahoo": "cash dividend events grouped by ex-date",
            "exact_total_equality_asserted": False,
        },
        "annual": [
            {
                "year": year, "official_paid_per_share": official[index],
                "yahoo_ex_date_sum": round(yahoo[index], 6) if yahoo[index] is not None else None,
            }
            for index, year in enumerate(years)
        ],
        "official_continuous_increase": official_increasing,
        "yahoo_ex_date_continuous_increase": yahoo_increasing,
        "source_url": reference["source_url"],
        "source_sha256": reference["source_sha256"],
        "source_pages": reference["source_pages"],
        "warning": reference["comparison_semantics"],
    }


def significance_gate(
    estimate: float | None, low: float | None, high: float | None, observations: int,
    previous: dict[str, Any] | None = None,
) -> tuple[float, str]:
    if estimate is None or low is None or high is None:
        return 0.0, "estimate_unavailable"
    if low <= 0 <= high:
        return 0.0, "ci_crosses_zero"
    if observations < MIN_WEEKS:
        prior_used = (previous or {}).get("used_effect_per_100bp_pct")
        prior_streak = int(
            ((previous or {}).get("gate_hysteresis") or {})
            .get("consecutive_sample_failures", 0)
        )
        if (isinstance(prior_used, (int, float)) and float(prior_used) != 0
                and prior_streak < 1):
            return round(float(prior_used), 3), "hysteresis_hold_1_of_2"
        return 0.0, f"insufficient_sample_{observations}_of_{MIN_WEEKS}"
    return round(float(estimate), 3), "eligible"


def _weekly_map(dates: list[date], values: list[float]) -> dict[tuple[int, int], tuple[date, float]]:
    result: dict[tuple[int, int], tuple[date, float]] = {}
    for day, value in zip(dates, values, strict=True):
        iso = day.isocalendar()
        result[(iso.year, iso.week)] = (day, float(value))
    return result


def _regression_rows(
    o: feed.YahooPriceSeriesResult, nasdaq: feed.YahooPriceSeriesResult,
    rate: FredSeries, credit: FredSeries | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    maps = [
        _weekly_map(o.dates, o.adjusted), _weekly_map(nasdaq.dates, nasdaq.adjusted),
        _weekly_map(rate.dates, rate.values),
    ]
    if credit:
        maps.append(_weekly_map(credit.dates, credit.values))
    common = sorted(set.intersection(*(set(mapping) for mapping in maps)))
    if len(common) < 3:
        return np.empty(0), np.empty((0, len(maps) - 1))
    levels = [[mapping[key][1] for key in common] for mapping in maps]
    y = np.diff(np.log(np.asarray(levels[0], dtype=float)))
    market = np.diff(np.log(np.asarray(levels[1], dtype=float)))
    factors = [market, np.diff(np.asarray(levels[2], dtype=float)) * 100]
    if credit:
        factors.append(np.diff(np.asarray(levels[3], dtype=float)) * 100)
    return y, np.column_stack(factors)


def _ols_factor(y: np.ndarray, x: np.ndarray, factor_index: int) -> float | None:
    if len(y) < max(30, x.shape[1] + 5) or len(y) != len(x):
        return None
    design = np.column_stack([np.ones(len(y)), x])
    try:
        coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None
    value = float(coefficients[factor_index + 1] * 10_000)
    return round(value, 3) if math.isfinite(value) else None


def _bootstrap_factor(
    y: np.ndarray, x: np.ndarray, factor_index: int, *, seed: int,
) -> tuple[float | None, float | None, int]:
    if len(y) < 30:
        return None, None, 0
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(len(y) / BOOTSTRAP_BLOCK_WEEKS))
    starts_max = max(1, len(y) - BOOTSTRAP_BLOCK_WEEKS + 1)
    offsets = np.arange(BOOTSTRAP_BLOCK_WEEKS)
    estimates = []
    for _ in range(BOOTSTRAP_REPETITIONS):
        starts = rng.integers(0, starts_max, size=blocks)
        indexes = (starts[:, None] + offsets).reshape(-1)[:len(y)]
        estimate = _ols_factor(y[indexes], x[indexes], factor_index)
        if estimate is not None:
            estimates.append(estimate)
    if not estimates:
        return None, None, 0
    return (
        round(float(np.percentile(estimates, 10)), 3),
        round(float(np.percentile(estimates, 90)), 3), len(estimates),
    )


def _sensitivity_record(
    y: np.ndarray, x: np.ndarray, factor_index: int, *, seed: int,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    estimate = _ols_factor(y, x, factor_index)
    low, high, samples = _bootstrap_factor(y, x, factor_index, seed=seed)
    used, status = significance_gate(estimate, low, high, len(y), previous)
    margin = len(y) - MIN_WEEKS
    prior_streak = int(
        ((previous or {}).get("gate_hysteresis") or {})
        .get("consecutive_sample_failures", 0)
    )
    sample_failed = status == "hysteresis_hold_1_of_2" or status.startswith(
        "insufficient_sample_")
    failure_streak = min(2, prior_streak + 1) if sample_failed else 0
    return {
        "measured_effect_per_100bp_pct": estimate,
        "bootstrap_10_90_pct": [low, high],
        "used_effect_per_100bp_pct": used,
        "status": status, "observations": len(y),
        "minimum_observations": MIN_WEEKS,
        "gate_margin_observations": margin,
        "gate_proximity": "at_boundary" if margin == 0 else (
            "near_boundary" if 0 < margin < 2 else (
                "below_boundary" if margin < 0 else "clear"
            )
        ),
        "gate_hysteresis": {
            "required_consecutive_failures": 2,
            "consecutive_sample_failures": failure_streak,
            "held_previous_effect": status == "hysteresis_hold_1_of_2",
        },
        "bootstrap_samples": samples, "block_weeks": BOOTSTRAP_BLOCK_WEEKS,
        "market_control": "NASDAQ weekly log return",
    }


def _asof_value(series: FredSeries, target: date) -> float | None:
    values = [value for day, value in zip(series.dates, series.values, strict=True) if day <= target]
    return values[-1] if values else None


def _ttm_dividend(rows: list[dict[str, Any]], target: date) -> float:
    start = target - timedelta(days=365)
    return sum(
        float(row["amount"]) for row in rows
        if start < date.fromisoformat(row["ex_date"]) <= target
    )


def build_rate_sensitivity(
    *, asof: date, o: feed.YahooPriceSeriesResult,
    nasdaq: feed.YahooPriceSeriesResult, fred: dict[str, FredSeries],
    dividends: list[dict[str, Any]], history_o: feed.YahooPriceSeriesResult,
    dividend_reference: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rate_y, rate_x = _regression_rows(o, nasdaq, fred["DGS10"])
    credit_y, credit_x = _regression_rows(
        o, nasdaq, fred["DGS10"], fred["BAMLH0A0HYM2"])
    rate = _sensitivity_record(
        rate_y[-MIN_WEEKS:], rate_x[-MIN_WEEKS:], 1, seed=BOOTSTRAP_SEED,
        previous=(previous or {}).get("beta_rate"))
    credit = _sensitivity_record(
        credit_y, credit_x, 2, seed=BOOTSTRAP_SEED + 1,
        previous=(previous or {}).get("beta_credit"))

    latest_close = next(
        (value for day, value in reversed(list(zip(o.dates, o.closes, strict=True))) if day <= asof),
        None,
    )
    dgs10 = _asof_value(fred["DGS10"], asof)
    ttm = _ttm_dividend(dividends, asof)
    yield_pct = ttm / latest_close * 100 if latest_close else None
    spread = yield_pct - dgs10 if yield_pct is not None and dgs10 is not None else None

    historical_spreads = []
    for day, close in zip(history_o.dates, history_o.closes, strict=True):
        if day < date(2000, 1, 1) or day > asof:
            continue
        if (day.year, day.month) == (asof.year, asof.month):
            continue
        historical_rate = _asof_value(fred["DGS10"], day)
        dividend = _ttm_dividend(dividends, day)
        if historical_rate is not None and close > 0 and dividend > 0:
            historical_spreads.append(dividend / close * 100 - historical_rate)
    percentile = None
    if spread is not None and historical_spreads:
        percentile = round(
            sum(value <= spread for value in historical_spreads) / len(historical_spreads) * 100, 1)

    receipts = [fred[key].receipt for key in ("DGS10", "DFII10", "BAMLH0A0HYM2", "BAMLC0A0CM", "FEDFUNDS")]
    fingerprints = sorted(str(item["response_sha256"]) for item in receipts)
    return {
        "schema_version": 1, "asof": asof.isoformat(),
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "probability_space": "reference_only", "status": "partial" if credit["status"] != "eligible" else "ok",
        "beta_rate": rate, "beta_credit": credit,
        "dividend_yield_ttm_pct": round(yield_pct, 2) if yield_pct is not None else None,
        "spread_vs_10y_pp": round(spread, 2) if spread is not None else None,
        "spread_percentile_since_2000": percentile,
        "spread_percentile_observations": len(historical_spreads),
        "dividend_monitor": build_dividend_monitor(dividends, asof=asof),
        "dividend_crosscheck": build_dividend_crosscheck(
            dividends, dividend_reference) if dividend_reference else {
                "status": "source_unavailable",
            },
        "observation_period": asof.isoformat(),
        "available_at": max(str(item["fetched_at"]) for item in receipts),
        "source_url": " + ".join(str(item["request_url"]) for item in receipts),
        "source_fingerprint": hashlib.sha256("|".join(fingerprints).encode()).hexdigest(),
        "revision_vintage": "captured_current",
        "receipts": receipts,
        "warning": "CI가 0을 가로지르면 즉시 0, n<156은 2회 연속 미달 시 O 경로에서 0으로 둡니다.",
    }


def _period_return(
    dates: list[date], values: list[float], start: date, end: date,
) -> tuple[float | None, int]:
    rows = [(day, value) for day, value in zip(dates, values, strict=True) if start <= day <= end]
    if len(rows) < 2 or (rows[0][0] - start).days > 14:
        return None, len(rows)
    return round((rows[-1][1] / rows[0][1] - 1) * 100, 1), len(rows)


def _period_change_bp(series: FredSeries, start: date, end: date) -> tuple[float | None, int]:
    rows = [(day, value) for day, value in zip(series.dates, series.values, strict=True) if start <= day <= end]
    if len(rows) < 2 or (rows[0][0] - start).days > 14:
        return None, len(rows)
    return round((rows[-1][1] - rows[0][1]) * 100, 1), len(rows)


def build_event_study(
    *, asof: date, registry: dict[str, Any],
    o: feed.YahooPriceSeriesResult, nasdaq: feed.YahooPriceSeriesResult,
    fred: dict[str, FredSeries], sector: feed.YahooPriceSeriesResult | None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    events = []
    for item in registry["events"]:
        start = date.fromisoformat(str(item["start"]))
        end = min(date.fromisoformat(str(item["end"])), asof)
        if end <= start:
            continue
        o_price, n_o = _period_return(o.dates, o.closes, start, end)
        o_total, _ = _period_return(o.dates, o.adjusted, start, end)
        ndx, n_ndx = _period_return(nasdaq.dates, nasdaq.closes, start, end)
        sector_return, n_sector = (None, 0)
        if sector:
            sector_return, n_sector = _period_return(
                sector.dates, sector.adjusted, start, end)
        d10, n_rate = _period_change_bp(fred["DGS10"], start, end)
        dhy, n_hy = _period_change_bp(fred["BAMLH0A0HYM2"], start, end)
        events.append({
            "event_id": item["event_id"], "type": item["type"],
            "start": start.isoformat(), "end": end.isoformat(),
            "description": item["description"],
            "returns_pct": {
                "realty_income_price": o_price, "realty_income_total_return": o_total,
                "nasdaq_price": ndx, "reit_sector_total_return": sector_return,
            },
            "macro_change_bp": {"dgs10": d10, "hy_oas": dhy},
            "observations": {"realty_income": n_o, "nasdaq": n_ndx, "sector": n_sector,
                             "dgs10": n_rate, "hy_oas": n_hy},
            "hy_status": "available_full_history" if dhy is not None else "history_unavailable",
        })
    hy_complete = bool(events) and all(
        item["macro_change_bp"]["hy_oas"] is not None for item in events)
    return {
        "schema_version": 1, "asof": asof.isoformat(),
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "probability_space": "reference_only", "status": "ok" if hy_complete else "partial",
        "registry_version": registry["registry_version"], "events": events,
        "hy_history_receipt": deepcopy(fred["BAMLH0A0HYM2"].receipt),
        "sector_comparison": {
            "source": "IYR", "status": "available" if sector else "source_unavailable",
            "primary_willreitind": "unavailable_http_404",
        },
        "warning": "사전 등록 사건의 구간 진단이며 인과 추정이나 미래 확률이 아닙니다.",
    }


def build_history_preview(
    nasdaq: feed.YahooPriceSeriesResult, o: feed.YahooPriceSeriesResult,
    sector: feed.YahooPriceSeriesResult | None,
) -> dict[str, Any]:
    labels = sorted({
        day.strftime("%Y-%m") for day in nasdaq.dates
        if date(1998, 1, 1) <= day <= date(2005, 12, 31)
    } & {
        day.strftime("%Y-%m") for day in o.dates
        if date(1998, 1, 1) <= day <= date(2005, 12, 31)
    })
    maps = {
        "nasdaq_price": {day.strftime("%Y-%m"): value for day, value in zip(nasdaq.dates, nasdaq.closes, strict=True)},
        "realty_income_price": {day.strftime("%Y-%m"): value for day, value in zip(o.dates, o.closes, strict=True)},
        "realty_income_total_return": {day.strftime("%Y-%m"): value for day, value in zip(o.dates, o.adjusted, strict=True)},
    }
    if sector:
        maps["reit_sector_total_return"] = {
            day.strftime("%Y-%m"): value for day, value in zip(sector.dates, sector.adjusted, strict=True)
        }
    series: dict[str, list[float | None]] = {}
    for key, mapping in maps.items():
        first = next((mapping[label] for label in labels if label in mapping), None)
        series[key] = [
            round(mapping[label] / first * 100, 1) if first and label in mapping else None
            for label in labels
        ]
    return {
        "period": f"{labels[0]} to {labels[-1]}", "labels": labels, "series": series,
        "sector": {
            "primary": "WILLREITIND", "primary_status": "unavailable_http_404",
            "fallback": "IYR", "fallback_status": "available" if sector else "source_unavailable",
        },
        "semantics": "1998 preview only; each available series is independently rebased to 100.",
    }


def _semantic_text(payload: dict[str, Any]) -> str:
    value = deepcopy(payload)

    def strip(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("generated_at", "available_at", "fetched_at", "response_sha256", "source_fingerprint"):
                node.pop(key, None)
            for child in node.values():
                strip(child)
        elif isinstance(node, list):
            for child in node:
                strip(child)
    strip(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def persist_derived(
    root: Path, latest_relative: Path, archive_relative: Path, payload: dict[str, Any],
) -> tuple[Path, bool]:
    latest = root / latest_relative
    archive = root / archive_relative / f"{payload['asof']}.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if archive.exists():
        existing_raw = archive.read_text(encoding="utf-8")
        existing = json.loads(existing_raw)
        if _semantic_text(existing) != _semantic_text(payload):
            correction_id = None
            ledger = root / "calibration" / "corrections.csv"
            correction_table = {
                EVENT_STUDY_LATEST: "rate_event_studies",
                SENSITIVITY_LATEST: "realty_income_rate_sensitivity",
            }.get(latest_relative)
            if correction_table and ledger.exists():
                with ledger.open(encoding="utf-8", newline="") as handle:
                    corrections = [
                        row for row in csv.DictReader(handle)
                        if row.get("target_table") == correction_table
                        and row.get("target_key") == payload["asof"]
                        and row.get("status") == "approved"
                    ]
                correction_id = corrections[-1].get("correction_id") if corrections else None
            if not correction_id:
                raise RealtyIncomeError(f"immutable derived archive conflict: {archive}")
            candidates = list((root / archive_relative).glob(f"{payload['asof']}*.json"))
            revisions = []
            for candidate in candidates:
                try:
                    revisions.append(int(json.loads(candidate.read_text(encoding="utf-8")).get("revision") or 1))
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    continue
            payload = deepcopy(payload)
            revision = max(revisions or [1]) + 1
            payload.update({
                "snapshot_id": (
                    f"rate-event-study:{payload['asof']}:r{revision}"
                    if latest_relative == EVENT_STUDY_LATEST
                    else f"realty-income-sensitivity:{payload['asof']}:r{revision}"
                ),
                "revision": revision, "correction_id": correction_id,
                "supersedes": (
                    f"rate-event-study:{payload['asof']}:r{revision - 1}"
                    if latest_relative == EVENT_STUDY_LATEST
                    else f"realty-income-sensitivity:{payload['asof']}:r{revision - 1}"
                ),
            })
            archive = root / archive_relative / f"{payload['asof']}_{correction_id}.json"
            serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            if archive.exists():
                revised = json.loads(archive.read_text(encoding="utf-8"))
                if _semantic_text(revised) != _semantic_text(payload):
                    raise RealtyIncomeError(f"immutable derived correction conflict: {archive}")
            else:
                archive.write_text(serialized, encoding="utf-8", newline="\n")
            latest.write_text(serialized, encoding="utf-8", newline="\n")
            return latest, True
        changed = not latest.exists() or latest.read_text(encoding="utf-8") != existing_raw
        if changed:
            latest.write_text(existing_raw, encoding="utf-8", newline="\n")
        return latest, changed
    archive.write_text(serialized, encoding="utf-8", newline="\n")
    latest.write_text(serialized, encoding="utf-8", newline="\n")
    return latest, True
