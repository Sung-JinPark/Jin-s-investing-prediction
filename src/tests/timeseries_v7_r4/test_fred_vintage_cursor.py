import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from ai_fc.timeseries_v7_r4.fred_vintages import FredVintageIngestor


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "migrations/timeseries_v7_r4/001_control_plane.sql"
ADMIN_URL = os.getenv(
    "RALPH_V7_R4_TEST_ADMIN_URL",
    "postgresql://postgres@127.0.0.1:55432/postgres",
)
PAYLOAD = b"realtime_start,realtime_end,date,value\n2024-01-02,2024-01-03,2023-12-01,1.0\n2024-01-03,9999-12-31,2023-12-01,1.1\n"


@pytest.fixture(scope="module")
def postgres_url():
    name = "v7r4_fred_" + uuid.uuid4().hex[:12]
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as exc:
        pytest.skip(f"disposable PostgreSQL unavailable: {exc}")
    url = f"postgresql://postgres@127.0.0.1:55432/{name}"
    try:
        with psycopg.connect(url) as conn:
            conn.execute(MIGRATION.read_text(encoding="utf-8"))
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (name,))
            conn.execute(f'DROP DATABASE "{name}"')


@pytest.fixture()
def ingestor(tmp_path, postgres_url):
    return FredVintageIngestor(tmp_path, postgres_url)


def test_full_and_incremental_ingestion_are_idempotent(ingestor):
    first = ingestor.ingest("GDP", PAYLOAD, mode="full", retrieved_at=_now())
    second = ingestor.ingest("GDP", PAYLOAD, mode="full", retrieved_at=_now())
    third = ingestor.ingest("GDP", PAYLOAD, mode="incremental", output_type=3,
                            retrieved_at=_now())

    assert (first.inserted_revisions, second.inserted_revisions,
            third.inserted_revisions) == (2, 0, 0)
    assert ingestor.revision_count("GDP") == 2
    assert ingestor.cursor("GDP") == "2024-01-03"


@pytest.mark.parametrize("fail_after", ["raw", "receipt", "parse", "db"])
def test_cursor_advances_only_after_all_durable_stages(ingestor, fail_after):
    series_id = "FAIL_" + fail_after
    with pytest.raises(RuntimeError, match="injected failure"):
        ingestor.ingest(series_id, PAYLOAD, mode="incremental", output_type=3,
                        retrieved_at=_now(), fail_after=fail_after)
    assert ingestor.cursor(series_id) is None
    assert ingestor.revision_count(series_id) == 0


def test_reconciliation_detects_missing_revisions(ingestor):
    result = ingestor.ingest("RECON", PAYLOAD, mode="full", retrieved_at=_now())
    with psycopg.connect(ingestor.database_url) as connection:
        connection.execute(
            "DELETE FROM timeseries_v7_r4.fred_revisions "
            "WHERE series_id='RECON' AND realtime_start='2024-01-02'"
        )

    report = ingestor.reconcile(result.parse_path)
    assert report["missing_count"] == 1
    assert report["missing_revisions"][0]["realtime_start"] == "2024-01-02"


def test_available_at_is_preserved_as_alfred_realtime_start(ingestor):
    ingestor.ingest("PIT", PAYLOAD, mode="full", retrieved_at=_now())
    with psycopg.connect(ingestor.database_url) as connection:
        rows = connection.execute(
            "SELECT realtime_start::text, available_at::text "
            "FROM timeseries_v7_r4.fred_revisions WHERE series_id='PIT' "
            "ORDER BY realtime_start"
        ).fetchall()
    assert rows == [("2024-01-02", "2024-01-02"), ("2024-01-03", "2024-01-03")]


def _now():
    return datetime(2024, 1, 4, tzinfo=timezone.utc)
