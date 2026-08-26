"""PostgreSQL authoritative control plane with leases and fencing."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .integrity import canonical_json, sha256_bytes


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Lease:
    run_id: str
    task_key: str
    attempt_id: str
    lease_token: str
    title: str
    payload: dict[str, Any]


class PostgresControlPlane:
    def __init__(self, database_url: str):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - integration guard
            raise RuntimeError("psycopg is required in the frozen R4 runtime") from exc
        self._psycopg = psycopg
        self.database_url = database_url

    def connect(self):
        return self._psycopg.connect(self.database_url)

    def migrate(self, migration: Path) -> None:
        sql = migration.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.execute(sql)
            conn.commit()

    def create_run(self, *, run_id: str, config_hash: str, backlog_hash: str,
                   review_pack_hash: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO timeseries_v7_r4.runs"
                " (run_id,state,config_hash,backlog_hash,review_pack_hash)"
                " VALUES (%s,'BOOTSTRAPPED',%s,%s,%s) ON CONFLICT DO NOTHING",
                (run_id, config_hash, backlog_hash, review_pack_hash),
            )
            conn.execute(
                "INSERT INTO timeseries_v7_r4.cycles(run_id,cycle_id,ordinal,state)"
                " VALUES (%s,%s,1,'ACTIVE') ON CONFLICT DO NOTHING",
                (run_id, f"{run_id}-c001"),
            )
            conn.commit()

    def import_tasks(self, run_id: str, tasks: Iterable[dict[str, Any]]) -> int:
        inserted = 0
        with self.connect() as conn:
            for ordinal, task in enumerate(tasks):
                task_key = str(task.get("task_id") or task.get("id") or task["task_key"])
                title = str(task.get("title") or task_key)
                priority = int(task.get("priority", ordinal + 100))
                capability = str(task.get("worker_capability", "codex"))
                row = conn.execute(
                    "INSERT INTO timeseries_v7_r4.tasks"
                    " (run_id,task_key,title,priority,worker_capability,payload)"
                    " VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING RETURNING 1",
                    (run_id, task_key, title, priority, capability,
                     canonical_json(task).decode("utf-8")),
                ).fetchone()
                inserted += int(row is not None)
            conn.commit()
        return inserted

    def import_catalog(self, catalog_id: str, tasks: Iterable[dict[str, Any]]) -> int:
        inserted = 0
        with self.connect() as conn:
            for ordinal, task in enumerate(tasks):
                task_key = str(task.get("task_id") or task.get("id") or f"catalog-{ordinal:03d}")
                blob = canonical_json(task)
                row = conn.execute(
                    "INSERT INTO timeseries_v7_r4.backlog_catalog"
                    " (catalog_id,task_key,payload,payload_hash) VALUES (%s,%s,%s::jsonb,%s)"
                    " ON CONFLICT DO NOTHING RETURNING 1",
                    (catalog_id, task_key, blob.decode("utf-8"), sha256_bytes(blob)),
                ).fetchone()
                inserted += int(row is not None)
            conn.commit()
        return inserted

    def claim(self, run_id: str, worker_id: str, lease_seconds: int) -> Lease | None:
        with self.connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT t.task_key,t.title,t.payload FROM timeseries_v7_r4.tasks t "
                    "WHERE t.run_id=%s AND t.state IN ('PENDING','RETRY_WAIT') "
                    "AND t.available_at<=now() "
                    "AND NOT EXISTS (SELECT 1 FROM timeseries_v7_r4.task_dependencies d "
                    " JOIN timeseries_v7_r4.tasks p ON p.run_id=d.run_id "
                    " AND p.task_key=d.dependency_key WHERE d.run_id=t.run_id "
                    " AND d.task_key=t.task_key AND p.state<>'SUCCEEDED') "
                    "ORDER BY t.priority,t.created_at FOR UPDATE SKIP LOCKED LIMIT 1",
                    (run_id,),
                ).fetchone()
                if row is None:
                    return None
                task_key, title, payload = row
                lease_token = uuid.uuid4().hex
                attempt_id = f"{task_key}-a{uuid.uuid4().hex[:12]}"
                conn.execute(
                    "UPDATE timeseries_v7_r4.tasks SET state='RUNNING',lease_owner=%s,"
                    " lease_token=%s,lease_expires_at=now()+(%s * interval '1 second'),"
                    " attempts=attempts+1,updated_at=now() WHERE run_id=%s AND task_key=%s",
                    (worker_id, lease_token, lease_seconds, run_id, task_key),
                )
                conn.execute(
                    "INSERT INTO timeseries_v7_r4.attempts"
                    " (run_id,task_key,attempt_id,lease_token,worker_id,state,started_at)"
                    " VALUES (%s,%s,%s,%s,%s,'RUNNING',now())",
                    (run_id, task_key, attempt_id, lease_token, worker_id),
                )
            return Lease(run_id, task_key, attempt_id, lease_token, title, dict(payload))

    def heartbeat(self, lease: Lease, worker_id: str, lease_seconds: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "UPDATE timeseries_v7_r4.tasks SET lease_expires_at=now()+(%s * interval '1 second'),"
                " updated_at=now() WHERE run_id=%s AND task_key=%s AND state='RUNNING'"
                " AND lease_token=%s AND lease_owner=%s RETURNING 1",
                (lease_seconds, lease.run_id, lease.task_key, lease.lease_token, worker_id),
            ).fetchone()
            conn.commit()
            return row is not None

    def finish(self, lease: Lease, worker_id: str, result: dict[str, Any], state: str) -> bool:
        blob = canonical_json(result)
        with self.connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "UPDATE timeseries_v7_r4.tasks SET state=%s,lease_owner=NULL,lease_token=NULL,"
                    " lease_expires_at=NULL,blocker_signature=%s,updated_at=now(),"
                    " available_at=CASE WHEN %s='RETRY_WAIT' THEN now()+interval '60 seconds' ELSE available_at END"
                    " WHERE run_id=%s AND task_key=%s AND state='RUNNING'"
                    " AND lease_token=%s AND lease_owner=%s RETURNING 1",
                    (state, result.get("blocker_signature"), state, lease.run_id, lease.task_key,
                     lease.lease_token, worker_id),
                ).fetchone()
                if row is None:
                    return False
                conn.execute(
                    "UPDATE timeseries_v7_r4.attempts SET state=%s,completed_at=now(),"
                    " result=%s::jsonb,result_hash=%s WHERE run_id=%s AND attempt_id=%s"
                    " AND lease_token=%s",
                    (state, blob.decode("utf-8"), sha256_bytes(blob), lease.run_id,
                     lease.attempt_id, lease.lease_token),
                )
            return True

    def requeue_expired(self, run_id: str) -> int:
        with self.connect() as conn:
            rows = conn.execute(
                "UPDATE timeseries_v7_r4.tasks SET state='RETRY_WAIT',lease_owner=NULL,"
                " lease_token=NULL,lease_expires_at=NULL,available_at=now(),updated_at=now()"
                " WHERE run_id=%s AND state='RUNNING' AND lease_expires_at<now() RETURNING task_key",
                (run_id,),
            ).fetchall()
            conn.commit()
            return len(rows)

    def event(self, run_id: str, event_type: str, payload: dict[str, Any],
              task_key: str | None = None) -> None:
        blob = canonical_json(payload)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO timeseries_v7_r4.events"
                " (run_id,event_type,task_key,payload,payload_hash) VALUES (%s,%s,%s,%s::jsonb,%s)",
                (run_id, event_type, task_key, blob.decode("utf-8"), sha256_bytes(blob)),
            )
            conn.commit()

    def set_run_state(self, run_id: str, state: str, reason: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE timeseries_v7_r4.runs SET state=%s,terminal_reason=%s::jsonb,updated_at=now()"
                " WHERE run_id=%s",
                (state, json.dumps(reason) if reason is not None else None, run_id),
            )
            conn.commit()

    def status(self, run_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            run = conn.execute(
                "SELECT state,created_at,updated_at,terminal_reason FROM timeseries_v7_r4.runs"
                " WHERE run_id=%s", (run_id,),
            ).fetchone()
            if run is None:
                raise KeyError(run_id)
            counts = conn.execute(
                "SELECT state,count(*) FROM timeseries_v7_r4.tasks WHERE run_id=%s GROUP BY state",
                (run_id,),
            ).fetchall()
            return {
                "run_id": run_id,
                "state": run[0],
                "created_at": run[1].isoformat(),
                "updated_at": run[2].isoformat(),
                "terminal_reason": run[3],
                "task_counts": {row[0]: row[1] for row in counts},
            }

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT event_id,event_type,task_key,payload,created_at"
                " FROM timeseries_v7_r4.events WHERE run_id=%s ORDER BY event_id", (run_id,),
            ).fetchall()
        return [{"event_id": row[0], "event_type": row[1], "task_key": row[2],
                 "payload": row[3], "created_at": row[4].isoformat()} for row in rows]
