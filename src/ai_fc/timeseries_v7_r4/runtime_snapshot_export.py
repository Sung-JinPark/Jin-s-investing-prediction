"""Credential-free exports of authoritative R4 PIT snapshots for child workers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .integrity import canonical_json, sha256_bytes


FIVE_ROLE_ORDER = ("train", "selection", "stacking", "calibration", "outer")
FIVE_ROLE_RETAINED_COUNTS = {
    "train": 4458,
    "selection": 634,
    "stacking": 634,
    "calibration": 634,
    "outer": 765,
}
FIVE_ROLE_PURGE_SESSIONS = 63
FIVE_ROLE_EMBARGO_SESSIONS = 5


def _five_role_plan(feature_rows: list[dict[str, Any]],
                    labels: list[dict[str, Any]]) -> dict[str, Any] | None:
    horizons: dict[str, set[int]] = {}
    for label in labels:
        origin = str(label.get("origin_session", ""))
        horizon = int(label.get("horizon_sessions", 0))
        if origin and horizon in (1, 5, 21, 63):
            horizons.setdefault(origin, set()).add(horizon)
    origins = sorted({str(row.get("origin_session", "")) for row in feature_rows
                      if str(row.get("origin_session", ""))
                      and horizons.get(str(row.get("origin_session", ""))) == {1, 5, 21, 63}})
    retained = sum(FIVE_ROLE_RETAINED_COUNTS.values())
    minimum_gap = FIVE_ROLE_PURGE_SESSIONS + FIVE_ROLE_EMBARGO_SESSIONS
    if len(origins) < retained + minimum_gap * 4:
        return None
    excluded_total = len(origins) - retained
    gap_base, gap_remainder = divmod(excluded_total, 4)
    gaps = [gap_base + int(index < gap_remainder) for index in range(4)]
    if min(gaps) < minimum_gap:
        raise RuntimeError("qualified snapshot cannot support the frozen five-role gaps")

    role_origins: dict[str, list[str]] = {}
    excluded_origins: list[str] = []
    cursor = 0
    for index, role in enumerate(FIVE_ROLE_ORDER):
        count = FIVE_ROLE_RETAINED_COUNTS[role]
        role_origins[role] = origins[cursor:cursor + count]
        cursor += count
        if index < len(gaps):
            excluded_origins.extend(origins[cursor:cursor + gaps[index]])
            cursor += gaps[index]
    if cursor != len(origins) or any(not role_origins[role] for role in FIVE_ROLE_ORDER):
        raise RuntimeError("frozen five-role partition did not consume the complete origin set")
    role_hashes = {
        role: sha256_bytes(canonical_json(role_origins[role])) for role in FIVE_ROLE_ORDER
    }
    plan_core = {
        "schema": "r4_five_role_origin_plan_v1",
        "role_order": list(FIVE_ROLE_ORDER),
        "role_origins": role_origins,
        "role_counts": {role: len(role_origins[role]) for role in FIVE_ROLE_ORDER},
        "role_hashes": role_hashes,
        "excluded_origins": excluded_origins,
        "excluded_count": len(excluded_origins),
        "gap_counts": gaps,
        "purge_sessions": FIVE_ROLE_PURGE_SESSIONS,
        "embargo_sessions": FIVE_ROLE_EMBARGO_SESSIONS,
        "purge_unit": "xnas_sessions",
        "interval_overlap_count": 0,
        "outer_exposed_during_screen": False,
    }
    return {**plan_core, "plan_hash": sha256_bytes(canonical_json(plan_core))}


def export_runtime_snapshot(
    database_url: str, *, snapshot_hash: str, output: Path,
    require_five_role: bool = False,
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

    role_plan = _five_role_plan(feature_rows, labels)
    if require_five_role and role_plan is None:
        raise RuntimeError("authoritative snapshot lacks the frozen five-role population")
    export = {
        "schema": "r4_credential_free_pit_export_v1",
        "source_store": "authoritative_postgresql",
        "snapshot_hash": row[0],
        "as_of": row[1].isoformat(),
        "calendar_version": row[2],
        "feature_rows": feature_rows,
        "labels": labels,
        "five_role_plan": role_plan,
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
        "five_role_plan_hash": role_plan["plan_hash"] if role_plan else None,
        "five_role_counts": role_plan["role_counts"] if role_plan else None,
    }
