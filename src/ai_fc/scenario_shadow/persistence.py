"""Deterministic hashing, atomic writes, and freshness gates for candidates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import ScenarioShadowContractError, validate_candidate_payload


LEGACY_DIAGNOSTIC_RELATIVE_PATH = (
    Path("data")
    / "scenarios"
    / "shadow"
    / "legacy_gbm_actual_member_v1_latest.json"
)
OFFICIAL_RELATIVE_PATH = Path("data") / "scenarios" / "nasdaq_latest.json"


@dataclass(frozen=True)
class CandidateLoadResult:
    status: str
    display_allowed: bool
    payload: dict[str, Any] | None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "display_allowed": self.display_allowed,
            "reason": self.reason,
            "payload": self.payload,
        }


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_payload_projection(payload: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(payload)
    projected.pop("receipt", None)
    reproducibility = projected.get("reproducibility")
    if isinstance(reproducibility, dict):
        reproducibility.pop("canonical_payload_sha256", None)
        # Runtime repository state is receipt metadata, not canonical model content.
        reproducibility.pop("code_revision", None)
        reproducibility.pop("code_revision_dirty", None)
    return projected


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(canonical_payload_projection(payload)))


def _serialized(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _append_immutable(path: Path, data: bytes) -> None:
    """Create an append-only file or verify the exact existing bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise ScenarioShadowContractError(
                f"immutable archive conflict: {path.name}"
            )


def write_candidate(
    root: Path,
    payload: dict[str, Any],
    *,
    relative_path: Path = LEGACY_DIAGNOSTIC_RELATIVE_PATH,
) -> tuple[Path, dict[str, Any], bool]:
    prepared = deepcopy(payload)
    reproducibility = prepared.setdefault("reproducibility", {})
    reproducibility["canonical_payload_sha256"] = canonical_payload_sha256(prepared)
    prepared.setdefault("receipt", {})["generated_at"] = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")
    validate_candidate_payload(prepared)
    expected_hash = canonical_payload_sha256(prepared)
    if reproducibility["canonical_payload_sha256"] != expected_hash:
        raise ScenarioShadowContractError("canonical payload hash is inconsistent")

    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            validate_candidate_payload(existing)
            existing_hash = canonical_payload_sha256(existing)
            stored_hash = (existing.get("reproducibility") or {}).get(
                "canonical_payload_sha256"
            )
        except (OSError, json.JSONDecodeError, ScenarioShadowContractError):
            existing = None
            existing_hash = None
            stored_hash = None
        if existing is not None and existing_hash == stored_hash == expected_hash:
            return path, existing, False

        old_bytes = path.read_bytes()
        old_sha = sha256_bytes(old_bytes)
        archive = path.parent / "archive" / f"{path.stem}_{old_sha[:8]}.json"
        _append_immutable(archive, old_bytes)
        archive_receipt = archive.with_suffix(".receipt.json")
        receipt_payload = {
            "schema_version": 1,
            "record_type": "scenario_shadow_candidate_supersession",
            "append_only": True,
            "original_relative_path": relative_path.as_posix(),
            "archived_relative_path": archive.relative_to(root).as_posix(),
            "archived_file_sha256": old_sha,
            "superseded_by_canonical_payload_sha256": expected_hash,
            "reason": "canonical_candidate_content_changed",
        }
        _append_immutable(
            archive_receipt,
            _serialized(receipt_payload).encode("utf-8"),
        )

    serialized = _serialized(prepared)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
    return path, prepared, True


def load_candidate(
    root: Path,
    *,
    relative_path: Path = LEGACY_DIAGNOSTIC_RELATIVE_PATH,
) -> CandidateLoadResult:
    path = root / relative_path
    if not path.exists():
        return CandidateLoadResult("missing", False, None, "candidate file is absent")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CandidateLoadResult("invalid", False, None, f"invalid JSON: {exc}")
    try:
        validate_candidate_payload(payload)
        stored_hash = (payload.get("reproducibility") or {}).get(
            "canonical_payload_sha256"
        )
        actual_hash = canonical_payload_sha256(payload)
        if stored_hash != actual_hash:
            raise ScenarioShadowContractError("canonical payload hash mismatch")
    except (ScenarioShadowContractError, KeyError, TypeError, ValueError) as exc:
        summary = {
            "candidate_id": payload.get("candidate_id"),
            "status": payload.get("status"),
        }
        return CandidateLoadResult("invalid", False, summary, str(exc))

    official_path = root / OFFICIAL_RELATIVE_PATH
    try:
        official_bytes = official_path.read_bytes()
        official = json.loads(official_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return CandidateLoadResult(
            "invalid_source", False, None, f"official snapshot unavailable: {exc}"
        )
    source = payload["source"]
    comparisons = {
        "snapshot_id": official.get("snapshot_id"),
        "snapshot_sha256": sha256_bytes(official_bytes),
        "asof": official.get("asof"),
    }
    for field, current in comparisons.items():
        if source.get(field) != current:
            summary = {
                "candidate_id": payload.get("candidate_id"),
                "source": source,
                "current_source": comparisons,
            }
            return CandidateLoadResult(
                "stale_source",
                False,
                summary,
                f"source {field} mismatch",
            )
    return CandidateLoadResult("shadow_only", True, payload)
