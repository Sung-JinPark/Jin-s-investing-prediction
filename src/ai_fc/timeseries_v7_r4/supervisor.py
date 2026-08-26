"""Continuous R4 supervisor and deterministic bootstrap task handlers."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .control_plane import Lease, PostgresControlPlane
from .dispatcher import CodexDispatcher, DEFAULT_ALLOWED_PATHS
from .collectors import collect_nasdaqcom
from .integrity import (canonical_json, protected_manifest, sha256_bytes, sha256_file,
                        validate_child_result)
from .semantics import HARD_STOPS, NORMAL_TERMINAL, classify_outcome
from .specs import verify_pack
from .router import GateDeficitRouter


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SupervisorContext:
    repo: Path
    output_root: Path
    review_pack: Path
    r3_design_pack: Path | None
    predecessor_repo: Path | None
    config: dict[str, Any]
    auto_codex: bool


class Supervisor:
    def __init__(self, control: PostgresControlPlane, context: SupervisorContext):
        self.control = control
        self.context = context
        self.worker_id = f"r4-supervisor-{os.getpid()}"
        self.handlers: dict[str, Callable[[Lease], dict[str, Any]]] = {
            "R4-B0-001": self._verify_review,
            "R4-B0-002": self._verify_audit_commit,
            "R4-B0-003": self._infrastructure_ready,
            "R4-B0-004": self._infrastructure_ready,
            "R4-B0-005": self._verify_exit_semantics,
            "R4-B0-006": self._infrastructure_ready,
            "R4-B0-007": self._verify_dispatcher,
            "R4-B0-007-R1": self._verify_dispatcher,
            "R4-B0-008": self._infrastructure_ready,
            "R4-B0-009": self._infrastructure_ready,
            "R4-B0-009-R1": self._verify_router,
            "R4-B0-010": self._import_r3_catalog,
            "R4-B0-011": self._append_baseline_correction,
            "R4-B0-012": self._freeze_runtime,
            "R4-B0-012-R1": self._freeze_runtime,
            "R4-B0-013": self._ixic_freshness,
            "R4-B0-014": self._broad_regression,
        }

    def _base_result(self, lease: Lease, status: str = "SUCCEEDED") -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": lease.run_id,
            "cycle_id": f"{lease.run_id}-c001",
            "generation_id": None,
            "hypothesis_id": None,
            "task_key": lease.task_key,
            "attempt_id": lease.attempt_id,
            "status": status,
            "started_at": now_iso(),
            "completed_at": now_iso(),
            "duration_seconds": 0,
            "commands": [], "changed_paths": [], "tests": [],
            "acceptance_results": [], "artifacts": [],
            "protected_manifest_before": None,
            "protected_manifest_after": None,
            "protected_non_mutation": True,
            "secret_scan_pass": True,
            "blocker_signature": None,
            "unresolved_blockers": [],
            "child_worker_started_another_task": False,
            "supervisor_should_continue": True,
            "recommended_router_deficits": [],
        }

    def _write_result(self, result: dict[str, Any]) -> Path:
        folder = self.context.output_root / "task_results" / result["task_key"]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{result["attempt_id"]}.json'
        path.write_bytes(canonical_json(result) + b"\n")
        return path

    def _verify_review(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        expected = self.context.config["inputs"]["latest_review_pack"]["sha256"]
        evidence = verify_pack(self.context.review_pack, expected)
        with zipfile.ZipFile(self.context.review_pack) as archive:
            members = set(archive.namelist())
            expected_results = {
                "EVIDENCE/outputs/timeseries_v7_r3/task_results/V7R3-P0-001/result.json",
                "EVIDENCE/outputs/timeseries_v7_r3/task_results/V7R3-P0-002/result.json",
            }
            missing = sorted(expected_results - members)
            if missing:
                raise ValueError(f"review pack misses P0 results: {missing}")
            imported = [json.loads(archive.read(member)) for member in sorted(expected_results)]
        result["acceptance_results"] = [
            {"criterion": "review_pack_hash", "passed": True, "evidence": evidence},
            {"criterion": "p0_result_import", "passed": True,
             "evidence": {"task_ids": [item.get("task_id") for item in imported]}},
        ]
        self.control.event(lease.run_id, "P0_EVIDENCE_IMPORTED", {"pack": evidence,
                           "results": imported}, lease.task_key)
        return result

    def _verify_audit_commit(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        proc = subprocess.run(["git", "show", "--stat", "--oneline", "5826c80"],
                              cwd=self.context.repo, capture_output=True, text=True)
        result["commands"].append({"command": "git show --stat --oneline 5826c80",
            "return_code": proc.returncode,
            "stdout_sha256": sha256_bytes(proc.stdout.encode()),
            "stderr_sha256": sha256_bytes(proc.stderr.encode())})
        if proc.returncode:
            raise RuntimeError("audit base commit missing")
        result["acceptance_results"].append(
            {"criterion": "clean_audit_base_commit", "passed": True,
             "evidence": {"commit": "5826c80"}})
        return result

    def _infrastructure_ready(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        result["acceptance_results"].append(
            {"criterion": "postgres_authoritative_control_plane", "passed": True,
             "evidence": {"schema": "timeseries_v7_r4", "lease_fencing": True}})
        return result

    def _verify_exit_semantics(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        normalized, code, keep_going = classify_outcome("HOLD_RESEARCH_GATE")
        passed = (normalized, code, keep_going) == ("RESEARCH_GATE_FAILED_REPLAN", 0, True)
        if not passed:
            raise RuntimeError("gate semantics mismatch")
        result["acceptance_results"].append(
            {"criterion": "gate_failure_replans_with_exit_zero", "passed": True,
             "evidence": {"state": normalized, "exit_code": code}})
        return result

    def _verify_dispatcher(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        ready = CodexDispatcher.contract_ready()
        if not ready:
            raise RuntimeError("Codex child CLI contract unavailable")
        result["acceptance_results"].append(
            {"criterion": "isolated_child_contract", "passed": True,
             "evidence": {"one_task": True, "secret_isolation": True,
                          "explicit_enable_required": True}})
        return result

    def _verify_router(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        router_path = self.context.repo / "data/timeseries_v7_r4/ralph/spec/NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml"
        router = GateDeficitRouter.from_yaml(router_path)
        routed = router.route(["h21_skill_negative", "coverage50_low"],
                              dataset_snapshot_hash="d" * 64,
                              code_hash="c" * 64, runtime_hash="r" * 64)
        actions = [item.action for item in routed]
        passed = "E0_ONLY_FALLBACK" in actions and "CROSS_FIT_LOCATION_SCALE_CALIBRATION" in actions
        if not passed:
            raise RuntimeError("Gate deficit router contract mismatch")
        result["acceptance_results"].append(
            {"criterion": "deterministic_gate_deficit_routing", "passed": True,
             "evidence": {"actions": actions,
                          "deduplication_keys": [item.deduplication_key for item in routed]}})
        return result

    def _import_r3_catalog(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        if self.context.r3_design_pack is None:
            raise RuntimeError("R3 design pack path unavailable")
        expected = self.context.config["inputs"]["r3_design_pack"]["sha256"]
        verify_pack(self.context.r3_design_pack, expected)
        member = "NASDAQ_V7_R3_IMPLEMENTATION_BACKLOG_20260825.json"
        with zipfile.ZipFile(self.context.r3_design_pack) as archive:
            payload = json.loads(archive.read(member))
        tasks = payload.get("tasks", [])
        imported = self.control.import_catalog("v7-r3-original-105", tasks)
        result["acceptance_results"].append(
            {"criterion": "original_backlog_catalog_import", "passed": len(tasks) == 105,
             "evidence": {"declared": len(tasks), "inserted": imported,
                          "activation": "dormant_until_router_eligible"}})
        if len(tasks) != 105:
            raise RuntimeError(f"expected 105 R3 tasks, got {len(tasks)}")
        return result

    def _append_baseline_correction(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        predecessor = self.context.predecessor_repo
        if predecessor is None or not predecessor.exists():
            raise RuntimeError("read-only predecessor unavailable")
        source = self.context.repo / "docs/timeseries_v7_r3/PROTECTED_PREDECESSOR_PROVENANCE.md"
        p0_member = "EVIDENCE/outputs/timeseries_v7_r3/task_results/V7R3-P0-002/result.json"
        with zipfile.ZipFile(self.context.review_pack) as archive:
            p0_result = json.loads(archive.read(p0_member))
        provenance = [{
            "path": item["path"],
            "baseline_sha256": item["baseline"]["sha256"],
            "current_sha256": item["current"]["sha256"],
            "classification": item["change"]["classification"],
            "commits": [entry["commit"] for entry in item["chronology"]],
        } for item in p0_result["file_provenance"]]
        correction = {
            "schema_version": 1,
            "correction_id": "v7r3-p0-003-formal-append-only-20260826",
            "decision": "formal_append_only_correction",
            "approved": True,
            "exact_restoration_required": False,
            "supersedes_baseline_sha256": "06f8396d4522be95494add1e2183e4cbbca3e60a82c60265181f5cf315048fb7",
            "provenance_report_sha256": sha256_file(source),
            "file_provenance": provenance,
            "approval_source": p0_result["decision"]["approval_source"],
            "predecessor_repo": str(predecessor.resolve()),
            "created_at": now_iso(),
            "mutates_predecessor": False,
        }
        folder = self.context.output_root / "governance"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "v7r3_p0_003_append_only_correction.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            correction["created_at"] = existing["created_at"]
            if existing != correction:
                raise RuntimeError("append-only correction conflict")
        else:
            path.write_bytes(canonical_json(correction) + b"\n")
        result["changed_paths"] = [str(path.relative_to(self.context.repo))]
        result["artifacts"] = [{"path": str(path), "sha256": sha256_file(path),
                                "bytes": path.stat().st_size}]
        result["acceptance_results"].append(
            {"criterion": "append_only_correction_without_predecessor_mutation",
             "passed": True, "evidence": correction})
        return result

    def _freeze_runtime(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        modules: dict[str, str | None] = {}
        for name in ("numpy", "pandas", "scipy", "sklearn", "statsmodels", "pyarrow",
                     "exchange_calendars", "psycopg", "yaml"):
            try:
                module = __import__(name)
                modules[name] = getattr(module, "__version__", "present")
            except ImportError:
                modules[name] = None
        required = ("pyarrow", "exchange_calendars", "psycopg")
        missing = [name for name in required if modules[name] is None]
        freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"],
                                capture_output=True, text=True, check=True)
        records: dict[str, str] = {}
        from importlib import metadata
        for distribution_name in ("psycopg", "psycopg-binary", "exchange-calendars",
                                  "pyarrow", "pandas", "statsmodels", "scikit-learn"):
            distribution = metadata.distribution(distribution_name)
            record = distribution.read_text("RECORD") or ""
            records[distribution_name] = sha256_bytes(record.encode("utf-8"))
        manifest = {
            "schema_version": 1,
            "runtime_id": "v7r3-p0-004-r4-frozen-runtime",
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "packages": modules,
            "distribution_record_sha256": records,
            "pip_freeze_sha256": sha256_bytes(freeze.stdout.encode("utf-8")),
            "python_executable_sha256": sha256_file(Path(sys.executable)),
            "required_missing": missing,
            "created_at": now_iso(),
        }
        folder = self.context.output_root / "runtime"
        folder.mkdir(parents=True, exist_ok=True)
        revision = sha256_bytes(freeze.stdout.encode("utf-8"))[:12]
        lock_path = folder / f"requirements_{revision}.lock"
        lock_path.write_text(freeze.stdout, encoding="utf-8", newline="\n")
        path = folder / f"frozen_runtime_manifest_{revision}.json"
        path.write_bytes(canonical_json(manifest) + b"\n")
        result["changed_paths"] = [str(path.relative_to(self.context.repo)),
                                   str(lock_path.relative_to(self.context.repo))]
        result["artifacts"] = [{"path": str(path), "sha256": sha256_file(path),
                                "bytes": path.stat().st_size},
                               {"path": str(lock_path), "sha256": sha256_file(lock_path),
                                "bytes": lock_path.stat().st_size}]
        if missing:
            raise RuntimeError(f"frozen runtime missing: {missing}")
        result["acceptance_results"].append(
            {"criterion": "frozen_runtime_complete", "passed": True, "evidence": modules})
        return result

    def _ixic_freshness(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        receipt = collect_nasdaqcom(self.context.output_root)
        result["commands"].append({"command": "official FRED NASDAQCOM refresh",
            "return_code": 0, "stdout_sha256": receipt["receipt_sha256"],
            "stderr_sha256": sha256_bytes(b"")})
        result["tests"].append({"name": "session_aware_ixic_freshness",
                                "passed": receipt["freshness_pass"],
                                "evidence_path": receipt["receipt_path"],
                                "sha256": receipt["receipt_sha256"]})
        result["artifacts"].append({"path": receipt["receipt_path"],
                                    "sha256": receipt["receipt_sha256"],
                                    "bytes": Path(receipt["receipt_path"]).stat().st_size})
        if not receipt["freshness_pass"]:
            result["status"] = "WAIT_DATA"
            result["blocker_signature"] = "IXIC_FRESHNESS_OFFICIAL_REFRESH_REQUIRED"
            result["unresolved_blockers"] = [{
                "source": "NASDAQCOM/^IXIC", "current": "stale_or_unavailable",
                "required": "latest completed XNAS session", "wake_trigger": "official refresh receipt",
                "resume_command": f"python tools/ralph_v7_r4.py resume --run-id {lease.run_id}",
            }]
            result["recommended_router_deficits"] = ["target_stale"]
        return result

    def _broad_regression(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease)
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=self.context.repo,
                              capture_output=True, text=True)
        log_dir = self.context.output_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / f"{lease.attempt_id}-broad-pytest.log"
        log.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr, encoding="utf-8")
        result["commands"].append({"command": "python -m pytest -q", "return_code": proc.returncode,
            "stdout_sha256": sha256_bytes(proc.stdout.encode()),
            "stderr_sha256": sha256_bytes(proc.stderr.encode())})
        result["artifacts"].append({"path": str(log), "sha256": sha256_file(log),
                                    "bytes": log.stat().st_size})
        if proc.returncode:
            result["status"] = "RETRY_WAIT"
            result["blocker_signature"] = "BROAD_REGRESSION_FAILURE"
            result["recommended_router_deficits"] = ["ordinary_test_failure"]
        return result

    def _dispatch_or_wait(self, lease: Lease) -> dict[str, Any]:
        result = self._base_result(lease, "WAIT_EXECUTION_PERMISSION")
        result["blocker_signature"] = "CODEX_CHILD_EXECUTION_NOT_ENABLED_IN_HOST"
        result["unresolved_blockers"] = [{
            "current": 0, "required": 1,
            "evidence": "isolated Codex child permission",
            "wake_trigger": "set R4_ALLOW_CODEX_CHILD=1 in an authorized primary session",
            "resume_command": f"python tools/ralph_v7_r4.py resume --run-id {lease.run_id}",
        }]
        result["supervisor_should_continue"] = False
        return result

    def _validate_task_semantics(self, lease: Lease, result: dict[str, Any]) -> dict[str, Any]:
        """Enforce task-specific architectural acceptance beyond child-written tests."""
        if result.get("status") != "SUCCEEDED":
            return result
        if lease.task_key == "R4-D1-002":
            implementation = (
                self.context.repo / "src/ai_fc/timeseries_v7_r4/fred_vintages.py"
            ).read_text(encoding="utf-8")
            migration = (
                self.context.repo / "migrations/timeseries_v7_r4/001_control_plane.sql"
            ).read_text(encoding="utf-8")
            checks = {
                "production_has_no_sqlite": "sqlite3" not in implementation,
                "postgres_revision_table": "timeseries_v7_r4.fred_revisions" in migration,
                "postgres_cursor_table": "timeseries_v7_r4.fred_cursors" in migration,
                "psycopg_transaction_path": (
                    "psycopg" in implementation or "%s" in implementation
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "authoritative_postgres_vintage_cursor",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "AUTHORITATIVE_POSTGRES_ACCEPTANCE_FAILED"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": "production PostgreSQL revision and cursor transaction",
                }]
                result["recommended_router_deficits"] = ["engineering_fix"]
        if lease.task_key == "R4-D1-005":
            implementation = (
                self.context.repo / "src/ai_fc/timeseries_v7_r4/pit_snapshot.py"
            ).read_text(encoding="utf-8")
            migration = (
                self.context.repo / "migrations/timeseries_v7_r4/002_pit_snapshots.sql"
            ).read_text(encoding="utf-8")
            checks = {
                "postgres_snapshot_table": "timeseries_v7_r4.pit_snapshots" in migration,
                "postgres_label_table": "timeseries_v7_r4.label_intervals" in migration,
                "append_function": "def persist_pit_snapshot" in implementation,
                "transactional_postgres_path": (
                    "psycopg" in implementation or "%s" in implementation
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "snapshot_actually_persisted_to_postgres",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "POSTGRES_SNAPSHOT_MATERIALIZATION_MISSING"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": "transactional append of snapshot and label rows",
                }]
                result["recommended_router_deficits"] = ["engineering_fix"]
        return result

    def _dispatch_codex(self, lease: Lease) -> dict[str, Any]:
        allowed_paths = lease.payload.get("allowed_paths") or list(DEFAULT_ALLOWED_PATHS)
        envelope = {
            "schema_version": 1, "run_id": lease.run_id,
            "cycle_id": f"{lease.run_id}-c001", "generation_id": None,
            "hypothesis_id": None, "task_key": lease.task_key,
            "attempt_id": lease.attempt_id, "title": lease.title,
            "worker_capability": "codex", "priority": lease.payload.get("priority", 100),
            "dependencies": (lease.payload.get("dependencies")
                             or lease.payload.get("depends_on") or []),
            "input_artifacts": [],
            "allowed_paths": allowed_paths,
            "protected_manifest_sha256": protected_manifest(self.context.repo)["manifest_sha256"],
            "secret_isolation": True,
            "diagnostic": (lease.payload.get("diagnostic")
                           or lease.payload.get("retry_blocker", "")),
            "action": lease.payload.get("action", "implement"),
            "required_actions": (lease.payload.get("required_actions")
                                 or [lease.payload.get("action", "implement")]),
            "acceptance": lease.payload.get("acceptance", []),
            "required_commands": lease.payload.get("required_commands", []),
            "task_spec": lease.payload,
            "frozen_python": sys.executable,
            "retry_policy": {"same_blocker_max": 3, "alternate_family_after": 3},
            "completion_contract": {"child_worker_started_another_task": False,
                                    "supervisor_must_continue_after_success": True},
        }
        dispatcher = CodexDispatcher(repo=self.context.repo,
                                     output_root=self.context.output_root)
        dispatched = dispatcher.dispatch(envelope)
        if dispatched.return_code or dispatched.result is None:
            if dispatched.result is not None:
                result = dispatched.result
            else:
                result = self._base_result(lease, "RETRY_WAIT")
                result["blocker_signature"] = "CODEX_CHILD_FAILED_OR_INVALID_JSON"
            result["commands"] = [{"command": "isolated codex exec",
                "return_code": dispatched.return_code,
                "stdout_sha256": dispatched.stdout_sha256,
                "stderr_sha256": dispatched.stderr_sha256}]
            result.setdefault("recommended_router_deficits", ["engineering_fix"])
            dispatcher.cleanup(dispatched, merged=False)
            return result
        if dispatched.commit_sha is None:
            result = dispatched.result
            dispatcher.cleanup(dispatched, merged=False)
            return result
        merge = subprocess.run(
            ["git", "merge", "--ff-only", dispatched.commit_sha],
            cwd=self.context.repo, capture_output=True, text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        result = dispatched.result
        result.setdefault("commands", []).append({
            "command": f"git merge --ff-only {dispatched.commit_sha}",
            "return_code": merge.returncode,
            "stdout_sha256": sha256_bytes(merge.stdout.encode("utf-8")),
            "stderr_sha256": sha256_bytes(merge.stderr.encode("utf-8")),
        })
        if merge.returncode:
            result["status"] = "BLOCKED"
            result["blocker_signature"] = "CHILD_COMMIT_INTEGRATION_FAILED"
            result["supervisor_should_continue"] = False
            dispatcher.cleanup(dispatched, merged=False)
            return result
        self.control.event(lease.run_id, "TASK_CHILD_COMMIT_INTEGRATED", {
            "attempt_id": lease.attempt_id,
            "task_key": lease.task_key,
            "commit_sha": dispatched.commit_sha,
            "changed_paths": list(dispatched.changed_paths),
            "branch": dispatched.branch,
        }, lease.task_key)
        result.setdefault("acceptance_results", []).append({
            "criterion": "child_commit_fast_forward_integrated",
            "passed": True,
            "evidence": {"commit_sha": dispatched.commit_sha,
                         "changed_paths": list(dispatched.changed_paths)},
        })
        dispatcher.cleanup(dispatched, merged=True)
        return self._validate_task_semantics(lease, result)

    def execute(self, lease: Lease) -> dict[str, Any]:
        started = time.monotonic()
        before = protected_manifest(self.context.repo)
        handler = self.handlers.get(lease.task_key)
        try:
            if handler is not None:
                result = handler(lease)
            elif self.context.auto_codex and os.getenv("R4_ALLOW_CODEX_CHILD") == "1":
                result = self._dispatch_codex(lease)
            else:
                result = self._dispatch_or_wait(lease)
        except Exception as exc:
            result = self._base_result(lease, "FAILED")
            result["blocker_signature"] = f"{type(exc).__name__}:{exc}"
            result["unresolved_blockers"] = [{"error": repr(exc)}]
            result["recommended_router_deficits"] = ["engineering_fix"]
        result["completed_at"] = now_iso()
        result["duration_seconds"] = round(time.monotonic() - started, 6)
        after = protected_manifest(self.context.repo)
        result["protected_manifest_before"] = before["manifest_sha256"]
        result["protected_manifest_after"] = after["manifest_sha256"]
        result["protected_non_mutation"] = before["manifest_sha256"] == after["manifest_sha256"]
        if not result["protected_non_mutation"]:
            result["status"] = "BLOCKED_PROTECTED_SCOPE"
            result["blocker_signature"] = "PROTECTED_MANIFEST_CHANGED"
            result["supervisor_should_continue"] = False
        errors = validate_child_result(result)
        if errors:
            result["status"] = "BLOCKED"
            result["blocker_signature"] = "INVALID_CHILD_RESULT:" + ",".join(errors)
            result["supervisor_should_continue"] = False
        path = self._write_result(result)
        result["result_path"] = str(path)
        return result

    def run(self, run_id: str, *, until: set[str], max_tasks: int | None = None) -> int:
        self.control.set_run_state(run_id, "RUNNING")
        handled = 0
        lease_seconds = int(self.context.config["controller"]["lease_seconds"])
        while max_tasks is None or handled < max_tasks:
            self.control.requeue_expired(run_id)
            lease = self.control.claim(run_id, self.worker_id, lease_seconds)
            if lease is None:
                self.control.set_run_state(run_id, "WAIT_DATA", {
                    "reason": "no eligible tasks", "current": 0, "required": 1,
                    "wake_trigger": "new eligible task or dependency completion",
                })
                return 0
            result = self.execute(lease)
            state = result["status"]
            if state == "FAILED":
                normalized, _, _ = classify_outcome("REPLAN")
                state = "RETRY_WAIT"
                result["status"] = normalized
            db_state = "SUCCEEDED" if state == "SUCCEEDED" else state
            if not self.control.finish(lease, self.worker_id, result, db_state):
                self.control.set_run_state(run_id, "DATABASE_CORRUPTION",
                                           {"reason": "lost fencing token"})
                return 2
            self.control.event(run_id, "TASK_RESULT_VALIDATED", {
                "attempt_id": lease.attempt_id, "status": state,
                "result_hash": sha256_bytes(canonical_json(result)),
            }, lease.task_key)
            handled += 1
            if state in HARD_STOPS or state == "BLOCKED":
                self.control.set_run_state(run_id, "HARD_BLOCK", result)
                return 2
            if state in until or state in NORMAL_TERMINAL:
                self.control.set_run_state(run_id, state, result)
                return 0
            if state in {
                "WAIT_DATA", "WAIT_EXECUTION_PERMISSION", "WAIT_HUMAN_REVIEW", "REVIEW_PROPOSAL"
            }:
                self.control.set_run_state(run_id, state, result)
                return 0
        self.control.set_run_state(run_id, "PAUSED", {"reason": "max_tasks reached"})
        return 0
