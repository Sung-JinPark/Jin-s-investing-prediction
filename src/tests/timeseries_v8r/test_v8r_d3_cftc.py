from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from ai_fc.timeseries_v8r.cftc_cot import (
    MARKETS,
    build_query_url,
    materialize_facts,
    release_timestamp,
    row_to_fact,
    verify_repository_collection,
)


def _row(*, code: str = "209742", row_id: str = "x", long: str = "60",
         short: str = "40") -> dict[str, str]:
    return {
        "id": row_id,
        "market_and_exchange_names": "NASDAQ-100 STOCK INDEX (MINI) - CME",
        "report_date_as_yyyy_mm_dd": "2026-08-04T00:00:00",
        "cftc_contract_market_code": code,
        "open_interest_all": "200",
        "lev_money_positions_long": long,
        "lev_money_positions_short": short,
    }


def test_query_is_fixed_to_official_https_dataset_and_three_codes():
    url = build_query_url()
    assert url.startswith("https://publicreporting.cftc.gov/resource/gpe5-46if.json?")
    assert all(code in url for code in MARKETS)
    query = parse_qs(urlparse(build_query_url(start_date=date(2026, 7, 21))).query)
    assert "report_date_as_yyyy_mm_dd >= '2026-07-21T00:00:00.000'" in query["$where"][0]


def test_tuesday_report_is_not_available_until_friday_1530_new_york():
    timestamp = release_timestamp(date(2026, 8, 4))
    assert timestamp.isoformat() == "2026-08-07T19:30:00+00:00"
    assert release_timestamp(date(2026, 8, 3)) == timestamp
    assert release_timestamp(date(2026, 8, 5)) == timestamp
    with pytest.raises(ValueError, match="Monday, Tuesday, or Wednesday"):
        release_timestamp(date(2026, 8, 6))


def test_fact_uses_fraction_and_receipt_lineage():
    fact = row_to_fact(_row(), receipt_sha256="a" * 64)
    assert fact["series_id"] == "CFTC_NQ_LEV_NET_SHARE"
    assert fact["value"] == pytest.approx(0.1)
    assert fact["unit"] == "fraction_of_open_interest"
    assert fact["available_at"] == "2026-08-07T19:30:00Z"
    assert fact["receipt_sha256"] == "a" * 64


def test_append_is_duplicate_free_and_revision_supersedes_prior():
    first, duplicates = materialize_facts([_row()], receipt_sha256="a" * 64)
    assert len(first) == 1 and duplicates == 0
    second, duplicates = materialize_facts([_row()], receipt_sha256="b" * 64,
                                           existing=first)
    assert second == [] and duplicates == 1
    revised, duplicates = materialize_facts(
        [_row(long="80")], receipt_sha256="c" * 64, existing=first
    )
    assert duplicates == 0
    assert revised[0]["revision"] == 2
    assert revised[0]["supersedes"] == first[0]["fact_id"]


def test_repository_verifier_rejects_missing_collection(tmp_path):
    base = tmp_path / "data" / "timeseries_v8r"
    (base / "raw" / "cftc_cot").mkdir(parents=True)
    (base / "receipts" / "cftc_cot").mkdir(parents=True)
    (base / "facts").mkdir(parents=True)
    (base / "cursors").mkdir(parents=True)
    (base / "facts" / "cftc_cot.jsonl").write_text("", encoding="utf-8")
    (base / "cursors" / "cftc_cot.json").write_text(
        '{"source_id":"cftc_cot"}', encoding="utf-8"
    )
    verification = verify_repository_collection(tmp_path)
    assert verification["pass"] is False
    assert verification["checks"]["fact_count_positive"] is False
