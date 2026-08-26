"""Credential-free exports of authoritative R4 PIT snapshots for child workers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .integrity import canonical_json, sha256_bytes


def export_runtime_snapshot(
    database_url: str, *, snapshot_hash: str, output: Path,
) -> dict[str, Any]:
    """Export one immutable PostgreSQL snapshot without connection credentials.

    The parent Supervisor owns the database connection.  Isolated child workers
    receive only this content-addressed JSON export, so secret isolation does not
    become an execution-permission blocker for trainer and evaluator tasks.
    """
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("authoritative PostgreSQL database URL is required")
    if len(snapshot_hash) != 64 or any(
        character not in "0123456789abcdef" for character in snapshot_hash
    ):
        raise ValueError("snapshot_hash must be a lowercase SHA-256 hash")

    import psycopg

    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT snapshot_hash,as_of,calendar_version,payload "
            "FROM timeseries_v7_r4.pit_snapshots WHERE snapshot_hash=%s",
            (snapshot_hash,),
        ).fetchone()
    if row is None:
        raise RuntimeError("authoritative R4 PIT snapshot is unavailable")
    payload = row[3]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise RuntimeError("authoritative R4 PIT snapshot payload is invalid")
    feature_rows = payload.get("feature_rows")
    labels = payload.get("labels")
    if not isinstance(feature_rows, list) or not isinstance(labels, list):
        raise RuntimeError("authoritative R4 PIT snapshot lacks rows or labels")

    export = {
        "schema": "r4_credential_free_pit_export_v1",
        "source_store": "authoritative_postgresql",
        "snapshot_hash": row[0],
        "as_of": row[1].isoformat(),
        "calendar_version": row[2],
        "feature_rows": feature_rows,
        "labels": labels,
    }
    encoded = canonical_json(export) + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(output)
    return {
        "path": str(output.resolve()),
        "sha256": sha256_bytes(encoded),
        "snapshot_hash": snapshot_hash,
        "feature_rows": len(feature_rows),
        "label_rows": len(labels),
        "credential_fields": 0,
    }
