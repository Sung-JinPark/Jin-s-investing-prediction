from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np

from ai_fc.market_extensions import (
    FredSeries,
    build_liquidity,
    build_scenario_tracker,
    classify_liquidity_zone,
    validate_liquidity,
    validate_scenario_tracker,
)
from ai_fc.quant.feed import YahooDividendResult, YahooPriceSeriesResult


def _rules() -> dict:
    return {
        "rules_version": "test.v1", "probability_space": "reference_only",
        "aggregation": {"probability_conversion": "prohibited"},
        "signals": {
            "S1": {"name": "HY", "deleveraging": {"metric": "four_week_change_bp", "operator": "gte", "threshold": 50}, "easing_rotation": {"metric": "drawdown_from_13w_peak_bp", "operator": "lte", "threshold": -25}},
            "S2": {"name": "real", "deleveraging": {"metric": "weekly_increases_last_4", "operator": "gte", "threshold": 3}, "easing_rotation": {"metric": "drawdown_from_13w_peak_bp", "operator": "lte", "threshold": -30}},
            "S3": {"name": "dollar", "deleveraging": {"metric": "four_week_change_pct", "operator": "gte", "threshold": 2}, "easing_rotation": {"metric": "four_week_change_pct", "operator": "lte", "threshold": -2}},
            "S4": {"name": "net", "deleveraging": {"metric": "weekly_decreases_last_4", "operator": "gte", "threshold": 3}, "easing_rotation": {"metric": "four_week_change_pct", "operator": "gt", "threshold": 0}},
            "S5": {"name": "stable", "activation_gate": "14 days"},
            "S6": {"name": "etf", "activation_gate": "two sources"},
            "S7": {"name": "relative", "deleveraging": {"metric": "relative_return_60d_pct", "operator": "lt", "threshold": 0}, "easing_rotation": {"all": [{"metric": "relative_return_60d_pct", "operator": "lt", "threshold": 0}, {"metric": "relative_return_20d_pct", "operator": "gt", "threshold": 0}]}},
        },
        "liquidity_zone": {
            "expansion": {"operator": "gte", "threshold": .5},
            "contraction": {"operator": "lte", "threshold": -.5},
        },
    }


def _data(weeks: int = 220):
    start = date(2022, 1, 7)
    dates = [start + timedelta(days=7 * index) for index in range(weeks)]
    receipt = lambda key: {"request_url": f"mock://{key}", "response_sha256": key, "fetched_at": "2026-08-03T00:00:00Z"}
    fred = {}
    for key, values in {
        "BAMLH0A0HYM2": np.linspace(3, 4, weeks),
        "DFII10": np.linspace(1, 2, weeks),
        "DTWEXBGS": np.linspace(100, 104, weeks),
        "WALCL": np.linspace(7_000_000, 8_000_000, weeks),
        "WTREGEN": np.linspace(600_000, 650_000, weeks),
        "RRPONTSYD": np.linspace(500, 100, weeks),
        "DGS10": np.linspace(3, 4, weeks),
    }.items():
        fred[key] = FredSeries(key, dates, list(map(float, values)), receipt(key))
    prices = {}
    for key, drift in (("nasdaq", .001), ("bitcoin", .0014), ("realty_income", .0004)):
        values = list(100 * np.exp(np.arange(weeks) * drift))
        prices[key] = YahooPriceSeriesResult(dates, values, values, receipt(key), {"status": "ok", "dropped_rows": 0})
    dividends = YahooDividendResult([dates[-10], dates[-5]], [.25, .25], receipt("div"))
    return dates[-1], fred, prices, dividends


def test_tracker_is_count_only_and_marks_unverified_sources_unavailable() -> None:
    asof, fred, prices, dividends = _data()
    payload = build_scenario_tracker(
        rules=_rules(), asof=asof, fred=fred, prices=prices, dividends=dividends,
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc))
    assert payload["probability_space"] == "reference_only"
    assert payload["summary"]["available"] == 5
    assert [item["state"] for item in payload["signals"][4:6]] == ["source_unavailable"] * 2
    assert not ({"probability", "score", "weights"} & payload.keys())
    validate_scenario_tracker(payload)


def test_liquidity_lead_lag_respects_156_week_gate() -> None:
    asof, fred, prices, _ = _data(120)
    payload = build_liquidity(rules=_rules(), asof=asof, fred=fred, prices=prices)
    assert all(row["correlation"] is None for row in payload["lead_lag"]["bitcoin"])
    assert all(row["status"] == "accumulating" for row in payload["lead_lag"]["nasdaq"])
    validate_liquidity(payload)


def test_liquidity_zone_uses_preregistered_shared_thresholds() -> None:
    assert classify_liquidity_zone(.5, _rules()) == "expansion"
    assert classify_liquidity_zone(-.5, _rules()) == "contraction"
    assert classify_liquidity_zone(.1, _rules()) == "neutral"
