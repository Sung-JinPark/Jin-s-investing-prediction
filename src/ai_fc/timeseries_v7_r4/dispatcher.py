"""Isolated, single-task Codex child dispatcher.

The dispatcher is implemented for the primary authorized session.  Execution
remains opt-in via ``R4_ALLOW_CODEX_CHILD=1``; the supervisor never silently
widens permissions or forwards provider credentials.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .integrity import (canonical_json, protected_manifest, sanitized_environment,
                        scan_secret_bytes, sha256_bytes, sha256_file,
                        validate_child_result)


@dataclass(frozen=True)
class DispatchResult:
    return_code: int
    command: list[str]
    stdout_sha256: str
    stderr_sha256: str
    result: dict[str, Any] | None
    worktree: Path
    branch: str
    commit_sha: str | None
    changed_paths: tuple[str, ...]


DEFAULT_ALLOWED_PATHS = (
    "src/ai_fc/timeseries_v7_r4/**",
    "src/tests/timeseries_v7_r4/**",
    "migrations/timeseries_v7_r4/**",
    "data/timeseries_v7_r4/contracts/**",
    "data/timeseries_v7_r4/generated/**",
    "data/timeseries_v7_r4/snapshots/**",
    "outputs/timeseries_v7_r4/**",
    "docs/timeseries_v7_r4/**",
    "tools/ralph_v7_r4.py",
    "tools/*v7_r4*.py",
)


class CodexDispatcher:
    def __init__(self, *, repo: Path, output_root: Path,
                 central_worktree_root: Path | None = None):
        self.repo = repo
        self.output_root = output_root
        self.central_worktree_root = central_worktree_root or Path(
            os.getenv("R4_CENTRAL_WORKTREE_ROOT", r"C:\workspace\ai-investing\worktrees\active"))

    @staticmethod
    def executable() -> str:
        candidate = shutil.which("codex.cmd" if os.name == "nt" else "codex")
        if not candidate:
            raise FileNotFoundError("Codex CLI executable unavailable")
        return candidate

    @staticmethod
    def contract_ready() -> bool:
        try:
            executable = CodexDispatcher.executable()
            probe = subprocess.run([executable, "exec", "--help"], capture_output=True, text=True)
        except (FileNotFoundError, PermissionError):
            return False
        required = ("--ephemeral", "--sandbox", "--output-last-message")
        return probe.returncode == 0 and all(item in probe.stdout for item in required)

    def _worktree_path(self, task_key: str, attempt_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "-", f"r4-{task_key}-{attempt_id}")[:100]
        return self.central_worktree_root / safe

    @staticmethod
    def _changed_paths(worktree: Path) -> tuple[str, ...]:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"], cwd=worktree,
            capture_output=True,
        )
        if completed.returncode:
            raise RuntimeError("unable to inspect isolated worktree")
        paths: set[str] = set()
        records = completed.stdout.decode("utf-8", errors="strict").split("\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 4:
                raise RuntimeError(f"malformed git status record: {record!r}")
            status = record[:2]
            path = record[3:].replace("\\", "/")
            if "R" in status or "C" in status:
                if index >= len(records) or not records[index]:
                    raise RuntimeError("rename/copy status lacks destination")
                path = records[index].replace("\\", "/")
                index += 1
            paths.add(path)
        return tuple(sorted(paths))

    @staticmethod
    def _path_allowed(path: str, patterns: list[str]) -> bool:
        normalized = path.replace("\\", "/")
        return any(fnmatchcase(normalized, pattern) for pattern in patterns)

    @staticmethod
    def _build_prompt(envelope: dict[str, Any]) -> str:
        identity = {
            field: envelope[field]
            for field in ("run_id", "cycle_id", "task_key", "attempt_id")
        }
        replan = envelope.get("execution_replan_history") or []
        required_changed_paths = sorted({
            str(item.get("evidence", {}).get("required_changed_path"))
            for item in replan
            if isinstance(item, dict)
            and item.get("evidence", {}).get("required_changed_path")
        })
        verification_instruction = ""
        if required_changed_paths:
            verification_instruction = (
                " This retry has preserved implementation evidence. Independently verify it and "
                "write and commit an auditable verification receipt at each required path: "
                + ", ".join(required_changed_paths)
                + ". A successful verification-only retry therefore still has a real changed path."
            )
        qualification_instruction = ""
        if envelope.get("task_key") == "R4-M3-008":
            qualification_instruction = (
                " This is the one-time frozen core qualification. Emit a compact summary plus a "
                "row-level, independently recomputable score matrix for all 4,082 coordinates on "
                "the unchanged 1,025-origin weekly grid. Bind the exact E0 comparator, R4 snapshot, "
                "G1 and G2 artifact hashes. Record qualification_count=1 and prove that screening "
                "used zero qualification rows before this task. Recompute every frozen Gate without "
                "changing thresholds: long 21/63 CRPS skill, each long skill, dependence-aware CI, "
                "80% and 50% coverage, balanced direction, P(up) Brier, extreme-Q4 coverage, "
                "catastrophic underperformance, and historical-stress qualification. Emit the "
                "complete machine-readable deficit vector. A research Gate failure is valid evidence: "
                "report HOLD_RESEARCH_GATE/RESEARCH_GATE_FAILED_REPLAN with process exit semantics 0, "
                "never alter scores or claim PASS, while the task itself may succeed only if the "
                "qualification evidence is complete and reproducible."
            )
        return (
            "Execute exactly one task from the attached JSON envelope. Do not start another task. "
            "Respect allowed_paths and protected manifest. Write a failing test first, implement the "
            "smallest coherent patch, and run targeted tests with the frozen Python executable in "
            "the envelope. PostgreSQL is the authoritative durable store; SQLite may appear only in "
            "disposable unit-test fixtures and must not back production R4 ingestion, control, model, "
            "or Gate state. Preserve point-in-time available_at semantics and all frozen research "
            "coordinates. For materializer, trainer, or evaluator tasks, execute acceptance against "
            "the real evidence pack declared in input_artifacts; synthetic fixtures are tests only "
            "and cannot prove run acceptance. A credential-free authoritative PIT export in "
            "input_artifacts is prepared by the Supervisor specifically so the child must not ask "
            "for or depend on a database URL. Launch each long-running acceptance command exactly "
            "once and poll the returned process/session until completion; never start a duplicate "
            "while an earlier process with the same command is alive. Persist content-addressed "
            "per-family checkpoints so a retry resumes completed evidence instead of refitting it. "
            "Do not commit or run git worktree commands. Return only a JSON object matching the R4 "
            "result contract. The final JSON must echo these envelope identity fields exactly: "
            + canonical_json(identity).decode("utf-8")
            + ". The tests field must be a JSON array, never an object."
            + verification_instruction
            + qualification_instruction
            + "\n\n"
            + canonical_json(envelope).decode("utf-8")
        )

    def cleanup(self, dispatched: DispatchResult, *, merged: bool) -> None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(dispatched.worktree)],
            cwd=self.repo, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "branch", "-d" if merged else "-D", dispatched.branch],
            cwd=self.repo, capture_output=True, text=True,
        )

    def dispatch(self, envelope: dict[str, Any]) -> DispatchResult:
        if os.getenv("R4_ALLOW_CODEX_CHILD") != "1":
            raise PermissionError("R4_ALLOW_CODEX_CHILD=1 is required")
        worktree = self._worktree_path(envelope["task_key"], envelope["attempt_id"])
        if worktree.exists():
            raise FileExistsError(worktree)
        branch = "codex/" + worktree.name.lower()
        create = subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"],
                                cwd=self.repo, capture_output=True, text=True)
        if create.returncode:
            raise RuntimeError(f"isolated worktree creation failed: {create.stderr}")
        task_dir = self.output_root / "dispatch" / envelope["attempt_id"]
        task_dir.mkdir(parents=True, exist_ok=False)
        envelope_path = task_dir / "task_envelope.json"
        envelope_path.write_bytes(canonical_json(envelope) + b"\n")
        last_message = task_dir / "last_message.json"
        prompt = self._build_prompt(envelope)
        command = [self.executable(), "exec", "--ephemeral", "--ignore-user-config",
                   "--sandbox", "danger-full-access", "--json", "-C", str(worktree),
                   "-o", str(last_message), "-"]
        completed = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   env=sanitized_environment())
        parsed: dict[str, Any] | None = None
        if completed.returncode == 0 and last_message.exists():
            try:
                value = json.loads(last_message.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    parsed = value
            except json.JSONDecodeError:
                parsed = None
        changed = self._changed_paths(worktree)
        allowed = list(envelope.get("allowed_paths") or DEFAULT_ALLOWED_PATHS)
        violations = [path for path in changed if not self._path_allowed(path, allowed)]
        commit_sha: str | None = None
        validation_return_code = completed.returncode
        if parsed is not None:
            identity = {
                field: parsed.get(field) == envelope.get(field)
                for field in ("run_id", "cycle_id", "task_key", "attempt_id")
            }
            before_hash = envelope["protected_manifest_sha256"]
            after_hash = protected_manifest(worktree)["manifest_sha256"]
            secret_findings: list[str] = []
            for relative in changed:
                path = worktree / relative
                if path.is_file():
                    secret_findings.extend(scan_secret_bytes(path.read_bytes()))
            parsed["changed_paths"] = list(changed)
            parsed["protected_manifest_before"] = before_hash
            parsed["protected_manifest_after"] = after_hash
            parsed["protected_non_mutation"] = before_hash == after_hash
            parsed["secret_scan_pass"] = not secret_findings
            parsed.setdefault("commands", [])
            parsed.setdefault("tests", [])
            parsed.setdefault("acceptance_results", [])
            parsed["acceptance_results"].append({
                "criterion": "dispatcher_identity_and_allowlist",
                "passed": all(identity.values()) and not violations,
                "evidence": {"identity": identity, "violations": violations},
            })
            if parsed.get("status") == "SUCCEEDED" and not changed:
                violations.append("successful implementation produced no changed paths")
            test_command = [
                envelope.get("frozen_python") or sys.executable,
                "-m", "pytest", "-q", "src/tests/timeseries_v7_r4",
            ]
            tests = subprocess.run(
                test_command, cwd=worktree, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env=sanitized_environment(),
            )
            parsed["commands"].append({
                "command": " ".join(test_command),
                "return_code": tests.returncode,
                "stdout_sha256": sha256_bytes(tests.stdout.encode("utf-8")),
                "stderr_sha256": sha256_bytes(tests.stderr.encode("utf-8")),
            })
            parsed["tests"].append({
                "name": "supervisor_independent_r4_targeted_suite",
                "passed": tests.returncode == 0,
                "evidence_path": "src/tests/timeseries_v7_r4",
                "sha256": sha256_bytes((tests.stdout + tests.stderr).encode("utf-8")),
            })
            errors = validate_child_result(parsed, require_evidence=True)
            if violations:
                errors.append("allowlist_violation")
            if errors:
                parsed["status"] = "BLOCKED" if violations or secret_findings else "RETRY_WAIT"
                parsed["blocker_signature"] = "DISPATCH_VALIDATION:" + ",".join(sorted(set(errors)))
                parsed["supervisor_should_continue"] = parsed["status"] == "RETRY_WAIT"
                validation_return_code = 3
            elif parsed.get("status") == "SUCCEEDED":
                check = subprocess.run(
                    ["git", "diff", "--check"], cwd=worktree,
                    capture_output=True, text=True,
                )
                if check.returncode:
                    parsed["status"] = "RETRY_WAIT"
                    parsed["blocker_signature"] = "GIT_DIFF_CHECK_FAILED"
                    validation_return_code = 3
                else:
                    subprocess.run(["git", "add", "--", *changed], cwd=worktree, check=True)
                    commit = subprocess.run(
                        ["git", "commit", "-m", f"feat: complete {envelope['task_key']}"],
                        cwd=worktree, capture_output=True, text=True,
                        env=sanitized_environment(),
                    )
                    if commit.returncode:
                        parsed["status"] = "RETRY_WAIT"
                        parsed["blocker_signature"] = "ISOLATED_COMMIT_FAILED"
                        validation_return_code = 3
                    else:
                        commit_sha = subprocess.run(
                            ["git", "rev-parse", "HEAD"], cwd=worktree,
                            capture_output=True, text=True, check=True,
                        ).stdout.strip()
                        parsed["integration"] = {
                            "branch": branch,
                            "commit_sha": commit_sha,
                            "changed_paths": list(changed),
                        }
        return DispatchResult(
            validation_return_code, command,
            sha256_bytes(completed.stdout.encode("utf-8")),
            sha256_bytes(completed.stderr.encode("utf-8")), parsed, worktree,
            branch, commit_sha, changed,
        )
