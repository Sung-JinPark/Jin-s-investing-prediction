"""R4 specification loading and validation."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import yaml

from .integrity import safe_zip_inventory, sha256_file


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping: {path}")
    return value


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping: {path}")
    return value


def verify_pack(path: Path, expected_sha: str | None = None) -> dict[str, Any]:
    actual = sha256_file(path)
    if expected_sha and actual != expected_sha:
        raise ValueError(f"input hash mismatch for {path}: {actual} != {expected_sha}")
    inventory = safe_zip_inventory(path)
    return {"path": str(path.resolve()), "sha256": actual, "bytes": path.stat().st_size,
            "entry_count": len(inventory)}


def read_zip_json(path: Path, member: str) -> dict[str, Any]:
    safe_zip_inventory(path)
    with zipfile.ZipFile(path) as archive:
        value = json.loads(archive.read(member))
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping: {member}")
    return value


def verify_delivery_spec(spec_root: Path) -> dict[str, Any]:
    manifest_path = spec_root / "NASDAQ_V7_R3_RALPH_R4_DELIVERY_MANIFEST_20260826.json"
    manifest = read_json(manifest_path)
    rows: list[dict[str, Any]] = []
    for expected in manifest["files"]:
        path = spec_root / expected["name"]
        actual = {"name": expected["name"], "exists": path.is_file()}
        if path.is_file():
            actual.update({"bytes": path.stat().st_size, "sha256": sha256_file(path)})
        actual["pass"] = (actual.get("bytes") == expected["bytes"] and
                          actual.get("sha256") == expected["sha256"])
        rows.append(actual)
    backlog = read_json(spec_root / "NASDAQ_V7_R3_RALPH_R4_BOOTSTRAP_BACKLOG_20260826.json")
    ids = [str(item.get("task_id") or item.get("id")) for item in backlog["tasks"]]
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "files": rows,
        "file_hashes_pass": all(row["pass"] for row in rows),
        "backlog_task_count": len(ids),
        "backlog_duplicate_ids": len(ids) - len(set(ids)),
        "backlog_internal_pass": len(ids) == backlog["task_count"] == 45 and len(ids) == len(set(ids)),
    }
