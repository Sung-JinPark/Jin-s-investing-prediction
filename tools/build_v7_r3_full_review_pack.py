#!/usr/bin/env python3
"""Build and independently verify the combined V7-R3 P0-001/P0-002 review pack."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


FIXED_ZIP_TIME = (2026, 8, 26, 0, 0, 0)
TEXT_SUFFIXES = {
    ".csv", ".json", ".jsonl", ".log", ".md", ".patch", ".py",
    ".sql", ".toml", ".txt", ".xml", ".yaml", ".yml",
}
TASK_SOURCE_FILES = [
    "tools/audit_v7_alfred_pit.py",
    "tools/audit_v7_r3_predecessor_provenance.py",
    "tools/build_v7_r3_full_review_pack.py",
    "src/tests/timeseries_v7_r3/test_alfred_pit_audit.py",
    "src/tests/timeseries_v7_r3/test_protected_predecessor_provenance.py",
    "src/tests/timeseries_v7_r3/test_v7_r3_review_pack.py",
    "docs/timeseries_v7_r3/ALFRED_PIT_FAILURE_BASELINE.md",
    "docs/timeseries_v7_r3/PROTECTED_PREDECESSOR_PROVENANCE.md",
]
PREDECESSOR_FILES = [
    "data/timeseries_v7/manifests/protected_v6_baseline.json",
    "src/ai_fc/timeseries_v6/source_coverage.py",
    "src/tests/timeseries_v6/test_v6_research_dataset.py",
    "src/tests/timeseries_v6/test_v6_research_verify.py",
    "src/tests/timeseries_v7/test_v6_gate_audit.py",
]


class PackError(RuntimeError):
    """Raised when a review pack cannot be built or verified safely."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def safe_name(name: str) -> str:
    if not name or "\\" in name or "\x00" in name:
        raise PackError(f"unsafe ZIP path syntax: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise PackError(f"unsafe ZIP traversal: {name!r}")
    if path.parts and re.match(r"^[A-Za-z]:", path.parts[0]):
        raise PackError(f"unsafe ZIP drive path: {name!r}")
    normalized = "/".join(part for part in path.parts if part not in {"", "."})
    if not normalized:
        raise PackError("empty normalized ZIP path")
    return normalized


def inspect_archive(archive: zipfile.ZipFile, *, max_total: int = 2 * 1024**3) -> dict[str, Any]:
    seen: set[str] = set()
    total = 0
    for info in archive.infolist():
        normalized = safe_name(info.filename)
        collision = normalized.casefold()
        if collision in seen:
            raise PackError(f"duplicate normalized ZIP path: {normalized}")
        seen.add(collision)
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise PackError(f"ZIP symlink prohibited: {normalized}")
        if info.file_size > 512 * 1024**2:
            raise PackError(f"ZIP entry too large: {normalized}")
        total += info.file_size
        if total > max_total:
            raise PackError("ZIP uncompressed total exceeds safety limit")
    return {"entry_count": len(seen), "uncompressed_bytes": total, "path_safety_pass": True}


def add_file(contents: dict[str, bytes], source: Path, arcname: str) -> None:
    arcname = safe_name(arcname)
    if arcname.casefold() in {name.casefold() for name in contents}:
        raise PackError(f"duplicate pack destination: {arcname}")
    if not source.is_file():
        raise PackError(f"required input missing: {source}")
    contents[arcname] = source.read_bytes()


def add_tree(contents: dict[str, bytes], source: Path, prefix: str) -> None:
    if not source.is_dir():
        raise PackError(f"required directory missing: {source}")
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        add_file(contents, path, f"{prefix}/{path.relative_to(source).as_posix()}")


SECRET_PATTERNS = [
    ("credential_assignment", re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{16,})"
    )),
    ("credential_url", re.compile(r"(?i)https?://[^\s/:]+:[^\s/@]+@")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
]


def _scan_text(
    name: str,
    payload: bytes,
    findings: list[dict[str, Any]],
    synthetic_exclusions: list[dict[str, Any]],
) -> None:
    text = payload.decode("utf-8", errors="replace")
    lines = text.splitlines()
    for line_number, line in enumerate(lines, start=1):
        for pattern_name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                context = "\n".join(
                    lines[max(0, line_number - 6):min(len(lines), line_number + 3)]
                ).casefold()
                is_test_path = "/test" in f"/{name.casefold()}" or "src/tests/" in name.casefold()
                fixture_markers = (
                    "synthetic", "fake_", "fake-", "redaction_and_secret_scan", "monkeypatch"
                )
                if is_test_path and any(marker in context for marker in fixture_markers):
                    synthetic_exclusions.append({
                        "path": name,
                        "line": line_number,
                        "pattern": pattern_name,
                        "reason": "synthetic_test_fixture_context",
                    })
                    continue
                findings.append({
                    "path": name,
                    "line": line_number,
                    "pattern": pattern_name,
                    "match": "redacted",
                })


def scan_contents(contents: dict[str, bytes]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    synthetic_exclusions: list[dict[str, Any]] = []
    scanned_text = 0
    scanned_nested_archives = 0
    for name, payload in sorted(contents.items()):
        suffix = Path(name).suffix.lower()
        if suffix in TEXT_SUFFIXES:
            scanned_text += 1
            _scan_text(name, payload, findings, synthetic_exclusions)
        elif suffix == ".zip":
            scanned_nested_archives += 1
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    inspect_archive(archive)
                    for info in archive.infolist():
                        nested_name = safe_name(info.filename)
                        if Path(nested_name).suffix.lower() not in TEXT_SUFFIXES:
                            continue
                        scanned_text += 1
                        _scan_text(
                            f"{name}!/{nested_name}",
                            archive.read(info),
                            findings,
                            synthetic_exclusions,
                        )
            except zipfile.BadZipFile as exc:
                raise PackError(f"invalid nested review ZIP: {name}") from exc
    return {
        "schema_version": 1,
        "secret_scan_pass": not findings,
        "finding_count": len(findings),
        "findings": findings,
        "synthetic_fixture_exclusion_count": len(synthetic_exclusions),
        "synthetic_fixture_exclusions": synthetic_exclusions,
        "scanned_text_files": scanned_text,
        "scanned_nested_archives": scanned_nested_archives,
        "secrets_directory_accessed": False,
    }


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 & 0xFFFF) << 16
    return info


def write_pack(output: Path, contents: dict[str, bytes]) -> dict[str, Any]:
    for name in contents:
        safe_name(name)
    secret_scan = scan_contents(contents)
    if not secret_scan["secret_scan_pass"]:
        raise PackError("secret scan failed; review pack not written")
    contents = dict(contents)
    contents["REVIEW/SECRET_SCAN.json"] = canonical_json(secret_scan)
    file_rows = [
        {"path": name, "bytes": len(payload), "sha256": sha256_bytes(payload)}
        for name, payload in sorted(contents.items())
    ]
    manifest = {
        "schema_version": 1,
        "pack_id": "nasdaq_v7_r3_p0_001_p0_002_full_review_20260826",
        "fixed_build_date": "2026-08-26",
        "file_count_excluding_manifest": len(file_rows),
        "files": file_rows,
    }
    contents["MANIFEST.json"] = canonical_json(manifest)
    sha_manifest = "".join(
        f"{sha256_bytes(payload)}  {name}\n" for name, payload in sorted(contents.items())
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
        for name, payload in sorted(contents.items()):
            archive.writestr(zip_info(name), payload)
        archive.writestr(zip_info("MANIFEST.sha256"), sha_manifest)
    os.replace(temporary, output)
    return verify_pack(output)


def parse_sha_manifest(payload: bytes) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line_number, line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise PackError(f"invalid SHA manifest line {line_number}")
        digest, name = match.groups()
        normalized = safe_name(name)
        if normalized.casefold() in {item.casefold() for item in rows}:
            raise PackError(f"duplicate SHA manifest path: {normalized}")
        rows[normalized] = digest
    return rows


def verify_pack(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        safety = inspect_archive(archive)
        names = {safe_name(info.filename): info for info in archive.infolist()}
        if "MANIFEST.json" not in names or "MANIFEST.sha256" not in names:
            raise PackError("review pack manifest is missing")
        hashes = parse_sha_manifest(archive.read(names["MANIFEST.sha256"]))
        expected_names = set(names) - {"MANIFEST.sha256"}
        if set(hashes) != expected_names:
            raise PackError("SHA manifest path set mismatch")
        failures = []
        for name, expected in hashes.items():
            actual = sha256_bytes(archive.read(names[name]))
            if actual != expected:
                failures.append(name)
        if failures:
            raise PackError(f"payload hash mismatch: {failures}")
        manifest = json.loads(archive.read(names["MANIFEST.json"]))
        listed = {row["path"]: row for row in manifest["files"]}
        payload_names = expected_names - {"MANIFEST.json"}
        if set(listed) != payload_names:
            raise PackError("MANIFEST.json path set mismatch")
        for name, row in listed.items():
            payload = archive.read(names[name])
            if row["bytes"] != len(payload) or row["sha256"] != sha256_bytes(payload):
                raise PackError(f"MANIFEST.json metadata mismatch: {name}")
        secret_scan = json.loads(archive.read(names["REVIEW/SECRET_SCAN.json"]))
        if not secret_scan["secret_scan_pass"]:
            raise PackError("embedded secret scan is not PASS")
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "manifest_pass": True,
        "secret_scan_pass": True,
        **safety,
    }


def git_snapshot(repo: Path, relevant_paths: Iterable[str]) -> dict[str, Any]:
    def run(*args: str) -> str:
        process = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return process.stdout.decode("utf-8", errors="replace").strip()

    return {
        "repo": str(repo.resolve()),
        "branch": run("branch", "--show-current"),
        "head": run("rev-parse", "HEAD"),
        "relevant_status": {
            path: run("status", "--porcelain=v1", "--", path) for path in relevant_paths
        },
    }


def implementation_patch(repo: Path, paths: Iterable[str]) -> bytes:
    chunks = []
    for relative in paths:
        path = repo / relative
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.extend(difflib.unified_diff(
            [],
            text.splitlines(keepends=True),
            fromfile="/dev/null",
            tofile=f"b/{relative}",
        ))
    return "".join(chunks).encode("utf-8")


def review_readme(p0_001: dict[str, Any], p0_002: dict[str, Any]) -> bytes:
    text = f"""# NASDAQ V7-R3 P0-001 + P0-002 Full Review Pack

## Review verdict

- P0-001 audit task: **{p0_001['status']}**
- V7 research model state: **{p0_001['state']}**
- V7 research Gate: **{'PASS' if p0_001['research_gate_pass'] else 'HOLD'}**
- P0-002 provenance task: **{p0_002['status']}**
- Protected repositories unchanged: **{p0_002['protected_manifest']['pass']}**
- Approved decision: **{p0_002['decision']['decision']}**
- P0-003 started: **false**

Task success is not model-Gate success. P0-001 independently reproduced the failed
ALFRED/PIT run and kept `HOLD_RESEARCH_GATE`. P0-002 proved that the four protected
differences are attributable commits made after the frozen baseline and recorded an
append-only correction decision without modifying that baseline.

## Where to start

1. `REVIEW/REVIEW_INDEX.json`
2. `REVIEW/TEST_AND_GATE_SUMMARY.json`
3. `EVIDENCE/outputs/timeseries_v7_r3/task_results/V7R3-P0-001/result.json`
4. `EVIDENCE/outputs/timeseries_v7_r3/task_results/V7R3-P0-002/result.json`
5. `SOURCE/task_repo/docs/timeseries_v7_r3/`

## Evidence boundaries

- The original V7-R3 design and failed-run review ZIPs are preserved under `INPUTS/`.
- Full P0-001/P0-002 logs, manifests, source, tests and human-readable findings are included.
- Provider secrets and `.secrets` were not accessed or packaged.
- P0-003 baseline correction, model training, commit, push and deployment are outside this pack.
"""
    return text.encode("utf-8")


def build_contents(args: argparse.Namespace) -> dict[str, bytes]:
    repo = Path(args.repo).resolve()
    predecessor = Path(args.predecessor_repo).resolve()
    contents: dict[str, bytes] = {}
    for relative in TASK_SOURCE_FILES:
        add_file(contents, repo / relative, f"SOURCE/task_repo/{relative}")
    add_tree(
        contents,
        repo / "outputs/timeseries_v7_r3",
        "EVIDENCE/outputs/timeseries_v7_r3",
    )
    for relative in PREDECESSOR_FILES:
        add_file(contents, predecessor / relative, f"SOURCE/predecessor_current/{relative}")

    nested_inputs = [
        (Path(args.design_pack), "INPUTS/NASDAQ_V7_FRED_ALFRED_OPEN_DATA_RALPH_R3_PACK_20260825.zip"),
        (Path(args.training_pack), "INPUTS/NASDAQ_V7_ALFRED_PIT_TRAINING_REVIEW_PACK_20260825.zip"),
        (Path(args.v6_pack), "INPUTS/NASDAQ_V6_AUTONOMOUS_RESEARCH_REVIEW_PACK_20260824.zip"),
        (Path(args.v7_wait_pack), "INPUTS/NASDAQ_V7_WAIT_DATA_REVIEW_PACK_20260825.zip"),
    ]
    for source, arcname in nested_inputs:
        add_file(contents, source.resolve(), arcname)

    p0_001 = json.loads(
        (repo / "outputs/timeseries_v7_r3/task_results/V7R3-P0-001/result.json").read_text(encoding="utf-8")
    )
    p0_002 = json.loads(
        (repo / "outputs/timeseries_v7_r3/task_results/V7R3-P0-002/result.json").read_text(encoding="utf-8")
    )
    input_rows = [
        {"path": arcname, "bytes": source.stat().st_size, "sha256": sha256_file(source)}
        for source, arcname in nested_inputs
    ]
    review_index = {
        "schema_version": 1,
        "pack_scope": ["V7R3-P0-001", "V7R3-P0-002", "V7-R3 source prompts and evidence"],
        "inputs": input_rows,
        "tasks": {
            "V7R3-P0-001": {
                "status": p0_001["status"],
                "state": p0_001["state"],
                "research_gate_pass": p0_001["research_gate_pass"],
                "protected_non_mutation": p0_001["protected_manifest"]["pass"],
                "secret_scan_pass": p0_001["secret_scan"]["secret_scan_pass"],
            },
            "V7R3-P0-002": {
                "status": p0_002["status"],
                "decision": p0_002["decision"]["decision"],
                "protected_non_mutation": p0_002["protected_manifest"]["pass"],
                "secret_scan_pass": p0_002["secret_scan"]["secret_scan_pass"],
            },
        },
        "next_task_started": False,
    }
    test_summary = {
        "schema_version": 1,
        "p0_001": {
            "assertions": p0_001["assertions"],
            "test_receipts": p0_001.get("test_receipts", []),
            "auxiliary_checks": p0_001.get("auxiliary_checks", []),
            "unresolved_blockers": p0_001.get("unresolved_blockers", []),
        },
        "p0_002": {
            "assertions": p0_002["assertions"],
            "test_receipts": p0_002.get("test_receipts", []),
            "decision": p0_002["decision"],
        },
        "known_non_code_failure": {
            "test": "dualdb/tests/test_sentinels.py::test_ixic_coverage",
            "classification": "missing_data_freshness",
            "last_ixic_date": "2026-08-12",
            "evaluation_date": "2026-08-26",
        },
    }
    plan = """# Implemented V7R3-P0-002 Plan\n\n"""
    plan += "- Audit repository: `C:/workspace/ai-investing`\n"
    plan += "- Read-only predecessor: `C:/workspace/ai-investing/worktrees/active/timeseries-v5-gate`\n"
    plan += "- Reproduced Git, ZIP and protected-baseline provenance for four files.\n"
    plan += "- Recorded `formal_append_only_correction`; exact restoration is false.\n"
    plan += "- Protected baseline was not changed and P0-003 was not started.\n"

    contents["README.md"] = review_readme(p0_001, p0_002)
    contents["REVIEW/REVIEW_INDEX.json"] = canonical_json(review_index)
    contents["REVIEW/TEST_AND_GATE_SUMMARY.json"] = canonical_json(test_summary)
    contents["REVIEW/IMPLEMENTED_PLAN_V7R3_P0_002.md"] = plan.encode("utf-8")
    contents["REVIEW/GIT_STATE.json"] = canonical_json({
        "task_repo": git_snapshot(repo, TASK_SOURCE_FILES),
        "predecessor_repo": git_snapshot(predecessor, PREDECESSOR_FILES),
    })
    contents["REVIEW/IMPLEMENTATION.patch"] = implementation_patch(repo, TASK_SOURCE_FILES)
    return contents


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--repo", required=True)
    build.add_argument("--predecessor-repo", required=True)
    build.add_argument("--design-pack", required=True)
    build.add_argument("--training-pack", required=True)
    build.add_argument("--v6-pack", required=True)
    build.add_argument("--v7-wait-pack", required=True)
    build.add_argument("--output", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--pack", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "build":
            contents = build_contents(args)
            result = write_pack(Path(args.output).resolve(), contents)
        else:
            result = verify_pack(Path(args.pack).resolve())
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (PackError, OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"PACK_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
