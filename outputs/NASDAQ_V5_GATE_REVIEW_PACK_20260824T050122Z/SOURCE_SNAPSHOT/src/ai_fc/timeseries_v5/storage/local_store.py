"""Crash-safe local control plane used by tests and offline research."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class LocalControlPlane:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._indexes: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self._row_cache: dict[str, list[dict[str, Any]]] = {}

    def _path(self, ledger: str) -> Path:
        if not ledger.replace("_", "").replace("-", "").isalnum(): raise ValueError("invalid ledger name")
        return self.root / "ledgers" / f"{ledger}.jsonl"

    def rows(self, ledger: str) -> list[dict[str, Any]]:
        if ledger in self._row_cache:
            return list(self._row_cache[ledger])
        path = self._path(ledger)
        if not path.is_file():
            self._row_cache[ledger] = []
            return []
        output: list[dict[str, Any]] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line: continue
            value = json.loads(line)
            if not isinstance(value, dict): raise ValueError(f"invalid JSONL object {path}:{number}")
            output.append(value)
        self._row_cache[ledger] = output
        return list(output)

    def append(self, ledger: str, row: dict[str, Any], *, identity: str) -> bool:
        return bool(self.append_many(ledger, [row], identity=identity))

    def _pending(self, ledger: str, rows: list[dict[str, Any]], *, identity: str) -> list[dict[str, Any]]:
        if not rows:
            return []
        for row in rows:
            if identity not in row: raise ValueError(f"identity missing: {identity}")
        key = (ledger, identity)
        if key not in self._indexes:
            self._indexes[key] = {str(row[identity]): row for row in self.rows(ledger)}
        index = self._indexes[key]
        pending: list[dict[str, Any]] = []
        pending_ids: set[str] = set()
        for row in rows:
            row_id = str(row[identity])
            prior = index.get(row_id)
            if prior is not None:
                if prior != row: raise ValueError(f"append-only identity collision: {ledger}/{row_id}")
                continue
            if row_id in pending_ids:
                raise ValueError(f"duplicate identity inside append batch: {ledger}/{row_id}")
            pending.append(row); pending_ids.add(row_id)
        return pending

    def validate_many(self, ledger: str, rows: list[dict[str, Any]], *, identity: str) -> int:
        return len(self._pending(ledger, rows, identity=identity))

    def append_many(self, ledger: str, rows: list[dict[str, Any]], *, identity: str) -> int:
        """Validate a batch before one durable append operation.

        This preserves the same append-only collision semantics as ``append``
        without the quadratic full-ledger scan and one-fsync-per-observation cost.
        """
        pending = self._pending(ledger, rows, identity=identity)
        if not pending:
            return 0
        path = self._path(ledger)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.writelines(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in pending)
            handle.flush(); os.fsync(handle.fileno())
        self._indexes[(ledger, identity)].update({str(row[identity]): row for row in pending})
        self._row_cache.setdefault(ledger, []).extend(pending)
        return len(pending)

    def append_bundle(self, batches: list[tuple[str, list[dict[str, Any]], str]]) -> int:
        """Prevalidate every ledger batch before any source-derived row is written."""
        for ledger, rows, identity in batches:
            self.validate_many(ledger, rows, identity=identity)
        return sum(self.append_many(ledger, rows, identity=identity) for ledger, rows, identity in batches)
