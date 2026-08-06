from __future__ import annotations

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
    assert all("yahoo" not in row["source_url"].lower() for row in events)


def test_calendar_correction_is_an_appended_superseding_row(tmp_path: Path) -> None:
    contract = {
        "schema_version": 1,
        "sources": [
            {"id": source_id, "official": True, "access": "free",
             "url": f"https://example.com/{source_id}"}
            for source_id in ("fed", "bls", "bea")
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
