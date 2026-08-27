"""R6 immutable-input, protected-scope and PIT preflight utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from .outer_guard import R5OuterDenylist


PROTECTED_ROOTS = (
    "data/scenarios",
    "data/statistics/official_store",
    "forecasts",
    "calibration",
)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_manifest(repo_root: Path) -> dict[str, object]:
    root = repo_root.resolve()
    entries: list[dict[str, object]] = []
    for relative_root in PROTECTED_ROOTS:
        candidate = root / relative_root
        if not candidate.exists():
            continue
        for path in sorted(item for item in candidate.rglob("*") if item.is_file()):
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    payload: dict[str, object] = {
        "schema": "r6_protected_manifest_v1",
        "roots": list(PROTECTED_ROOTS),
        "entries": entries,
        "entry_count": len(entries),
    }
    payload["manifest_sha256"] = hashlib.sha256(canonical_json(entries)).hexdigest()
    return payload


def verify_inputs(repo_root: Path, contract: dict[str, object]) -> dict[str, object]:
    root = repo_root.resolve()
    guard = R5OuterDenylist.load(root)
    results = []
    for name, record in contract["input_artifacts"].items():
        path = root / record["path"]
        role = str(record["allowed_role"])
        guard.assert_role_allowed(role)
        guard.assert_path_allowed(path)
        actual = sha256_file(path)
        expected = str(record["sha256"])
        results.append(
            {
                "name": name,
                "path": record["path"],
                "role": role,
                "sha256": actual,
                "matched": actual == expected,
            }
        )
    return {
        "schema": "r6_input_verification_v1",
        "inputs": results,
        "all_matched": all(item["matched"] for item in results),
        "outer_rows_used": 0,
    }


def role_hash(origins: Iterable[str]) -> str:
    return hashlib.sha256(canonical_json(sorted(set(origins)))).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(payload) + b"\n")
