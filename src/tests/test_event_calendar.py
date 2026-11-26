from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from ai_fc import event_calendar


ROOT = Path(__file__).parents[2]


def test_calendar_contract_and_twelve_month_events_are_registered() -> None:
    contract = event_calendar.load_source_contract(ROOT)
    events = event_calendar.load_events(ROOT)
    assert len(contract["sources"]) >= 3
    assert all(source["official"] and source["access"] == "free"
               for source in contract["sources"])
    assert len([row for row in events if row["kind"] == "fomc"]) == 8
    assert len([row for row in events
                if row["kind"] == "cpi" and row["status"] == "confirmed"]) == 5
    assert any(row["kind"] == "earnings" and row["status"] == "estimated"
               for row in events)
    assert {"bea_pce", "conference_board_consumer_confidence", "ism_pmi"} <= {
        source["id"] for source in contract["sources"]
    }
    assert {"pce", "consumer_confidence", "manufacturing_pmi", "services_pmi"} <= {
        row["kind"] for row in events
    }
    assert all("yahoo" not in row["source_url"].lower() for row in events)


def test_calendar_correction_is_an_appended_superseding_row(tmp_path: Path) -> None:
    contract = {
        "schema_version": 1,
        "sources": [
            {"id": source_id, "official": True, "access": "free",
             "url": f"https://example.com/{source_id}", "kinds": [kind]}
            for source_id, kind in (("fed", "fomc"), ("bls", "cpi"), ("bea", "gdp"))
        ],
    }
    path = tmp_path / event_calendar.SOURCES_PATH
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    base = {
        "event_id": "fomc_2027_03", "kind": "fomc", "date": "2027-03-17",
        "time_et": "14:00", "status": "estimated", "title": "FOMC 잠정",
        "source_id": "fed", "source_url": "https://example.com/fed",
        "available_at": "2026-08-04T12:00:00Z",
        "registered_at": "2026-08-04T12:00:00Z",
    }
    assert event_calendar.append_event(tmp_path, base)
    csv_path = tmp_path / event_calendar.EVENTS_PATH
    prefix = csv_path.read_bytes()
    correction = {
        **base, "event_id": "fomc_2027_03_r2", "date": "2027-03-18",
        "status": "confirmed", "title": "FOMC 확정",
        "supersedes": "fomc_2027_03",
    }
    assert event_calendar.append_event(tmp_path, correction)
    assert csv_path.read_bytes().startswith(prefix)
    active = event_calendar.load_events(tmp_path)
    assert [row["event_id"] for row in active] == ["fomc_2027_03_r2"]
    with pytest.raises(event_calendar.CalendarError, match="append-only"):
        event_calendar.append_event(tmp_path, {**correction, "date": "2027-03-19"})


def _calendar_refresh_fixture(tmp_path: Path) -> dict[str, str]:
    contract = {
        "schema_version": 1,
        "sources": [
            {
                "id": "bea_gdp", "official": True, "access": "free",
                "url": event_calendar.BEA_SCHEDULE_URL, "kinds": ["gdp"],
            },
            {
                "id": "bea_pce", "official": True, "access": "free",
                "url": event_calendar.BEA_PCE_ICS_URL, "kinds": ["pce"],
            },
            {
                "id": "conference_board_consumer_confidence",
                "official": True, "access": "free",
                "url": event_calendar.CONSUMER_CONFIDENCE_URL,
                "kinds": ["consumer_confidence"],
            },
            {
                "id": "ism_pmi", "official": True, "access": "free",
                "url": event_calendar.ISM_CALENDAR_URL,
                "kinds": ["manufacturing_pmi", "services_pmi"],
                "confirmed_through": "2026-12-31",
            },
        ],
    }
    contract_path = tmp_path / event_calendar.SOURCES_PATH
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    nyse = ROOT / "data" / "contracts" / "nyse_holidays.yaml"
    (contract_path.parent / "nyse_holidays.yaml").write_text(
        nyse.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return {
        event_calendar.BEA_PCE_ICS_URL: """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Personal Income and Outlays\\, October 2026
DTSTART;VALUE=DATE-TIME:20261125T133000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Personal Income and Outlays\\, November 2026
DTSTART;VALUE=DATE-TIME:20261223T133000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:GDP (Second Estimate) and Corporate Profits\\, 3rd Quarter 2026
DTSTART;VALUE=DATE-TIME:20261125T133000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:GDP (Advance Estimate)\\, 4th Quarter and Year 2026
DTSTART;VALUE=DATE-TIME:20270128T133000Z
END:VEVENT
END:VCALENDAR
""",
        event_calendar.CONSUMER_CONFIDENCE_URL: """
<p class="date">Updated: Tuesday, October 27, 2026</p>
<p>The next release is Tuesday, November 24th at 10 AM ET.</p>
""",
        event_calendar.ISM_CALENDAR_URL: """
<table><tr><th>Month</th><th>Manufacturing PMI</th><th>Services PMI</th></tr>
<tr><td>December 2026</td><td>1</td><td>3</td></tr></table>
""",
    }


def test_refresh_adds_all_four_indicators_and_is_idempotent(tmp_path: Path) -> None:
    payloads = _calendar_refresh_fixture(tmp_path)
    fetch = payloads.__getitem__
    first = event_calendar.refresh_calendar(
        tmp_path,
        as_of=date(2026, 11, 23),
        horizon_days=50,
        now=datetime(2026, 11, 23, 4, tzinfo=timezone.utc),
        fetch_text=fetch,
    )
    assert not first["failures"]
    events = event_calendar.load_events(tmp_path)
    by_kind = {row["kind"]: row for row in events if row["date"] <= "2026-12-03"}
    assert by_kind["pce"]["date"] == "2026-11-25"
    assert by_kind["gdp"]["date"] == "2026-11-25"
    assert by_kind["gdp"]["event_id"] == "gdp_2026_q3_2"
    assert by_kind["consumer_confidence"]["date"] == "2026-11-24"
    assert by_kind["consumer_confidence"]["status"] == "confirmed"
    assert by_kind["manufacturing_pmi"]["date"] == "2026-12-01"
    assert by_kind["services_pmi"]["date"] == "2026-12-03"
    assert by_kind["manufacturing_pmi"]["status"] == "confirmed"

    before = (tmp_path / event_calendar.EVENTS_PATH).read_bytes()
    replay = event_calendar.refresh_calendar(
        tmp_path,
        as_of=date(2026, 11, 23),
        horizon_days=50,
        now=datetime(2026, 11, 24, 4, tzinfo=timezone.utc),
        fetch_text=fetch,
    )
    assert replay["appended"] == []
    assert (tmp_path / event_calendar.EVENTS_PATH).read_bytes() == before


def test_new_official_date_supersedes_estimate_without_rewrite(tmp_path: Path) -> None:
    payloads = _calendar_refresh_fixture(tmp_path)
    event_calendar.refresh_calendar(
        tmp_path,
        as_of=date(2026, 11, 23),
        horizon_days=50,
        now=datetime(2026, 11, 23, 4, tzinfo=timezone.utc),
        fetch_text=payloads.__getitem__,
    )
    path = tmp_path / event_calendar.EVENTS_PATH
    prefix = path.read_bytes()
    payloads[event_calendar.CONSUMER_CONFIDENCE_URL] = """
<p class="date">Updated: Tuesday, November 24, 2026</p>
<p>The next release is Tuesday, December 29th at 10 AM ET.</p>
"""
    result = event_calendar.refresh_calendar(
        tmp_path,
        as_of=date(2026, 11, 28),
        horizon_days=45,
        now=datetime(2026, 11, 28, 4, tzinfo=timezone.utc),
        fetch_text=payloads.__getitem__,
    )
    assert path.read_bytes().startswith(prefix)
    assert "consumer_confidence_2026_12_r2" in result["corrected"]
    active = event_calendar.load_events(tmp_path)
    december = next(
        row for row in active if row["event_id"] == "consumer_confidence_2026_12_r2"
    )
    assert december["status"] == "confirmed"
    assert december["supersedes"] == "consumer_confidence_2026_12"
