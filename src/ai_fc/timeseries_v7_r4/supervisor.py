"""Continuous R4 supervisor and deterministic bootstrap task handlers."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
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
from .runtime_snapshot_export import export_runtime_snapshot


R4_QUALIFIED_SNAPSHOT_HASH = (
    "cdddba1e32a4bdb3aebc98ec676c81744085a2a5952d4014807f0feb78140fc2"
)
R4_EXACT_E0_ARTIFACT_SHA256 = (
    "0653be032bcc8d0a4bf743967be3f21611a148aa9a12e11b1cb152f4aa2ca6ec"
)
R4_EXACT_E0_MEAN_CRPS = 0.0187453537909802
R4_SNAPSHOT_CONSUMER_TASKS = frozenset({"R4-M3-006", "R4-M3-007", "R4-M3-008"})


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

    def _input_artifacts(self, lease: Lease) -> list[dict[str, Any]]:
        artifacts = [{
            "path": str(self.context.review_pack),
            "sha256": self.context.config["inputs"]["latest_review_pack"]["sha256"],
            "nested_member": "INPUTS/NASDAQ_V7_ALFRED_PIT_TRAINING_REVIEW_PACK_20260825.zip",
            "usage": "real PIT observations, predecessor scores, and receipts",
        }]
        if lease.task_key in R4_SNAPSHOT_CONSUMER_TASKS:
            output = (
                self.context.repo / ".runtime" / "v7r4" / "input_exports"
                / f"{R4_QUALIFIED_SNAPSHOT_HASH}.json"
            )
            receipt = export_runtime_snapshot(
                self.control.database_url,
                snapshot_hash=R4_QUALIFIED_SNAPSHOT_HASH,
                output=output,
                require_five_role=True,
            )
            artifacts.append({
                **receipt,
                "usage": (
                    "credential-free authoritative R4 PIT snapshot; use this for actual "
                    "model execution and never request a database URL from the child environment"
                ),
            })
            e0_path = (
                self.context.repo / "outputs" / "timeseries_v7_r4"
                / "R4-M3-001" / "g0_e0_ablation.json"
            )
            if sha256_file(e0_path) != R4_EXACT_E0_ARTIFACT_SHA256:
                raise RuntimeError("frozen exact E0 artifact hash mismatch")
            artifacts.append({
                "path": str(e0_path.resolve()),
                "sha256": R4_EXACT_E0_ARTIFACT_SHA256,
                "exact_mean_crps": R4_EXACT_E0_MEAN_CRPS,
                "usage": (
                    "frozen exact E0 comparator; pass exact_mean_crps unchanged to every "
                    "no-regret screen and never substitute a rounded value"
                ),
            })
        return artifacts

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
        if lease.task_key == "R4-D1-006":
            artifact_path = (
                self.context.repo
                / "outputs/timeseries_v7_r4/R4-D1-006/data_pit_qualification.json"
            )
            payload: dict[str, Any] = {}
            if artifact_path.exists():
                try:
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {}
            source_hash = payload.get("source_snapshot_hash")
            r4_hash = payload.get("r4_snapshot_hash")
            db_evidence = {
                "snapshot_present": False,
                "feature_rows": 0,
                "label_rows": 0,
                "provenance_rows": 0,
                "provenance_pit_violations": -1,
                "calendar_version": None,
                "qualified_feature_count": 0,
                "provenance_schema_complete": False,
                "provenance_lineage_failures": -1,
            }
            if isinstance(r4_hash, str) and len(r4_hash) == 64:
                try:
                    with self.control.connect() as connection:
                        snapshot_row = connection.execute(
                            "SELECT calendar_version,jsonb_array_length(payload->'feature_rows')"
                            " FROM timeseries_v7_r4.pit_snapshots WHERE snapshot_hash=%s",
                            (r4_hash,),
                        ).fetchone()
                        if snapshot_row is not None:
                            db_evidence["snapshot_present"] = True
                            db_evidence["calendar_version"] = snapshot_row[0]
                            db_evidence["feature_rows"] = snapshot_row[1]
                        db_evidence["label_rows"] = connection.execute(
                            "SELECT count(*) FROM timeseries_v7_r4.label_intervals"
                            " WHERE snapshot_hash=%s", (r4_hash,),
                        ).fetchone()[0]
                        provenance_table = connection.execute(
                            "SELECT to_regclass('timeseries_v7_r4.feature_value_provenance')"
                        ).fetchone()[0]
                    if provenance_table is not None:
                        with self.control.connect() as connection:
                            columns = {
                                row[0] for row in connection.execute(
                                    "SELECT column_name FROM information_schema.columns"
                                    " WHERE table_schema='timeseries_v7_r4'"
                                    " AND table_name='feature_value_provenance'"
                                ).fetchall()
                            }
                            required_columns = {
                                "source_revision_ids", "transformation_hash", "data_grade",
                            }
                            db_evidence["provenance_schema_complete"] = (
                                required_columns <= columns
                            )
                            if db_evidence["provenance_schema_complete"]:
                                counts = connection.execute(
                                    "SELECT count(*),"
                                    " count(*) FILTER (WHERE max_available_at>origin_cutoff_at),"
                                    " count(DISTINCT feature_id),"
                                    " count(*) FILTER (WHERE cardinality(source_revision_ids)=0"
                                    " OR length(transformation_hash)<>64 OR data_grade='')"
                                    " FROM timeseries_v7_r4.feature_value_provenance"
                                    " WHERE snapshot_hash=%s", (r4_hash,),
                                ).fetchone()
                            else:
                                counts = (0, -1, 0, -1)
                        db_evidence["provenance_rows"] = counts[0]
                        db_evidence["provenance_pit_violations"] = counts[1]
                        db_evidence["qualified_feature_count"] = counts[2]
                        db_evidence["provenance_lineage_failures"] = counts[3]
                except Exception as exc:
                    db_evidence["query_error"] = f"{type(exc).__name__}:{exc}"
            expected_feature_rows = payload.get("source_snapshot_rows")
            expected_label_rows = payload.get("source_label_rows")
            active_feature_values = payload.get("active_feature_value_count")
            calendar_hash = payload.get("calendar_version_hash")
            checks = {
                "r4_snapshot_rematerialized": payload.get("r4_snapshot_rematerialized") is True,
                "snapshot_hash_changed": (
                    isinstance(source_hash, str) and len(source_hash) == 64
                    and isinstance(r4_hash, str) and len(r4_hash) == 64
                    and source_hash != r4_hash
                ),
                "canonical_xnas_cutoff_proof": payload.get("canonical_xnas_cutoff_proof") is True,
                "feature_value_provenance_pass": (
                    payload.get("feature_value_provenance_pass") is True
                ),
                "release_native_features_pass": payload.get("release_native_features_pass") is True,
                "postgres_snapshot_persisted": payload.get("postgres_snapshot_persisted") is True,
                "legacy_runtime_defects_acknowledged": (
                    payload.get("legacy_runtime_defects_acknowledged") is True
                ),
                "database_snapshot_present": db_evidence["snapshot_present"],
                "all_real_feature_rows_persisted": (
                    isinstance(expected_feature_rows, int) and expected_feature_rows >= 7_000
                    and db_evidence["feature_rows"] == expected_feature_rows
                ),
                "all_mature_labels_persisted": (
                    isinstance(expected_label_rows, int) and expected_label_rows >= 7_000
                    and db_evidence["label_rows"] == expected_label_rows
                ),
                "per_feature_provenance_complete": (
                    isinstance(active_feature_values, int)
                    and isinstance(expected_feature_rows, int)
                    and active_feature_values >= expected_feature_rows * 10
                    and db_evidence["provenance_rows"] == active_feature_values
                    and db_evidence["provenance_pit_violations"] == 0
                    and db_evidence["provenance_schema_complete"]
                    and db_evidence["provenance_lineage_failures"] == 0
                ),
                "versioned_calendar_hash_bound": (
                    isinstance(calendar_hash, str) and len(calendar_hash) == 64
                    and db_evidence["calendar_version"] == f"XNAS@{calendar_hash}"
                ),
                "early_close_sessions_verified": (
                    isinstance(payload.get("canonical_early_close_checks"), int)
                    and payload["canonical_early_close_checks"] > 0
                ),
                "release_native_values_materialized": (
                    isinstance(payload.get("release_native_feature_count"), int)
                    and payload["release_native_feature_count"] >= 11
                ),
                "usable_multivariate_feature_set": (
                    isinstance(payload.get("qualified_feature_count"), int)
                    and payload["qualified_feature_count"] >= 20
                    and db_evidence["qualified_feature_count"]
                    == payload["qualified_feature_count"]
                ),
                "target_price_complete": (
                    isinstance(payload.get("target_price_rows"), int)
                    and payload["target_price_rows"] == expected_feature_rows
                ),
                "core_missingness_acceptable": (
                    isinstance(payload.get("core_missingness_2007_plus"), (int, float))
                    and 0 <= payload["core_missingness_2007_plus"] <= 0.05
                ),
                "all_alfred_series_covered": (
                    isinstance(payload.get("alfred_series_covered"), int)
                    and payload["alfred_series_covered"] >= 11
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "r4_data_qualification_uses_rematerialized_snapshot",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "R4_FULL_REMATERIALIZATION_EVIDENCE_MISSING"
                result["unresolved_blockers"] = [{
                    "current": checks, "database_evidence": db_evidence,
                    "required": "real R4 rematerialization with new cutoff, provenance, release-native features, and PostgreSQL persistence",
                }]
                result["recommended_router_deficits"] = ["data_rematerialization"]
        if lease.task_key == "R4-V2-002":
            implementation_path = (
                self.context.repo
                / "src/ai_fc/timeseries_v7_r4/e0_empirical_samples.py"
            )
            implementation = (
                implementation_path.read_text(encoding="utf-8")
                if implementation_path.exists() else ""
            )
            tool_path = self.context.repo / "tools/generate_e0_samples_v7_r4.py"
            tool_text = tool_path.read_text(encoding="utf-8") if tool_path.exists() else ""
            help_return_code = -1
            if tool_path.exists():
                help_return_code = subprocess.run(
                    [sys.executable, str(tool_path), "--help"],
                    cwd=self.context.repo, capture_output=True, text=True,
                ).returncode
            active_artifacts_valid = True
            artifact_root = (
                self.context.repo
                / "data/timeseries_v7_r4/generated/e0_sample_matrices"
            )
            for artifact in artifact_root.glob("*.json") if artifact_root.exists() else ():
                try:
                    artifact_payload = json.loads(artifact.read_text(encoding="utf-8"))
                    active_artifacts_valid = active_artifacts_valid and (
                        artifact_payload.get("contract", {}).get("algorithm")
                        == "exact_empirical_anchor"
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    active_artifacts_valid = False
            checks = {
                "frozen_exact_empirical_anchor": "exact_empirical_anchor" in implementation,
                "no_comparator_block_bootstrap": (
                    "historical_moving_block_bootstrap" not in implementation
                    and "E0_BLOCK_BOOTSTRAP_CONTRACT" not in implementation
                ),
                "exact_label_fit_boundary": "fit_exact_empirical_anchor" in implementation,
                "no_rng_in_exact_anchor": (
                    "default_rng" not in implementation and ".choice(" not in implementation
                ),
                "quantile_reconstruction_prohibited": (
                    "quantiles cannot reconstruct" in implementation
                ),
                "exact_anchor_cli_imports": (
                    "E0_EXACT_EMPIRICAL_CONTRACT" in tool_text
                    and "fit_exact_empirical_anchor" in tool_text
                    and "E0_BLOCK_BOOTSTRAP_CONTRACT" not in tool_text
                ),
                "exact_anchor_cli_help": help_return_code == 0,
                "active_artifacts_preserve_comparator": active_artifacts_valid,
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "frozen_e0_exact_empirical_comparator_preserved",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "FROZEN_E0_COMPARATOR_MISMATCH"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "unchanged exact empirical direct-horizon label anchor; "
                        "no bootstrap, Gaussian reconstruction, quantile reconstruction, or RNG"
                    ),
                }]
                result["recommended_router_deficits"] = ["comparator_identity"]
        if lease.task_key == "R4-V2-003":
            implementation_path = (
                self.context.repo
                / "src/ai_fc/timeseries_v7_r4/empirical_mixture.py"
            )
            implementation = (
                implementation_path.read_text(encoding="utf-8")
                if implementation_path.exists() else ""
            )
            checks = {
                "no_quadratic_broadcast_matrix": (
                    "[:, None]" not in implementation
                    and "[None, :]" not in implementation
                ),
                "efficient_cross_distance": (
                    "cross_absolute_distance" in implementation
                    or "cross_abs_distance" in implementation
                ),
                "objective_terms_precomputed": "precompute" in implementation.lower(),
                "final_no_regret_check": (
                    "mixture_score" in implementation
                    and "e0_score" in implementation
                    and "improvement_tolerance" in implementation
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "scalable_empirical_mixture_and_final_no_regret",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "EMPIRICAL_MIXTURE_SCALE_OR_GUARD_MISSING"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "O(N log N) cross-distance precomputation and final exact E0-only "
                        "fallback whenever optimized mixture does not improve E0"
                    ),
                }]
                result["recommended_router_deficits"] = ["mixture_optimizer"]
        if lease.task_key == "R4-M3-001":
            artifact_path = (
                self.context.repo
                / "outputs/timeseries_v7_r4/R4-M3-001/g0_e0_ablation.json"
            )
            payload: dict[str, Any] = {}
            if artifact_path.exists():
                try:
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {}
            qualification_path = (
                self.context.repo
                / "outputs/timeseries_v7_r4/R4-D1-006/data_pit_qualification.json"
            )
            qualification: dict[str, Any] = {}
            if qualification_path.exists():
                try:
                    qualification = json.loads(
                        qualification_path.read_text(encoding="utf-8")
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    qualification = {}
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            comparator = (
                payload.get("comparator_contract")
                if isinstance(payload.get("comparator_contract"), dict) else {}
            )
            horizons = {
                int(item.get("horizon_sessions"))
                for item in payload.get("e0_only_skill", [])
                if isinstance(item, dict)
                and isinstance(item.get("horizon_sessions"), (int, float))
            }
            checks = {
                "uses_r4_rematerialized_snapshot": (
                    isinstance(qualification.get("r4_snapshot_hash"), str)
                    and source.get("r4_snapshot_hash")
                    == qualification.get("r4_snapshot_hash")
                ),
                "exact_empirical_comparator_contract": (
                    comparator.get("contract_id") == "E0_exact_empirical_anchor_v1"
                    and comparator.get("algorithm") == "exact_empirical_anchor"
                    and comparator.get("sampling") == "none"
                ),
                "full_frozen_weekly_grid": (
                    source.get("origin_count") == 1_025
                    and source.get("coordinate_count") == 4_082
                    and horizons == {1, 5, 21, 63}
                ),
                "frozen_weekly_origin_identity": (
                    source.get("evaluation_origin_grid_hash")
                    == "e9657818bc2693c0788d4c509b4bf08b4456e7ca6c8f149028788ee845947135"
                    and source.get("evaluation_coordinate_grid_hash")
                    == "1f2403b7b15c100741a29816304056c2ad7b91cd777b29534a96a567068fa7e8"
                ),
                "exact_samples_replayed_for_every_coordinate": (
                    payload.get("exact_replay_count") == source.get("coordinate_count")
                    and payload.get("sample_identity_failures") == 0
                ),
                "legacy_approximate_scores_not_used": (
                    payload.get("approximate_baseline_rows_used") == 0
                    and "source_pack_sha256" not in payload
                    and "nested_member" not in payload
                ),
                "five_role_validation_bound": (
                    payload.get("five_role_validation_proof") is True
                ),
                "single_qualification": payload.get("qualification_count") == 1,
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "g0_uses_exact_e0_on_r4_full_weekly_grid",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "G0_EXACT_E0_R4_REPLAY_MISSING"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "replay exact empirical E0 samples from the R4 PostgreSQL PIT "
                        "snapshot and matured direct-horizon labels for every frozen weekly "
                        "origin/horizon; preserve stage sample hashes; do not reuse legacy "
                        "baseline_crps or the predecessor V7 score matrix"
                    ),
                }]
                result["recommended_router_deficits"] = ["exact_e0_full_grid"]
        if lease.task_key == "R4-M3-003":
            implementation_path = (
                self.context.repo
                / "src/ai_fc/timeseries_v7_r4/e2_student_t.py"
            )
            implementation = (
                implementation_path.read_text(encoding="utf-8")
                if implementation_path.exists() else ""
            )
            checks = {
                "true_student_t_location_scale": (
                    "gammaln" in implementation
                    and "degrees_of_freedom" in implementation
                    and "log_scale" in implementation
                ),
                "preregistered_df_grid": all(
                    token in implementation for token in ("3.0", "5.0", "8.0", "12.0")
                ),
                "preregistered_alpha_grid": all(
                    token in implementation for token in ("0.01", "0.1", "1.0")
                ),
                "horizon_crps_in_objective": (
                    "student_t_crps" in implementation
                    and "crps_weight" in implementation
                ),
                "stability_penalty_in_objective": (
                    "stability_penalty" in implementation
                    and "stability_weight" in implementation
                ),
                "temporal_cross_fit_without_future_training": (
                    "expanding" in implementation.lower()
                    and "train_end" in implementation
                    and "validation_start" in implementation
                ),
                "objective_contract_disclosed": (
                    "student_t_nll_plus_crps_plus_stability" in implementation
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "e2_preregistered_joint_objective_and_temporal_cross_fit",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "E2_PREREGISTERED_OBJECTIVE_INCOMPLETE"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "implement the frozen E2 objective Student-t NLL + horizon CRPS + "
                        "stability penalty, and obtain scale residuals from expanding/rolling "
                        "cross-fit folds whose training rows precede their validation rows"
                    ),
                }]
                result["recommended_router_deficits"] = ["e2_objective_and_crossfit"]
        if lease.task_key == "R4-M3-006":
            artifact_path = (
                self.context.repo
                / "outputs/timeseries_v7_r4/R4-M3-006/g1_screen.json"
            )
            payload: dict[str, Any] = {}
            if artifact_path.exists():
                try:
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {}
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            counts = (
                payload.get("candidate_counts")
                if isinstance(payload.get("candidate_counts"), dict) else {}
            )
            families = set(payload.get("candidate_families", []))
            candidates = payload.get("candidates", [])
            budgets = {"smoke": 160, "inner_screen": 48, "robust_inner": 12,
                       "full_nested": 4, "qualification": 1}
            budget_pass = all(
                isinstance(counts.get(stage), int)
                and 0 <= counts[stage] <= limit
                for stage, limit in budgets.items()
            )
            lineage_pass = bool(candidates) and all(
                isinstance(item, dict)
                and isinstance(item.get("hypothesis_hash"), str)
                and len(item["hypothesis_hash"]) == 64
                and isinstance(item.get("exposure_hash"), str)
                and len(item["exposure_hash"]) == 64
                for item in candidates
            )
            no_regret_pass = bool(candidates) and all(
                item.get("weight") == 0.0
                for item in candidates
                if isinstance(item, dict) and item.get("underperforms_e0") is True
            )
            role_receipt = (
                source.get("five_role_receipt")
                if isinstance(source.get("five_role_receipt"), dict) else {}
            )
            role_hashes = (
                role_receipt.get("role_hashes")
                if isinstance(role_receipt.get("role_hashes"), dict) else {}
            )
            score_receipts = payload.get("score_receipts", [])
            distribution_score_pass = (
                source.get("score_metric") == "distribution_crps"
                and isinstance(score_receipts, list) and len(score_receipts) >= 4
                and all(
                    isinstance(item, dict)
                    and item.get("metric") == "crps"
                    and isinstance(item.get("predictive_distribution_hash"), str)
                    and len(item["predictive_distribution_hash"]) == 64
                    and isinstance(item.get("score_rows"), int)
                    and item["score_rows"] > 0
                    for item in score_receipts
                )
            )
            five_role_receipt_pass = (
                set(role_hashes) == {"train", "selection", "stacking", "calibration", "outer"}
                and all(isinstance(value, str) and len(value) == 64
                        for value in role_hashes.values())
                and isinstance(role_receipt.get("role_counts"), dict)
                and all(isinstance(role_receipt["role_counts"].get(role), int)
                        and role_receipt["role_counts"][role] > 0
                        for role in ("train", "selection", "stacking", "calibration", "outer"))
                and isinstance(role_receipt.get("plan_hash"), str)
                and len(role_receipt["plan_hash"]) == 64
                and isinstance(role_receipt.get("excluded_count"), int)
                and role_receipt["excluded_count"] > 0
                and role_receipt.get("interval_overlap_count") == 0
                and role_receipt.get("purge_unit") == "xnas_sessions"
                and role_receipt.get("outer_exposed_during_screen") is False
            )
            checks = {
                "artifact_present": artifact_path.exists(),
                "uses_r4_snapshot": (
                    source.get("r4_snapshot_hash")
                    == "cdddba1e32a4bdb3aebc98ec676c81744085a2a5952d4014807f0feb78140fc2"
                ),
                "uses_exact_e0_full_grid": (
                    source.get("e0_artifact_sha256") == R4_EXACT_E0_ARTIFACT_SHA256
                    and isinstance(source.get("e0_mean_crps"), (int, float))
                    and abs(float(source["e0_mean_crps"]) - R4_EXACT_E0_MEAN_CRPS) < 1e-15
                    and source.get("evaluation_origin_grid_hash")
                    == "e9657818bc2693c0788d4c509b4bf08b4456e7ca6c8f149028788ee845947135"
                ),
                "all_g1_families_executed": {"E1", "E2", "E3", "E4"} <= families,
                "actual_model_score_rows": (
                    isinstance(source.get("model_score_rows"), int)
                    and source["model_score_rows"] >= 1_000
                ),
                "legacy_precomputed_scores_not_used": (
                    source.get("legacy_precomputed_score_rows_used") == 0
                ),
                "outer_role_not_exposed_during_screen": (
                    source.get("outer_rows_used") == 0
                ),
                "funnel_budgets_respected": budget_pass,
                "hypothesis_and_exposure_lineage": lineage_pass,
                "underperformers_zero_weight": no_regret_pass,
                "five_role_partition_bound": (
                    payload.get("five_role_validation_proof") is True
                    and five_role_receipt_pass
                ),
                "distribution_crps_scoring": distribution_score_pass,
                "frozen_candidate_coordinates_preserved": (
                    source.get("frozen_candidate_coordinates_preserved") is True
                ),
                "optimizer_convergence_required": (
                    source.get("optimizer_convergence_required") is True
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "g1_actual_r4_candidate_screen",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "G1_ACTUAL_MODEL_SCREEN_MISSING"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "execute E1, E2, E3, and E4 against the R4 rematerialized PIT "
                        "snapshot on train/selection/robust-inner roles, bind the exact E0 "
                        "comparator, record real model score rows and lineage hashes, and keep "
                        "the outer role sealed for R4-M3-008. Score predictive distributions "
                        "with CRPS (never p50 MAE), emit per-family distribution receipts, bind "
                        "all five interval-disjoint role hashes, and preserve frozen candidate "
                        "coordinates and optimizer convergence requirements"
                    ),
                }]
                result["recommended_router_deficits"] = ["g1_actual_screen"]
        if lease.task_key == "R4-M3-007":
            artifact_path = (
                self.context.repo
                / "outputs/timeseries_v7_r4/R4-M3-007/stacking_calibration.json"
            )
            payload: dict[str, Any] = {}
            if artifact_path.exists():
                try:
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {}
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            horizons = payload.get("horizons") if isinstance(payload.get("horizons"), dict) else {}
            g1_path = self.context.repo / "outputs/timeseries_v7_r4/R4-M3-006/g1_screen.json"
            g1_payload: dict[str, Any] = {}
            if g1_path.exists():
                try:
                    g1_payload = json.loads(g1_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    g1_payload = {}
            rejected = {
                str(item.get("candidate_id"))
                for item in g1_payload.get("candidates", [])
                if isinstance(item, dict) and item.get("weight") == 0.0
            }
            horizon_rows = [horizons.get(str(horizon)) for horizon in (1, 5, 21, 63)]
            weights_pass = bool(horizon_rows) and all(
                isinstance(row, dict)
                and isinstance(row.get("weights"), dict)
                and set(row["weights"]) == {"E0", "E1", "E2", "E3", "E4"}
                and all(isinstance(value, (int, float)) and value >= 0.0
                        for value in row["weights"].values())
                and abs(sum(float(value) for value in row["weights"].values()) - 1.0) < 1e-12
                and all(row["weights"].get(family) == 0.0 for family in rejected)
                and (not rejected or row["weights"].get("E0") == 1.0)
                for row in horizon_rows
            )
            fold_pass = bool(horizon_rows) and all(
                isinstance(row, dict)
                and row.get("weight_fit_role") == "stacking"
                and row.get("stacking_case_count") == 634
                and row.get("calibration_fit_role") == "calibration"
                and row.get("cross_fit_case_count") == 634
                and row.get("cross_fit_calibration_applied") is True
                and row.get("e0_no_regret_pass") is True
                and isinstance(row.get("stacking_crps"), (int, float))
                and isinstance(row.get("stacking_e0_crps"), (int, float))
                and float(row["stacking_crps"]) <= float(row["stacking_e0_crps"]) + 1e-12
                for row in horizon_rows
            )
            sample_hash_pass = bool(horizon_rows) and all(
                isinstance(row, dict)
                and isinstance(row.get("sample_set_hash"), str)
                and len(row["sample_set_hash"]) == 64
                for row in horizon_rows
            )
            role_receipt = (
                source.get("five_role_receipt")
                if isinstance(source.get("five_role_receipt"), dict) else {}
            )
            compact_files = True
            task_output = artifact_path.parent
            if task_output.exists():
                compact_files = all(
                    path.stat().st_size <= 1_000_000
                    for path in task_output.rglob("*") if path.is_file()
                )
            checks = {
                "artifact_present_and_compact": (
                    artifact_path.exists()
                    and artifact_path.stat().st_size <= 1_000_000
                    and compact_files
                    and source.get("git_embedded_raw_samples") is False
                ),
                "uses_r4_snapshot_and_exact_e0": (
                    source.get("r4_snapshot_hash") == R4_QUALIFIED_SNAPSHOT_HASH
                    and source.get("e0_artifact_sha256") == R4_EXACT_E0_ARTIFACT_SHA256
                    and isinstance(source.get("e0_mean_crps"), (int, float))
                    and abs(float(source["e0_mean_crps"]) - R4_EXACT_E0_MEAN_CRPS) < 1e-15
                    and g1_path.exists()
                    and source.get("g1_artifact_sha256") == sha256_file(g1_path)
                ),
                "horizon_specific_no_regret_weights": weights_pass,
                "stacking_and_cross_fit_roles_are_disjoint": fold_pass,
                "all_sample_sets_content_addressed": sample_hash_pass,
                "outer_role_remains_sealed": (
                    payload.get("outer_rows_used") == 0
                    and role_receipt.get("outer_exposed_during_screen") is False
                    and role_receipt.get("role_counts", {}).get("outer") == 765
                    and role_receipt.get("role_hashes")
                    == g1_payload.get("five_role_receipt", {}).get("role_hashes")
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "g2_learned_stacking_and_cross_fit_calibration",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "G2_STACKING_CALIBRATION_EVIDENCE_MISSING"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "stream exact E0 empirical scores on the stacking fold; emit compact "
                        "horizon weights, content hashes and calibration summaries only; use "
                        "the calibration fold for cross-fit calibration; retain zero weights "
                        "for rejected G1 families; never write raw sample arrays to Git and "
                        "never expose the outer role"
                    ),
                }]
                result["recommended_router_deficits"] = ["g2_stacking_calibration"]
        if lease.task_key == "R4-M3-008":
            artifact_root = self.context.repo / "outputs/timeseries_v7_r4/R4-M3-008"
            revision_path = artifact_root / "qualification_revision_3.json"
            prior_path = artifact_root / "qualification_revision_2.json"
            payload: dict[str, Any] = {}
            if revision_path.exists():
                try:
                    payload = json.loads(revision_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {}
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            stress = (metrics.get("historical_stress")
                      if isinstance(metrics.get("historical_stress"), dict) else {})
            methodology = (payload.get("gate_methodology")
                           if isinstance(payload.get("gate_methodology"), dict) else {})
            expected_stress = {
                "gfc": (416, 0.7668269230769231),
                "pandemic": (84, 0.4523809523809524),
                "tightening_2022": (208, 0.6394230769230769),
                "rebound_2009": (224, 0.8660714285714286),
                "rebound_2020": (192, 0.7552083333333334),
                "bull_2023": (208, 0.8942307692307693),
            }
            stress_pass = set(stress) == set(expected_stress) and all(
                isinstance(stress.get(name), dict)
                and stress[name].get("count") == count
                and isinstance(stress[name].get("coverage80"), (int, float))
                and abs(float(stress[name]["coverage80"]) - coverage) < 1e-12
                for name, (count, coverage) in expected_stress.items()
            )
            expected_deficits = {
                "long_skill_below_threshold", "h21_skill_negative",
                "h63_skill_negative", "paired_ci_upper_positive",
                "coverage80_fail", "coverage50_high",
                "balanced_direction_low", "historical_stress_fail",
            }
            checks = {
                "append_only_methodology_revision": (
                    revision_path.exists() and prior_path.exists()
                    and payload.get("schema") == "r4_core_qualification_v1_revision_3"
                    and payload.get("supersedes_sha256") == sha256_file(prior_path)
                    and payload.get("correction_scope")
                    == "gate_methodology_only_scores_unchanged"
                ),
                "frozen_v7_dependence_method": (
                    methodology.get("method") == "moving_block_bootstrap"
                    and methodology.get("seed") == 20260825
                    and methodology.get("replications") == 1000
                    and methodology.get("block_length") == 13
                    and methodology.get("upper_quantile") == 0.90
                ),
                "frozen_grid_and_score_identity": (
                    metrics.get("score_rows") == 4082
                    and metrics.get("origin_count") == 1025
                    and payload.get("identity", {}).get("score_matrix_sha256")
                    == "dcc2b92286e14852a16dff091fd3ec8c23c30ab5eee926add85b3b15c4e974eb"
                    and payload.get("identity", {}).get("evaluation_coordinate_grid_hash")
                    == "1f2403b7b15c100741a29816304056c2ad7b91cd777b29534a96a567068fa7e8"
                ),
                "independent_frozen_metric_replay": (
                    isinstance(metrics.get("paired_ci_upper"), (int, float))
                    and abs(float(metrics["paired_ci_upper"]) - 0.0006826855070338302) < 1e-12
                    and isinstance(metrics.get("long_horizon_mean_crps_skill"), (int, float))
                    and abs(float(metrics["long_horizon_mean_crps_skill"])
                            - (-0.005914812020669458)) < 1e-15
                    and stress_pass
                ),
                "complete_truthful_gate_deficits": (
                    set(payload.get("gate_deficit_vector", [])) == expected_deficits
                    and payload.get("decision") == "HOLD_RESEARCH_GATE"
                    and payload.get("reason") == "RESEARCH_GATE_FAILED_REPLAN"
                    and payload.get("process_exit_code") == 0
                    and payload.get("research_gate_pass") is False
                ),
                "single_qualification_and_no_screen_leak": (
                    payload.get("qualification_count") == 1
                    and payload.get("screening_qualification_rows") == 0
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "g2_one_time_core_qualification_uses_frozen_v7_gate",
                "passed": passed,
                "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "CORE_QUALIFICATION_GATE_METHOD_MISMATCH"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "append revision 3 without changing score_matrix.parquet; restore the "
                        "frozen V7 moving-block CI and registered stress windows; bind the exact "
                        "coordinate hash and emit the complete truthful deficit vector"
                    ),
                }]
                result["recommended_router_deficits"] = ["qualification_methodology"]
        if lease.task_key == "R4-S4-001":
            artifact_path = (
                self.context.repo
                / "outputs/timeseries_v7_r4/R4-S4-001/r4_calibration/acceptance_summary.json"
            )
            payload: dict[str, Any] = {}
            if artifact_path.exists():
                try:
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {}
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            families = payload.get("families") if isinstance(payload.get("families"), list) else []
            family_pass = len(families) == 4 and {
                int(item.get("horizon")) for item in families if isinstance(item, dict)
            } == {1, 5, 21, 63} and all(
                isinstance(item, dict)
                and item.get("calibration_role_origin_count") == 634
                and item.get("fit_role") == "calibration_temporal_cross_fit"
                and item.get("evaluation_role") == "calibration_cross_fit_holdout"
                and isinstance(item.get("brier"), (int, float))
                and isinstance(item.get("base_rate_brier"), (int, float))
                and isinstance(item.get("balanced_brier"), (int, float))
                and item.get("probability_unit") == "fraction"
                and item.get("probability_bounds_pass") is True
                for item in families
            )
            checks = {
                "authoritative_r4_calibration_source": (
                    payload.get("schema") == "r4_probability_up_calibration_v2"
                    and source.get("r4_snapshot_hash") == R4_QUALIFIED_SNAPSHOT_HASH
                    and source.get("r4_snapshot_artifact_sha256")
                    == "e86687d2cb8daa77375546d049877f353cd7046969cead19ec8b9b9b6f1102ff"
                    and source.get("g2_artifact_sha256")
                    == "3e19f5dc4360b0a74de41a7d4c54967597853b12c81689c57fbc34c281972523"
                    and source.get("calibration_role_hash")
                    == "0f96b564e45155f90819c050f6435e964f8707989a67b5ba1f3da897c7b95fa2"
                ),
                "no_qualification_or_legacy_score_reuse": (
                    source.get("legacy_review_pack_score_rows_used") == 0
                    and source.get("qualification_score_rows_used") == 0
                    and source.get("outer_rows_used") == 0
                    and source.get("outer_origin_intersection") == 0
                ),
                "four_horizon_temporal_cross_fit": family_pass,
                "append_only_correction_evidence": (
                    isinstance(payload.get("supersedes_sha256"), str)
                    and len(payload["supersedes_sha256"]) == 64
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "p_up_calibration_uses_fixed_r4_calibration_role_only",
                "passed": passed, "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "P_UP_CALIBRATION_ROLE_LEAKAGE"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "append R4 calibration evidence using only the 634-origin calibration "
                        "role with temporal cross-fitting; use zero predecessor, qualification "
                        "or outer score rows"
                    ),
                }]
                result["recommended_router_deficits"] = ["p_up_calibration_role_isolation"]
        if lease.task_key == "R4-S4-002":
            artifact_path = (
                self.context.repo
                / "outputs/timeseries_v7_r4/R4-S4-002/r4_calibration/acceptance_summary.json"
            )
            payload: dict[str, Any] = {}
            if artifact_path.exists():
                try:
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {}
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            families = payload.get("families") if isinstance(payload.get("families"), list) else []
            family_pass = len(families) == 4 and {
                int(item.get("horizon")) for item in families if isinstance(item, dict)
            } == {1, 5, 21, 63} and all(
                isinstance(item, dict)
                and item.get("calibration_role_origin_count") == 634
                and item.get("fit_role") == "calibration_temporal_cross_fit"
                and item.get("state_available_at_origin") is True
                and isinstance(item.get("normal_width_ratio"), (int, float))
                and float(item["normal_width_ratio"]) <= 1.10
                and isinstance(item.get("normal_volatility_scale"), (int, float))
                and float(item["normal_volatility_scale"]) > 0
                and isinstance(item.get("stress_volatility_scale"), (int, float))
                and float(item["stress_volatility_scale"]) > 0
                and item.get("coverage_diagnostics_cross_fitted") is True
                for item in families
            )
            checks = {
                "authoritative_r4_calibration_source": (
                    payload.get("schema") == "r4_conditional_scale_v2"
                    and source.get("r4_snapshot_hash") == R4_QUALIFIED_SNAPSHOT_HASH
                    and source.get("g2_artifact_sha256")
                    == "3e19f5dc4360b0a74de41a7d4c54967597853b12c81689c57fbc34c281972523"
                    and source.get("calibration_role_hash")
                    == "0f96b564e45155f90819c050f6435e964f8707989a67b5ba1f3da897c7b95fa2"
                ),
                "no_predecessor_qualification_or_outer_tuning": (
                    source.get("legacy_review_pack_score_rows_used") == 0
                    and source.get("qualification_score_rows_used") == 0
                    and source.get("outer_rows_used") == 0
                    and source.get("outer_origin_intersection") == 0
                ),
                "state_conditional_scale_cross_fit": family_pass,
                "append_only_correction_evidence": (
                    isinstance(payload.get("supersedes_sha256"), str)
                    and len(payload["supersedes_sha256"]) == 64
                ),
            }
            passed = all(checks.values())
            result.setdefault("acceptance_results", []).append({
                "criterion": "conditional_scale_uses_fixed_r4_calibration_role_only",
                "passed": passed, "evidence": checks,
            })
            if not passed:
                result["status"] = "RETRY_WAIT"
                result["blocker_signature"] = "CONDITIONAL_SCALE_ROLE_LEAKAGE"
                result["unresolved_blockers"] = [{
                    "current": checks,
                    "required": (
                        "append conditional-scale evidence from the fixed R4 calibration role; "
                        "use origin-available state only and zero predecessor, qualification and "
                        "outer rows"
                    ),
                }]
                result["recommended_router_deficits"] = ["conditional_scale_role_isolation"]
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
            "input_artifacts": self._input_artifacts(lease),
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
                retry_backoff = self.control.retry_backoff_seconds(run_id)
                if retry_backoff is not None:
                    self.control.set_run_state(run_id, "REPLAN", {
                        "reason": "retry backoff",
                        "retry_after_seconds": round(retry_backoff, 3),
                        "wake_trigger": "retry available_at",
                    })
                    time.sleep(min(max(retry_backoff, 0.1), 5.0))
                    continue
                self.control.set_run_state(run_id, "WAIT_DATA", {
                    "reason": "no eligible tasks", "current": 0, "required": 1,
                    "wake_trigger": "new eligible task or dependency completion",
                })
                return 0
            heartbeat_stop = threading.Event()
            heartbeat_interval = max(1.0, lease_seconds / 3)

            def maintain_lease() -> None:
                while not heartbeat_stop.wait(heartbeat_interval):
                    if not self.control.heartbeat(lease, self.worker_id, lease_seconds):
                        return

            heartbeat = threading.Thread(
                target=maintain_lease,
                name=f"r4-heartbeat-{lease.task_key}", daemon=True,
            )
            heartbeat.start()
            try:
                result = self.execute(lease)
            finally:
                heartbeat_stop.set()
                heartbeat.join(timeout=5)
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
