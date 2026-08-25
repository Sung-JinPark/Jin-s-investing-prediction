"""Protected predecessor manifests and V6 write-boundary enforcement.

The repository can already be dirty when a V6 task starts.  Consequently V6
does not attempt to clean or restore the worktree.  It snapshots every
protected predecessor byte before work, validates those bytes again after the
task, and separately checks the task's declared changed paths against a closed
allowlist.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


PROTECTED_ROOTS: tuple[str, ...] = (
    "data/timeseries",
    "data/timeseries_v1",
    "data/timeseries_v2",
    "data/timeseries_v3",
    "data/timeseries_v4",
    "data/timeseries_v5",
    "data/scenarios",
    "data/forecasts",
    "data/ledgers",
    "outputs/timeseries_v1",
    "outputs/timeseries_v2",
    "outputs/timeseries_v3",
    "outputs/timeseries_v4",
    "outputs/timeseries_v5",
)

# Exact files and directory prefixes that a V6 task is allowed to create or
# modify.  Root project metadata is intentionally not included: adding a
# dependency or changing a workflow requires its own reviewed capability.
V6_ALLOWED_PATHS: tuple[str, ...] = (
    "data/timeseries_v6/",
    "data/contracts/multivariate_timeseries_v6.yaml",
    "data/contracts/multivariate_timeseries_v6.schema.json",
    "src/ai_fc/timeseries_v6/",
    "src/tests/timeseries_v6/",
    "tools/audit_v5_gate.py",
    "tools/atlas_v2.py",
    "tools/build_v6_audit_workbook.mjs",
    "tools/build_v6_review_pack.py",
    "tools/collect_v6_public.py",
    "tools/export_v6_audit_input.py",
    "tools/run_v6_research.py",
    "tools/validate_v6_promotion.py",
    "docs/timeseries_v6/",
    "outputs/timeseries_v6/",
    "migrations/timeseries_v6/",
    "locks/timeseries_v6/",
    "containers/timeseries_v6/",
    ".github/workflows/timeseries-v6-manual-promotion.yml",
)


class IsolationError(RuntimeError):
    """Raised when a protected byte or V6 write boundary is violated."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_relative(path: str) -> str:
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise IsolationError(f"unsafe repository path: {path!r}")
    if ":" in pure.parts[0]:
        raise IsolationError(f"drive-qualified repository path: {path!r}")
    return pure.as_posix()


def create_protected_manifest(
    repository_root: Path,
    roots: Sequence[str] = PROTECTED_ROOTS,
) -> dict[str, Any]:
    """Hash every protected predecessor file deterministically."""

    root = repository_root.resolve()
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for relative_root in roots:
        relative_root = _safe_relative(relative_root)
        base = root / relative_root
        if not base.exists():
            continue
        candidates: Iterable[Path] = (base,) if base.is_file() else base.rglob("*")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            files.append(
                {
                    "path": relative,
                    "bytes": candidate.stat().st_size,
                    "sha256": _sha256(candidate),
                }
            )
    files.sort(key=lambda row: row["path"])
    return {
        "schema_version": 1,
        "manifest_role": "immutable_v1_v5_scenario_official_baseline",
        "roots": list(roots),
        "files": files,
        "file_count": len(files),
        "content_hash": _canonical_hash(files),
    }


def compare_manifests(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Return an auditable byte-level protected-manifest comparison."""

    left = {row["path"]: row for row in before.get("files", [])}
    right = {row["path"]: row for row in after.get("files", [])}
    added = sorted(set(right) - set(left))
    removed = sorted(set(left) - set(right))
    changed = sorted(
        path for path in set(left) & set(right) if left[path] != right[path]
    )
    return {
        "pass": not (added or removed or changed),
        "before_hash": before.get("content_hash"),
        "after_hash": after.get("content_hash"),
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def is_v6_write_allowed(path: str, allowed: Sequence[str] = V6_ALLOWED_PATHS) -> bool:
    relative = _safe_relative(path)
    for candidate in allowed:
        if candidate.endswith("/"):
            if relative.startswith(candidate):
                return True
        elif relative == candidate:
            return True
    return False


def validate_v6_write_paths(
    paths: Iterable[str],
    allowed: Sequence[str] = V6_ALLOWED_PATHS,
) -> list[str]:
    """Validate task-scoped changed paths and return canonical paths.

    This function deliberately receives the paths changed by the current task,
    not the entire pre-existing dirty worktree.
    """

    normalized = sorted({_safe_relative(path) for path in paths})
    forbidden = [path for path in normalized if not is_v6_write_allowed(path, allowed)]
    if forbidden:
        raise IsolationError(f"V6 write allowlist violation: {forbidden}")
    protected = [
        path
        for path in normalized
        if any(path == root or path.startswith(f"{root}/") for root in PROTECTED_ROOTS)
    ]
    if protected:
        raise IsolationError(f"protected predecessor write attempted: {protected}")
    return normalized
