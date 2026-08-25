"""Run/cycle/generation scoped V7 task identities."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


COORDINATE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class TaskIdentityError(ValueError):
    """A task coordinate or idempotency input is invalid."""


def _coordinate(value: str, name: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if not COORDINATE_RE.fullmatch(value):
        raise TaskIdentityError(f"invalid {name}")
    return value


def canonical_hash(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True, order=True)
class TaskIdentity:
    run_id: str
    cycle_id: str
    generation_id: str
    task_key: str

    def __post_init__(self) -> None:
        _coordinate(self.run_id, "run_id")
        _coordinate(self.cycle_id, "cycle_id")
        _coordinate(self.generation_id, "generation_id", allow_empty=True)
        _coordinate(self.task_key, "task_key")

    def as_tuple(self) -> tuple[str, str, str, str]:
        return self.run_id, self.cycle_id, self.generation_id, self.task_key

    def as_dict(self) -> dict[str, str]:
        return dict(zip(("run_id", "cycle_id", "generation_id", "task_key"), self.as_tuple()))

    def idempotency_key(self, *, payload_hash: str, input_snapshot_hash: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", payload_hash):
            raise TaskIdentityError("payload_hash must be lowercase sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", input_snapshot_hash):
            raise TaskIdentityError("input_snapshot_hash must be lowercase sha256")
        return canonical_hash({
            **self.as_dict(),
            "payload_hash": payload_hash,
            "input_snapshot_hash": input_snapshot_hash,
        })
