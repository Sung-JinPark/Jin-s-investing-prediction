from __future__ import annotations

import json

from ai_fc.official_sources import (
    alfred_facts,
    alfred_request,
    alfred_vintage_dates_request,
    edgar_companyfacts_request,
)


def test_alfred_request_carries_realtime_bounds() -> None:
    spec = alfred_request("GDP", api_key="x" * 32, realtime_start="2025-01-01")
    assert "series_id=GDP" in spec.url
    assert "realtime_start=2025-01-01" in spec.url
    assert "output_type=2" in spec.url


def test_alfred_history_requests_use_revision_delta_and_inventory_pagination() -> None:
    observations = alfred_request(
        "NASDAQCOM",
        api_key="x" * 32,
        realtime_start="1996-01-01",
        realtime_end="2020-12-31",
        output_type=3,
    )
    inventory = alfred_vintage_dates_request(
        "NASDAQCOM",
        api_key="x" * 32,
        realtime_start="1996-01-01",
        limit=10_000,
        offset=10_000,
    )
    assert "output_type=3" in observations.url
    assert "realtime_start=1996-01-01" in observations.url
    assert "realtime_end=2020-12-31" in observations.url
    assert "/fred/series/vintagedates?" in inventory.url
    assert "limit=10000" in inventory.url
    assert "offset=10000" in inventory.url


def test_alfred_normalization_preserves_vintage_interval() -> None:
    payload = json.dumps({"observations": [{
        "date": "2025-01-01", "value": "100.5",
        "realtime_start": "2025-04-30", "realtime_end": "2025-05-29",
    }]}).encode()
    fact = alfred_facts(payload, series_id="GDP", retrieved_at="2026-01-01T00:00:00")[0]
    assert fact.available_at == "2025-04-30T08:30:00"
    assert fact.vintage_end == "2025-05-29T08:30:00"
    assert fact.value == 100.5


def test_sec_user_agent_identity_is_mandatory() -> None:
    try:
        edgar_companyfacts_request("1045810", user_agent="anonymous")
    except ValueError as exc:
        assert "contact email" in str(exc)
    else:
        raise AssertionError("anonymous SEC access should be rejected")
