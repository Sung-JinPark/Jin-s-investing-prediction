"""Source contracts, raw manifests, and quarantine primitives."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ValueStatus(StrEnum):
    OK = "ok"
    NOT_PUBLISHED = "미산출"
    INSUFFICIENT_SAMPLE = "표본부족"
    STALE = "stale"
    FETCH_FAILED = "수집실패"


class ContractField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    required: bool = True
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None


class SourceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    source_id: str
    description: str
    timezone: str
    calendar_id: str
    cadence: str
    freshness_sla_hours: int = Field(ge=1)
    available_at_rule: str
    revision_policy: str
    missing_statuses: list[ValueStatus]
    fields: list[ContractField]
    quality_checks: list[str]
    fallback: str | None = None

    @model_validator(mode="after")
    def unique_fields(self) -> "SourceContract":
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("contract field names must be unique")
        return self


class ContractViolation(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def load_contract(path: Path) -> SourceContract:
    return SourceContract.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def validate_record(contract: SourceContract, record: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    for field in contract.fields:
        value = record.get(field.name)
        if field.required and value is None:
            reasons.append(f"missing required field: {field.name}")
            continue
        if value is None:
            continue
        if field.type in {"number", "integer"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                reasons.append(f"{field.name} must be {field.type}")
                continue
            if field.type == "integer" and not isinstance(value, int):
                reasons.append(f"{field.name} must be integer")
            if field.minimum is not None and value < field.minimum:
                reasons.append(f"{field.name} below minimum {field.minimum}")
            if field.maximum is not None and value > field.maximum:
                reasons.append(f"{field.name} above maximum {field.maximum}")
        elif field.type == "string" and not isinstance(value, str):
            reasons.append(f"{field.name} must be string")
    if reasons:
        raise ContractViolation(reasons)
    return record


def payload_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def preserve_raw(
    root: Path,
    *,
    source_id: str,
    payload: bytes,
    url: str,
    http_status: int,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Persist an immutable raw blob and append its content-addressed receipt."""
    stamp = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    digest = payload_sha256(payload)
    target = root / "data" / "raw" / source_id / f"{digest}.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(payload)
    receipt = {
        "source_id": source_id,
        "path": target.relative_to(root).as_posix(),
        "bytes": len(payload),
        "sha256": digest,
        "retrieved_at": stamp,
        "url": url,
        "http_status": http_status,
    }
    manifest = root / "data" / "raw" / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    existing = manifest.read_text(encoding="utf-8").splitlines() if manifest.exists() else []
    if not any(json.loads(line).get("sha256") == digest for line in existing if line.strip()):
        with manifest.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    return receipt


def quarantine_record(
    root: Path,
    *,
    source_id: str,
    record: dict[str, Any],
    reasons: list[str],
    retrieved_at: str | None = None,
) -> Path:
    envelope = {
        "source_id": source_id,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reasons": reasons,
        "record": record,
    }
    encoded = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")
    target = root / "data" / "quarantine" / source_id / f"{payload_sha256(encoded)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded + b"\n")
    return target
