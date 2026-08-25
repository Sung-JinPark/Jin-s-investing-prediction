"""Immutable V1-V6 protection contract for NASDAQ V7 research tasks."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
BASELINE_ID = "timeseries-v7-protected-v1-v6-baseline"

# Roots detect additions, removals, and edits anywhere below the declared path.
ROOT_SPECS: tuple[tuple[str, str], ...] = (
    ("predecessor_data", "data/timeseries"),
    ("predecessor_data", "data/timeseries_v1"),
    ("predecessor_data", "data/timeseries_v2"),
    ("predecessor_data", "data/timeseries_v3"),
    ("predecessor_data", "data/timeseries_v4"),
    ("predecessor_data", "data/timeseries_v5"),
    ("predecessor_data", "data/timeseries_v6"),
    ("predecessor_outputs", "outputs/timeseries_v1"),
    ("predecessor_outputs", "outputs/timeseries_v2"),
    ("predecessor_outputs", "outputs/timeseries_v3"),
    ("predecessor_outputs", "outputs/timeseries_v4"),
    ("predecessor_outputs", "outputs/timeseries_v5"),
    ("predecessor_outputs", "outputs/timeseries_v6"),
    ("scenario_forecast_data", "data/scenarios"),
    ("scenario_forecast_data", "data/forecasts"),
    ("official_ledgers", "data/ledgers"),
    ("official_ledgers", "data/statistics/official_store/ledgers"),
    ("official_ledgers", "calibration"),
    ("predecessor_source", "src/ai_fc/timeseries"),
    ("predecessor_source", "src/ai_fc/timeseries_v1"),
    ("predecessor_source", "src/ai_fc/timeseries_v2"),
    ("predecessor_source", "src/ai_fc/timeseries_v3"),
    ("predecessor_source", "src/ai_fc/timeseries_v4"),
    ("predecessor_source", "src/ai_fc/timeseries_v5"),
    ("predecessor_source", "src/ai_fc/timeseries_v6"),
    ("predecessor_source", "src/ai_fc/scenario_v5"),
    ("predecessor_source", "src/ai_fc/scenario_v5_2"),
    ("predecessor_tests", "src/tests/timeseries_v5"),
    ("predecessor_tests", "src/tests/timeseries_v6"),
    ("runtime_replay", "locks/timeseries_v6"),
    ("runtime_replay", "containers/timeseries_v6"),
)

# Globs protect predecessor entry points that do not live in versioned roots.
GLOB_SPECS: tuple[tuple[str, str], ...] = (
    ("predecessor_contract", "data/contracts/multivariate_timeseries_v[1-6]*"),
    ("scenario_contract", "data/contracts/scenario*.yaml"),
    ("scenario_contract", "data/contracts/*forecast*.yaml"),
    ("scenario_contract", "data/contracts/ledger_registry.yaml"),
    ("public_surface_contract", "data/contracts/website_data_lineage_v1.yaml"),
    ("predecessor_source", "src/ai_fc/scenario*.py"),
    ("predecessor_tests", "src/tests/test_multivariate_timeseries*.py"),
    ("predecessor_tests", "src/tests/test_scenario*.py"),
    ("predecessor_tests", "src/tests/test_ralph_timeseries.py"),
    ("predecessor_workflow", ".github/workflows/timeseries*.yml"),
    ("predecessor_workflow", ".github/workflows/scenario*.yml"),
    ("predecessor_tool", "tools/*timeseries*"),
    ("predecessor_tool", "tools/*scenario*"),
    ("predecessor_tool", "tools/*v6*"),
    ("predecessor_tool", "tools/atlas*.py"),
)

FILE_SPECS: tuple[tuple[str, str], ...] = (
    ("public_numerical_surface", "_site/data.json"),
    ("public_numerical_surface", "_site/future_paths.json"),
    ("public_numerical_surface", "_site/statistics.json"),
    ("v7_audit_seed", "docs/timeseries_v7/V6_FAILURE_BASELINE.md"),
    ("v7_audit_seed", "src/tests/timeseries_v7/test_v6_gate_audit.py"),
    ("v7_audit_seed", "outputs/timeseries_v7/audit/v6_gate_reproduction.json"),
    ("v7_audit_seed", "outputs/timeseries_v7/audit/protected_manifest_before.json"),
    ("v7_audit_seed", "outputs/timeseries_v7/audit/protected_manifest_after.json"),
    ("v7_audit_seed", "outputs/timeseries_v7/audit/secret_scan.json"),
    ("v7_audit_seed", "outputs/timeseries_v7/audit/ARTIFACTS.sha256"),
    ("v7_audit_seed", "outputs/timeseries_v7/task_results/V7-P0-001/result.json"),
    ("v7_audit_seed", "outputs/timeseries_v7/task_results/V7-P0-001/targeted_tests.log"),
    ("v7_audit_seed", "outputs/timeseries_v7/task_results/V7-P0-001/v6_gate_regression.log"),
    ("v7_audit_seed", "outputs/timeseries_v7/task_results/V7-P0-001/broad_suite_collection.log"),
)

IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".tmp"}


class ProtectedScopeError(RuntimeError):
    """The immutable predecessor scope could not be established or verified."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def logical_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def scope_contract() -> dict[str, Any]:
    return {
        "roots": [{"category": category, "path": path} for category, path in ROOT_SPECS],
        "globs": [{"category": category, "pattern": pattern} for category, pattern in GLOB_SPECS],
        "files": [{"category": category, "path": path} for category, path in FILE_SPECS],
        "ignored_parts": sorted(IGNORED_PARTS),
        "ignored_suffixes": sorted(IGNORED_SUFFIXES),
        "symlink_policy": "fail_closed",
    }


def scope_contract_hash() -> str:
    return logical_hash(scope_contract())


def _eligible(path: Path) -> bool:
    return not any(part in IGNORED_PARTS or part == ".secrets" for part in path.parts) and path.suffix not in IGNORED_SUFFIXES


def _add_file(selected: dict[str, tuple[str, Path]], repo_root: Path, path: Path, category: str) -> None:
    if not path.exists() or not path.is_file() or not _eligible(path):
        return
    if path.is_symlink():
        raise ProtectedScopeError(f"symlink in protected scope: {path}")
    try:
        relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ProtectedScopeError(f"protected path escapes repository: {path}") from exc
    previous = selected.get(relative)
    if previous is None or category < previous[0]:
        selected[relative] = (category, path)


def _walk_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_dir() and path.is_symlink():
            raise ProtectedScopeError(f"symlink directory in protected scope: {path}")
        if path.is_file() and _eligible(path):
            yield path


def build_protected_snapshot(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    selected: dict[str, tuple[str, Path]] = {}
    missing_roots: list[str] = []
    missing_files: list[str] = []
    for category, relative in ROOT_SPECS:
        root = repo_root / relative
        if not root.exists():
            missing_roots.append(relative)
            continue
        if root.is_file():
            _add_file(selected, repo_root, root, category)
        else:
            for path in _walk_files(root):
                _add_file(selected, repo_root, path, category)
    for category, pattern in GLOB_SPECS:
        for path in repo_root.glob(pattern):
            if path.is_dir():
                for child in _walk_files(path):
                    _add_file(selected, repo_root, child, category)
            else:
                _add_file(selected, repo_root, path, category)
    for category, relative in FILE_SPECS:
        path = repo_root / relative
        if not path.is_file():
            missing_files.append(relative)
        else:
            _add_file(selected, repo_root, path, category)
    entries = [
        {
            "category": category,
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for relative, (category, path) in sorted(selected.items())
    ]
    category_counts: dict[str, int] = {}
    for entry in entries:
        category_counts[entry["category"]] = category_counts.get(entry["category"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_contract_hash": scope_contract_hash(),
        "file_count": len(entries),
        "category_counts": dict(sorted(category_counts.items())),
        "missing_declared_roots": sorted(missing_roots),
        "missing_declared_files": sorted(missing_files),
        "entries": entries,
        "protected_hash": logical_hash(entries),
    }


def compare_snapshots(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_rows = {
        row["path"]: (row["category"], int(row["bytes"]), row["sha256"])
        for row in expected["entries"]
    }
    actual_rows = {
        row["path"]: (row["category"], int(row["bytes"]), row["sha256"])
        for row in actual["entries"]
    }
    contract_match = expected.get("scope_contract_hash") == actual.get("scope_contract_hash")
    return {
        "pass": expected_rows == actual_rows and contract_match,
        "expected_hash": expected.get("protected_hash"),
        "actual_hash": actual.get("protected_hash"),
        "scope_contract_match": contract_match,
        "added": sorted(set(actual_rows) - set(expected_rows)),
        "removed": sorted(set(expected_rows) - set(actual_rows)),
        "changed": sorted(
            path for path in set(expected_rows) & set(actual_rows)
            if expected_rows[path] != actual_rows[path]
        ),
    }


def _atomic_write(path: Path, body: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise ProtectedScopeError(f"baseline already exists: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(body)
        temp = Path(handle.name)
    if exclusive and path.exists():
        temp.unlink(missing_ok=True)
        raise ProtectedScopeError(f"baseline created concurrently: {path}")
    os.replace(temp, path)


def write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    body = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _atomic_write(path, body, exclusive=exclusive)


def create_baseline(repo_root: Path, output: Path) -> dict[str, Any]:
    snapshot = build_protected_snapshot(repo_root)
    baseline = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "predecessor_through": "V6",
        "v6_model_id": "shadow.nasdaq_pit_hierarchical_distribution_v6",
        "v6_run_id": "tsv6-sealed-46d58750db2abe8b40cec159",
        "v6_status": "shadow_gate_hold",
        "scope_contract": scope_contract(),
        "scope_contract_hash": scope_contract_hash(),
        "snapshot": snapshot,
    }
    baseline["content_sha256"] = logical_hash(
        {key: value for key, value in baseline.items() if key != "content_sha256"}
    )
    write_json(output, baseline, exclusive=True)
    return baseline


def load_baseline(path: Path, *, expected_physical_sha256: str | None = None) -> dict[str, Any]:
    if expected_physical_sha256 and sha256_file(path) != expected_physical_sha256:
        raise ProtectedScopeError("baseline physical SHA-256 does not match task envelope")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("baseline_id") != BASELINE_ID:
        raise ProtectedScopeError("unexpected baseline id")
    expected_content = logical_hash(
        {key: item for key, item in value.items() if key != "content_sha256"}
    )
    if value.get("content_sha256") != expected_content:
        raise ProtectedScopeError("baseline logical content hash mismatch")
    if value.get("scope_contract_hash") != scope_contract_hash():
        raise ProtectedScopeError("runtime protection scope differs from baseline")
    return value


def verify_baseline(
    repo_root: Path,
    baseline_path: Path,
    *,
    expected_physical_sha256: str | None = None,
) -> dict[str, Any]:
    baseline = load_baseline(
        baseline_path, expected_physical_sha256=expected_physical_sha256
    )
    actual = build_protected_snapshot(repo_root)
    comparison = compare_snapshots(baseline["snapshot"], actual)
    return {
        **comparison,
        "baseline_id": baseline["baseline_id"],
        "baseline_physical_sha256": sha256_file(baseline_path),
        "file_count": actual["file_count"],
        "category_counts": actual["category_counts"],
    }
