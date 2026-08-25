"""Fail-closed source schema registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaDecision:
    source_id: str
    expected: str | None
    observed: str
    state: str
    parse_allowed: bool


def decide_schema(source_id: str, observed: str, expected: str | None) -> SchemaDecision:
    if expected is None:
        return SchemaDecision(source_id, None, observed, "fixture_review_required", False)
    if observed != expected:
        return SchemaDecision(source_id, expected, observed, "schema_quarantine", False)
    return SchemaDecision(source_id, expected, observed, "accepted", True)
