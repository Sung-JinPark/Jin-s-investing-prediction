from __future__ import annotations

from datetime import date, timedelta
import json

import pytest

from ai_fc.o_entry_cohort import (
    OEntryCohortError, _entry_rows, _semantic_text, load_cohort,
    summarize_entries, validate_cohort,
)
from ai_fc import config
from ai_fc.quant.feed import YahooPriceSeriesResult


def _daily_o() -> YahooPriceSeriesResult:
    days = []
    cursor = date(2000, 1, 1)
    while cursor <= date(2004, 12, 31):
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    closes = [20 + index * 0.01 for index in range(len(days))]
    return YahooPriceSeriesResult(
        days, closes, closes, {"source": "fixture", "fetched_at": "2005-01-01"},
        {"status": "ok"},
    )


def test_o_entry_cohort_pit_uses_next_month_fill_and_realized_dividends_only() -> None:
    o = _daily_o()
    signals = {
        "2000-01": {
            "signal_date": "2000-01-31",
            "flags": {"nasdaq_drawdown_10": True},
            "observed": {"nasdaq_drawdown_pct": -12.0},
        }
    }
    dividends = [
        {"ex_date": "2000-01-15", "amount": "0.10"},
        {"ex_date": "2000-02-15", "amount": "0.10"},
        {"ex_date": "2000-05-03", "amount": "0.10"},
    ]
    rows = _entry_rows(
        {"fixture": ("2000-01", "2000-01")}, signals, o, dividends,
        date(2004, 12, 31), entry_bps=5, exit_bps=5,
    )
    three_month = next(row for row in rows if row["horizon_months"] == 3)
    assert three_month["execution_date"] == "2000-02-01"
    assert three_month["execution_date"] > three_month["signal_date"]
    assert three_month["dividend_ex_dates_used"] == ["2000-02-15"]
    assert three_month["metrics"]["total_return_proxy"]["return_pct"] > (
        three_month["metrics"]["price"]["return_pct"])


def test_o_entry_cohort_statistics_recalculate_from_fixed_fixture() -> None:
    def row(value: float | None, drawdown: float | None, recovery: int | None) -> dict:
        complete = value is not None
        metric = ({"return_pct": value, "max_drawdown_pct": drawdown,
                   "recovery_days": recovery, "recovered": recovery is not None}
                  if complete else {})
        return {
            "sample": "dotcom_1998_2005", "horizon_months": 3,
            "status": "complete" if complete else "incomplete_horizon",
            "signals": ["nasdaq_drawdown_10"],
            "metrics": {"price": metric, "total_return_proxy": metric} if complete else {},
        }

    summary = summarize_entries([row(10, -5, 10), row(-20, -25, None), row(None, None, None)])
    result = next(item for item in summary if item["cohort"] == "all_months"
                  and item["horizon_months"] == 3 and item["basis"] == "price")
    assert result == {
        "sample": "dotcom_1998_2005", "cohort": "all_months",
        "horizon_months": 3, "basis": "price", "n": 2, "incomplete_count": 1,
        "median_return_pct": -5.0, "hit_rate_pct": 50.0, "worst_return_pct": -20.0,
        "median_max_drawdown_pct": -15.0, "worst_max_drawdown_pct": -25.0,
        "median_recovery_days": 10.0, "unrecovered_count": 1,
    }


def test_cohort_semantics_ignore_transport_receipt_churn_only() -> None:
    left = {"asof": "2026-07-30", "value": 1,
            "sources": [{"response_sha256": "old", "fetched_at": "old"}]}
    right = {"asof": "2026-07-30", "value": 1,
             "sources": [{"response_sha256": "new", "fetched_at": "new"}]}
    assert _semantic_text(left) == _semantic_text(right)
    right["value"] = 2
    assert _semantic_text(left) != _semantic_text(right)


def test_o_entry_cohort_rejects_same_month_or_entry_state_output() -> None:
    payload = {
        "probability_space": "reference_only", "entry_state_rules_registered": False,
        "execution": {"holding_months": [3, 6, 12, 24, 36]},
        "entries": [{
            "signal_date": "2000-01-31", "execution_date": "2000-01-31",
            "dividend_ex_dates_used": [],
        }],
    }
    with pytest.raises(OEntryCohortError, match="next-month"):
        validate_cohort(payload)
    payload["entries"][0]["execution_date"] = "2000-02-01"
    payload["entry_state_rules_registered"] = True
    with pytest.raises(OEntryCohortError, match="entry-state"):
        validate_cohort(payload)


def test_repository_cohort_has_full_dotcom_and_oos_evidence() -> None:
    path = config.ROOT / "data/realty_income/o_entry_cohort_latest.json"
    latest = json.loads(path.read_text(encoding="utf-8"))
    assert "entries" not in latest and latest["entry_count"] == 840
    assert latest["entries_ref"].endswith("o_entry_cohort_archive/2026-07-30.json")
    payload = load_cohort(config.ROOT)
    validate_cohort(payload)
    assert len(payload["entries"]) == 840
    assert payload["entry_state_rules_registered"] is False
    assert "O_ENTRY_" not in path.read_text(encoding="utf-8")
    main = [row for row in payload["summary"]
            if row["sample"] == "dotcom_1998_2005" and row["cohort"] == "all_months"]
    assert {(row["horizon_months"], row["basis"], row["n"]) for row in main} == {
        (horizon, basis, 96)
        for horizon in (3, 6, 12, 24, 36)
        for basis in ("price", "total_return_proxy")
    }
    for sample in ("oos_2008", "oos_2020", "oos_2022"):
        twelve_month = next(row for row in payload["summary"]
                            if row["sample"] == sample and row["cohort"] == "all_months"
                            and row["horizon_months"] == 12
                            and row["basis"] == "total_return_proxy")
        assert twelve_month["n"] == 24 and twelve_month["incomplete_count"] == 0
