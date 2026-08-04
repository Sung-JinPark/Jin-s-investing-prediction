from __future__ import annotations

import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "forecast_lookup.js"


def _node(expression: str):
    source = json.dumps(str(SCRIPT))
    program = (
        f"const fs=require('fs');eval(fs.readFileSync({source},'utf8'));"
        f"console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_weekend_maps_to_previous_trading_day_without_interpolation() -> None:
    table = json.dumps({
        "status": "ok",
        "trading_days": ["2026-08-28", "2026-08-31", "2026-09-01"],
    })
    result = _node(
        f"ForecastLookup.mapDate({table},'2026-08-30','2026-08-03')")
    assert result == {
        "ok": True,
        "index": 0,
        "requested": "2026-08-30",
        "mapped": "2026-08-28",
        "mapping": "previous",
        "tradingDay": 1,
    }


def test_lookup_rejects_out_of_range_and_before_asof() -> None:
    table = json.dumps({"status": "ok", "trading_days": ["2026-08-04", "2027-08-04"]})
    assert _node(
        f"ForecastLookup.mapDate({table},'2027-08-05','2026-08-03')")["reason"] == "out_of_range"
    assert _node(
        f"ForecastLookup.mapDate({table},'2026-08-03','2026-08-03')")["reason"] == "before_asof"


def test_quick_dates_are_deterministic_calendar_dates() -> None:
    assert _node("ForecastLookup.quickDates('2026-08-03')") == {
        "week": "2026-08-10",
        "month": "2026-09-03",
        "quarter": "2026-11-03",
        "yearEnd": "2026-12-31",
    }


def test_lookup_helper_has_no_storage_or_network_dependency() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage", "fetch(", "XMLHttpRequest"):
        assert forbidden not in source
