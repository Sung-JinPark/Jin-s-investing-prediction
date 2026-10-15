"""Bounded warm polling for confirmed earnings; no ledger or network transport."""

from __future__ import annotations

import json
import math
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .earnings_refresh import EarningsRefreshError, _time, capture_earnings


MAX_WATCH_SECONDS = 19_800


def _duration(value: Any, name: str, *, maximum: float, zero: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EarningsRefreshError(f"{name} must be a finite numeric duration")
    if value < 0 or (not zero and value == 0) or value > maximum:
        raise EarningsRefreshError(f"{name} exceeds the bounded watch duration")
    return float(value)


def _watch_remaining(manifest: dict[str, Any], now: datetime) -> float:
    """A reported actual from either provider completes that event's watch."""
    events, statuses = manifest.get("events"), manifest.get("event_status")
    if not isinstance(events, list) or not isinstance(statuses, list):
        raise EarningsRefreshError("watch bundle lacks registered events/source statuses")
    reported: set[str] = set()
    for status in statuses:
        if (not isinstance(status, dict) or status.get("kind") not in {"nasdaq", "official"}
                or status.get("status") not in {"reported", "pending", "failed"}
                or not status.get("event_id")):
            raise EarningsRefreshError("invalid watch source status")
        if status["status"] == "reported":
            reported.add(status["event_id"])
    deadlines = []
    for event in events:
        if not isinstance(event, dict) or not event.get("event_id"):
            raise EarningsRefreshError("invalid watch registered event")
        if event.get("kind") != "earnings" or event.get("status") != "confirmed":
            continue
        if event["event_id"] in reported:
            continue
        scheduled = _time(event.get("scheduled_at")) if event.get("scheduled_at") else None
        if scheduled is None:
            raise EarningsRefreshError("confirmed watch event lacks scheduled_at")
        if scheduled - timedelta(hours=6) <= now <= scheduled + timedelta(hours=3):
            deadlines.append(scheduled + timedelta(hours=3))
    return max(((deadline - now).total_seconds() for deadline in deadlines), default=0.0)


def watch_earnings(root: Path, *, output_dir: Path | str,
                   clock: Callable[[], datetime] | None = None,
                   sleep: Callable[[float], Any] | None = None,
                   capture: Callable[..., dict[str, Any]] | None = None,
                   max_seconds: float = MAX_WATCH_SECONDS,
                   poll_seconds: float = 60) -> dict[str, Any]:
    """Capture immediately, then poll pending confirmed releases on this runner.

    Each attempt has a fresh immutable directory. Only the selected final bundle
    is renamed to ``output_dir``; temporary attempts are discarded. A changed or
    partial capture returns immediately. No existing output can be reused.
    """
    budget = _duration(max_seconds, "max_seconds", maximum=MAX_WATCH_SECONDS, zero=True)
    interval = _duration(poll_seconds, "poll_seconds", maximum=60, zero=False)
    workspace = Path(root).resolve()
    if not workspace.is_dir():
        raise EarningsRefreshError("earnings watch workspace is unavailable")
    supplied = Path(output_dir)
    destination = (supplied if supplied.is_absolute() else workspace / supplied).resolve()
    if destination == workspace or not destination.is_relative_to(workspace):
        raise EarningsRefreshError("earnings watch output must stay within its workspace")
    parent = destination.parent
    if not parent.is_relative_to(workspace):
        raise EarningsRefreshError("earnings watch output parent escaped its workspace")
    if destination.exists() or destination.is_symlink():
        raise EarningsRefreshError("earnings watch output already exists")
    parent.mkdir(parents=True, exist_ok=True)
    if parent.resolve() != parent or not parent.resolve().is_relative_to(workspace):
        raise EarningsRefreshError("earnings watch output parent changed")

    tick = clock or (lambda: datetime.now(timezone.utc))
    pause = sleep or time.sleep
    collect = capture or capture_earnings
    started = previous = _time(tick())
    attempts = 0

    def checked_time() -> datetime:
        nonlocal previous
        current = _time(tick())
        if current < previous:
            raise EarningsRefreshError("earnings watch clock moved backwards")
        previous = current
        return current

    while True:
        # The context owns only this verified workspace-local scratch directory.
        # On completion, the bundle is moved out before scratch cleanup runs.
        with tempfile.TemporaryDirectory(prefix=".earnings-watch-", dir=parent) as scratch:
            temporary = Path(scratch).resolve()
            if not temporary.is_relative_to(parent) or not temporary.is_relative_to(workspace):
                raise EarningsRefreshError("earnings watch scratch directory escaped its parent")
            attempt = temporary / "bundle"
            report = collect(workspace, output_dir=attempt, now=checked_time(), clock=checked_time)
            attempts += 1
            finished = checked_time()
            if (not isinstance(report, dict) or type(report.get("changed_hint")) is not bool
                    or report.get("status") not in {"captured", "partial", "failed"}):
                raise EarningsRefreshError("invalid earnings capture watch decision")
            if (not report.get("bundle_path") or Path(report["bundle_path"]).resolve() != attempt
                    or not attempt.is_dir() or attempt.is_symlink()):
                raise EarningsRefreshError("earnings capture returned a different bundle directory")
            manifest_path = attempt / "manifest.json"
            if not manifest_path.resolve().is_relative_to(attempt) or not manifest_path.is_file():
                raise EarningsRefreshError("earnings watch bundle manifest escaped or is missing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            remaining_window = _watch_remaining(manifest, finished)
            elapsed = (finished - started).total_seconds()
            final = (report["changed_hint"] or report["status"] != "captured"
                     or elapsed >= budget or remaining_window <= 0)
            if final:
                # Recheck resolved parent and target immediately before rename.
                if (destination.parent.resolve() != parent or destination.resolve() != destination
                        or not destination.is_relative_to(workspace)
                        or attempt.resolve() != attempt or not attempt.is_relative_to(temporary)):
                    raise EarningsRefreshError("earnings watch publication path changed")
                if destination.exists() or destination.is_symlink():
                    raise EarningsRefreshError("earnings watch output already exists")
                attempt.rename(destination)
                return {**report, "bundle_path": str(destination),
                        "watch_attempts": attempts, "watch_seconds": elapsed,
                        "watch_pending": remaining_window > 0,
                        "watch_until": (finished + timedelta(seconds=remaining_window)).isoformat() if remaining_window > 0 else None}
            delay = min(interval, budget - elapsed, remaining_window)
        # Discard the prior immutable attempt before waiting; only the selected
        # final attempt is retained. No durable source or ledger is modified.
        print(f"Earnings watch: attempt {attempts}, no new result; next check in {delay:.0f}s "
              f"({elapsed:.0f}s elapsed).", file=sys.stderr, flush=True)
        pause(delay)
