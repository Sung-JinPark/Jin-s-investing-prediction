"""Repository identity and deterministic source fingerprints for the read index."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepositoryContext:
    repo_id: str
    branch: str
    head: str
    source_fingerprint: str


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def iter_truth_files(root: Path) -> list[Path]:
    """Return stable, source-of-truth inputs; derived databases/reports are excluded."""
    candidates: list[Path] = []
    fixed = (
        root / "questions" / "registry.yaml",
        root / "calibration" / "ledger.csv",
        root / "calibration" / "benchmark_ledger.csv",
        root / "calibration" / "research_status_overrides.csv",
        root / "calibration" / "corrections.csv",
        root / "calibration" / "approvals.csv",
        root / "calibration" / "provider_shadow_ledger.csv",
        root / "data" / "source_registry.yaml",
    )
    candidates.extend(path for path in fixed if path.exists())
    for base, patterns in (
        (root / "forecasts", ("*.md",)),
        (root / "data" / "ml_history", ("*.jsonl",)),
        (root / "data" / "contracts", ("*.yaml", "*.yml")),
        (root / "data" / "scenarios", ("*.json",)),
    ):
        if not base.exists():
            continue
        for pattern in patterns:
            candidates.extend(base.rglob(pattern))
    return sorted({p.resolve() for p in candidates}, key=lambda p: p.as_posix())


def source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in iter_truth_files(root):
        rel = path.relative_to(root.resolve()).as_posix()
        content = path.read_bytes()
        # Git stores YAML/JSON truth files as text, but Python's Windows text writer
        # can materialize CRLF while Linux Actions checks out LF.  Their semantic
        # content is identical, so hash a canonical newline form.  Immutable
        # forecasts and append-only CSV/JSONL ledgers stay byte-sensitive.
        if path.suffix.lower() in {".json", ".yaml", ".yml"}:
            content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def repository_context(root: Path) -> RepositoryContext:
    top = _git(root, "rev-parse", "--show-toplevel")
    repo_id = hashlib.sha256((top or str(root.resolve())).encode("utf-8")).hexdigest()[:16]
    return RepositoryContext(
        repo_id=repo_id,
        branch=_git(root, "branch", "--show-current") or "detached-or-unversioned",
        head=_git(root, "rev-parse", "HEAD"),
        source_fingerprint=source_fingerprint(root),
    )
