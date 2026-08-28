"""Append-only V8 development experiment ledgers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .contracts import (
    EXPERIMENT_LEDGER_RELATIVE,
    HOLDOUT_LEDGER_RELATIVE,
    canonical_hash,
)


class TimeSeriesV8ArtifactError(RuntimeError):
    """A V8 append-only ledger invariant failed closed."""


def append_unique(root: Path, relative: Path, payload: dict[str, Any], *, key: str) -> bool:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                row = json.loads(line)
                existing[str(row[key])] = row
    identity = str(payload[key])
    if identity in existing:
        if existing[identity] != payload:
            raise TimeSeriesV8ArtifactError(f"append-only collision for {identity}")
        return False
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def read_ledger(root: Path, relative: Path) -> list[dict[str, Any]]:
    path = root / relative
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_experiments(root: Path) -> list[dict[str, Any]]:
    return read_ledger(root, EXPERIMENT_LEDGER_RELATIVE)


def read_holdout_scorings(root: Path) -> list[dict[str, Any]]:
    return read_ledger(root, HOLDOUT_LEDGER_RELATIVE)


def append_experiment(root: Path, payload: dict[str, Any]) -> bool:
    if payload.get("window_role") != "design":
        raise TimeSeriesV8ArtifactError("the experiment ledger records design-window runs only")
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    payload = {**body, "content_hash": canonical_hash(body)}
    return append_unique(root, EXPERIMENT_LEDGER_RELATIVE, payload, key="experiment_id")


def append_holdout_scoring(root: Path, payload: dict[str, Any]) -> bool:
    if payload.get("window_role") != "holdout":
        raise TimeSeriesV8ArtifactError("the holdout ledger records holdout scorings only")
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    payload = {**body, "content_hash": canonical_hash(body)}
    return append_unique(root, HOLDOUT_LEDGER_RELATIVE, payload, key="experiment_id")
