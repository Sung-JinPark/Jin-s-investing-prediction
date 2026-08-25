"""Transactional PostgreSQL store for the V7 Ralph control plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from .task_identity import TaskIdentity


LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 30


class LeaseLost(RuntimeError):
    """The caller no longer owns the task's current fencing token."""


class ConnectionLike(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class Lease:
    identity: TaskIdentity
    owner: str
    fencing_token: int
    lease_expires_at: datetime
    attempt_count: int
    payload_hash: str
    input_snapshot_hash: str


LEASE_SQL = """
WITH candidate AS (
  SELECT run_id, cycle_id, generation_id, task_key
  FROM timeseries_v7.task
  WHERE required_capability = %s
    AND attempt_count < max_attempts
    AND cancellation_requested_at IS NULL
    AND (
      (state IN ('pending','ready','retry_wait') AND (next_attempt_at IS NULL OR next_attempt_at <= %s))
      OR (state IN ('leased','running','validating') AND lease_expires_at < %s)
    )
  ORDER BY priority DESC, created_at, run_id, cycle_id, generation_id, task_key
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE timeseries_v7.task AS task
SET state='leased', lease_owner=%s, fencing_token=task.fencing_token + 1,
    lease_expires_at=%s, heartbeat_at=%s, attempt_count=task.attempt_count + 1,
    updated_at=clock_timestamp()
FROM candidate
WHERE (task.run_id,task.cycle_id,task.generation_id,task.task_key) =
      (candidate.run_id,candidate.cycle_id,candidate.generation_id,candidate.task_key)
RETURNING task.run_id,task.cycle_id,task.generation_id,task.task_key,
          task.lease_owner,task.fencing_token,task.lease_expires_at,task.attempt_count,
          task.payload_hash,task.input_snapshot_hash
"""


class RalphStore:
    def __init__(self, connection_factory: Callable[[], ConnectionLike]):
        self._connection_factory = connection_factory

    def _connection(self) -> ConnectionLike:
        return self._connection_factory()

    def lease(self, capability: str, owner: str, *, now: datetime | None = None) -> Lease | None:
        current = now or datetime.now(timezone.utc)
        expires = current + timedelta(seconds=LEASE_SECONDS)
        connection = self._connection()
        try:
            row = connection.execute(
                LEASE_SQL, (capability, current, current, owner, expires, current)
            ).fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        if row is None:
            return None
        return Lease(
            identity=TaskIdentity(row[0], row[1], row[2], row[3]),
            owner=row[4], fencing_token=int(row[5]), lease_expires_at=row[6],
            attempt_count=int(row[7]), payload_hash=row[8], input_snapshot_hash=row[9],
        )

    def _cas(self, lease: Lease, query: str, params: tuple[Any, ...]) -> None:
        connection = self._connection()
        try:
            cursor = connection.execute(query, params + lease.identity.as_tuple() + (lease.owner, lease.fencing_token))
            if cursor.rowcount != 1:
                connection.rollback()
                raise LeaseLost(f"lease lost for {lease.identity.as_tuple()} token={lease.fencing_token}")
            connection.commit()
        except LeaseLost:
            raise
        except Exception:
            connection.rollback()
            raise

    def start(self, lease: Lease) -> None:
        self._cas(lease, """
UPDATE timeseries_v7.task SET state='running', updated_at=clock_timestamp()
WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)
  AND lease_owner=%s AND fencing_token=%s AND state='leased'
""", ())

    def heartbeat(self, lease: Lease, *, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        expires = current + timedelta(seconds=LEASE_SECONDS)
        self._cas(lease, """
UPDATE timeseries_v7.task SET heartbeat_at=%s, lease_expires_at=%s, updated_at=clock_timestamp()
WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)
  AND lease_owner=%s AND fencing_token=%s AND state IN ('leased','running','validating')
""", (current, expires))

    def complete(self, lease: Lease, *, result_uri: str, result_hash: str) -> None:
        self._cas(lease, """
UPDATE timeseries_v7.task SET state='succeeded', result_artifact_uri=%s,
  result_artifact_hash=%s, lease_owner=NULL, lease_expires_at=NULL, updated_at=clock_timestamp()
WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)
  AND lease_owner=%s AND fencing_token=%s AND state IN ('running','validating')
""", (result_uri, result_hash))

    def checkpoint(self, lease: Lease, *, uri: str, artifact_hash: str) -> None:
        self._cas(lease, """
UPDATE timeseries_v7.task SET checkpoint_uri=%s, checkpoint_hash=%s, updated_at=clock_timestamp()
WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)
  AND lease_owner=%s AND fencing_token=%s AND state IN ('running','validating')
""", (uri, artifact_hash))

    def cancellation_requested(self, lease: Lease) -> bool:
        connection = self._connection()
        row = connection.execute("""
SELECT cancellation_requested_at IS NOT NULL FROM timeseries_v7.task
WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)
  AND lease_owner=%s AND fencing_token=%s
""", lease.identity.as_tuple() + (lease.owner, lease.fencing_token)).fetchone()
        return row is None or bool(row[0])
