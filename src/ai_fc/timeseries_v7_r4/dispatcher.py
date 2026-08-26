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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .integrity import canonical_json, sanitized_environment, sha256_bytes


@dataclass(frozen=True)
class DispatchResult:
    return_code: int
    command: list[str]
    stdout_sha256: str
    stderr_sha256: str
    result: dict[str, Any] | None
    worktree: Path


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
        prompt = (
            "Execute exactly one task from the attached JSON envelope. Do not start another task. "
            "Respect allowed_paths and protected manifest. Return only a JSON object matching the "
            "R4 result contract.\n\n" + canonical_json(envelope).decode("utf-8")
        )
        command = [self.executable(), "exec", "--ephemeral", "--ignore-user-config",
                   "--sandbox", "workspace-write", "--json", "-C", str(worktree),
                   "-o", str(last_message), "-"]
        completed = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                   env=sanitized_environment())
        parsed: dict[str, Any] | None = None
        if completed.returncode == 0 and last_message.exists():
            try:
                value = json.loads(last_message.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    parsed = value
            except json.JSONDecodeError:
                parsed = None
        return DispatchResult(
            completed.returncode, command,
            sha256_bytes(completed.stdout.encode("utf-8")),
            sha256_bytes(completed.stderr.encode("utf-8")), parsed, worktree,
        )
