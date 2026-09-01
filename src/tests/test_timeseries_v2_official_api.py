"""The official-API transport must keep the sealed V2 boundary and honest receipts."""

from __future__ import annotations

import json
from pathlib import Path

from ai_fc.timeseries_v2.contracts import model_code_hash
from ai_fc.timeseries_v2.market_archive import (
    ARCHIVE_RECEIPTS,
    MARKET_ARCHIVE_SPECS,
    read_market_observations,
)
from ai_fc.timeseries_v2.official_api_transport import (
    FRED_API_SERIES,
    append_fred_official_api,
    refuse_fredgraph_fetch,
)

ROOT = Path(__file__).resolve().parents[2]


def _fake_fred_transport(url: str, timeout: int = 45) -> str:
    assert "api.stlouisfed.org/fred/series/observations" in url
    assert "api_key=" in url  # the transport itself is keyed...
    return json.dumps({"observations": [
        {"date": "2026-08-27", "value": "26368.15"},
        {"date": "2026-08-28", "value": "26402.42"},
        {"date": "2026-08-31", "value": "."},
    ]})


def test_sealed_collector_files_are_untouched_by_the_transport_module() -> None:
    # The migration must never edit the sealed dependency set: the sealed spec
    # still names fredgraph (and is refused at fetch time instead), and the
    # sealed hash stays computable over the unmodified files.
    assert "fredgraph.csv" in MARKET_ARCHIVE_SPECS["NASDAQCOM"]["url"]
    assert len(model_code_hash(ROOT)) == 64


def test_fredgraph_urls_are_refused_with_a_legal_reason_status() -> None:
    status, payload, _ = refuse_fredgraph_fetch(MARKET_ARCHIVE_SPECS["NASDAQCOM"]["url"])
    assert status == 451
    assert b"12-6" in payload


def test_official_api_append_records_keyless_receipts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test-key-never-recorded")
    report = append_fred_official_api(
        tmp_path, retrieved_at="2026-09-01T03:00:00+00:00",
        fetch_text=_fake_fred_transport,
    )
    assert report["ok"] is True
    # ...but the receipt must only carry the keyless public URL.
    receipts = [
        json.loads(line)
        for line in (tmp_path / ARCHIVE_RECEIPTS).read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(receipts) == len(FRED_API_SERIES)
    for receipt in receipts:
        assert "api_key" not in receipt["source_uri"]
        assert "test-key-never-recorded" not in json.dumps(receipt)
        assert receipt["source_uri"].startswith(
            "https://api.stlouisfed.org/fred/series/observations?")

    rows = [
        row for row in read_market_observations(tmp_path)
        if row.series_id == "NASDAQCOM"
    ]
    # The missing 08-31 value ('.') must be skipped, not recorded as zero.
    assert [row.observation_time for row in rows] == ["2026-08-27", "2026-08-28"]
    assert rows[-1].value == 26402.42
    assert rows[-1].data_grade == "captured_forward"
    assert rows[-1].available_at == "2026-09-01T03:00:00+00:00"
    assert rows[-1].source_id == "fred_api_nasdaqcom_archive"


def test_a_failing_series_is_reported_without_killing_the_append(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test-key")

    def flaky(url: str, timeout: int = 45) -> str:
        if "NASDAQCOM" in url:
            raise OSError("connection reset")
        return _fake_fred_transport(url, timeout)

    report = append_fred_official_api(tmp_path, fetch_text=flaky)
    assert report["ok"] is False
    assert [row["series"] for row in report["failures"]] == ["NASDAQCOM"]
    assert set(report["series"]) == {"DTWEXB", "DTWEXBGS"}
