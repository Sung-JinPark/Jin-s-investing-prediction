"""Typed PostgreSQL repositories for V6 core entities.

No method writes to a generic JSONB ledger.  Inputs are passed as typed scalar
columns and append-only entities never expose update/delete methods.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterator, Mapping, Protocol, Sequence

from .bulk import ObservationBatchRow, validate_observation_batch


class Cursor(Protocol):
    def execute(self, query: str, params: Sequence[Any] | None = None) -> Any: ...
    def fetchone(self) -> Sequence[Any] | None: ...
    def __enter__(self) -> "Cursor": ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class TypedRepository:
    connection: Connection

    @contextmanager
    def _transaction(self) -> Iterator[Cursor]:
        cursor = self.connection.cursor()
        try:
            with cursor:
                yield cursor
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def append_source(
        self, *, source_id: str, provider: str, authority_class: str,
        adapter_status: str, data_grade: str, availability_policy_version: str,
        source_uri_template: str,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.source_registry
                (source_id, provider, authority_class, adapter_status, data_grade,
                 availability_policy_version, source_uri_template)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (source_id, provider, authority_class, adapter_status, data_grade,
                 availability_policy_version, source_uri_template),
            )

    def create_collection_attempt(
        self, *, attempt_id: str, source_id: str, scheduled_for: datetime,
        retry_sequence: int, started_at: datetime, request_fingerprint_sha256: str,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.collection_attempt
                (attempt_id, source_id, scheduled_for, retry_sequence, started_at,
                 request_fingerprint_sha256) VALUES (%s,%s,%s,%s,%s,%s)""",
                (attempt_id, source_id, scheduled_for, retry_sequence, started_at,
                 request_fingerprint_sha256),
            )

    def finish_collection_attempt(
        self, *, attempt_id: str, terminal_status: str, completed_at: datetime,
        reason_code: str | None,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT timeseries_v6.finish_collection_attempt(%s,%s,%s,%s)",
                (attempt_id, terminal_status, completed_at, reason_code),
            )

    def overdue_collection_attempts(self, *, started_before: datetime) -> list[str]:
        with self._transaction() as cursor:
            cursor.execute(
                """SELECT attempt_id FROM timeseries_v6.collection_attempt
                WHERE terminal_status IS NULL AND started_at < %s
                ORDER BY started_at, attempt_id FOR UPDATE SKIP LOCKED""",
                (started_before,),
            )
            rows: list[str] = []
            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                rows.append(str(row[0]))
            return rows

    def append_raw_object(
        self, *, object_sha256: str, stored_sha256: str, decompressed_bytes: int,
        stored_bytes: int, object_uri: str, compression: str,
        encryption_status: str, license_class: str,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.raw_object
                (object_sha256, stored_sha256, decompressed_bytes, stored_bytes,
                 object_uri, compression, encryption_status, license_class)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (object_sha256, stored_sha256, decompressed_bytes, stored_bytes,
                 object_uri, compression, encryption_status, license_class),
            )

    def append_receipt(
        self, *, receipt_id: str, source_id: str, attempt_id: str,
        object_sha256: str, fetched_at: datetime, available_at: datetime,
        http_status: int, media_type: str, schema_fingerprint_sha256: str,
        parser_version: str,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.receipt
                (receipt_id, source_id, attempt_id, object_sha256, fetched_at,
                 available_at, http_status, media_type, schema_fingerprint_sha256,
                 parser_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (receipt_id, source_id, attempt_id, object_sha256, fetched_at,
                 available_at, http_status, media_type, schema_fingerprint_sha256,
                 parser_version),
            )

    def append_receipt_outcome(
        self, *, receipt_id: str, outcome_status: str, observation_count: int,
        reason_code: str | None, recorded_at: datetime,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.receipt_terminal_outcome
                (receipt_id, outcome_status, observation_count, reason_code, recorded_at)
                VALUES (%s,%s,%s,%s,%s)""",
                (receipt_id, outcome_status, observation_count, reason_code, recorded_at),
            )

    def append_observation_key(
        self, *, observation_key_id: str, source_id: str, series_id: str,
        observation_time: datetime, unit: str, semantic_type: str,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.observation_key
                (observation_key_id, source_id, series_id, observation_time, unit,
                 semantic_type) VALUES (%s,%s,%s,%s,%s,%s)""",
                (observation_key_id, source_id, series_id, observation_time, unit,
                 semantic_type),
            )

    def append_observation_version(
        self, *, observation_version_id: str, observation_key_id: str,
        revision_seq: int, value_numeric: float | None, value_text: str | None,
        available_at: datetime, vintage_start: date | None, vintage_end: date | None,
        raw_object_sha256: str, supersedes_observation_version_id: str | None,
        status: str,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.observation_version
                (observation_version_id, observation_key_id, revision_seq,
                 value_numeric, value_text, available_at, vintage_start, vintage_end,
                 raw_object_sha256, supersedes_observation_version_id, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (observation_version_id, observation_key_id, revision_seq,
                 value_numeric, value_text, available_at, vintage_start, vintage_end,
                 raw_object_sha256, supersedes_observation_version_id, status),
            )

    def append_receipt_fact_link(
        self, *, receipt_id: str, observation_version_id: str, relation: str,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.receipt_fact_link
                (receipt_id, observation_version_id, relation) VALUES (%s,%s,%s)""",
                (receipt_id, observation_version_id, relation),
            )

    def append_observation_batch(
        self, rows: Sequence[ObservationBatchRow], *, knowledge_cutoff: datetime,
    ) -> int:
        """Append keys, versions, and receipt links in one all-or-nothing transaction."""

        batch = validate_observation_batch(rows, knowledge_cutoff=knowledge_cutoff)
        with self._transaction() as cursor:
            for row in batch:
                cursor.execute(
                    """INSERT INTO timeseries_v6.observation_key
                    (observation_key_id, source_id, series_id, observation_time, unit, semantic_type)
                    VALUES (%s,%s,%s,%s,%s,%s)""",
                    (row.observation_key_id, row.source_id, row.series_id,
                     row.observation_time, row.unit, row.semantic_type),
                )
                cursor.execute(
                    """INSERT INTO timeseries_v6.observation_version
                    (observation_version_id, observation_key_id, revision_seq,
                     value_numeric, value_text, available_at, vintage_start, vintage_end,
                     raw_object_sha256, supersedes_observation_version_id, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (row.observation_version_id, row.observation_key_id, row.revision_seq,
                     row.value_numeric, row.value_text, row.available_at, row.vintage_start,
                     row.vintage_end, row.raw_object_sha256,
                     row.supersedes_observation_version_id, row.status),
                )
                cursor.execute(
                    """INSERT INTO timeseries_v6.receipt_fact_link
                    (receipt_id, observation_version_id, relation) VALUES (%s,%s,%s)""",
                    (row.receipt_id, row.observation_version_id, row.relation),
                )
        return len(batch)

    def append_dataset_snapshot(
        self, *, dataset_snapshot_id: str, contract_hash: str,
        partition_manifest_sha256: str, knowledge_cutoff: datetime,
        source_count: int, observation_version_count: int,
        object_manifest_uri: str, created_at: datetime,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.dataset_snapshot
                (dataset_snapshot_id, contract_hash, partition_manifest_sha256,
                 knowledge_cutoff, source_count, observation_version_count,
                 object_manifest_uri, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (dataset_snapshot_id, contract_hash, partition_manifest_sha256,
                 knowledge_cutoff, source_count, observation_version_count,
                object_manifest_uri, created_at),
            )

    def append_dataset_snapshot_partition(
        self, *, dataset_snapshot_id: str, partition_path: str,
        partition_sha256: str, schema_sha256: str, byte_count: int,
        row_count: int, source_count: int, min_available_at: datetime | None,
        max_available_at: datetime | None,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.dataset_snapshot_partition
                (dataset_snapshot_id, partition_path, partition_sha256, schema_sha256,
                 byte_count, row_count, source_count, min_available_at, max_available_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (dataset_snapshot_id, partition_path, partition_sha256, schema_sha256,
                 byte_count, row_count, source_count, min_available_at, max_available_at),
            )

    def enqueue_task(
        self, *, task_id: str, task_type: str, required_capability: str,
        state: str, priority: int, dependency_task_ids: Sequence[str],
        task_payload_sha256: str, created_at: datetime, updated_at: datetime,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.task_queue
                (task_id, task_type, required_capability, state, priority,
                 dependency_task_ids, task_payload_sha256, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (task_id, task_type, required_capability, state, priority,
                 list(dependency_task_ids), task_payload_sha256, created_at, updated_at),
            )

    def append_score(
        self, *, score_id: str, backtest_run_id: str, origin_id: str,
        horizon_sessions: int, candidate_id: str, metric_name: str,
        metric_value: float, comparator_metric_value: float | None,
        sample_role: str, recorded_at: datetime,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.score
                (score_id, backtest_run_id, origin_id, horizon_sessions, candidate_id,
                 metric_name, metric_value, comparator_metric_value, sample_role,
                 recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (score_id, backtest_run_id, origin_id, horizon_sessions, candidate_id,
                 metric_name, metric_value, comparator_metric_value, sample_role,
                 recorded_at),
            )

    def append_gate_decision(
        self, *, gate_decision_id: str, backtest_run_id: str, gate_type: str,
        gate_pass: bool, reason_code: str, score_snapshot_sha256: str,
        contract_hash: str, decided_at: datetime,
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """INSERT INTO timeseries_v6.gate_decision
                (gate_decision_id, backtest_run_id, gate_type, gate_pass, reason_code,
                 score_snapshot_sha256, contract_hash, decided_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (gate_decision_id, backtest_run_id, gate_type, gate_pass, reason_code,
                 score_snapshot_sha256, contract_hash, decided_at),
            )


def connect_postgres(database_url: str) -> TypedRepository:
    """Create the production repository lazily so non-DB workers need no psycopg."""

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised in replay container
        raise RuntimeError("psycopg is required only for PostgreSQL repository use") from exc
    return TypedRepository(psycopg.connect(database_url))
