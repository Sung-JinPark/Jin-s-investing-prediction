"""Raw-first receipts, terminal parse outcomes and bitemporal observations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .identifiers import content_hash, stable_id


DataGrade = Literal["native_pit", "reconstructed_market_archive", "reconstructed_official_archive", "captured_forward"]
TerminalOutcome = Literal["new_facts", "revised_facts", "unchanged_facts", "no_fact_expected", "rejected", "quarantined", "parse_failed", "schema_drift"]


class RawReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_id: str
    run_id: str
    source_id: str
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_uri: str
    source_uri: str
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime
    http_status: int
    content_type: str
    schema_fingerprint: str | None = None
    etag: str | None = None
    last_modified: str | None = None

    @field_validator("retrieved_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None: raise ValueError("retrieved_at timezone required")
        return value


class ParsedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    series_id: str
    observation_time: datetime
    value: float
    unit: str
    available_at: datetime
    data_grade: DataGrade
    dimensions: dict[str, str] = Field(default_factory=dict)
    vintage_start: datetime | None = None
    vintage_end: datetime | None = None
    normalization_rule_version: str = "v1"
    parser_semantic_version: str = "v1"

    @field_validator("observation_time", "available_at")
    @classmethod
    def timestamp_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None: raise ValueError("PIT timestamps require timezone")
        return value


class ObservationVersion(ParsedObservation):
    observation_id: str
    observation_key: str
    source_id: str
    receipt_id: str
    raw_sha256: str
    revision_seq: int = Field(ge=1)
    supersedes: str | None = None
    created_at: datetime


class ReceiptParseOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome_id: str
    receipt_id: str
    outcome: TerminalOutcome
    parser_version: str
    fact_count: int = Field(ge=0)
    reason: str | None = None
    created_at: datetime


def observation_key(value: ParsedObservation) -> str:
    return stable_id("obskey", {"series_id": value.series_id, "observation_time": value.observation_time, "dimensions": value.dimensions})


def semantic_payload(value: ParsedObservation) -> dict[str, Any]:
    return {
        "value": value.value, "unit": value.unit, "available_at": value.available_at,
        "data_grade": value.data_grade, "dimensions": value.dimensions,
        "normalization_rule_version": value.normalization_rule_version,
        "parser_semantic_version": value.parser_semantic_version,
    }


def build_versions(
    *, source_id: str, receipt: RawReceipt, parsed: list[ParsedObservation],
    prior_rows: list[dict[str, Any]], created_at: datetime | None = None,
) -> tuple[list[ObservationVersion], list[dict[str, str]], TerminalOutcome]:
    now = created_at or datetime.now(timezone.utc)
    prior_by_key: dict[str, list[ObservationVersion]] = {}
    for raw in prior_rows:
        if raw.get("source_id") != source_id:
            continue
        row = ObservationVersion.model_validate(raw)
        prior_by_key.setdefault(row.observation_key, []).append(row)
    versions: list[ObservationVersion] = []; links: list[dict[str, str]] = []; revised = False
    for item in parsed:
        key = observation_key(item); history = sorted(prior_by_key.get(key, []), key=lambda row: row.revision_seq); prior = history[-1] if history else None
        if prior is not None and semantic_payload(prior) == semantic_payload(item):
            links.append({"link_id": stable_id("link", [receipt.receipt_id, prior.observation_id, "unchanged"]), "receipt_id": receipt.receipt_id, "observation_id": prior.observation_id, "relation": "unchanged"})
            continue
        revision = 1 if prior is None else prior.revision_seq + 1; revised = revised or prior is not None
        core = {**item.model_dump(mode="json"), "source_id": source_id, "receipt_id": receipt.receipt_id, "raw_sha256": receipt.raw_sha256, "observation_key": key, "revision_seq": revision, "supersedes": None if prior is None else prior.observation_id, "created_at": now}
        row = ObservationVersion(observation_id=stable_id("obs", core), **core); versions.append(row)
        links.append({"link_id": stable_id("link", [receipt.receipt_id, row.observation_id, "new_or_revised"]), "receipt_id": receipt.receipt_id, "observation_id": row.observation_id, "relation": "revised" if prior else "new"})
        prior_by_key.setdefault(key, []).append(row)
    if versions: outcome: TerminalOutcome = "revised_facts" if revised else "new_facts"
    elif parsed: outcome = "unchanged_facts"
    else: outcome = "no_fact_expected"
    return versions, links, outcome


def make_outcome(receipt_id: str, outcome: TerminalOutcome, *, parser_version: str, fact_count: int, reason: str | None = None, created_at: datetime | None = None) -> ReceiptParseOutcome:
    now = created_at or datetime.now(timezone.utc); core = {"receipt_id": receipt_id, "outcome": outcome, "parser_version": parser_version, "fact_count": fact_count, "reason": reason, "created_at": now}
    return ReceiptParseOutcome(outcome_id=stable_id("outcome", core), **core)


def verify_lineage(receipts: list[dict[str, Any]], outcomes: list[dict[str, Any]], observations: list[dict[str, Any]], links: list[dict[str, Any]]) -> dict[str, Any]:
    receipt_ids = {RawReceipt.model_validate(row).receipt_id for row in receipts}; outcome_rows = [ReceiptParseOutcome.model_validate(row) for row in outcomes]
    terminal_by_receipt = {row.receipt_id for row in outcome_rows}; observation_rows = [ObservationVersion.model_validate(row) for row in observations]
    observation_ids = {row.observation_id for row in observation_rows}; errors: list[str] = []
    linked_observation_ids = {str(row.get("observation_id")) for row in links}
    errors += [f"receipt_without_terminal:{value}" for value in sorted(receipt_ids - terminal_by_receipt)]
    errors += [f"orphan_outcome:{row.receipt_id}" for row in outcome_rows if row.receipt_id not in receipt_ids]
    errors += [f"orphan_observation:{row.observation_id}" for row in observation_rows if row.receipt_id not in receipt_ids]
    errors += [f"orphan_link:{row.get('link_id')}" for row in links if row.get("receipt_id") not in receipt_ids or row.get("observation_id") not in observation_ids]
    errors += [f"observation_without_receipt_link:{value}" for value in sorted(observation_ids - linked_observation_ids)]
    for row in observation_rows:
        if row.supersedes and row.supersedes not in observation_ids: errors.append(f"missing_supersedes:{row.observation_id}")
    return {"ok": not errors, "errors": errors, "receipt_count": len(receipts), "terminal_outcome_coverage": 1.0 if not receipts else len(receipt_ids & terminal_by_receipt) / len(receipt_ids), "observation_linkage": 1.0 if not observations else len(observation_ids & linked_observation_ids) / len(observation_ids), "observation_count": len(observations), "link_count": len(links)}
