from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

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


def test_external_event_forecasts_have_pit_source_and_correct_event() -> None:
    before = event_calendar.load_event_forecasts(
        ROOT, datetime(2026, 9, 20, tzinfo=timezone.utc)
    )
    assert before == {}
    forecasts = event_calendar.load_event_forecasts(
        ROOT, datetime(2026, 9, 21, 9, tzinfo=timezone.utc)
    )
    assert {"gdp_2026_q2_3", "nfp_2026_10", "cpi_2026_10"} <= forecasts.keys()
    assert len(forecasts["cpi_2026_10"]) == 2
    assert forecasts["nfp_2026_10"][0]["unit"] == "thousand_people"
    assert all(row["source_url"].startswith("https://") for rows in forecasts.values() for row in rows)

    after_fomc_capture = event_calendar.load_event_forecasts(
        ROOT, datetime(2026, 9, 23, tzinfo=timezone.utc)
    )
    fomc = after_fomc_capture["fomc_2026_10"]
    assert len(fomc) == 2
    assert fomc[0]["unit"] == "rate_percent"
    assert fomc[0]["value"] == "4.1"
    assert "12/18명은 4.125%" in fomc[0]["label"]
    assert "federalreserve.gov" in fomc[0]["source_url"]
    assert fomc[1]["unit"] == "probability_fraction"
    assert fomc[1]["value"] == "0.515"
    assert "동결 YES 47~48¢" in fomc[1]["label"]
    assert "kalshi.com" in fomc[1]["source_url"]


def test_external_forecast_probability_requires_fraction_unit(tmp_path: Path) -> None:
    import csv
    import shutil

    for relative in (event_calendar.SOURCES_PATH, event_calendar.EVENTS_PATH):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    target = tmp_path / event_calendar.FORECASTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_calendar.FORECAST_FIELDS)
        writer.writeheader()
        writer.writerow({
            "snapshot_id": "bad-probability", "event_id": "fomc_2026_10",
            "metric": "hike_25", "label": "인상", "value": "51.5",
            "unit": "probability_fraction",
            "source_name": "source", "source_url": "https://example.com/x",
            "published_on": "2026-09-22", "captured_at": "2026-09-22T10:00:00Z",
            "supersedes": "",
        })
    with pytest.raises(event_calendar.CalendarError, match="must be a fraction"):
        event_calendar.load_event_forecasts(
            tmp_path, datetime(2026, 9, 23, tzinfo=timezone.utc)
        )


def test_external_forecast_rejects_post_release_capture(tmp_path: Path) -> None:
    import csv
    import shutil

    for relative in (event_calendar.SOURCES_PATH, event_calendar.EVENTS_PATH):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    target = tmp_path / event_calendar.FORECASTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_calendar.FORECAST_FIELDS)
        writer.writeheader()
        writer.writerow({
            "snapshot_id": "bad", "event_id": "cpi_2026_10", "metric": "cpi_mom",
            "label": "CPI", "value": "0.4", "unit": "percent",
            "source_name": "source", "source_url": "https://example.com/x",
            "published_on": "2026-10-13", "captured_at": "2026-10-15T00:00:00Z",
            "supersedes": "",
        })
    with pytest.raises(event_calendar.CalendarError, match="not pre-release"):
        event_calendar.load_event_forecasts(tmp_path, datetime(2026, 10, 15, tzinfo=timezone.utc))


def test_future_correction_cannot_hide_prior_forecast_at_older_cutoff(tmp_path: Path) -> None:
    import csv
    import shutil

    for relative in (event_calendar.SOURCES_PATH, event_calendar.EVENTS_PATH):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    target = tmp_path / event_calendar.FORECASTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    base = {
        "snapshot_id": "first", "event_id": "cpi_2026_10", "metric": "cpi_mom",
        "label": "CPI", "value": "0.4", "unit": "percent", "source_name": "source",
        "source_url": "https://example.com/x", "published_on": "2026-09-20",
        "captured_at": "2026-09-20T10:00:00Z", "supersedes": "",
    }
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_calendar.FORECAST_FIELDS)
        writer.writeheader()
        writer.writerow(base)
        writer.writerow({**base, "snapshot_id": "second", "value": "0.5",
                         "published_on": "2026-09-22", "captured_at": "2026-09-22T10:00:00Z",
                         "supersedes": "first"})
    before = event_calendar.load_event_forecasts(
        tmp_path, datetime(2026, 9, 21, tzinfo=timezone.utc)
    )
    after = event_calendar.load_event_forecasts(
        tmp_path, datetime(2026, 9, 23, tzinfo=timezone.utc)
    )
    assert [row["snapshot_id"] for row in before["cpi_2026_10"]] == ["first"]
    assert [row["snapshot_id"] for row in after["cpi_2026_10"]] == ["second"]
