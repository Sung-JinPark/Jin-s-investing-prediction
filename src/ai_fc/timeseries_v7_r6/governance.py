"""R6 immutable-input, protected-scope and PIT preflight utilities."""

from __future__ import annotations

import hashlib
import json
import copy
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


def load_active_contract(repo_root: Path) -> dict[str, object]:
    """Resolve the append-only v1.1 input registration over the frozen v1 contract."""

    root = repo_root.resolve()
    base_path = (
        root / "data/timeseries_v7_r6/contracts/r6_sharpen_tilt_shadow_v1.json"
    )
    revision_path = (
        root / "data/timeseries_v7_r6/contracts/r6_sharpen_tilt_shadow_v1_1.json"
    )
    base = json.loads(base_path.read_text(encoding="utf-8"))
    revision = json.loads(revision_path.read_text(encoding="utf-8"))
    supersedes = revision.get("supersedes", {})
    if supersedes.get("path") != base_path.relative_to(root).as_posix():
        raise ValueError("R6 v1.1 must supersede the frozen v1 path")
    if supersedes.get("sha256") != sha256_file(base_path):
        raise ValueError("R6 v1 parent hash drift")
    if revision.get("candidate_outputs_seen_before_registration") is not False:
        raise ValueError("R6 input correction must precede every candidate output")
    if revision.get("outer_rows_used") != 0:
        raise ValueError("R6 input correction may not use outer rows")

    resolved = copy.deepcopy(base)
    appended = revision.get("appended_input_artifacts", {})
    overlap = set(resolved["input_artifacts"]) & set(appended)
    if overlap:
        raise ValueError(f"R6 input correction may not replace inputs: {sorted(overlap)}")
    resolved["input_artifacts"].update(copy.deepcopy(appended))
    resolved["active_revision"] = {
        "revision": revision["revision"],
        "path": revision_path.relative_to(root).as_posix(),
        "sha256": sha256_file(revision_path),
        "supersedes_sha256": supersedes["sha256"],
    }
    return resolved


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
