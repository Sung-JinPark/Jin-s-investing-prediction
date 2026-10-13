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
TRENDLINE_SNAPSHOT_ID = re.compile(
    r'"snapshot_id"\s*:\s*"(trendlines-sk-hynix-[0-9a-f]{24})"'
)


def scan(root: Path) -> list[str]:
    findings = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if relative.parts[:2] in (("outputs", "trendlines"), ("outputs", "trendlines_preview")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            # The deterministic SK Hynix snapshot ID contains a public asset slug.
            # Exempt only the complete ID in its JSON field; keys elsewhere still fail.
            public_ids = [match.span(1) for match in TRENDLINE_SNAPSHOT_ID.finditer(line)]
            if any(
                not any(start <= match.start() and match.end() <= end for start, end in public_ids)
                for pattern in SECRET_PATTERNS for match in pattern.finditer(line)
            ):
                findings.append(f"{path.relative_to(root).as_posix()}:{line_no}")
    return findings
