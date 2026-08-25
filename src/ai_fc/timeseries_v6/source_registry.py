"""Frozen 37-source V6 registry and contract reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml


class SourceRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    provider: str
    authority_class: str
    adapter_status: str
    data_grade: str
    cadence: str
    availability_policy_version: str
    redistribution: str
    source_uri_template: str


def load_source_registry(path: Path) -> dict[str, SourceDefinition]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SourceRegistryError("source registry rows are required")
    result: dict[str, SourceDefinition] = {}
    for raw in rows:
        row = SourceDefinition(**raw)
        if row.source_id in result:
            raise SourceRegistryError(f"duplicate source id: {row.source_id}")
        if row.authority_class not in {"official", "licensed", "academic", "research_reference"}:
            raise SourceRegistryError(f"invalid authority class: {row.source_id}")
        if row.adapter_status not in {"implemented", "blocked_no_history", "forward_capture", "licensed_unavailable", "retired"}:
            raise SourceRegistryError(f"invalid adapter status: {row.source_id}")
        if row.data_grade not in {"native_pit", "reconstructed_official_archive", "captured_forward", "licensed_reference_only", "quarantined"}:
            raise SourceRegistryError(f"invalid data grade: {row.source_id}")
        lowered = row.source_uri_template.lower()
        if any(f"{name}=" in lowered for name in ("api_key", "apikey", "token", "password", "secret")):
            raise SourceRegistryError(f"credential-bearing URI: {row.source_id}")
        parsed = urlsplit(row.source_uri_template)
        if parsed.scheme not in {"https", "captured-forward"} or parsed.username or parsed.password:
            raise SourceRegistryError(f"unsafe source URI: {row.source_id}")
        if row.adapter_status == "forward_capture" and row.data_grade != "captured_forward":
            raise SourceRegistryError(f"forward source has invalid grade: {row.source_id}")
        result[row.source_id] = row
    return result


def reconcile_registry_contract(registry: dict[str, SourceDefinition], contract_path: Path) -> dict[str, Any]:
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    expected = contract["source_registry_contract"]
    expected_ids = set(expected["canonical_ids"])
    actual_ids = set(registry)
    contract_only = sorted(expected_ids - actual_ids)
    registry_only = sorted(actual_ids - expected_ids)
    passed = (
        len(registry) == expected["expected_source_count"]
        and not contract_only
        and not registry_only
    )
    return {
        "pass": passed,
        "expected_count": expected["expected_source_count"],
        "actual_count": len(registry),
        "contract_only": contract_only,
        "registry_only": registry_only,
    }
