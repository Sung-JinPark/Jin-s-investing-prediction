from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).parents[2]


def _json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_l0_sec_snapshot_regression_constants() -> None:
    capex = _json("data/ai_capital_cycle/company_capex_quarterly_latest.json")
    coverage = _json("data/ai_capital_cycle/coverage_latest.json")
    amzn_periods = [
        date.fromisoformat(row["observation_period"])
        for row in capex["records"]
        if row["company"] == "AMZN" and row["metric"] == "capex"
    ]
    assert max(amzn_periods) >= date(2026, 3, 31)

    records = {}
    for row in capex["records"]:
        records.setdefault((row["company"], row["metric"]), []).append(row)
    companies = {row["company"]: row for row in coverage["companies"]}
    reason_states = {
        "tag_missing", "not_disclosed", "tag_stale", "unit_unsupported",
    }
    for symbol in ("MSFT", "GOOGL"):
        for metric in (
            "capex", "operating_cashflow", "depreciation_amortization", "debt_issued",
        ):
            rows = records.get((symbol, metric), [])
            state = companies[symbol]["metrics"][metric]["status"]
            assert len(rows) == 8 or state in reason_states

    if float(coverage["coverage"]) >= 0.6:
        segment_rows = [row for row in capex["records"] if row["metric"] == "segment_revenue"]
        assert segment_rows
        assert all(row.get("accession") for row in segment_rows)


def test_l0_existing_market_regression_constants_are_unchanged() -> None:
    cross = _json("data/cross_asset/cross_asset_latest.json")
    scenario = _json("data/scenarios/nasdaq_latest.json")
    summary = cross["history"]["summary"]
    realism = scenario["path_realism"]["S1"]
    assert len(cross["history"]["labels"]) == 61
    assert summary["nasdaq_price_pct"] == -10.7
    assert summary["realty_income_price_pct"] == 73.8
    assert summary["realty_income_total_return_pct"] == 140.9
    assert realism["sample_count"] == 16_702
    assert (
        realism["median_max_drawdown_pct"],
        realism["p90_max_drawdown_pct"],
        realism["share_with_5pct_pullback"],
        realism["share_with_10pct_pullback"],
    ) == (12.7, 20.9, 100, 76)
