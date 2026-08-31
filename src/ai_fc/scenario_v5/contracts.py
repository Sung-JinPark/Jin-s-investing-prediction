"""Contract loading, canonical serialization, and protected-file audit helpers."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import yaml


CONTRACT_FILES = (
    "data/contracts/scenario_v5_evidence_view.yaml",
    "data/contracts/scenario_v5_model.yaml",
    "data/contracts/scenario_v5_event_impact.yaml",
)

# V5 and V5.1 are historical shadow candidates whose pre-jobs information set
# is part of their audit identity.  The mutable latest snapshot moved forward
# after those candidates were defined, so replay must use the immutable vintage
# whose bytes match the source hash recorded by the original build.
V5_SOURCE_SNAPSHOT = "data/scenarios/archive/2026-08-06.json"

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

# These protected roots are tracked as text with LF in .gitattributes.  Hash
# their working-tree content in the same canonical form Git places in a fresh
# Linux checkout, while byte-protected forecasts/calibration/ML ledgers remain
# exact.  This prevents core.autocrlf from creating false immutability alarms.
LF_CANONICAL_PROTECTED_PATHS = (
    "data/scenarios",
    "questions/registry.yaml",
    "data/signals",
    "data/liquidity",
    "data/cross_asset",
    "data/ai_capital_cycle",
)

# OpenTimestamps rewrites its proof envelope after the forecast hash has been
# committed.  The proof remains protected and independently audited, but its
# refresh is not a model input change and must not invalidate a V5.2 display
# candidate built from the same forecast ledger bytes.
#
# ``forecasts/.hashes`` is the anchor manifest that proof envelops, and it is
# derived: appending a forecast round necessarily rewrites it, because
# verify_track_record.py fails any forecast file missing from the anchor.  The
# automated refresh regenerates the manifest and the candidate in one commit,
# so only a forecast recorded outside that loop -- the /forecast skill path,
# which CLAUDE.md supports as a first-class route -- would otherwise invalidate
# a candidate for doing exactly what it is supposed to do.  Whitelisting the
# manifest costs no tamper coverage: every forecast file is hashed individually
# in the same manifest, so mutating or deleting one still lands in ``changed``
# or ``removed`` and remains fail-closed.
RUNTIME_AUXILIARY_REFRESH_PATHS = frozenset({
    "forecasts/.hashes",
    "forecasts/.hashes.ots",
})

# ``protected_before`` snapshots the whole audit surface (164 files), but the
# candidate's actual inputs are the files listed in ``source_hashes`` -- every
# one of them under ``data/``.  The calibration ledgers and the question
# registry are audited alongside, never consumed: the candidate payload
# contains no question_id and no brier, and the V5.2 engine never opens either
# file.  Appending a resolution row or flipping a question's status therefore
# cannot move a number in the candidate, yet it closed the runtime gate and
# silently degraded the dashboard's future surface until the next automated
# rebuild.  Their own integrity is enforced by ``sync --check`` and
# ``audit-ledgers --check`` as separate CI steps, so disclosing these rather
# than failing on them costs no tamper coverage.  Deletion stays fail-closed.
NON_INPUT_PROTECTED_PREFIXES = ("calibration/", "questions/")


def _is_runtime_auxiliary(path: str) -> bool:
    """True when a change to ``path`` cannot alter a candidate's numbers."""
    return (
        path in RUNTIME_AUXILIARY_REFRESH_PATHS
        or path.startswith(NON_INPUT_PROTECTED_PREFIXES)
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


def _canonical_numeric_value(value: Any, *, decimal_places: int) -> Any:
    """Normalize insignificant floating-point noise before semantic hashing.

    This helper is intentionally opt-in: byte-exact ledgers and historical
    model hashes continue to use :func:`canonical_hash`.  Research artifacts
    that are deterministically replayed across NumPy/BLAS platforms may use
    ``canonical_numerical_hash`` so machine-epsilon differences do not create
    a false model change.  Lists and tuples share one JSON representation;
    material numerical changes remain visible at the declared precision.
    """
    if isinstance(value, dict):
        return {
            key: _canonical_numeric_value(item, decimal_places=decimal_places)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _canonical_numeric_value(item, decimal_places=decimal_places)
            for item in value
        ]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float cannot be semantically hashed")
        normalized = round(value, decimal_places)
        return 0.0 if normalized == 0 else normalized
    return value


def canonical_numerical_hash(value: Any, *, decimal_places: int = 12) -> str:
    """Return a platform-stable hash for numerical research output."""
    normalized = _canonical_numeric_value(value, decimal_places=decimal_places)
    return canonical_hash(normalized)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_file_hash(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    canonical_lf = any(
        relative == prefix or relative.startswith(f"{prefix}/")
        for prefix in LF_CANONICAL_PROTECTED_PATHS
    )
    if not canonical_lf:
        return file_hash(path)
    digest = hashlib.sha256()
    digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
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
            files[key] = _protected_file_hash(root, path)
    return {
        "algorithm": "sha256",
        "canonicalization": {
            "lf_text_roots": list(LF_CANONICAL_PROTECTED_PATHS),
            "byte_exact_roots": [
                relative for relative in PROTECTED_PATHS
                if not any(
                    relative == prefix or relative.startswith(f"{prefix}/")
                    for prefix in LF_CANONICAL_PROTECTED_PATHS
                )
            ],
        },
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


def compare_protected_append_only(
    before: dict[str, Any], after: dict[str, Any],
) -> dict[str, Any]:
    """Verify an historical protected manifest without rejecting later appends.

    Every file that existed in ``before`` must still exist with the same hash.
    Files first observed in ``after`` are disclosed but allowed.  This is the
    runtime rule for a research candidate: unrelated append-only ledger growth
    must not invalidate a candidate, while deletion or mutation of any byte the
    candidate was built alongside remains fail-closed.
    """
    old = before.get("files", {})
    new = after.get("files", {})
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    all_changed = sorted(path for path in set(old) & set(new) if old[path] != new[path])
    refreshed_auxiliary = [path for path in all_changed if _is_runtime_auxiliary(path)]
    changed = [path for path in all_changed if not _is_runtime_auxiliary(path)]
    return {
        "ok": not (removed or changed),
        "append_only_consistent": not (removed or changed),
        "new_files_allowed": True,
        "refreshed_auxiliary_proofs_allowed": True,
        "added": added,
        "removed": removed,
        "changed": changed,
        "refreshed_auxiliary": refreshed_auxiliary,
        "before_manifest_sha256": before.get("manifest_sha256"),
        "after_manifest_sha256": after.get("manifest_sha256"),
    }
