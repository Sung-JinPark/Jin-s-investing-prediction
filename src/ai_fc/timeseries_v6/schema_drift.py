"""Deterministic response schema fingerprints and quarantine decisions."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any


class SchemaDriftError(RuntimeError):
    pass


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        distinct = {_canonical(_shape(item)).decode() for item in value[:100]}
        return {"array_item_shapes": sorted(distinct)}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def schema_fingerprint(body: bytes, media_type: str) -> str:
    lowered = media_type.lower()
    if "json" in lowered:
        shape = _shape(json.loads(body))
    elif "csv" in lowered or "text/plain" in lowered:
        reader = csv.reader(io.StringIO(body.decode("utf-8-sig")))
        header = next(reader, None)
        if not header:
            raise SchemaDriftError("CSV has no header")
        shape = {"csv_header": header}
    else:
        shape = {"media_type": lowered, "prefix_sha256": hashlib.sha256(body[:65536]).hexdigest()}
    return hashlib.sha256(_canonical(shape)).hexdigest()


@dataclass(frozen=True)
class SchemaDecision:
    status: str
    fingerprint_sha256: str
    reason_code: str


def decide_schema(body: bytes, media_type: str, *, approved_fingerprints: set[str]) -> SchemaDecision:
    fingerprint = schema_fingerprint(body, media_type)
    if fingerprint not in approved_fingerprints:
        return SchemaDecision("schema_quarantine", fingerprint, "unapproved_schema_fingerprint")
    return SchemaDecision("approved", fingerprint, "schema_fingerprint_registered")
