"""Independent deadline examples, not observations synthesized from calendars."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from ai_fc.forecast_source_freshness import source_freshness
from ai_fc.daily6m_calendar_compatibility import legacy_run_compatible

ROOT = Path(__file__).resolve().parents[2]


def report(sid, observed, stamp):
    return source_freshness(sid, observed, datetime.fromisoformat(stamp))


@pytest.mark.parametrize("stamp", ["2026-10-24T23:00:00+00:00", "2026-10-25T23:00:00+00:00",
                                   "2026-10-26T05:00:00+00:00"])
@pytest.mark.parametrize("sid", ["NASDAQCOM", "VIX", "VIXCLS", "DGS2", "DGS10", "T10Y2Y"])
def test_last_friday_remains_fresh_over_weekend(sid, stamp):
    assert report(sid, "2026-10-23", stamp)["status"] == "fresh"


def test_h10_monday_release_exact_deadline_and_real_miss():
    before = report("DTWEXBGS", "2026-10-16", "2026-10-26T22:14:59+00:00")
    after = report("DTWEXBGS", "2026-10-16", "2026-10-26T22:15:00+00:00")
    assert before["expected_observation"] == "2026-10-16" and before["status"] == "fresh"
    assert after["expected_observation"] == "2026-10-23" and after["status"] == "stale"
    assert report("DTWEXBGS", "2026-10-23", "2026-10-26T22:15:00+00:00")["status"] == "fresh"
    # A whole prior release cannot be forgiven merely because it is a weekend.
    assert report("DTWEXBGS", "2026-10-09", "2026-10-26T05:00:00+00:00")["status"] == "stale"


def test_h10_federal_monday_holiday_moves_to_tuesday():
    # Columbus Day: equities open; Board releases move to Tuesday.
    old = "2026-10-02"
    assert report("DTWEXBGS", old, "2026-10-13T22:14:59+00:00")["status"] == "fresh"
    overdue = report("DTWEXBGS", old, "2026-10-13T22:15:00+00:00")
    assert overdue["status"] == "stale" and overdue["expected_observation"] == "2026-10-09"


def test_dst_changes_utc_release_deadline():
    x = report("DTWEXBGS", "2026-10-23", "2026-11-02T23:14:59+00:00")
    assert x["status"] == "fresh"
    x = report("DTWEXBGS", "2026-10-23", "2026-11-02T23:15:00+00:00")
    assert x["status"] == "stale" and x["expected_observation"] == "2026-10-30"


def test_exchange_holiday_and_early_close_are_real_sessions():
    # Good Friday is an equity closure, not a Federal Reserve holiday.
    assert report("NASDAQCOM", "2026-04-02", "2026-04-06T05:00:00+00:00")["status"] == "fresh"
    assert report("NASDAQCOM", "2026-04-03", "2026-04-06T05:00:00+00:00")["status"] == "invalid_date"
    # Friday after Thanksgiving closes at 13:00 ET, not 16:00 ET.
    assert report("NASDAQCOM", "2026-11-25", "2026-11-28T11:59:59+00:00")["status"] == "fresh"
    x = report("NASDAQCOM", "2026-11-25", "2026-11-28T12:00:00+00:00")
    assert x["status"] == "stale" and x["expected_observation"] == "2026-11-27"


def test_daily_prices_missing_after_deadline_and_future_bar_rejected():
    x = report("VIX", "2026-10-22", "2026-10-26T05:00:00+00:00")
    assert x["status"] == "stale" and x["expected_observation"] == "2026-10-23"
    assert report("NASDAQCOM", "2026-10-26", "2026-10-26T19:59:00+00:00")["status"] == "invalid_date"
    with pytest.raises(ValueError, match="timezone"):
        report("NASDAQCOM", "2026-10-23", "2026-10-26T05:00:00")


def test_h15_missing_after_next_board_release_and_federal_holiday():
    # Friday's observation is due Monday 16:15 ET + two-hour distribution grace.
    assert report("DGS2", "2026-10-22", "2026-10-26T22:14:59+00:00")["status"] == "fresh"
    assert report("DGS2", "2026-10-22", "2026-10-26T22:15:00+00:00")["status"] == "stale"
    # July 3 is the Board's observed July 4 holiday, unlike the Reserve Banks.
    assert report("DGS2", "2026-07-02", "2026-07-06T05:00:00+00:00")["status"] == "fresh"


@pytest.mark.parametrize("sid", ["DGS2", "DGS10", "T10Y2Y"])
def test_h15_release_day_and_treasury_quote_day_are_distinct(sid):
    # Board open, bonds fully closed; no Friday quote is due on Monday.
    for observed, stamp in [("2025-04-17", "2025-04-21T22:15:00+00:00"),
                            ("2027-03-25", "2027-03-29T22:15:00+00:00")]:
        x = report(sid, observed, stamp)
        assert x["status"] == "fresh" and x["expected_observation"] == observed
    # Employment-report exception: April 3, 2026 is an actual quote day.
    x = report(sid, "2026-04-02", "2026-04-06T22:15:00+00:00")
    assert x["status"] == "stale" and x["expected_observation"] == "2026-04-03"
    assert report(sid, "2026-04-03", "2026-04-06T22:15:00+00:00")["status"] == "fresh"


def test_h10_fx_does_not_inherit_bond_good_friday_closure():
    x = report("DTWEXBGS", "2025-04-17", "2025-04-21T22:15:00+00:00")
    assert x["status"] == "stale" and x["expected_observation"] == "2025-04-18"


def test_legacy_compatibility_pins_all_numerics_and_rejects_other_old_hashes(tmp_path):
    rel = Path("data/contracts/daily6m_calendar_gate_compatibility_v1.json")
    policy = json.loads((ROOT / rel).read_text())
    for path in [str(rel), *policy["unchanged_files"], *policy["unchanged_ast"]]:
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, dest)
    run = {"model_code_hash": policy["legacy_model_code_hash"], "contract_hash": policy["contract_hash"]}
    assert legacy_run_compatible(tmp_path, run)
    assert not legacy_run_compatible(tmp_path, {**run, "model_code_hash": "0" * 64})
    path = tmp_path / "src/ai_fc/timeseries_daily6m/model.py"
    path.write_bytes(path.read_bytes() + b"\n# numerical code drift\n")
    assert not legacy_run_compatible(tmp_path, run)
    shutil.copyfile(ROOT / "src/ai_fc/timeseries_daily6m/model.py", path)
    path = tmp_path / "src/ai_fc/timeseries_daily6m/features.py"
    path.write_text(path.read_text(encoding="utf-8") + "\ndef altered_feature(): return 1\n", encoding="utf-8")
    assert not legacy_run_compatible(tmp_path, run)
