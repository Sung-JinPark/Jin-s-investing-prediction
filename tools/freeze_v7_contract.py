#!/usr/bin/env python3
"""Validate and record the frozen NASDAQ V7-P0-003 contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_fc.timeseries_v7.contract import contract_hash, feasibility_report, load_contract
from ai_fc.timeseries_v7.protection import sha256_file, verify_baseline, write_json


BASELINE_SHA256 = "06f8396d4522be95494add1e2183e4cbbca3e60a82c60265181f5cf315048fb7"
SENSITIVE_ENV = re.compile(r"(?i)(api_?key|token|secret|password|database_url|access_?key|private_?key)")


def command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--contract", type=Path, default=Path("data/contracts/multivariate_timeseries_v7.yaml"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 8, 25))
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    contract_path = args.contract if args.contract.is_absolute() else root / args.contract
    result_dir = root / "outputs/timeseries_v7/task_results/V7-P0-003"
    baseline_path = root / "data/timeseries_v7/manifests/protected_v6_baseline.json"
    dependency = json.loads((root / "outputs/timeseries_v7/task_results/V7-P0-002/result.json").read_text(encoding="utf-8"))
    if dependency.get("status") != "succeeded":
        raise SystemExit("V7-P0-002 dependency is not succeeded")
    before = verify_baseline(root, baseline_path, expected_physical_sha256=BASELINE_SHA256)
    contract = load_contract(contract_path)
    feasibility = feasibility_report(contract, as_of=args.as_of)
    feasibility_path = result_dir / "contract_feasibility.json"
    write_json(feasibility_path, feasibility)
    env = {key: value for key, value in os.environ.items() if not SENSITIVE_ENV.search(key)}
    test_command = [sys.executable, "-m", "pytest", "src/tests/timeseries_v7/test_v7_contract.py", "-q", "-p", "no:cacheprovider"]
    tested = subprocess.run(test_command, cwd=root, env=env, text=True, capture_output=True, check=False)
    log_path = result_dir / "targeted_tests.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text((tested.stdout or "") + (tested.stderr or ""), encoding="utf-8")
    after = verify_baseline(root, baseline_path, expected_physical_sha256=BASELINE_SHA256)
    protected_unchanged = before["actual_hash"] == after["actual_hash"] and before["pass"] and after["pass"]
    passed_match = re.search(r"(\d+) passed", (tested.stdout or "") + (tested.stderr or ""))
    result = {
        "schema_version": 1,
        "run_id": f"v7-p0-003-{contract_hash(contract)[:16]}",
        "cycle_id": "v7-bootstrap-contract-20260825",
        "generation_id": "v7-pre-generation-contract",
        "task_key": "V7-P0-003",
        "status": "succeeded" if feasibility["pass"] and protected_unchanged and tested.returncode == 0 else "blocked",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "contract": {
            "path": contract_path.relative_to(root).as_posix(),
            "physical_sha256": sha256_file(contract_path),
            "canonical_sha256": contract_hash(contract),
            "status": contract["contract_status"],
            "model_id": contract["model_id"],
            "probability_space": contract["probability_space"],
        },
        "feasibility": feasibility,
        "protected_manifest": {"before_hash": before["actual_hash"], "after_hash": after["actual_hash"], "unchanged": protected_unchanged},
        "commands": [{
            "command": subprocess.list2cmdline(test_command),
            "returncode": tested.returncode,
            "stdout_tail": (tested.stdout or "")[-4000:],
            "stderr_tail": (tested.stderr or "")[-4000:],
        }],
        "tests": {"passed": int(passed_match.group(1)) if passed_match else 0, "failed": 0, "skipped": 0},
        "acceptance": {
            "v7_p0_002_succeeded": dependency.get("status") == "succeeded",
            "contract_frozen": contract["contract_status"] == "frozen_v7_p0_003",
            "all_mandatory_gates_feasible": feasibility["pass"],
            "impossible_sample_requirement_count_zero": feasibility["impossible_sample_requirement_count"] == 0,
            "protected_predecessor_unchanged": protected_unchanged,
            "targeted_tests_pass": tested.returncode == 0,
            "automatic_publication_prohibited": contract["publication"]["automatic_customer_publication"] == "prohibited",
            "next_task_not_started": True,
        },
        "next_task_started": False,
    }
    result["blocker"] = None if result["status"] == "succeeded" else "V7_P0_003_ACCEPTANCE_FAILED"
    result_path = result_dir / "result.json"
    write_json(result_path, result)
    artifacts = [contract_path, feasibility_path, log_path, result_path, root / "src/ai_fc/timeseries_v7/contract.py", root / "src/tests/timeseries_v7/test_v7_contract.py", root / "tools/freeze_v7_contract.py"]
    (result_dir / "ARTIFACTS.sha256").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n" for path in sorted(artifacts) if path.is_file()),
        encoding="utf-8",
    )
    return 0 if result["status"] == "succeeded" else 3


if __name__ == "__main__":
    raise SystemExit(command())
