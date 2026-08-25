"""Durable Atlas V2 execution loop with leases, checkpoints, and honest HOLDs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .security import build_worker_environment


class AtlasError(RuntimeError):
    pass


TERMINAL = {"succeeded", "hold", "failed", "cancelled"}


@dataclass(frozen=True)
class AtlasTask:
    task_id: str
    task_type: str
    capability: str
    dependencies: tuple[str, ...]
    command: tuple[str, ...]
    max_attempts: int = 3
    timeout_seconds: int = 3600

    def validate(self) -> None:
        if self.capability not in {"collector", "materializer", "trainer_cpu", "trainer_gpu", "evaluator", "codex_worker", "reviewer"}:
            raise AtlasError("unknown task capability")
        if not self.command or self.command[0] not in {sys.executable, "python", "pytest"}:
            raise AtlasError("task command executable is not allowlisted")
        joined = " ".join(self.command).lower()
        if any(token in joined for token in ("git push", "git merge", "gh pr", "pages deploy", "--auto-merge")):
            raise AtlasError("publication commands are prohibited in autonomous Atlas")
        if self.max_attempts < 1 or self.timeout_seconds < 1:
            raise AtlasError("invalid task retry/timeout budget")


class AtlasStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS plan(plan_hash TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task(
              task_id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL, task_type TEXT NOT NULL,
              capability TEXT NOT NULL, dependencies TEXT NOT NULL, command TEXT NOT NULL,
              max_attempts INTEGER NOT NULL, timeout_seconds INTEGER NOT NULL,
              state TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
              lease_owner TEXT, lease_expires_at TEXT, heartbeat_at TEXT,
              blocker_fingerprint TEXT, blocker_repetitions INTEGER NOT NULL DEFAULT 0,
              checkpoint_sha256 TEXT, result_json TEXT, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS event(
              event_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              event_type TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
            """
        )
        self.connection.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def register_plan(self, tasks: Iterable[AtlasTask]) -> str:
        rows = tuple(tasks)
        for task in rows:
            task.validate()
        ids = {task.task_id for task in rows}
        if len(ids) != len(rows) or any(set(task.dependencies) - ids for task in rows):
            raise AtlasError("task ids/dependencies are invalid")
        payload = json.dumps([asdict(task) for task in rows], sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        self.connection.execute("INSERT OR IGNORE INTO plan VALUES (?,?,?)", (digest, payload, self._now()))
        for task in rows:
            self.connection.execute(
                "INSERT OR IGNORE INTO task VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task.task_id, digest, task.task_type, task.capability, json.dumps(task.dependencies),
                 json.dumps(task.command), task.max_attempts, task.timeout_seconds, "pending", 0,
                 None, None, None, None, 0, None, None, self._now()),
            )
        self.connection.commit()
        return digest

    def lease_next(self, worker_id: str, capabilities: set[str], lease_seconds: int = 120) -> sqlite3.Row | None:
        now = datetime.now(timezone.utc)
        self.connection.execute("BEGIN IMMEDIATE")
        rows = self.connection.execute("SELECT * FROM task WHERE state IN ('pending','retry','leased','running') ORDER BY task_id").fetchall()
        for row in rows:
            if row["capability"] not in capabilities:
                continue
            expiry = datetime.fromisoformat(row["lease_expires_at"]) if row["lease_expires_at"] else None
            if row["state"] in {"leased", "running"} and expiry and expiry > now:
                continue
            deps = json.loads(row["dependencies"])
            states = {item["task_id"]: item["state"] for item in self.connection.execute("SELECT task_id,state FROM task").fetchall()}
            if any(states.get(dep) != "succeeded" for dep in deps):
                continue
            until = (now + timedelta(seconds=lease_seconds)).isoformat()
            self.connection.execute(
                "UPDATE task SET state='leased',lease_owner=?,lease_expires_at=?,heartbeat_at=?,updated_at=? WHERE task_id=?",
                (worker_id, until, now.isoformat(), now.isoformat(), row["task_id"]),
            )
            self.connection.commit()
            return self.connection.execute("SELECT * FROM task WHERE task_id=?", (row["task_id"],)).fetchone()
        self.connection.commit()
        return None

    def heartbeat(self, task_id: str, worker_id: str, lease_seconds: int = 120) -> None:
        now = datetime.now(timezone.utc)
        cursor = self.connection.execute(
            "UPDATE task SET state='running',heartbeat_at=?,lease_expires_at=?,updated_at=? WHERE task_id=? AND lease_owner=? AND state IN ('leased','running')",
            (now.isoformat(), (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat(), task_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise AtlasError("lease ownership lost")
        self.connection.commit()

    def finish(self, task_id: str, worker_id: str, *, returncode: int, result: dict, blocker: str | None = None) -> str:
        row = self.connection.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
        if not row or row["lease_owner"] != worker_id:
            raise AtlasError("cannot finish a task without its lease")
        attempts = row["attempt_count"] + 1
        fingerprint = hashlib.sha256((blocker or "").encode()).hexdigest() if blocker else None
        repetitions = row["blocker_repetitions"] + 1 if fingerprint and fingerprint == row["blocker_fingerprint"] else (1 if fingerprint else 0)
        if returncode == 0:
            state = "succeeded"
        elif repetitions >= 3:
            state = "hold"
        elif attempts >= row["max_attempts"]:
            state = "failed"
        else:
            state = "retry"
        checkpoint = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.connection.execute(
            "UPDATE task SET state=?,attempt_count=?,lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL,blocker_fingerprint=?,blocker_repetitions=?,checkpoint_sha256=?,result_json=?,updated_at=? WHERE task_id=?",
            (state, attempts, fingerprint, repetitions, checkpoint, json.dumps(result, sort_keys=True), self._now(), task_id),
        )
        self.connection.execute("INSERT INTO event(task_id,event_type,payload,recorded_at) VALUES (?,?,?,?)", (task_id, state, json.dumps(result, sort_keys=True), self._now()))
        self.connection.commit()
        return state

    def status(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM task ORDER BY task_id")]


class AtlasWorker:
    def __init__(self, store: AtlasStore, *, worker_id: str, capabilities: set[str], root: Path) -> None:
        self.store = store
        self.worker_id = worker_id
        self.capabilities = capabilities
        self.root = root

    def run_once(self) -> str | None:
        row = self.store.lease_next(self.worker_id, self.capabilities)
        if row is None:
            return None
        self.store.heartbeat(row["task_id"], self.worker_id)
        command = json.loads(row["command"])
        role = "codex" if row["capability"] == "codex_worker" else row["capability"]
        environment = build_worker_environment(role, os.environ).values
        try:
            completed = subprocess.run(command, cwd=self.root, env=environment, capture_output=True, text=True, timeout=row["timeout_seconds"], check=False)
            blocker = completed.stderr[-4000:] or completed.stdout[-4000:] if completed.returncode else None
            result = {"returncode": completed.returncode, "stdout_tail": completed.stdout[-4000:], "stderr_tail": completed.stderr[-4000:]}
            return self.store.finish(row["task_id"], self.worker_id, returncode=completed.returncode, result=result, blocker=blocker)
        except subprocess.TimeoutExpired as exc:
            return self.store.finish(row["task_id"], self.worker_id, returncode=124, result={"timeout": True}, blocker="timeout")

    def run_until_terminal(self, *, max_iterations: int = 100) -> list[dict]:
        for _ in range(max_iterations):
            state = self.run_once()
            if state is None:
                break
        return self.store.status()
