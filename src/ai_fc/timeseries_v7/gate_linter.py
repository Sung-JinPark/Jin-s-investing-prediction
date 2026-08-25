"""Static sample-feasibility linter for V7 gate windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


@dataclass(frozen=True)
class GateWindow:
    name: str
    start: date
    end: date
    minimum_origins: int


def weekly_capacity(start: date, end: date) -> int:
    if end < start:
        return 0
    cursor = start + timedelta(days=(4 - start.weekday()) % 7)
    count = 0
    while cursor <= end:
        count += 1
        cursor += timedelta(days=7)
    return count


def intersection(left_start: date, left_end: date, right_start: date, right_end: date) -> tuple[date, date] | None:
    start, end = max(left_start, right_start), min(left_end, right_end)
    return None if end < start else (start, end)


def lint_gate_windows(*, evaluation_start: date, evaluation_end: date, windows: Iterable[GateWindow]) -> dict[str, object]:
    checks = []
    for window in windows:
        overlap = intersection(evaluation_start, evaluation_end, window.start, window.end)
        capacity = 0 if overlap is None else weekly_capacity(*overlap)
        checks.append({
            "gate": window.name, "available_capacity": capacity,
            "required": window.minimum_origins, "feasible": capacity >= window.minimum_origins,
        })
    failures = [row for row in checks if not row["feasible"]]
    return {"checks": checks, "failure_count": len(failures), "failures": failures, "pass": not failures}
