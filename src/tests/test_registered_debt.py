from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ai_fc.market_extensions import MarketExtensionError
from ai_fc.registered_debt import (
    REGISTERED_DEBT_ISSUERS,
    collect_registered_debt,
    parse_filing_fees,
    refresh_registered_debt,
    summarize_registered_debt,
)

NS = 'xmlns:ffd="http://www.sec.gov/Archives/edgar/data/ffd"'


def _fees_xml(rows: list[tuple[str, str]], total: str | None = None) -> bytes:
    """Build a filing-fee exhibit where each offering row has its own context."""
    facts = []
    for index, (security_type, amount) in enumerate(rows, start=1):
        context = f"c{index}"
        facts.append(
            f'<ffd:OfferingSctyTp contextRef="{context}">{security_type}</ffd:OfferingSctyTp>'
            f'<ffd:MaxAggtOfferingPric contextRef="{context}">{amount}</ffd:MaxAggtOfferingPric>'
        )
    if total is not None:
        facts.append(f'<ffd:TtlOfferingAmt contextRef="c0">{total}</ffd:TtlOfferingAmt>')
    return (f"<xbrl {NS}>" + "".join(facts) + "</xbrl>").encode("utf-8")


def test_all_debt_filing_uses_the_declared_total() -> None:
    raw = _fees_xml([("Debt", "600000000.00"), ("Debt", "400000000.00")], total="1000000000.00")
    parsed = parse_filing_fees(raw)
    assert parsed["debt_amount_usd"] == pytest.approx(1_000_000_000.0)
    assert parsed["basis"] == "total_offering_amount_all_rows_typed_debt"
    assert parsed["security_types"] == ["Debt"]


def test_mixed_filing_sums_only_the_debt_rows() -> None:
    """An equity tranche must never inflate the debt figure."""
    raw = _fees_xml(
        [("Debt", "600000000.00"), ("Equity", "900000000.00")], total="1500000000.00")
    parsed = parse_filing_fees(raw)
    assert parsed["debt_amount_usd"] == pytest.approx(600_000_000.0)
    assert parsed["basis"] == "sum_of_debt_typed_rows"
    assert parsed["security_types"] == ["Debt", "Equity"]


def test_filing_without_a_fee_table_is_skipped_not_counted_as_zero() -> None:
    submissions = {"filings": {"recent": {
        "form": ["424B5"], "filingDate": ["2026-03-02"],
        "accessionNumber": ["0001104659-26-000001"],
    }}}
    index = {"directory": {"item": [{"name": "tm-424b5.htm"}]}}

    def fetcher(url: str) -> bytes:
        if "submissions" in url:
            return json.dumps(submissions).encode()
        if url.endswith("index.json"):
            return json.dumps(index).encode()
        raise AssertionError(f"unexpected fetch: {url}")

    rows = collect_registered_debt(
        start=date(2026, 1, 1), end=date(2026, 12, 31), fetcher=fetcher,
        issuers={"AMZN": "0001018724"})
    assert len(rows) == 1
    assert rows[0]["status"] == "no_filing_fee_exhibit"
    assert rows[0]["debt_amount_usd"] is None


def test_summary_separates_unmeasured_issuers_from_measured_zero() -> None:
    rows = [
        {"company": "GOOGL", "cik": REGISTERED_DEBT_ISSUERS["GOOGL"],
         "accession": "a", "form": "424B2", "filing_date": "2026-02-02",
         "status": "parsed", "debt_amount_usd": 5_000_000_000.0},
        {"company": "AMZN", "cik": REGISTERED_DEBT_ISSUERS["AMZN"],
         "accession": "b", "form": "424B5", "filing_date": "2026-02-03",
         "status": "no_filing_fee_exhibit", "debt_amount_usd": None},
    ]
    summary = summarize_registered_debt(
        rows, start=date(2026, 1, 1), end=date(2026, 12, 31),
        generated_at=datetime(2026, 8, 31, tzinfo=timezone.utc))
    by_company = {row["company"]: row for row in summary["companies"]}
    assert by_company["GOOGL"]["coverage"] == "measured"
    # Amazon filed prospectuses but none were machine readable: not a zero.
    assert by_company["AMZN"]["coverage"] == "no_machine_readable_fee_table_in_window"
    # Microsoft filed nothing at all in the window.
    assert by_company["MSFT"]["coverage"] == "no_registered_prospectus_in_window"
    assert summary["measured_issuers"] == ["GOOGL"]
    assert set(summary["unmeasured_issuers"]) == {"AMZN", "META", "MSFT", "ORCL"}
    assert summary["total_debt_amount_usd"] == pytest.approx(5_000_000_000.0)
    assert summary["ai_attribution"] == "not_inferred"
    assert summary["probability_space"] == "reference_only"


def test_refresh_ledger_is_append_only(tmp_path: Path) -> None:
    submissions = {"filings": {"recent": {
        "form": ["424B2"], "filingDate": ["2026-02-02"],
        "accessionNumber": ["0001193125-26-000001"],
    }}}
    index = {"directory": {"item": [{"name": "d1exfilingfees_htm.xml"}]}}
    fees = _fees_xml([("Debt", "5000000000.00")], total="5000000000.00")

    def fetcher(url: str) -> bytes:
        if "submissions" in url:
            return json.dumps(submissions).encode()
        if url.endswith("index.json"):
            return json.dumps(index).encode()
        return fees

    # EDGAR accession numbers are globally unique, so the fixture roster is
    # restricted to one issuer rather than handing every issuer the same one.
    window = {
        "start": date(2026, 1, 1), "end": date(2026, 12, 31),
        "issuers": {"GOOGL": REGISTERED_DEBT_ISSUERS["GOOGL"]},
    }
    first = refresh_registered_debt(tmp_path, fetcher=fetcher, **window)
    assert first["rows_appended"] == 1
    second = refresh_registered_debt(tmp_path, fetcher=fetcher, **window)
    assert second["rows_appended"] == 0
    assert second["rows_total"] == 1

    ledger = tmp_path / "data/ai_capital_cycle/registered_debt_offerings.jsonl"
    assert len(ledger.read_text(encoding="utf-8").strip().splitlines()) == 1

    def conflicting_fetcher(url: str) -> bytes:
        if "submissions" in url:
            return json.dumps(submissions).encode()
        if url.endswith("index.json"):
            return json.dumps(index).encode()
        return _fees_xml([("Debt", "9000000000.00")], total="9000000000.00")

    with pytest.raises(MarketExtensionError):
        refresh_registered_debt(tmp_path, fetcher=conflicting_fetcher, **window)
