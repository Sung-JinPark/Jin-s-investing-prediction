from __future__ import annotations

from datetime import date, timedelta

from ai_fc.ai_capital_cycle import CIKS
from ai_fc.segment_filing_inventory import build_inventory, validate_inventory


def _fixture(symbol: str, cik: str) -> tuple[dict, dict]:
    start = date(2026, 7, 30)
    forms = ["10-Q", "10-K"] * 7
    recent = {key: [] for key in (
        "accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")}
    for index, form in enumerate(forms):
        day = start - timedelta(days=index * 80)
        recent["accessionNumber"].append(f"0000000000-26-{index:06d}")
        recent["filingDate"].append(day.isoformat())
        recent["reportDate"].append((day - timedelta(days=30)).isoformat())
        recent["form"].append(form)
        recent["primaryDocument"].append(f"{symbol.lower()}-{index}.htm")
    return ({"cik": int(cik), "filings": {"recent": recent}}, {
        "source": "fixture", "request_url": f"mock://{symbol}",
        "response_sha256": symbol, "fetched_at": "2026-08-04T00:00:00+00:00",
    })


def test_segment_inventory_stops_at_four_by_twelve_accessions() -> None:
    payload = build_inventory(
        asof=date(2026, 8, 4),
        submissions={symbol: _fixture(symbol, cik) for symbol, cik in CIKS.items()},
    )
    validate_inventory(payload)
    assert payload["status"] == "accession_inventory_complete"
    assert payload["coverage_gate_effect"] == "none_segment_values_not_extracted"
    for company in payload["companies"].values():
        assert company["filing_count"] == 12
        assert company["segment_extraction_status"] == "not_started"
        assert all(row["segment_rows"] == [] for row in company["filings"])
