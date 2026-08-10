"""Small deterministic secret-pattern gate for tracked source artifacts."""

from __future__ import annotations

import re
from pathlib import Path


SECRET_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![0-9A-Z])"),
    re.compile(r"(?<![A-Za-z0-9])ghp_[A-Za-z0-9]{30,}(?![A-Za-z0-9])"),
)

SCANNED_SUFFIXES = {".py", ".js", ".css", ".html", ".yaml", ".yml", ".json", ".csv", ".toml"}
SKIP_PARTS = {".git", ".venv", ".tmp-pytest", "db", "reports", "codex-forecast-demo"}


def scan(root: Path) -> list[str]:
    findings = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                findings.append(f"{path.relative_to(root).as_posix()}:{line_no}")
    return findings
