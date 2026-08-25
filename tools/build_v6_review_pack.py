#!/usr/bin/env python3
"""Build a deterministic, secret-safe V6 offline review/replay package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FORBIDDEN_PARTS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    ".tmp", ".secrets", "node_modules",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".db", ".duckdb", ".tmp"}
EXACT_FILES = {
    "data/contracts/multivariate_timeseries_v6.yaml",
    "data/contracts/multivariate_timeseries_v6.schema.json",
    "tools/audit_v5_gate.py",
    "tools/build_v6_audit_workbook.mjs",
    "tools/build_v6_review_pack.py",
    "tools/collect_v6_public.py",
    "tools/export_v6_audit_input.py",
    "tools/run_v6_research.py",
    "tools/validate_v6_promotion.py",
    ".github/workflows/timeseries-v6-manual-promotion.yml",
    "outputs/NASDAQ_V5_GATE_REVIEW_PACK_20260824T050122Z.zip",
}
ALLOWED_PREFIXES = (
    "data/timeseries_v6/",
    "src/ai_fc/timeseries_v6/",
    "src/tests/timeseries_v6/",
    "docs/timeseries_v6/",
    "outputs/timeseries_v6/audit/",
    "outputs/timeseries_v6/research/",
    "outputs/timeseries_v6/task_results/",
    "migrations/timeseries_v6/",
    "locks/timeseries_v6/",
    "containers/timeseries_v6/",
)
TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".txt", ".log", ".lock", ".in"}


class PackError(RuntimeError):
    """Raised when deterministic packaging or secret policy fails."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PackError(f"path escapes repository: {path}") from exc
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise PackError(f"unsafe pack path: {relative}")
    return relative


def _allowed(relative: str) -> bool:
    return relative in EXACT_FILES or any(relative.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _forbidden(relative: str) -> bool:
    pure = PurePosixPath(relative)
    if any(part in FORBIDDEN_PARTS for part in pure.parts):
        return True
    return pure.suffix.lower() in FORBIDDEN_SUFFIXES


def discover_files(root: Path = ROOT) -> list[tuple[str, Path]]:
    candidates: list[Path] = []
    for exact in sorted(EXACT_FILES):
        path = root / exact
        if path.is_file():
            candidates.append(path)
    for prefix in ALLOWED_PREFIXES:
        base = root / prefix
        if base.is_dir():
            candidates.extend(path for path in base.rglob("*") if path.is_file())
    unique: dict[str, Path] = {}
    for path in candidates:
        relative = _safe_relative(path, root)
        if not _allowed(relative) or _forbidden(relative):
            continue
        if relative.startswith("outputs/timeseries_v6/review/"):
            continue
        if relative.startswith("outputs/timeseries_v6/task_results/") and path.suffix.lower() == ".log":
            continue
        if relative in unique:
            raise PackError(f"duplicate pack path: {relative}")
        if path.is_symlink():
            raise PackError(f"symlink is not allowed in review pack: {relative}")
        unique[relative] = path
    return sorted(unique.items())


def scan_pack_secrets(files: Iterable[tuple[str, Path]]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    private_key = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
    credential_url = re.compile(r"(?i)https?://[^\s/:]+:[^\s/@]+@")
    assignment = re.compile(
        r"(?i)(?:api_?key|token|secret|password)\s*[:=]\s*['\"]([^'\"]{16,})['\"]"
    )
    for relative, path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if private_key.search(text):
            findings.append({"path": relative, "reason": "private_key_block"})
        if credential_url.search(text):
            findings.append({"path": relative, "reason": "credential_url"})
        for match in assignment.finditer(text):
            value = match.group(1)
            if not value.lower().startswith(("fake-", "example-", "test-", "[redacted]")):
                findings.append({"path": relative, "reason": "credential_assignment"})
                break
    return findings


def build_pack(output: Path, *, root: Path = ROOT) -> dict[str, object]:
    files = discover_files(root)
    secret_findings = scan_pack_secrets(files)
    if secret_findings:
        raise PackError(f"secret scan failed: {secret_findings}")
    manifest = [
        {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for relative, path in files
    ]
    manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    manifest_sha = "".join(f"{row['sha256']}  {row['path']}\n" for row in manifest).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip.tmp", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for relative, path in files:
                info = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o100644 << 16
                info.create_system = 3
                archive.writestr(info, path.read_bytes())
            for name, data in (("MANIFEST.json", manifest_json), ("MANIFEST.sha256", manifest_sha)):
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o100644 << 16
                info.create_system = 3
                archive.writestr(info, data)
        os.replace(temp_path, output)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return {
        "schema_version": 1,
        "output": output.relative_to(root).as_posix() if output.is_relative_to(root) else str(output),
        "file_count": len(manifest),
        "zip_sha256": sha256_file(output),
        "zip_bytes": output.stat().st_size,
        "manifest_hash": sha256_bytes(manifest_json),
        "secret_scan_pass": True,
        "compression": "stored",
        "fixed_timestamp": "1980-01-01T00:00:00Z",
    }


def verify_pack(pack: Path) -> dict[str, object]:
    failures: list[str] = []
    with zipfile.ZipFile(pack) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            failures.append("duplicate paths")
        if any(_forbidden(name) for name in names):
            failures.append("cache or mutable database included")
        if any(info.date_time != FIXED_ZIP_TIME for info in archive.infolist()):
            failures.append("non-deterministic timestamp")
        manifest = json.loads(archive.read("MANIFEST.json"))
        rows = {row["path"]: row for row in manifest}
        payload_names = set(names) - {"MANIFEST.json", "MANIFEST.sha256"}
        if payload_names != set(rows):
            failures.append("manifest membership mismatch")
        for name in sorted(payload_names & set(rows)):
            data = archive.read(name)
            row = rows[name]
            if len(data) != row["bytes"] or sha256_bytes(data) != row["sha256"]:
                failures.append(f"byte mismatch: {name}")
    return {
        "pass": not failures,
        "failures": failures,
        "zip_sha256": sha256_file(pack),
        "zip_bytes": pack.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        result = build_pack(args.output.resolve(), root=ROOT)
        if args.verify:
            result["verification"] = verify_pack(args.output.resolve())
    except (PackError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
