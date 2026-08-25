"""Logical-row and physical-byte identities for V7 artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ArtifactIdentity:
    logical_rows_sha256: str
    physical_artifact_sha256: str
    row_count: int
    byte_count: int
    encoding: str
    newline: str


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_jsonl(rows: Iterable[dict[str, Any]]) -> tuple[bytes, int]:
    parts: list[bytes] = []
    for row in rows:
        parts.append(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    return (b"\n".join(parts) + (b"\n" if parts else b""), len(parts))


def identify_jsonl(rows: Iterable[dict[str, Any]], physical_bytes: bytes, *, encoding: str = "utf-8", newline: str) -> ArtifactIdentity:
    logical, count = canonical_jsonl(rows)
    if newline not in {"lf", "crlf"}:
        raise ValueError("newline must be lf or crlf")
    return ArtifactIdentity(_sha(logical), _sha(physical_bytes), count, len(physical_bytes), encoding, newline)


def verify_physical(identity: ArtifactIdentity, physical_bytes: bytes) -> bool:
    return identity.physical_artifact_sha256 == _sha(physical_bytes) and identity.byte_count == len(physical_bytes)
