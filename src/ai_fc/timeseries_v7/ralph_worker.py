"""Lease-aware subprocess worker with continuous heartbeat and cancellation."""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .ralph_store import HEARTBEAT_SECONDS, Lease, LeaseLost, RalphStore


@dataclass(frozen=True)
class WorkerOutcome:
    state: str
    returncode: int | None
    stdout_tail: str
    stderr_tail: str
    heartbeat_count: int
    terminated: bool


def _tail(handle, limit: int = 8192) -> str:
    handle.flush()
    size = handle.tell()
    handle.seek(max(0, size - limit))
    return handle.read().decode("utf-8", errors="replace")


def _terminate(process: subprocess.Popen[bytes], grace_seconds: float) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=grace_seconds)


def run_leased_process(
    store: RalphStore,
    lease: Lease,
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    heartbeat_interval: float = HEARTBEAT_SECONDS,
    poll_interval: float = 0.1,
    timeout_seconds: float | None = None,
    termination_grace_seconds: float = 5.0,
) -> WorkerOutcome:
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("command must be a non-empty argv sequence")
    if heartbeat_interval <= 0 or poll_interval <= 0:
        raise ValueError("heartbeat and poll intervals must be positive")
    store.start(lease)
    stop = threading.Event()
    lease_lost = threading.Event()
    heartbeat_count = 0
    heartbeat_lock = threading.Lock()

    def heartbeat_loop() -> None:
        nonlocal heartbeat_count
        while not stop.wait(heartbeat_interval):
            try:
                store.heartbeat(lease)
                with heartbeat_lock:
                    heartbeat_count += 1
            except LeaseLost:
                lease_lost.set()
                stop.set()
                return

    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            list(command), cwd=str(cwd), env=dict(environment), shell=False,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        )
        thread = threading.Thread(target=heartbeat_loop, name="v7-heartbeat", daemon=True)
        thread.start()
        started = time.monotonic()
        state = "running"
        terminated = False
        try:
            while process.poll() is None:
                if lease_lost.is_set():
                    state = "lease_lost"
                    _terminate(process, termination_grace_seconds)
                    terminated = True
                    break
                if store.cancellation_requested(lease):
                    state = "cancelled"
                    _terminate(process, termination_grace_seconds)
                    terminated = True
                    break
                if timeout_seconds is not None and time.monotonic() - started >= timeout_seconds:
                    state = "timeout"
                    _terminate(process, termination_grace_seconds)
                    terminated = True
                    break
                time.sleep(poll_interval)
            if state == "running":
                state = "succeeded" if process.returncode == 0 else "failed"
        finally:
            stop.set()
            thread.join(timeout=max(heartbeat_interval * 2, 1.0))
        return WorkerOutcome(
            state=state,
            returncode=process.returncode,
            stdout_tail=_tail(stdout), stderr_tail=_tail(stderr),
            heartbeat_count=heartbeat_count, terminated=terminated,
        )
