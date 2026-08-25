from datetime import datetime, timezone
from pathlib import Path

from ai_fc.timeseries_v6.public_archive import (
    PUBLIC_SERIES,
    PublicSeriesSpec,
    collect_public_archives,
    parse_cftc_nasdaq,
)


def test_public_archive_preserves_raw_and_materializes_immutable_partition(tmp_path: Path) -> None:
    spec = PublicSeriesSpec("fred_alfred", "TEST", "https://example.com/test.csv", "TEST", "daily", "index_points", 1)
    body = ("observation_date,TEST\n" + "\n".join(f"2025-01-{1 + i % 28:02d},{100+i}" for i in range(120))).encode()
    result = collect_public_archives(tmp_path, specs=[spec], fetcher=lambda _uri: (body, "text/csv"), collected_at=datetime(2026, 8, 24, tzinfo=timezone.utc))
    assert result["partitions"][0]["row_count"] == 120
    assert (tmp_path / result["partitions"][0]["path"]).exists()
    object_uri = result["receipts"][0]["object"]["object_uri"]
    assert "api_key" not in object_uri


def test_expanded_public_archive_uses_registered_valid_grades() -> None:
    expected = {"VIX9D", "VIX3M", "VVIX", "SKEW", "OFR_FSI", "EBP", "CMDI", "CFTC_NASDAQ_LEV_NET_PCT_OI"}
    assert expected <= {spec.series_id for spec in PUBLIC_SERIES}
    assert {spec.data_grade for spec in PUBLIC_SERIES} == {"reconstructed_official_archive"}


def test_cftc_nasdaq_parser_aggregates_contract_aliases_without_lookahead() -> None:
    header = "report_date_as_yyyy_mm_dd,open_interest_all,lev_money_positions_long,lev_money_positions_short\n"
    rows = []
    for index in range(120):
        day = datetime(2023, 1, 3, tzinfo=timezone.utc) + __import__("datetime").timedelta(days=7 * index)
        rows.extend([
            f"{day.date().isoformat()}T00:00:00.000,1000,300,200",
            f"{day.date().isoformat()}T00:00:00.000,500,100,150",
        ])
    spec = PublicSeriesSpec("cftc_tff", "CFTC_NASDAQ_LEV_NET_PCT_OI", "https://example.com", "x", "weekly", "percentage_point", 3, parser_kind="cftc_nasdaq")
    parsed = parse_cftc_nasdaq(spec, (header + "\n".join(rows)).encode())
    assert len(parsed) == 120
    assert parsed[0]["value_numeric"] == 100.0 * 50.0 / 1500.0
    assert parsed[0]["available_at"] - parsed[0]["observation_time"] == __import__("datetime").timedelta(days=3)
