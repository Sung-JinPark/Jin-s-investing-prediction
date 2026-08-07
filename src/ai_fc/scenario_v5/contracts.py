"""Contract loading, canonical serialization, and protected-file audit helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import yaml


CONTRACT_FILES = (
    "data/contracts/scenario_v5_evidence_view.yaml",
    "data/contracts/scenario_v5_model.yaml",
    "data/contracts/scenario_v5_event_impact.yaml",
)

PROTECTED_PATHS = (
    "data/scenarios/nasdaq_latest.json",
    "data/scenarios/archive",
    "forecasts",
    "calibration",
    "questions/registry.yaml",
    "data/ml_history",
    "data/signals",
    "data/liquidity",
    "data/cross_asset",
    "data/ai_capital_cycle",
)


def load_contracts(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for relative in CONTRACT_FILES:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing Scenario V5 contract: {relative}")
        result[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return result


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files_under(root: Path, relative: str) -> Iterable[Path]:
    target = root / relative
    if target.is_file():
        yield target
    elif target.is_dir():
        yield from sorted(path for path in target.rglob("*") if path.is_file())


def protected_hashes(root: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    missing: list[str] = []
    for relative in PROTECTED_PATHS:
        matched = list(_files_under(root, relative))
        if not matched:
            missing.append(relative)
        for path in matched:
            key = path.relative_to(root).as_posix()
            files[key] = file_hash(path)
    return {
        "algorithm": "sha256",
        "protected_roots": list(PROTECTED_PATHS),
        "files": files,
        "missing_roots": missing,
        "manifest_sha256": canonical_hash(files),
    }


def compare_protected_hashes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = before.get("files", {})
    new = after.get("files", {})
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(path for path in set(old) & set(new) if old[path] != new[path])
    return {
        "ok": not (added or removed or changed),
        "added": added,
        "removed": removed,
        "changed": changed,
        "before_manifest_sha256": before.get("manifest_sha256"),
        "after_manifest_sha256": after.get("manifest_sha256"),
    }
