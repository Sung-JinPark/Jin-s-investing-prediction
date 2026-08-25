"""Worker capability and secret-isolation policy for V7."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Mapping


SECRET_NAME_RE = re.compile(r"(?:API[_-]?KEY|TOKEN|PASSWORD|SECRET|CREDENTIAL|GH_TOKEN|GITHUB_TOKEN)", re.I)
EXPLICIT_PROVIDER_SECRETS = {
    "FRED_API_KEY", "BLS_API_KEY", "BEA_API_KEY", "EIA_API_KEY", "CME_API_KEY",
    "CBOE_API_KEY", "NASDAQ_DATA_LINK_API_KEY", "GH_TOKEN", "GITHUB_TOKEN",
}
CAPABILITIES = {
    "collector", "materializer", "trainer_cpu", "trainer_gpu", "evaluator",
    "codex_worker", "reviewer",
}
CODE_ROOTS = ("src/", "tools/", "data/contracts/", "migrations/", ".github/")


class SecurityBoundaryError(PermissionError):
    """A worker attempted to cross its capability or secret boundary."""


def sanitized_environment(capability: str, source: Mapping[str, str] | None = None) -> dict[str, str]:
    if capability not in CAPABILITIES:
        raise SecurityBoundaryError(f"unknown capability: {capability}")
    values = dict(source if source is not None else os.environ)
    if capability != "collector":
        for name in list(values):
            if name in EXPLICIT_PROVIDER_SECRETS or SECRET_NAME_RE.search(name):
                values.pop(name, None)
    if capability not in {"reviewer"}:
        values.pop("GH_TOKEN", None)
        values.pop("GITHUB_TOKEN", None)
    values["V7_WORKER_CAPABILITY"] = capability
    return values


def assert_write_paths(capability: str, paths: Iterable[str | Path]) -> None:
    normalized = []
    for path in paths:
        value = Path(path).as_posix()
        normalized.append(value[2:] if value.startswith("./") else value)
    if any(".secrets" in Path(path).parts for path in normalized):
        raise SecurityBoundaryError(".secrets access is prohibited")
    if capability == "collector":
        forbidden = [path for path in normalized if path.startswith(CODE_ROOTS)]
        if forbidden:
            raise SecurityBoundaryError(f"collector cannot modify code: {forbidden}")
    elif capability != "codex_worker" and any(path.startswith(CODE_ROOTS) for path in normalized):
        raise SecurityBoundaryError(f"{capability} cannot modify code")


def secret_name_matches(values: Mapping[str, str]) -> list[str]:
    return sorted(name for name in values if name in EXPLICIT_PROVIDER_SECRETS or SECRET_NAME_RE.search(name))
