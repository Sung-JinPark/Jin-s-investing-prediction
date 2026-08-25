from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_fc.timeseries_v7.ralph_store import Lease
from ai_fc.timeseries_v7.ralph_worker import run_leased_process
from ai_fc.timeseries_v7.task_identity import TaskIdentity


class FakeStore:
    def __init__(self, *, cancel_after: int | None = None):
        self.started = False
        self.heartbeats = 0
        self.polls = 0
        self.cancel_after = cancel_after

    def start(self, lease: Lease) -> None:
        self.started = True

    def heartbeat(self, lease: Lease) -> None:
        self.heartbeats += 1

    def cancellation_requested(self, lease: Lease) -> bool:
        self.polls += 1
        return self.cancel_after is not None and self.polls >= self.cancel_after


def lease() -> Lease:
    return Lease(
        identity=TaskIdentity("run", "cycle", "gen", "task"), owner="worker",
        fencing_token=1, lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=1),
        attempt_count=1, payload_hash="a" * 64, input_snapshot_hash="b" * 64,
    )


def test_long_process_keeps_heartbeating() -> None:
    store = FakeStore()
    outcome = run_leased_process(
        store, lease(), [sys.executable, "-c", "import time; time.sleep(.28); print('ok')"],
        cwd=Path.cwd(), environment=os.environ, heartbeat_interval=0.04, poll_interval=0.01,
    )
    assert store.started
    assert outcome.state == "succeeded"
    assert outcome.heartbeat_count >= 5
    assert "ok" in outcome.stdout_tail


def test_cancellation_terminates_child_and_records_outcome() -> None:
    store = FakeStore(cancel_after=3)
    outcome = run_leased_process(
        store, lease(), [sys.executable, "-c", "import time; time.sleep(10)"],
        cwd=Path.cwd(), environment=os.environ, heartbeat_interval=0.02, poll_interval=0.01,
        termination_grace_seconds=0.5,
    )
    assert outcome.state == "cancelled"
    assert outcome.terminated is True
    assert outcome.returncode is not None


def test_timeout_escalation_terminates_child() -> None:
    store = FakeStore()
    outcome = run_leased_process(
        store, lease(), [sys.executable, "-c", "import time; time.sleep(10)"],
        cwd=Path.cwd(), environment=os.environ, heartbeat_interval=0.02, poll_interval=0.01,
        timeout_seconds=0.06, termination_grace_seconds=0.5,
    )
    assert outcome.state == "timeout"
    assert outcome.terminated is True
