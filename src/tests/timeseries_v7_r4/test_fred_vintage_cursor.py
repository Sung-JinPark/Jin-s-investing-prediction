import sqlite3
from datetime import datetime, timezone

import pytest

from ai_fc.timeseries_v7_r4.fred_vintages import FredVintageIngestor


PAYLOAD = b"realtime_start,realtime_end,date,value\n2024-01-02,2024-01-03,2023-12-01,1.0\n2024-01-03,9999-12-31,2023-12-01,1.1\n"


def test_full_and_incremental_ingestion_are_idempotent(tmp_path):
    ingestor = FredVintageIngestor(tmp_path, sqlite3.connect(tmp_path / "vintages.db"))
    first = ingestor.ingest("GDP", PAYLOAD, mode="full", retrieved_at=_now())
    second = ingestor.ingest("GDP", PAYLOAD, mode="full", retrieved_at=_now())
    third = ingestor.ingest("GDP", PAYLOAD, mode="incremental", output_type=3,
                            retrieved_at=_now())

    assert (first.inserted_revisions, second.inserted_revisions,
            third.inserted_revisions) == (2, 0, 0)
    assert ingestor.revision_count("GDP") == 2
    assert ingestor.cursor("GDP") == "2024-01-03"


@pytest.mark.parametrize("fail_after", ["raw", "receipt", "parse", "db"])
def test_cursor_advances_only_after_all_durable_stages(tmp_path, fail_after):
    ingestor = FredVintageIngestor(tmp_path, sqlite3.connect(tmp_path / "vintages.db"))
    with pytest.raises(RuntimeError, match="injected failure"):
        ingestor.ingest("GDP", PAYLOAD, mode="incremental", output_type=3,
                        retrieved_at=_now(), fail_after=fail_after)
    assert ingestor.cursor("GDP") is None


def test_reconciliation_detects_missing_revisions(tmp_path):
    connection = sqlite3.connect(tmp_path / "vintages.db")
    ingestor = FredVintageIngestor(tmp_path, connection)
    result = ingestor.ingest("GDP", PAYLOAD, mode="full", retrieved_at=_now())
    connection.execute("DELETE FROM fred_revisions WHERE realtime_start = '2024-01-02'")
    connection.commit()

    report = ingestor.reconcile(result.parse_path)
    assert report["missing_count"] == 1
    assert report["missing_revisions"][0]["realtime_start"] == "2024-01-02"


def _now():
    return datetime(2024, 1, 4, tzinfo=timezone.utc)
