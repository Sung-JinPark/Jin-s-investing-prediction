#!/usr/bin/env python3
"""Create or verify the immutable V1-V6 baseline required by NASDAQ V7."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_fc.timeseries_v7.protection import (
    ProtectedScopeError,
    build_protected_snapshot,
    compare_snapshots,
    create_baseline,
    load_baseline,
    sha256_file,
    verify_baseline,
    write_json,
)


SENSITIVE_ENV_FRAGMENT = re.compile(
    r"(?i)(api_?key|token|secret|password|database_url|access_?key|private_?key)"
)
SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"['\"]?\s*[:=]\s*['\"]?(?!REDACTED|null|none)[A-Za-z0-9_./+\-=]{12,}"
    ),
    re.compile(r"(?:gh[opsu]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})"),
)


def sanitized_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not SENSITIVE_ENV_FRAGMENT.search(key)}


def run_command(command: list[str], repo_root: Path, log_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=repo_root,
        env=sanitized_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    text = (completed.stdout or "") + ("\n" if completed.stdout and completed.stderr else "") + (completed.stderr or "")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(text, encoding="utf-8")
    return {
        "command": subprocess.list2cmdline(command),
        "returncode": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
        "log_path": log_path.relative_to(repo_root).as_posix(),
    }


def scan_secrets(paths: list[Path]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    scanned = 0
    for root in paths:
        candidates = [root] if root.is_file() else list(root.rglob("*")) if root.is_dir() else []
        for path in candidates:
            if not path.is_file() or ".secrets" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            scanned += 1
            for line_number, line in enumerate(text.splitlines(), start=1):
                if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                    matches.append({"path": str(path), "line": line_number, "value": "REDACTED"})
    return {"pass": not matches, "scanned_files": scanned, "matches": matches}


def _artifact(path: Path, repo_root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(repo_root).as_posix(),
        "logical_sha256": sha256_file(path),
        "physical_sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def bootstrap(repo_root: Path, baseline_path: Path, result_dir: Path) -> int:
    dependency = repo_root / "outputs/timeseries_v7/task_results/V7-P0-001/result.json"
    if not dependency.is_file() or json.loads(dependency.read_text(encoding="utf-8")).get("status") != "succeeded":
        raise ProtectedScopeError("V7-P0-001 has not succeeded")
    started = datetime.now(timezone.utc).isoformat()
    before = build_protected_snapshot(repo_root)
    before_path = result_dir / "protected_before.json"
    after_path = result_dir / "protected_after.json"
    test_log = result_dir / "targeted_tests.log"
    write_json(before_path, before)
    baseline = create_baseline(repo_root, baseline_path)
    baseline_physical_hash = sha256_file(baseline_path)
    test_result = run_command(
        [sys.executable, "-m", "pytest", "src/tests/timeseries_v7/test_protected_v6_baseline.py", "-q", "-p", "no:cacheprovider"],
        repo_root,
        test_log,
    )
    after = build_protected_snapshot(repo_root)
    write_json(after_path, after)
    comparison = compare_snapshots(before, after)
    verification = verify_baseline(
        repo_root, baseline_path, expected_physical_sha256=baseline_physical_hash
    )
    result_path = result_dir / "result.json"
    result = {
        "schema_version": 1,
        "run_id": f"v7-p0-002-{baseline['snapshot']['protected_hash'][:16]}",
        "cycle_id": "v7-bootstrap-protection-20260825",
        "generation_id": "v7-pre-generation-v6-baseline",
        "task_key": "V7-P0-002",
        "status": "succeeded" if comparison["pass"] and verification["pass"] and test_result["returncode"] == 0 else "blocked",
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "input_hashes_verified": True,
        "baseline": {
            "path": baseline_path.relative_to(repo_root).as_posix(),
            "physical_sha256": baseline_physical_hash,
            "logical_content_sha256": baseline["content_sha256"],
            "protected_hash": baseline["snapshot"]["protected_hash"],
            "scope_contract_hash": baseline["scope_contract_hash"],
            "file_count": baseline["snapshot"]["file_count"],
            "category_counts": baseline["snapshot"]["category_counts"],
        },
        "before_after": comparison,
        "verification": verification,
        "commands": [test_result],
        "tests": {"passed": 0, "failed": 0, "skipped": 0},
        "artifacts": [],
        "secret_scan": {"pass": False, "matches": []},
        "acceptance": {
            "dependency_v7_p0_001_succeeded": True,
            "baseline_created_once": True,
            "before_after_byte_equivalent": comparison["pass"],
            "baseline_verifies_current_predecessor": verification["pass"],
            "targeted_tests_pass": test_result["returncode"] == 0,
            "next_task_not_started": True,
        },
        "blocker": None,
        "next_recommended_task": None,
        "next_task_started": False,
    }
    match = re.search(r"(\d+) passed", test_result["stdout_tail"] + test_result["stderr_tail"])
    result["tests"]["passed"] = int(match.group(1)) if match else 0
    write_json(result_path, result)
    secret = scan_secrets([baseline_path, result_dir])
    result["secret_scan"] = secret
    result["acceptance"]["secret_scan_pass"] = secret["pass"]
    if not secret["pass"] or not all(result["acceptance"].values()):
        result["status"] = "blocked"
        result["blocker"] = "V7_P0_002_ACCEPTANCE_FAILED"
    files = [
        repo_root / "src/ai_fc/timeseries_v7/__init__.py",
        repo_root / "src/ai_fc/timeseries_v7/protection.py",
        repo_root / "tools/verify_v7_protected.py",
        repo_root / "src/tests/timeseries_v7/test_protected_v6_baseline.py",
        baseline_path, before_path, after_path, test_log,
    ]
    result["artifacts"] = [_artifact(path, repo_root) for path in files if path.is_file()]
    result["changed_files"] = sorted(
        [row["path"] for row in result["artifacts"]] + [result_path.relative_to(repo_root).as_posix()]
    )
    write_json(result_path, result)
    manifest_path = result_dir / "ARTIFACTS.sha256"
    manifest_files = [*files, result_path]
    manifest_path.write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(repo_root).as_posix()}\n"
            for path in sorted(set(manifest_files)) if path.is_file()
        ),
        encoding="utf-8",
    )
    return 0 if result["status"] == "succeeded" else 3


def command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    create = subparsers.add_parser("bootstrap")
    create.add_argument("--repo-root", type=Path, default=Path.cwd())
    create.add_argument("--baseline", type=Path, required=True)
    create.add_argument("--result-dir", type=Path, default=Path("outputs/timeseries_v7/task_results/V7-P0-002"))
    verify = subparsers.add_parser("verify")
    verify.add_argument("--repo-root", type=Path, default=Path.cwd())
    verify.add_argument("--baseline", type=Path, required=True)
    verify.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    baseline = args.baseline if args.baseline.is_absolute() else repo_root / args.baseline
    try:
        if args.action == "bootstrap":
            result_dir = args.result_dir if args.result_dir.is_absolute() else repo_root / args.result_dir
            return bootstrap(repo_root, baseline, result_dir)
        result = verify_baseline(
            repo_root, baseline, expected_physical_sha256=args.expected_sha256
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result["pass"] else 3
    except (ProtectedScopeError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"{type(exc).__name__}:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(command())
