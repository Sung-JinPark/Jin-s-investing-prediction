from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pytest

from ai_fc.timeseries_v6.repositories import TypedRepository


ROOT = Path(__file__).resolve().parents[3]


class RecordingCursor(AbstractContextManager):
    def __init__(self, log: list[tuple[str, Sequence[Any] | None]]) -> None:
        self.log = log

    def execute(self, query: str, params: Sequence[Any] | None = None) -> None:
        self.log.append((" ".join(query.split()), params))

    def fetchone(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class RecordingConnection:
    def __init__(self) -> None:
        self.log: list[tuple[str, Sequence[Any] | None]] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self.log)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_migration_defines_typed_core_tables_and_append_only_triggers() -> None:
    sql = (ROOT / "migrations/timeseries_v6/0001_typed_core.sql").read_text(encoding="utf-8").lower()
    for table in (
        "source_registry", "collection_attempt", "raw_object", "receipt",
        "receipt_terminal_outcome", "observation_key", "observation_version",
        "receipt_fact_link", "dataset_snapshot", "task_queue", "score", "gate_decision",
    ):
        assert f"create table if not exists timeseries_v6.{table}" in sql
    assert "research_append_ledger" not in sql
    assert "generic" not in sql
    assert "jsonb" not in sql
    assert "foreign key" not in sql or "references timeseries_v6" in sql
    assert "reject_mutation" in sql


def test_repository_uses_direct_typed_table_inserts_only() -> None:
    connection = RecordingConnection()
    repo = TypedRepository(connection)
    now = datetime.now(timezone.utc)
    repo.append_source(
        source_id="fred_alfred", provider="Federal Reserve Bank of St. Louis",
        authority_class="official", adapter_status="implemented", data_grade="native_pit",
        availability_policy_version="v1", source_uri_template="https://api.stlouisfed.org/fred",
    )
    repo.create_collection_attempt(
        attempt_id="a1", source_id="fred_alfred", scheduled_for=now,
        retry_sequence=0, started_at=now, request_fingerprint_sha256="a" * 64,
    )
    repo.append_raw_object(
        object_sha256="b" * 64, stored_sha256="c" * 64, decompressed_bytes=1,
        stored_bytes=1, object_uri="local://sha256/b", compression="none",
        encryption_status="local_ci_unencrypted", license_class="public_official",
    )
    repo.enqueue_task(
        task_id="V6-P0-009", task_type="engineering", required_capability="codex",
        state="pending", priority=0, dependency_task_ids=[], task_payload_sha256="d" * 64,
        created_at=now, updated_at=now,
    )
    queries = "\n".join(query.lower() for query, _ in connection.log)
    assert "timeseries_v6.source_registry" in queries
    assert "timeseries_v6.collection_attempt" in queries
    assert "timeseries_v6.raw_object" in queries
    assert "timeseries_v6.task_queue" in queries
    assert "jsonb" not in queries
    assert "research_append_ledger" not in queries
    assert connection.commits == 4
    assert connection.rollbacks == 0


def test_repository_rolls_back_on_database_error() -> None:
    class FailingCursor(RecordingCursor):
        def execute(self, query: str, params: Sequence[Any] | None = None) -> None:
            raise ValueError("database rejected row")

    class FailingConnection(RecordingConnection):
        def cursor(self) -> FailingCursor:
            return FailingCursor(self.log)

    connection = FailingConnection()
    repo = TypedRepository(connection)
    with pytest.raises(ValueError, match="rejected"):
        repo.append_source(
            source_id="x", provider="x", authority_class="official",
            adapter_status="implemented", data_grade="native_pit",
            availability_policy_version="v1", source_uri_template="https://example.invalid",
        )
    assert connection.commits == 0
    assert connection.rollbacks == 1
