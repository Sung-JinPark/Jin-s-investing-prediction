"""Input, artifact, and result integrity helpers for R4."""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

SECRET_NAMES = {
    "FRED_API_KEY", "BLS_API_KEY", "BEA_API_KEY", "EIA_API_KEY",
    "CME_API_KEY", "CBOE_API_KEY", "NASDAQ_DATA_LINK_API_KEY",
    "GH_TOKEN", "GITHUB_TOKEN", "DATABASE_URL", "RALPH_V7_R4_DATABASE_URL",
    "R4_ALLOW_CODEX_CHILD",
}
TOKEN_PATTERNS = (
    re.compile(rb"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{24,}"),
    re.compile(rb"(?i)[?&](api_key|token|key)=[^&\s]{12,}"),
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_zip_inventory(path: Path, *, max_files: int = 20_000,
                       max_uncompressed: int = 2_000_000_000) -> list[dict[str, Any]]:
    seen: set[str] = set()
    folded: set[str] = set()
    inventory: list[dict[str, Any]] = []
    total = 0
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > max_files:
            raise ValueError("zip file-count limit exceeded")
        for info in archive.infolist():
            raw = info.filename
            if "\\" in raw:
                raise ValueError(f"zip backslash path rejected: {raw}")
            candidate = PurePosixPath(raw)
            drive_like = bool(candidate.parts and re.fullmatch(r"[A-Za-z]:", candidate.parts[0]))
            if candidate.is_absolute() or drive_like or ".." in candidate.parts or not candidate.parts:
                raise ValueError(f"unsafe zip path: {raw}")
            normalized = candidate.as_posix().rstrip("/")
            key = normalized.casefold()
            if normalized in seen or key in folded:
                raise ValueError(f"duplicate zip path: {raw}")
            seen.add(normalized)
            folded.add(key)
            total += info.file_size
            if total > max_uncompressed:
                raise ValueError("zip decompression limit exceeded")
            inventory.append({"path": normalized, "bytes": info.file_size, "crc": info.CRC})
    return inventory


def scan_secret_bytes(value: bytes) -> list[str]:
    findings: list[str] = []
    for pattern in TOKEN_PATTERNS:
        if pattern.search(value):
            findings.append(pattern.pattern.decode("ascii", errors="replace"))
    return findings


def sanitized_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key.upper() not in SECRET_NAMES
            and not any(word in key.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "API_KEY"))}


def validate_child_result(result: dict[str, Any], *, require_evidence: bool = False) -> list[str]:
    errors: list[str] = []
    required = {
        "run_id", "cycle_id", "task_key", "attempt_id", "status",
        "protected_non_mutation", "secret_scan_pass",
        "child_worker_started_another_task", "supervisor_should_continue",
    }
    errors.extend(f"missing:{name}" for name in sorted(required - result.keys()))
    allowed_statuses = {
        "SUCCEEDED", "RETRY_WAIT", "REPLAN", "FAILED", "BLOCKED",
        "WAIT_DATA", "WAIT_EXECUTION_PERMISSION", "WAIT_HUMAN_REVIEW",
        "REVIEW_PROPOSAL", "RESEARCH_GATE_FAILED_REPLAN",
        "BLOCKED_INPUT_INTEGRITY", "BLOCKED_SECURITY", "BLOCKED_SECRET_LEAK",
        "BLOCKED_PROTECTED_SCOPE", "BLOCKED_GOVERNANCE",
    }
    if result.get("status") not in allowed_statuses:
        errors.append("invalid_status")
    if result.get("child_worker_started_another_task") is not False:
        errors.append("child_started_another_task")
    if result.get("protected_non_mutation") is not True:
        errors.append("protected_mutation")
    if result.get("secret_scan_pass") is not True:
        errors.append("secret_scan_failed")
    if require_evidence and result.get("status") in {"SUCCEEDED", "REVIEW_PROPOSAL"}:
        commands = result.get("commands")
        tests = result.get("tests")
        acceptance = result.get("acceptance_results")
        if not isinstance(commands, list) or not commands:
            errors.append("missing_command_evidence")
        else:
            failed_commands = []
            for index, item in enumerate(commands):
                if not isinstance(item, dict) or item.get("return_code") == 0:
                    continue
                explicit_red = item.get("phase") == "red_test" and item.get("expected_failure")
                explicit_diagnostic = (
                    item.get("phase") == "expected_diagnostic"
                    and bool(item.get("expected_failure"))
                    and any(isinstance(later, dict) and later.get("return_code") == 0
                            for later in commands[index + 1:])
                )
                command = item.get("command")
                repaired_red = bool(command) and any(
                    isinstance(later, dict)
                    and later.get("command") == command
                    and later.get("return_code") == 0
                    for later in commands[index + 1:]
                )
                if not explicit_red and not explicit_diagnostic and not repaired_red:
                    failed_commands.append(command or f"command[{index}]")
            if failed_commands:
                errors.append("command_failed")
        if not isinstance(tests, list) or not tests:
            errors.append("missing_test_evidence")
        elif any(item.get("passed") is not True for item in tests
                 if isinstance(item, dict)):
            errors.append("test_failed")
        if not isinstance(acceptance, list) or not acceptance:
            errors.append("missing_acceptance_evidence")
        elif any(item.get("passed") is not True for item in acceptance
                 if isinstance(item, dict)):
            errors.append("acceptance_failed")
    return errors


def protected_manifest(repo: Path) -> dict[str, Any]:
    """Hash immutable predecessor and customer-surface files.

    The R4 namespace is intentionally absent.  Every included file is read-only
    for this supervisor run.
    """
    roots = [
        *(repo / "data" / f"timeseries_v{version}" for version in range(1, 8)),
        repo / "data/scenarios", repo / "data/forecasts", repo / "data/ledgers",
        *(repo / "outputs" / f"timeseries_v{version}" for version in range(1, 8)),
        repo / "_site/data.json", repo / "website/data.json",
    ]
    entries: list[dict[str, Any]] = []
    for root in roots:
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = sorted(path for path in root.rglob("*") if path.is_file())
        else:
            continue
        for path in candidates:
            entries.append({
                "path": path.relative_to(repo).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    digest = sha256_bytes(canonical_json(entries))
    return {"schema_version": 1, "entries": entries, "entry_count": len(entries),
            "manifest_sha256": digest}
