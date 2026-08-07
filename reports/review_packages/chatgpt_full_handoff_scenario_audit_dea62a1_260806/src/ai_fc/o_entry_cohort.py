"""Preregistered PIT rolling-entry cohort for Realty Income.

The module publishes historical cohort evidence only.  It deliberately has no
current entry-state classifier: registering one before these results are public
would reverse the required research order and invite over-fitting.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from .quant import feed
from .realty_income import FredSeries, fetch_fred_series, fetch_hy_event_history

CONTRACT = Path("data/contracts/o_entry_cohort.yaml")
LATEST = Path("data/realty_income/o_entry_cohort_latest.json")
ARCHIVE = Path("data/realty_income/o_entry_cohort_archive")
DIVIDENDS = Path("data/realty_income/dividends.csv")
HOLDING_MONTHS = (3, 6, 12, 24, 36)
RETURN_BASES = ("price", "total_return_proxy")


class OEntryCohortError(ValueError):
    """PIT, schema, or append-only contract violation."""


def _add_months(day: date, months: int) -> date:
    month_index = day.year * 12 + day.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    month_days = (31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                  else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return date(year, month, min(day.day, month_days[month - 1]))


def _month_range(start: str, end: str) -> list[str]:
    cursor = date.fromisoformat(f"{start}-01")
    stop = date.fromisoformat(f"{end}-01")
    labels = []
    while cursor <= stop:
        labels.append(cursor.strftime("%Y-%m"))
        cursor = _add_months(cursor, 1)
    return labels


def load_contract(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / CONTRACT).read_text(encoding="utf-8"))
    if payload.get("status") != "preregistered_before_first_run":
        raise OEntryCohortError("cohort contract must be preregistered before first run")
    if payload.get("probability_space") != "reference_only":
        raise OEntryCohortError("cohort probability_space must be reference_only")
    if payload.get("entry_state_rules_allowed") is not False:
        raise OEntryCohortError("entry-state rules are forbidden before cohort publication")
    execution = payload.get("execution") or {}
    if tuple(execution.get("holding_months") or []) != HOLDING_MONTHS:
        raise OEntryCohortError("holding-month contract drifted")
    if int(execution.get("entry_cost_bps", -1)) != 5 or int(
            execution.get("exit_cost_bps", -1)) != 5:
        raise OEntryCohortError("round-trip cost must remain 10bp")
    return payload


def _last_at_or_before(dates: list[date], values: list[float], target: date) -> tuple[int, float] | None:
    for index in range(len(dates) - 1, -1, -1):
        if dates[index] <= target:
            return index, float(values[index])
    return None


def _first_at_or_after(dates: list[date], target: date) -> int | None:
    for index, day in enumerate(dates):
        if day >= target:
            return index
    return None


def _month_last_rows(dates: list[date], values: list[float]) -> dict[str, tuple[int, date, float]]:
    result: dict[str, tuple[int, date, float]] = {}
    for index, (day, value) in enumerate(zip(dates, values, strict=True)):
        result[day.strftime("%Y-%m")] = (index, day, float(value))
    return result


def _signal_rows(
    labels: list[str], nasdaq: feed.YahooPriceSeriesResult,
    dgs10: FredSeries, dff: FredSeries, hy: FredSeries,
) -> dict[str, dict[str, Any]]:
    ndx_monthly = _month_last_rows(nasdaq.dates, nasdaq.closes)
    dff_monthly = _month_last_rows(dff.dates, dff.values)
    signal_rows: dict[str, dict[str, Any]] = {}
    easing_active = False
    last_reversal_index: int | None = None
    previous_26w_change: float | None = None

    for month_index, label in enumerate(labels):
        ndx_row = ndx_monthly.get(label)
        if ndx_row is None:
            continue
        ndx_index, signal_day, ndx_close = ndx_row
        trailing_peak = max(float(value) for value in nasdaq.closes[:ndx_index + 1])
        drawdown = (ndx_close / trailing_peak - 1) * 100

        dff_row = dff_monthly.get(label)
        dff_change_bp = None
        if dff_row:
            dff_labels = sorted(key for key in dff_monthly if key <= label)
            if len(dff_labels) >= 2:
                previous = dff_monthly[dff_labels[-2]][2]
                dff_change_bp = (dff_row[2] - previous) * 100
                if dff_change_bp <= -25:
                    easing_active = True
                elif dff_change_bp >= 25:
                    easing_active = False

        hy_row = _last_at_or_before(hy.dates, hy.values, signal_day)
        hy_retreat_bp = None
        if hy_row:
            hy_index, hy_value = hy_row
            start = max(0, hy_index - 62)
            hy_retreat_bp = (max(hy.values[start:hy_index + 1]) - hy_value) * 100

        rate_row = _last_at_or_before(dgs10.dates, dgs10.values, signal_day)
        rate_change_bp = None
        if rate_row and rate_row[0] >= 126:
            rate_change_bp = (rate_row[1] - float(dgs10.values[rate_row[0] - 126])) * 100
            if rate_change_bp <= -25 and (
                    previous_26w_change is None or previous_26w_change > -25):
                last_reversal_index = month_index
            previous_26w_change = rate_change_bp
        reversal_active = (
            last_reversal_index is not None
            and month_index - last_reversal_index <= 6
            and rate_change_bp is not None and rate_change_bp < 0
        )

        flags = {
            f"nasdaq_drawdown_{threshold}": drawdown <= -threshold
            for threshold in (10, 20, 30, 40)
        }
        flags.update({
            "after_first_fed_cut": easing_active,
            "after_hy_oas_peak": hy_retreat_bp is not None and hy_retreat_bp >= 100,
            "after_10y_26w_reversal": reversal_active,
        })
        signal_rows[label] = {
            "signal_date": signal_day.isoformat(), "flags": flags,
            "observed": {
                "nasdaq_drawdown_pct": round(drawdown, 3),
                "dff_month_change_bp": round(dff_change_bp, 1) if dff_change_bp is not None else None,
                "hy_retreat_from_63obs_peak_bp": (
                    round(hy_retreat_bp, 1) if hy_retreat_bp is not None else None),
                "dgs10_126obs_change_bp": (
                    round(rate_change_bp, 1) if rate_change_bp is not None else None),
            },
        }
    return signal_rows


def _total_return_path(
    dates: list[date], closes: list[float], start_index: int, end_index: int,
    dividends: list[dict[str, Any]],
) -> tuple[list[float], list[str]]:
    shares = 1.0
    values = []
    used = []
    dividend_index = 0
    eligible = sorted(
        (row for row in dividends
         if dates[start_index] < date.fromisoformat(str(row["ex_date"])) <= dates[end_index]),
        key=lambda row: row["ex_date"],
    )
    for index in range(start_index, end_index + 1):
        day = dates[index]
        while dividend_index < len(eligible) and date.fromisoformat(
                str(eligible[dividend_index]["ex_date"])) <= day:
            row = eligible[dividend_index]
            shares += shares * float(row["amount"]) / float(closes[index])
            used.append(str(row["ex_date"]))
            dividend_index += 1
        values.append(shares * float(closes[index]))
    return values, used


def _path_metrics(values: list[float], dates: list[date], entry_bps: int, exit_bps: int) -> dict[str, Any]:
    entry_multiplier = 1 + entry_bps / 10_000
    exit_multiplier = 1 - exit_bps / 10_000
    return_pct = (values[-1] * exit_multiplier / (values[0] * entry_multiplier) - 1) * 100
    running_peak = values[0]
    peak_index = 0
    worst_drawdown = 0.0
    trough_index = 0
    worst_peak_index = 0
    for index, value in enumerate(values):
        if value > running_peak:
            running_peak, peak_index = value, index
        drawdown = value / running_peak - 1
        if drawdown < worst_drawdown:
            worst_drawdown = drawdown
            trough_index = index
            worst_peak_index = peak_index
    recovery_days = 0
    if worst_drawdown < 0:
        recovery_index = next(
            (index for index in range(trough_index + 1, len(values))
             if values[index] >= values[worst_peak_index]), None)
        recovery_days = ((dates[recovery_index] - dates[trough_index]).days
                         if recovery_index is not None else None)
    return {
        "return_pct": round(return_pct, 3),
        "max_drawdown_pct": round(worst_drawdown * 100, 3),
        "recovery_days": recovery_days,
        "recovered": recovery_days is not None,
    }


def _entry_rows(
    samples: dict[str, tuple[str, str]], signals: dict[str, dict[str, Any]],
    o: feed.YahooPriceSeriesResult, dividends: list[dict[str, Any]], asof: date,
    *, entry_bps: int, exit_bps: int,
) -> list[dict[str, Any]]:
    rows = []
    for sample_id, (start, end) in samples.items():
        for signal_month in _month_range(start, end):
            signal = signals.get(signal_month)
            if signal is None:
                continue
            next_month = _add_months(date.fromisoformat(f"{signal_month}-01"), 1)
            execution_index = _first_at_or_after(o.dates, next_month)
            if execution_index is None or o.dates[execution_index] > asof:
                continue
            execution_day = o.dates[execution_index]
            if execution_day.strftime("%Y-%m") != next_month.strftime("%Y-%m"):
                raise OEntryCohortError(f"no next-month execution for {signal_month}")
            for horizon in HOLDING_MONTHS:
                target = _add_months(execution_day, horizon)
                exit_index = _first_at_or_after(o.dates, target)
                complete = exit_index is not None and o.dates[exit_index] <= asof
                row = {
                    "sample": sample_id, "signal_month": signal_month,
                    "signal_date": signal["signal_date"],
                    "execution_date": execution_day.isoformat(),
                    "horizon_months": horizon,
                    "exit_date": o.dates[exit_index].isoformat() if complete else None,
                    "status": "complete" if complete else "incomplete_horizon",
                    "signals": [key for key, value in signal["flags"].items() if value],
                    "signal_observed": deepcopy(signal["observed"]),
                    "metrics": {}, "dividend_ex_dates_used": [],
                }
                if complete and exit_index is not None:
                    path_dates = o.dates[execution_index:exit_index + 1]
                    price_values = [float(value) for value in o.closes[execution_index:exit_index + 1]]
                    total_values, used = _total_return_path(
                        o.dates, o.closes, execution_index, exit_index, dividends)
                    row["metrics"] = {
                        "price": _path_metrics(price_values, path_dates, entry_bps, exit_bps),
                        "total_return_proxy": _path_metrics(
                            total_values, path_dates, entry_bps, exit_bps),
                    }
                    row["dividend_ex_dates_used"] = used
                rows.append(row)
    return rows


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None and math.isfinite(value) else None


def summarize_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cohorts = ["all_months", "nasdaq_drawdown_10", "nasdaq_drawdown_20",
               "nasdaq_drawdown_30", "nasdaq_drawdown_40", "after_first_fed_cut",
               "after_hy_oas_peak", "after_10y_26w_reversal"]
    sample_ids = list(dict.fromkeys(row["sample"] for row in rows))
    result = []
    for sample in sample_ids:
        sample_rows = [row for row in rows if row["sample"] == sample]
        for cohort in cohorts:
            selected = sample_rows if cohort == "all_months" else [
                row for row in sample_rows if cohort in row["signals"]]
            for horizon in HOLDING_MONTHS:
                candidates = [row for row in selected if row["horizon_months"] == horizon]
                complete = [row for row in candidates if row["status"] == "complete"]
                for basis in RETURN_BASES:
                    metrics = [row["metrics"][basis] for row in complete]
                    returns = [item["return_pct"] for item in metrics]
                    drawdowns = [item["max_drawdown_pct"] for item in metrics]
                    recoveries = [item["recovery_days"] for item in metrics
                                  if item["recovery_days"] is not None]
                    result.append({
                        "sample": sample, "cohort": cohort,
                        "horizon_months": horizon, "basis": basis,
                        "n": len(metrics), "incomplete_count": len(candidates) - len(complete),
                        "median_return_pct": _round_or_none(median(returns)) if returns else None,
                        "hit_rate_pct": _round_or_none(
                            sum(value > 0 for value in returns) / len(returns) * 100) if returns else None,
                        "worst_return_pct": _round_or_none(min(returns)) if returns else None,
                        "median_max_drawdown_pct": _round_or_none(
                            median(drawdowns)) if drawdowns else None,
                        "worst_max_drawdown_pct": _round_or_none(min(drawdowns)) if drawdowns else None,
                        "median_recovery_days": _round_or_none(
                            median(recoveries), 1) if recoveries else None,
                        "unrecovered_count": sum(not item["recovered"] for item in metrics),
                    })
    return result


def build_cohort(
    *, asof: date, contract: dict[str, Any], o: feed.YahooPriceSeriesResult,
    nasdaq: feed.YahooPriceSeriesResult, dgs10: FredSeries, dff: FredSeries,
    hy: FredSeries, dividends: list[dict[str, Any]], generated_at: datetime | None = None,
) -> dict[str, Any]:
    in_sample = contract["samples"]["in_sample"]
    out_samples = contract["samples"]["out_of_sample"]
    samples = {in_sample["id"]: (in_sample["signal_month_start"], in_sample["signal_month_end"])}
    samples.update({row["id"]: (row["signal_month_start"], row["signal_month_end"])
                    for row in out_samples})
    # Signals with state (Fed easing and 10Y reversal age) must advance through
    # every intervening month; skipping the quiet years between OOS windows would
    # incorrectly carry an old regime into the next crisis sample.
    all_labels = _month_range(
        min(start for start, _end in samples.values()),
        max(end for _start, end in samples.values()),
    )
    signals = _signal_rows(all_labels, nasdaq, dgs10, dff, hy)
    execution = contract["execution"]
    rows = _entry_rows(
        samples, signals, o, dividends, asof,
        entry_bps=int(execution["entry_cost_bps"]), exit_bps=int(execution["exit_cost_bps"]),
    )
    contract_text = yaml.safe_dump(contract, allow_unicode=True, sort_keys=True)
    payload = {
        "schema_version": 1, "asof": asof.isoformat(),
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "probability_space": "reference_only", "status": "ok",
        "contract_id": contract["contract_id"],
        "contract_sha256": hashlib.sha256(contract_text.encode("utf-8")).hexdigest(),
        "entry_state_rules_registered": False,
        "execution": deepcopy(execution),
        "samples": deepcopy(contract["samples"]),
        "summary": summarize_entries(rows), "entries": rows,
        "sources": [deepcopy(o.receipt), deepcopy(nasdaq.receipt), deepcopy(dgs10.receipt),
                    deepcopy(dff.receipt), deepcopy(hy.receipt)],
        "warning": (
            "사전 등록 historical cohort이며 진입 시점·가격을 추천하지 않습니다. "
            "현재 O 진입상태 규칙이나 미래 성과 확률이 아닙니다."),
    }
    validate_cohort(payload)
    return payload


def validate_cohort(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("probability_space") != "reference_only":
        raise OEntryCohortError("cohort must remain reference_only")
    if payload.get("entry_state_rules_registered") is not False:
        raise OEntryCohortError("entry-state rules cannot ship with L2-2")
    if tuple((payload.get("execution") or {}).get("holding_months") or []) != HOLDING_MONTHS:
        raise OEntryCohortError("cohort holding horizons drifted")
    rows = payload.get("entries")
    if not isinstance(rows, list) or not rows:
        raise OEntryCohortError("cohort entries required")
    for row in rows:
        signal_day = date.fromisoformat(row["signal_date"])
        execution_day = date.fromisoformat(row["execution_date"])
        if execution_day <= signal_day or execution_day.strftime("%Y-%m") != _add_months(
                date(signal_day.year, signal_day.month, 1), 1).strftime("%Y-%m"):
            raise OEntryCohortError("PIT execution must be first eligible next-month fill")
        if any(date.fromisoformat(day) <= execution_day for day in row["dividend_ex_dates_used"]):
            raise OEntryCohortError("future-return dividends must occur after execution")
    if any(key.startswith("O_ENTRY_") for key in payload):
        raise OEntryCohortError("entry-state output is forbidden in L2-2")
    return payload


def _load_dividends(root: Path) -> list[dict[str, Any]]:
    with (root / DIVIDENDS).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _semantic_text(payload: dict[str, Any]) -> str:
    value = deepcopy(payload)

    def strip_transport(node: Any) -> None:
        if isinstance(node, dict):
            for key in (
                "generated_at", "fetched_at", "response_sha256",
                "primary_response_sha256", "fallback_response_sha256",
                "source_fingerprint",
            ):
                node.pop(key, None)
            for child in node.values():
                strip_transport(child)
        elif isinstance(node, list):
            for child in node:
                strip_transport(child)

    strip_transport(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def persist_cohort(root: Path, payload: dict[str, Any]) -> tuple[Path, bool]:
    validate_cohort(payload)
    latest = root / LATEST
    archive = root / ARCHIVE / f"{payload['asof']}.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def latest_projection(full: dict[str, Any]) -> str:
        projected = deepcopy(full)
        entries = projected.pop("entries")
        projected["entry_count"] = len(entries)
        projected["entries_ref"] = archive.relative_to(root).as_posix()
        return json.dumps(projected, ensure_ascii=False, indent=2) + "\n"

    if archive.exists():
        existing = json.loads(archive.read_text(encoding="utf-8"))
        if _semantic_text(existing) != _semantic_text(payload):
            raise OEntryCohortError(f"immutable cohort archive conflict: {archive}")
        projected = latest_projection(existing)
        changed = not latest.exists() or latest.read_text(encoding="utf-8") != projected
        if changed:
            latest.write_text(projected, encoding="utf-8", newline="\n")
        return latest, changed
    archive.write_text(serialized, encoding="utf-8", newline="\n")
    latest.write_text(latest_projection(payload), encoding="utf-8", newline="\n")
    return latest, True


def refresh_cohort(root: Path, asof: date | None = None) -> tuple[Path, dict[str, Any], bool]:
    contract = load_contract(root)
    requested = asof or date.today()
    start = date(1997, 1, 1)
    end = requested if asof else date.today()
    fetch_end = _add_months(end, 1)
    o = feed.yahoo_price_series_detail("O", start, fetch_end, "1d")
    nasdaq = feed.yahoo_price_series_detail("^IXIC", start, fetch_end, "1d")
    dgs10 = fetch_fred_series("DGS10", start)
    dff = fetch_fred_series("DFF", start)
    hy = fetch_hy_event_history(start)
    common_asof = min(o.dates[-1], nasdaq.dates[-1], dgs10.dates[-1], dff.dates[-1], hy.dates[-1], requested)
    payload = build_cohort(
        asof=common_asof, contract=contract, o=o, nasdaq=nasdaq,
        dgs10=dgs10, dff=dff, hy=hy, dividends=_load_dividends(root),
    )
    path, changed = persist_cohort(root, payload)
    return path, payload, changed


def load_cohort(root: Path) -> dict[str, Any]:
    try:
        payload = json.loads((root / LATEST).read_text(encoding="utf-8"))
        if "entries" not in payload and payload.get("entries_ref"):
            payload = json.loads((root / str(payload["entries_ref"])).read_text(encoding="utf-8"))
        return validate_cohort(payload)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, OEntryCohortError) as exc:
        return {
            "schema_version": 1, "status": "blocked", "probability_space": "reference_only",
            "entry_state_rules_registered": False, "summary": [], "entries": [],
            "reason": f"cohort_unavailable:{type(exc).__name__}",
        }


def load_cohort_summary(root: Path) -> dict[str, Any]:
    """Load only public aggregate rows; raw entry cases stay outside data.json."""
    payload = load_cohort(root)
    if payload.get("status") != "ok":
        return payload
    public_rows = [
        deepcopy(row) for row in payload["summary"]
        if row["basis"] == "total_return_proxy" and (
            (row["sample"] == "dotcom_1998_2005" and row["cohort"] == "all_months")
            or (row["sample"] == "dotcom_1998_2005" and row["horizon_months"] == 12)
            or (row["sample"].startswith("oos_") and row["cohort"] == "all_months"
                and row["horizon_months"] == 12)
        )
    ]
    return {
        "schema_version": payload["schema_version"], "status": payload["status"],
        "asof": payload["asof"], "probability_space": payload["probability_space"],
        "contract_id": payload["contract_id"],
        "contract_sha256": payload["contract_sha256"],
        "entry_state_rules_registered": payload["entry_state_rules_registered"],
        "execution": deepcopy(payload["execution"]),
        "samples": deepcopy(payload["samples"]),
        "summary": public_rows,
        "full_summary_row_count": len(payload["summary"]),
        "entry_count": len(payload["entries"]), "warning": payload["warning"],
        "full_evidence_path": LATEST.as_posix(),
    }
