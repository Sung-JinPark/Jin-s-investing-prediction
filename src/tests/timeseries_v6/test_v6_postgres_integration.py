from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_fc.timeseries_v6.repositories import connect_postgres


ROOT = Path(__file__).resolve().parents[3]
DATABASE_URL = os.environ.get("TSV6_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ephemeral PostgreSQL URL not provided")


def test_postgresql_migration_constraints_and_typed_repository() -> None:
    assert DATABASE_URL
    import psycopg

    connection = psycopg.connect(DATABASE_URL)
    migration = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "migrations/timeseries_v6").glob("*.sql"))
    )
    with connection.cursor() as cursor:
        cursor.execute(migration)
    connection.commit()

    repo = connect_postgres(DATABASE_URL)
    now = datetime.now(timezone.utc)
    repo.append_source(
        source_id="fred_alfred", provider="Federal Reserve Bank of St. Louis",
        authority_class="official", adapter_status="implemented", data_grade="native_pit",
        availability_policy_version="v1", source_uri_template="https://api.stlouisfed.org/fred",
    )
    repo.create_collection_attempt(
        attempt_id="attempt-1", source_id="fred_alfred", scheduled_for=now,
        retry_sequence=0, started_at=now, request_fingerprint_sha256="a" * 64,
    )
    repo.append_raw_object(
        object_sha256="b" * 64, stored_sha256="c" * 64,
        decompressed_bytes=3, stored_bytes=3, object_uri="local://sha256/b",
        compression="none", encryption_status="local_ci_unencrypted",
        license_class="public_official",
    )
    repo.append_receipt(
        receipt_id="receipt-1", source_id="fred_alfred", attempt_id="attempt-1",
        object_sha256="b" * 64, fetched_at=now, available_at=now,
        http_status=200, media_type="application/json",
        schema_fingerprint_sha256="d" * 64, parser_version="v1",
    )
    repo.append_receipt_outcome(
        receipt_id="receipt-1", outcome_status="parsed", observation_count=1,
        reason_code=None, recorded_at=now,
    )
    repo.append_observation_key(
        observation_key_id="key-1", source_id="fred_alfred", series_id="NASDAQCOM",
        observation_time=now, unit="index_points", semantic_type="close",
    )
    repo.append_observation_version(
        observation_version_id="version-1", observation_key_id="key-1", revision_seq=0,
        value_numeric=100.0, value_text=None, available_at=now, vintage_start=None,
        vintage_end=None, raw_object_sha256="b" * 64,
        supersedes_observation_version_id=None, status="active",
    )
    repo.append_receipt_fact_link(
        receipt_id="receipt-1", observation_version_id="version-1", relation="parsed_from",
    )
    repo.finish_collection_attempt(
        attempt_id="attempt-1", terminal_status="success", completed_at=now,
        reason_code=None,
    )
    repo.append_dataset_snapshot(
        dataset_snapshot_id="tsv6-snapshot-test", contract_hash="e" * 64,
        partition_manifest_sha256="f" * 64, knowledge_cutoff=now,
        source_count=1, observation_version_count=1,
        object_manifest_uri="local-content://sha256/manifest", created_at=now,
    )
    repo.append_dataset_snapshot_partition(
        dataset_snapshot_id="tsv6-snapshot-test", partition_path="series=NASDAQCOM/part.parquet",
        partition_sha256="1" * 64, schema_sha256="2" * 64,
        byte_count=100, row_count=1, source_count=1,
        min_available_at=now, max_available_at=now,
    )
    with pytest.raises(psycopg.errors.RaiseException):
        repo.finish_collection_attempt(
            attempt_id="attempt-1", terminal_status="success", completed_at=now,
            reason_code=None,
        )
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.append_receipt_outcome(
            receipt_id="receipt-1", outcome_status="parsed", observation_count=1,
            reason_code=None, recorded_at=now,
        )
    with psycopg.connect(DATABASE_URL) as check:
        with check.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM timeseries_v6.receipt_fact_link")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT terminal_status, integrity_pass FROM timeseries_v6.collection_attempt_integrity")
            assert cursor.fetchone() == ("success", True)
            cursor.execute("SELECT count(*) FROM timeseries_v6.receipt_lineage_integrity WHERE NOT integrity_pass")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM timeseries_v6.observation_revision_integrity WHERE NOT integrity_pass")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM timeseries_v6.orphan_observation_version")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT row_count FROM timeseries_v6.dataset_snapshot_partition")
            assert cursor.fetchone()[0] == 1
            with pytest.raises(psycopg.errors.RaiseException):
                cursor.execute("UPDATE timeseries_v6.dataset_snapshot_partition SET row_count=2")
            check.rollback()
        with check.cursor() as cursor:
            with pytest.raises(psycopg.errors.RaiseException):
                cursor.execute("UPDATE timeseries_v6.receipt SET parser_version='v2' WHERE receipt_id='receipt-1'")
