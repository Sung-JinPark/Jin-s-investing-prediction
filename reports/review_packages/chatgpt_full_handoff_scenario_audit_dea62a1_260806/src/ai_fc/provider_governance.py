"""Human approval boundary for changing the official LLM forecast producer."""

from __future__ import annotations

import csv
from pathlib import Path


APPROVAL_HEADER = [
    "approved_at", "action", "from_value", "to_value", "scope",
    "status", "reviewer", "reason", "commit",
]


class ProviderApprovalError(PermissionError):
    pass


def read_approvals(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != APPROVAL_HEADER:
            raise ValueError(f"approval ledger header mismatch: {reader.fieldnames}")
        return list(reader)


def assert_official_provider_allowed(root: Path, provider: str, snapshot: str = "") -> None:
    """Allow the established producer, otherwise require an exact approved snapshot."""
    if provider == "anthropic":
        return
    if provider != "openai":
        raise ProviderApprovalError(f"unsupported official LLM provider: {provider}")
    if not snapshot:
        raise ProviderApprovalError("OpenAI official producer requires an explicit model identity")
    target = f"openai:{snapshot}"
    rows = read_approvals(root / "calibration" / "approvals.csv")
    approved = any(
        row.get("action") == "official_llm_provider_change"
        and row.get("from_value") == "anthropic"
        and row.get("to_value") == target
        and row.get("scope") == "official_llm_provider"
        and row.get("status") == "approved"
        and bool(row.get("reviewer"))
        and bool(row.get("reason"))
        for row in rows
    )
    if not approved:
        raise ProviderApprovalError(
            "official provider switch blocked: append an explicit approved row for "
            f"{target} to calibration/approvals.csv"
        )
