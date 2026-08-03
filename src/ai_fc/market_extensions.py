"""Weekly Scenario Tracker and reference-only Liquidity Tide Map.

Rules live in ``data/contracts/scenario_tracker_rules.yaml`` and are loaded at
runtime.  The module counts directional states but never converts them into a
score or probability.  Current-vintage FRED CSV history is valid for monitoring
from capture onward, not for point-in-time backtests.
"""

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
from typing import Any

import numpy as np
import yaml

from .cross_asset import load_cross_asset
from .market_session import completed_market_cutoff
from .quant import feed

TRACKER_LATEST = Path("data/signals/scenario_tracker_latest.json")
TRACKER_ARCHIVE = Path("data/signals/archive")
LIQUIDITY_LATEST = Path("data/liquidity/liquidity_latest.json")
LIQUIDITY_ARCHIVE = Path("data/liquidity/archive")
PATH_TRACKING = Path("data/cross_asset/path_tracking.csv")
RULES_PATH = Path("data/contracts/scenario_tracker_rules.yaml")
FRED_SERIES = (
    "BAMLH0A0HYM2", "DFII10", "DTWEXBGS", "WALCL", "WTREGEN",
    "RRPONTSYD", "DGS10",
)
DISPLAY_WEEKS = 78
LEAD_LAG_MIN_WEEKS = 156
TRACKER_BUDGET_BYTES = 8_000


class MarketExtensionError(ValueError):
    """Invalid input, contract drift, or immutable archive conflict."""


@dataclass(frozen=True)
class FredSeries:
    series_id: str
    dates: list[date]
    values: list[float]
    receipt: dict[str, Any]


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None or not math.isfinite(value) else round(float(value), digits)


def fetch_fred_series(series_id: str, start: date) -> FredSeries:
    url = (
        "https://fred.stlouisfed.org/graph/fredgraph.csv?"
        f"id={series_id}&cosd={start.isoformat()}"
    )
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        raw = feed.get_with_curl_fallback(url, timeout=30)
    except Exception as exc:  # noqa: BLE001 - preserve provider context for stale fallback
        raise MarketExtensionError(
            f"FRED {series_id} fetch failed; previous snapshot must remain active"
        ) from exc
    reader = csv.reader(io.StringIO(raw))
    next(reader, None)
    rows: list[tuple[date, float]] = []
    for row in reader:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            rows.append((date.fromisoformat(row[0]), float(row[1])))
        except (TypeError, ValueError):
            continue
    if not rows:
        raise MarketExtensionError(f"FRED {series_id} returned no numeric observations")
    fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return FredSeries(
        series_id=series_id,
        dates=[row[0] for row in rows], values=[row[1] for row in rows],
        receipt={
            "source": "fred_market_signals", "series_id": series_id,
            "request_url": url, "response_sha256": fingerprint,
            "fetched_at": fetched_at, "revision_vintage": "captured_current",
        },
    )


def _last_friday(cutoff: date) -> date:
    return cutoff - timedelta(days=(cutoff.weekday() - 4) % 7)


def _fridays(start: date, end: date) -> list[date]:
    cursor = _last_friday(start)
    if cursor < start:
        cursor += timedelta(days=7)
    rows = []
    while cursor <= end:
        rows.append(cursor)
        cursor += timedelta(days=7)
    return rows


def _asof_values(dates: list[date], values: list[float], anchors: list[date]
                  ) -> list[float | None]:
    result: list[float | None] = []
    index = 0
    last: float | None = None
    for anchor in anchors:
        while index < len(dates) and dates[index] <= anchor:
            last = float(values[index])
            index += 1
        result.append(last)
    return result


def _weekly_series(series: FredSeries, anchors: list[date]) -> list[float | None]:
    return _asof_values(series.dates, series.values, anchors)


def _weekly_prices(result: feed.YahooPriceSeriesResult, anchors: list[date], *, adjusted: bool
                   ) -> list[float | None]:
    values = result.adjusted if adjusted else result.closes
    return _asof_values(result.dates, values, anchors)


def _numeric_tail(values: list[float | None], count: int) -> list[float]:
    return [float(value) for value in values if value is not None][-count:]


def _pct_change(values: list[float], periods: int) -> float | None:
    if len(values) <= periods or values[-periods - 1] == 0:
        return None
    return (values[-1] / values[-periods - 1] - 1) * 100


def _point_change_bp(values: list[float], periods: int) -> float | None:
    if len(values) <= periods:
        return None
    return (values[-1] - values[-periods - 1]) * 100


def _drawdown_from_peak_bp(values: list[float], window: int = 13) -> float | None:
    tail = values[-window:]
    return None if len(tail) < window else (tail[-1] - max(tail)) * 100


def _weekly_direction_count(values: list[float], *, rising: bool) -> int | None:
    if len(values) < 5:
        return None
    changes = np.diff(np.asarray(values[-5:], dtype=float))
    return int(np.sum(changes > 0 if rising else changes < 0))


def _operator(value: float | int | None, spec: dict[str, Any]) -> bool:
    if value is None:
        return False
    threshold = float(spec["threshold"])
    return {
        "gte": value >= threshold, "gt": value > threshold,
        "lte": value <= threshold, "lt": value < threshold,
    }[spec["operator"]]


def _state(metrics: dict[str, float | int | None], rule: dict[str, Any]) -> str:
    easing = rule.get("easing_rotation") or {}
    if "all" in easing:
        easing_match = all(_operator(metrics.get(item["metric"]), item) for item in easing["all"])
    else:
        easing_match = _operator(metrics.get(easing.get("metric")), easing) if easing else False
    deleveraging = rule.get("deleveraging") or {}
    deleveraging_match = (
        _operator(metrics.get(deleveraging.get("metric")), deleveraging)
        if deleveraging else False
    )
    if easing_match:
        return "easing_rotation_support"
    if deleveraging_match:
        return "deleveraging_support"
    return "neutral"


def _net_liquidity(fred: dict[str, FredSeries], anchors: list[date]) -> list[float | None]:
    walcl = _weekly_series(fred["WALCL"], anchors)
    tga = _weekly_series(fred["WTREGEN"], anchors)
    rrp = _weekly_series(fred["RRPONTSYD"], anchors)
    return [
        None if any(value is None for value in row)
        else float(row[0]) - float(row[1]) - float(row[2]) * 1000
        for row in zip(walcl, tga, rrp, strict=True)
    ]


def _common_meta(receipts: list[dict[str, Any]], observation_period: str) -> dict[str, Any]:
    fingerprints = sorted(str(item.get("response_sha256") or "") for item in receipts)
    return {
        "observation_period": observation_period,
        "available_at": max(str(item.get("fetched_at") or "") for item in receipts),
        "source_url": " + ".join(str(item.get("request_url") or "") for item in receipts),
        "source_fingerprint": hashlib.sha256("|".join(fingerprints).encode()).hexdigest(),
        "revision_vintage": "captured_current",
    }


def _relative_return(left: list[float], right: list[float], periods: int) -> float | None:
    if min(len(left), len(right)) <= periods:
        return None
    return ((left[-1] / left[-periods - 1]) / (right[-1] / right[-periods - 1]) - 1) * 100


def _corr(left: list[float], right: list[float]) -> float | None:
    length = min(len(left), len(right))
    if length < 8:
        return None
    l = np.asarray(left[-length:], dtype=float)
    r = np.asarray(right[-length:], dtype=float)
    if float(np.std(l)) == 0 or float(np.std(r)) == 0:
        return None
    return round(float(np.corrcoef(l, r)[0, 1]), 3)


def load_rules(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / RULES_PATH).read_text(encoding="utf-8"))
    if payload.get("probability_space") != "reference_only":
        raise MarketExtensionError("scenario tracker rules must remain reference_only")
    if payload.get("aggregation", {}).get("probability_conversion") != "prohibited":
        raise MarketExtensionError("scenario tracker probability conversion must be prohibited")
    return payload


def build_scenario_tracker(*, rules: dict[str, Any], asof: date,
                           fred: dict[str, FredSeries],
                           prices: dict[str, feed.YahooPriceSeriesResult],
                           dividends: feed.YahooDividendResult,
                           generated_at: datetime | None = None) -> dict[str, Any]:
    anchors = _fridays(date(2019, 1, 4), asof)
    hy = _numeric_tail(_weekly_series(fred["BAMLH0A0HYM2"], anchors), 20)
    real10 = _numeric_tail(_weekly_series(fred["DFII10"], anchors), 20)
    dollar = _numeric_tail(_weekly_series(fred["DTWEXBGS"], anchors), 20)
    net = _numeric_tail(_net_liquidity(fred, anchors), 20)
    signal_metrics: dict[str, dict[str, float | int | None]] = {
        "S1": {
            "four_week_change_bp": _round(_point_change_bp(hy, 4), 1),
            "drawdown_from_13w_peak_bp": _round(_drawdown_from_peak_bp(hy), 1),
        },
        "S2": {
            "weekly_increases_last_4": _weekly_direction_count(real10, rising=True),
            "drawdown_from_13w_peak_bp": _round(_drawdown_from_peak_bp(real10), 1),
        },
        "S3": {"four_week_change_pct": _round(_pct_change(dollar, 4), 2)},
        "S4": {
            "weekly_decreases_last_4": _weekly_direction_count(net, rising=False),
            "four_week_change_pct": _round(_pct_change(net, 4), 2),
        },
    }
    ndx, btc = prices["nasdaq"].adjusted, prices["bitcoin"].adjusted
    signal_metrics["S7"] = {
        "relative_return_60d_pct": _round(_relative_return(btc, ndx, 60), 2),
        "relative_return_20d_pct": _round(_relative_return(btc, ndx, 20), 2),
    }
    signal_sources = {
        "S1": [fred["BAMLH0A0HYM2"].receipt], "S2": [fred["DFII10"].receipt],
        "S3": [fred["DTWEXBGS"].receipt],
        "S4": [fred[key].receipt for key in ("WALCL", "WTREGEN", "RRPONTSYD")],
        "S7": [prices["nasdaq"].receipt, prices["bitcoin"].receipt],
    }
    signals = []
    for signal_id in ("S1", "S2", "S3", "S4", "S5", "S6", "S7"):
        rule = rules["signals"][signal_id]
        if signal_id in ("S5", "S6"):
            signals.append({
                "id": signal_id, "name": rule["name"], "state": "source_unavailable",
                "status": "원천 미확보", "metrics": {},
                "reason": rule["activation_gate"],
            })
            continue
        metrics = signal_metrics[signal_id]
        receipts = signal_sources[signal_id]
        signals.append({
            "id": signal_id, "name": rule["name"], "state": _state(metrics, rule),
            "status": "available", "metrics": metrics,
            **_common_meta(receipts, asof.isoformat()),
        })
    counts = {
        state: sum(item["state"] == state for item in signals)
        for state in ("deleveraging_support", "easing_rotation_support", "neutral")
    }
    dgs = _numeric_tail(_weekly_series(fred["DGS10"], anchors), 60)
    o_weekly = _numeric_tail(_weekly_prices(prices["realty_income"], anchors, adjusted=True), 60)
    o_returns = list(np.diff(np.log(np.asarray(o_weekly, dtype=float))))
    rate_changes = list(np.diff(np.asarray(dgs, dtype=float)))
    ttm_start = asof - timedelta(days=365)
    ttm_dividend = sum(amount for day, amount in zip(dividends.dates, dividends.amounts)
                       if ttm_start < day <= asof)
    o_close = prices["realty_income"].closes[-1]
    yield_pct = ttm_dividend / o_close * 100 if o_close > 0 else None
    dgs10 = dgs[-1] if dgs else None
    halving = date(2024, 4, 20)
    halving_months = max(0, (asof.year - halving.year) * 12 + asof.month - halving.month)
    btc_200dma = float(np.mean(btc[-200:])) if len(btc) >= 200 else None
    payload = {
        "schema_version": 1, "asof": asof.isoformat(),
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "probability_space": "reference_only", "rules_version": rules["rules_version"],
        "status": "partial" if any(item["state"] == "source_unavailable" for item in signals) else "ok",
        "summary": {"available": 5, "total": 7, "counts": counts,
                    "text": "방향 일치 신호 개수이며 가중 점수·확률이 아닙니다."},
        "signals": signals,
        "asset_diagnostics": {
            "bitcoin": {
                "halving_anchor": "2024-04-20", "months_since_halving": halving_months,
                "price_vs_200dma_pct": _round((btc[-1] / btc_200dma - 1) * 100, 1)
                if btc_200dma else None,
            },
            "realty_income": {
                "ttm_dividend_yield_pct": _round(yield_pct, 2),
                "dgs10_pct": _round(dgs10, 2),
                "dividend_yield_spread_pp": _round(yield_pct - dgs10, 2)
                if yield_pct is not None and dgs10 is not None else None,
                "dgs10_four_week_change_bp": _round(_point_change_bp(dgs, 4), 1),
                "rate_change_o_return_corr_52w": _corr(rate_changes[-52:], o_returns[-52:]),
                "return_basis": "O adjusted-close weekly return vs DGS10 weekly change",
            },
        },
        "receipts": [series.receipt for series in fred.values()]
                    + [result.receipt for result in prices.values()] + [dividends.receipt],
        "warning": "이 체크리스트는 사전 등록된 방향 규칙이며 확률이 아닙니다.",
    }
    return validate_scenario_tracker(payload)


def validate_scenario_tracker(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("probability_space") != "reference_only":
        raise MarketExtensionError("scenario_tracker must be reference_only")
    date.fromisoformat(payload["asof"])
    signals = payload.get("signals") or []
    if [item.get("id") for item in signals] != [f"S{i}" for i in range(1, 8)]:
        raise MarketExtensionError("scenario_tracker requires ordered S1..S7")
    allowed = {"deleveraging_support", "easing_rotation_support", "neutral", "source_unavailable"}
    if any(item.get("state") not in allowed for item in signals):
        raise MarketExtensionError("scenario_tracker contains invalid state")
    if any(key in payload for key in ("probability", "score", "weights")):
        raise MarketExtensionError("scenario_tracker score/probability fields are prohibited")
    if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > TRACKER_BUDGET_BYTES:
        raise MarketExtensionError("scenario_tracker payload exceeds 8KB budget")
    return payload


def _rolling_z(values: list[float], window: int = 52) -> list[float | None]:
    output: list[float | None] = []
    for index in range(len(values)):
        sample = np.asarray(values[max(0, index - window + 1):index + 1], dtype=float)
        if len(sample) < window or float(np.std(sample, ddof=1)) == 0:
            output.append(None)
        else:
            output.append(round(float((sample[-1] - np.mean(sample)) / np.std(sample, ddof=1)), 3))
    return output


def _return_series(values: list[float], periods: int) -> list[float | None]:
    return [None if index < periods else round((value / values[index - periods] - 1) * 100, 2)
            for index, value in enumerate(values)]


def _lead_lag(net: list[float], asset: list[float]) -> list[dict[str, Any]]:
    net_change = np.diff(np.log(np.asarray(net, dtype=float)))
    asset_return = np.diff(np.log(np.asarray(asset, dtype=float)))
    rows = []
    for lag in (0, 4, 8, 12):
        x = net_change[:len(net_change) - lag or None]
        y = asset_return[lag:]
        n = min(len(x), len(y))
        correlation = None
        if n >= LEAD_LAG_MIN_WEEKS and float(np.std(x[-n:])) and float(np.std(y[-n:])):
            correlation = round(float(np.corrcoef(x[-n:], y[-n:])[0, 1]), 3)
        rows.append({"lag_weeks": lag, "correlation": correlation, "observations": n,
                     "minimum_observations": LEAD_LAG_MIN_WEEKS,
                     "status": "available" if correlation is not None else "accumulating"})
    return rows


def classify_liquidity_zone(four_week_change_pct: float | None,
                            rules: dict[str, Any]) -> str:
    zone = rules["liquidity_zone"]
    if _operator(four_week_change_pct, zone["expansion"]):
        return "expansion"
    if _operator(four_week_change_pct, zone["contraction"]):
        return "contraction"
    return "neutral"


def build_liquidity(*, rules: dict[str, Any], asof: date,
                    fred: dict[str, FredSeries],
                    prices: dict[str, feed.YahooPriceSeriesResult],
                    generated_at: datetime | None = None) -> dict[str, Any]:
    anchors = _fridays(date(2019, 1, 4), asof)
    net_raw = _net_liquidity(fred, anchors)
    ndx_raw = _weekly_prices(prices["nasdaq"], anchors, adjusted=True)
    btc_raw = _weekly_prices(prices["bitcoin"], anchors, adjusted=True)
    common = [(anchor, net, ndx, btc) for anchor, net, ndx, btc in
              zip(anchors, net_raw, ndx_raw, btc_raw, strict=True)
              if net is not None and ndx is not None and btc is not None]
    if len(common) < 52:
        raise MarketExtensionError("liquidity common weekly history is too short")
    labels = [row[0].isoformat() for row in common]
    net = [float(row[1]) for row in common]
    ndx = [float(row[2]) for row in common]
    btc = [float(row[3]) for row in common]
    net_z = _rolling_z(net)
    ndx_26w, btc_26w = _return_series(ndx, 26), _return_series(btc, 26)
    zone_by_week = [
        classify_liquidity_zone(
            None if index < 4 else (net[index] / net[index - 4] - 1) * 100,
            rules,
        ) for index in range(len(net))
    ]
    four_week_change = _pct_change(net, 4)
    start = max(0, len(labels) - DISPLAY_WEEKS)
    lead_lag = {"nasdaq": _lead_lag(net, ndx), "bitcoin": _lead_lag(net, btc)}
    payload = {
        "schema_version": 1, "asof": labels[-1],
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "status": "partial", "probability_space": "reference_only",
        "rules_version": rules["rules_version"],
        "zone": classify_liquidity_zone(four_week_change, rules),
        "zone_metric": {"name": "fed_net_liquidity_four_week_change_pct",
                        "value": _round(four_week_change, 2)},
        "series": {
            "labels": labels[start:],
            "fed_net_liquidity_trillion": [_round(value / 1_000_000, 3) for value in net[start:]],
            "fed_net_liquidity_z_52w": net_z[start:],
            "nasdaq_return_26w_pct": ndx_26w[start:],
            "bitcoin_return_26w_pct": btc_26w[start:],
            "liquidity_zone": zone_by_week[start:],
        },
        "lead_lag": lead_lag,
        "real_m2": {"status": "source_unavailable", "reason": "ALFRED vintage API key unavailable; current FRED M2 is not substituted"},
        "crypto_internal": {
            "stablecoin_supply": {"status": "source_unavailable", "reason": "14-day D0 stability/license gate incomplete"},
            "btc_etf_flows": {"status": "source_unavailable", "reason": "two-source and license gate incomplete"},
        },
        "receipts": [fred[key].receipt for key in ("WALCL", "WTREGEN", "RRPONTSYD")]
                    + [prices["nasdaq"].receipt, prices["bitcoin"].receipt],
        "semantics": "reference-only liquidity diagnostics; no probability, causal, or leading-indicator claim",
        "warning": "유동성 확장이 곧 상승을 뜻하지 않습니다. 시차 상관은 국면 의존 진단입니다.",
    }
    return validate_liquidity(payload)


def validate_liquidity(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("probability_space") != "reference_only":
        raise MarketExtensionError("liquidity must be reference_only")
    date.fromisoformat(payload["asof"])
    series = payload.get("series") or {}
    lengths = {len(series.get(key) or []) for key in (
        "labels", "fed_net_liquidity_trillion", "fed_net_liquidity_z_52w",
        "nasdaq_return_26w_pct", "bitcoin_return_26w_pct", "liquidity_zone")}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) > DISPLAY_WEEKS:
        raise MarketExtensionError("liquidity series length/budget contract failed")
    for rows in (payload.get("lead_lag") or {}).values():
        for row in rows:
            if row.get("observations", 0) < LEAD_LAG_MIN_WEEKS and row.get("correlation") is not None:
                raise MarketExtensionError("lead/lag correlation escaped the 156-week gate")
    if any(key in payload for key in ("probability", "weights", "expected_return")):
        raise MarketExtensionError("liquidity probability/weight fields are prohibited")
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 15_000:
        raise MarketExtensionError("liquidity payload exceeds 15KB budget")
    return payload


def _comparable(payload: dict[str, Any]) -> str:
    value = deepcopy(payload)

    def strip_transport_times(node: Any) -> None:
        if isinstance(node, dict):
            # These fields describe transport metadata, not a change in the
            # published read-model. Yahoo response metadata can change its raw hash
            # while all dated observations remain identical. Keep the first receipt
            # byte-for-byte and compare the actual derived metrics/series instead.
            for key in (
                "generated_at", "fetched_at", "available_at",
                "response_sha256", "source_fingerprint",
            ):
                node.pop(key, None)
            for child in node.values():
                strip_transport_times(child)
        elif isinstance(node, list):
            for child in node:
                strip_transport_times(child)

    strip_transport_times(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _persist_json(root: Path, latest_relative: Path, archive_relative: Path,
                  payload: dict[str, Any]) -> tuple[Path, dict[str, Any], bool]:
    latest, archive_dir = root / latest_relative, root / archive_relative
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"{payload['asof']}.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if archive.exists():
        existing_raw = archive.read_text(encoding="utf-8")
        existing = json.loads(existing_raw)
        if _comparable(existing) != _comparable(payload):
            raise MarketExtensionError(
                f"immutable archive conflict: {archive}; append an approved correction revision"
            )
        changed = not latest.exists() or latest.read_text(encoding="utf-8") != existing_raw
        if changed:
            latest.write_text(existing_raw, encoding="utf-8", newline="\n")
        return latest, existing, changed
    archive.write_text(serialized, encoding="utf-8", newline="\n")
    latest.write_text(serialized, encoding="utf-8", newline="\n")
    return latest, payload, True


def _append_path_tracking(root: Path, payload: dict[str, Any],
                          prices: dict[str, feed.YahooPriceSeriesResult]) -> bool:
    cross = load_cross_asset(root)
    if cross.get("status") == "blocked":
        return False
    origin = date.fromisoformat(cross["asof"])
    current = date.fromisoformat(payload["asof"])
    weeks = max(0, (current - origin).days // 7)
    month_index = min(12, int(round(weeks / 4.345)))
    scenarios = cross["forecast"]["scenarios"]
    asset_map = {"nasdaq": "nasdaq", "bitcoin": "bitcoin", "realty_income": "realty_income"}
    rows = []
    for asset, source_key in asset_map.items():
        result = prices[source_key]
        by_date = {day: value for day, value in zip(result.dates, result.closes)}
        eligible = [day for day in by_date if day <= current]
        if not eligible:
            continue
        actual = by_date[max(eligible)] / float(cross["anchors"][asset]) * 100
        rows.append({
            "asof": current.isoformat(), "origin_asof": origin.isoformat(),
            "weeks_elapsed": weeks, "scenario_month_index": month_index, "asset": asset,
            "actual_index": round(actual, 3),
            **{f"{scenario_id}_path": scenario["paths"][asset][month_index]
               for scenario_id, scenario in scenarios.items()},
            **{f"{scenario_id}_abs_gap": round(abs(actual - scenario["paths"][asset][month_index]), 3)
               for scenario_id, scenario in scenarios.items()},
        })
    path = root / PATH_TRACKING
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "asof", "origin_asof", "weeks_elapsed", "scenario_month_index", "asset", "actual_index",
        "deleveraging_path", "easing_rotation_path", "soft_landing_path",
        "deleveraging_abs_gap", "easing_rotation_abs_gap", "soft_landing_abs_gap",
    ]
    existing: dict[tuple[str, str, str], dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            existing = {(row["asof"], row["origin_asof"], row["asset"]): row
                        for row in csv.DictReader(handle)}
    pending = []
    for row in rows:
        key = (row["asof"], row["origin_asof"], row["asset"])
        text_row = {field: str(row[field]) for field in fields}
        if key in existing:
            if existing[key] != text_row:
                raise MarketExtensionError(f"append-only path_tracking conflict for {key}")
            continue
        pending.append(row)
    if not pending:
        return False
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        if path.stat().st_size == 0:
            writer.writeheader()
        writer.writerows(pending)
    return True


def refresh_market_extensions(root: Path, *, asof: date | None = None,
                              now: datetime | None = None) -> dict[str, Any]:
    cutoff = completed_market_cutoff(asof or date.today(), now=now)
    weekly_asof = _last_friday(cutoff)
    # Monitoring starts with a compact, reproducible operating window.  A
    # longer current-vintage download would not make a backtest point-in-time
    # safe; the 156-week lead/lag gate therefore stays closed until enough
    # weekly snapshots accumulate.
    start = date(2025, 1, 1)
    fred = {series_id: fetch_fred_series(series_id, start) for series_id in FRED_SERIES}
    prices = {
        key: feed.yahoo_price_series_detail(symbol, start, weekly_asof + timedelta(days=1), "1d")
        for key, symbol in (("nasdaq", "^IXIC"), ("bitcoin", "BTC-USD"),
                            ("realty_income", "O"))
    }
    dividends = feed.yahoo_dividends("O", weekly_asof - timedelta(days=730),
                                     weekly_asof + timedelta(days=1))
    rules = load_rules(root)
    tracker = build_scenario_tracker(
        rules=rules, asof=weekly_asof, fred=fred, prices=prices, dividends=dividends)
    liquidity = build_liquidity(
        rules=rules, asof=weekly_asof, fred=fred, prices=prices)
    tracker_path, tracker_payload, tracker_changed = _persist_json(
        root, TRACKER_LATEST, TRACKER_ARCHIVE, tracker)
    liquidity_path, liquidity_payload, liquidity_changed = _persist_json(
        root, LIQUIDITY_LATEST, LIQUIDITY_ARCHIVE, liquidity)
    tracking_changed = _append_path_tracking(root, tracker_payload, prices)
    return {
        "tracker_path": tracker_path, "tracker": tracker_payload,
        "tracker_changed": tracker_changed,
        "liquidity_path": liquidity_path, "liquidity": liquidity_payload,
        "liquidity_changed": liquidity_changed,
        "path_tracking_changed": tracking_changed,
    }


def _load(root: Path, relative: Path, validator) -> dict[str, Any]:
    try:
        return validator(json.loads((root / relative).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {
            "schema_version": 1, "status": "blocked",
            "probability_space": "reference_only", "asof": None,
            "reason": f"snapshot unavailable: {type(exc).__name__}",
        }


def load_scenario_tracker(root: Path) -> dict[str, Any]:
    return _load(root, TRACKER_LATEST, validate_scenario_tracker)


def load_liquidity(root: Path) -> dict[str, Any]:
    return _load(root, LIQUIDITY_LATEST, validate_liquidity)
