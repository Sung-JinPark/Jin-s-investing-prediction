"""Immutable point-in-time dataset snapshots and mature target labels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Iterable, Mapping

from .xnas_sessions import XnasSessionCalendar


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _date(value: date | str, field: str) -> date:
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc
    if not isinstance(parsed, date) or isinstance(parsed, datetime):
        raise ValueError(f"{field} must be a date")
    return parsed


@dataclass(frozen=True, slots=True)
class TargetObservation:
    target_id: str
    origin_session: date | str
    label_end_session: date | str
    value: object
    available_at: datetime


@dataclass(frozen=True, slots=True)
class LabelInterval:
    target_id: str
    origin_session: date
    label_start_session: date
    label_end_session: date
    mature_at: datetime
    horizon_sessions: int
    value: object


@dataclass(frozen=True, slots=True)
class PitSnapshot:
    snapshot_hash: str
    as_of: datetime
    calendar_version: str
    labels: tuple[LabelInterval, ...]
    feature_rows: tuple[Mapping[str, object], ...]


def materialize_pit_snapshot(
    *,
    calendar: XnasSessionCalendar,
    as_of: datetime,
    targets: Iterable[TargetObservation],
    feature_rows: Iterable[Mapping[str, object]],
) -> PitSnapshot:
    """Create a content-addressed PIT view without feature-driven target joins.

    Target maturity is evaluated solely from its own ``available_at``. Feature
    rows are captured independently, so an absent source cannot remove a label.
    """
    instant = _utc(as_of, "as_of")
    sessions = calendar.sessions
    positions = {session.session_date: index for index, session in enumerate(sessions)}
    labels: list[LabelInterval] = []
    seen: set[str] = set()
    for target in targets:
        if not target.target_id or target.target_id in seen:
            raise ValueError("target_id must be present and unique")
        seen.add(target.target_id)
        origin = _date(target.origin_session, "origin_session")
        end = _date(target.label_end_session, "label_end_session")
        if origin not in positions or end not in positions:
            raise ValueError("all label dates must be canonical XNAS sessions")
        origin_index, end_index = positions[origin], positions[end]
        if end_index <= origin_index:
            raise ValueError("label_end_session must follow origin_session")
        mature_at = _utc(target.available_at, "available_at")
        if mature_at > instant:
            continue
        labels.append(
            LabelInterval(
                target_id=target.target_id,
                origin_session=origin,
                label_start_session=sessions[origin_index + 1].session_date,
                label_end_session=end,
                mature_at=mature_at,
                horizon_sessions=end_index - origin_index,
                value=target.value,
            )
        )

    labels.sort(key=lambda row: (row.origin_session, row.label_end_session, row.target_id))
    features = tuple(feature_rows)
    payload = {
        "as_of": instant.isoformat(),
        "calendar_version": calendar.version,
        "labels": [_label_payload(row) for row in labels],
        "feature_rows": [_json_value(dict(row)) for row in features],
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return PitSnapshot(digest, instant, calendar.version, tuple(labels), features)


def persist_pit_snapshot(database_url: str, snapshot: PitSnapshot) -> bool:
    """Atomically append a materialized snapshot and all of its labels.

    Returns ``True`` for the first append and ``False`` when the identical
    content-addressed snapshot already exists. PostgreSQL is deliberately the
    only supported durable backend.
    """
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("R4 PIT snapshots require a PostgreSQL database URL")
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - frozen runtime guard
        raise RuntimeError("psycopg is required in the frozen R4 runtime") from exc

    payload = {
        "as_of": snapshot.as_of.isoformat(),
        "calendar_version": snapshot.calendar_version,
        "labels": [_label_payload(row) for row in snapshot.labels],
        "feature_rows": [_json_value(dict(row)) for row in snapshot.feature_rows],
    }
    encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with psycopg.connect(database_url) as connection:
        inserted = connection.execute(
            "INSERT INTO timeseries_v7_r4.pit_snapshots "
            "(snapshot_hash,as_of,calendar_version,payload) VALUES (%s,%s,%s,%s::jsonb) "
            "ON CONFLICT DO NOTHING RETURNING 1",
            (snapshot.snapshot_hash, snapshot.as_of, snapshot.calendar_version, encoded_payload),
        ).fetchone()
        if inserted is None:
            return False
        for label in snapshot.labels:
            connection.execute(
                "INSERT INTO timeseries_v7_r4.label_intervals "
                "(snapshot_hash,target_id,origin_session,label_start_session,label_end_session,"
                "mature_at,horizon_sessions,target_value) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (
                    snapshot.snapshot_hash,
                    label.target_id,
                    label.origin_session,
                    label.label_start_session,
                    label.label_end_session,
                    label.mature_at,
                    label.horizon_sessions,
                    json.dumps(_json_value(label.value), allow_nan=False),
                ),
            )
    return True


def persist_qualified_pit_snapshot(
    database_url: str,
    snapshot: PitSnapshot,
    provenance_rows: Iterable[Mapping[str, object]],
) -> bool:
    """Append the qualified snapshot, labels, and active-value provenance atomically."""
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("R4 PIT snapshots require a PostgreSQL database URL")
    import psycopg

    payload = {
        "as_of": snapshot.as_of.isoformat(), "calendar_version": snapshot.calendar_version,
        "labels": [_label_payload(row) for row in snapshot.labels],
        "feature_rows": [_json_value(dict(row)) for row in snapshot.feature_rows],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    rows = tuple(provenance_rows)
    with psycopg.connect(database_url) as connection:
        inserted = connection.execute(
            "INSERT INTO timeseries_v7_r4.pit_snapshots "
            "(snapshot_hash,as_of,calendar_version,payload) VALUES (%s,%s,%s,%s::jsonb) "
            "ON CONFLICT DO NOTHING RETURNING 1",
            (snapshot.snapshot_hash, snapshot.as_of, snapshot.calendar_version, encoded),
        ).fetchone()
        if inserted is None:
            return False
        cursor = connection.cursor()
        cursor.executemany(
            "INSERT INTO timeseries_v7_r4.label_intervals "
            "(snapshot_hash,target_id,origin_session,label_start_session,label_end_session,"
            "mature_at,horizon_sessions,target_value) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            [(snapshot.snapshot_hash, label.target_id, label.origin_session,
              label.label_start_session, label.label_end_session, label.mature_at,
              label.horizon_sessions, json.dumps(_json_value(label.value), allow_nan=False))
             for label in snapshot.labels],
        )
        cursor.executemany(
            "INSERT INTO timeseries_v7_r4.feature_value_provenance "
            "(snapshot_hash,origin_session,feature_id,max_available_at,origin_cutoff_at) "
            "VALUES (%s,%s,%s,%s,%s)",
            [(snapshot.snapshot_hash, row["origin_session"], row["feature_id"],
              row["max_available_at"], row["origin_cutoff_at"]) for row in rows],
        )
    return True


def verify_qualified_pit_snapshot(
    database_url: str,
    snapshot: PitSnapshot,
    provenance_rows: Iterable[Mapping[str, object]],
) -> dict[str, int]:
    """Read back an exact qualified snapshot from authoritative PostgreSQL."""
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("R4 PIT snapshots require a PostgreSQL database URL")
    import psycopg

    expected_provenance = len(tuple(provenance_rows))
    with psycopg.connect(database_url) as connection:
        stored = connection.execute(
            "SELECT jsonb_array_length(payload->'feature_rows') "
            "FROM timeseries_v7_r4.pit_snapshots WHERE snapshot_hash=%s",
            (snapshot.snapshot_hash,),
        ).fetchone()
        if stored is None:
            raise RuntimeError("qualified PIT snapshot was not persisted to PostgreSQL")
        label_count = connection.execute(
            "SELECT count(*) FROM timeseries_v7_r4.label_intervals WHERE snapshot_hash=%s",
            (snapshot.snapshot_hash,),
        ).fetchone()[0]
        provenance_count = connection.execute(
            "SELECT count(*) FROM timeseries_v7_r4.feature_value_provenance "
            "WHERE snapshot_hash=%s",
            (snapshot.snapshot_hash,),
        ).fetchone()[0]
    feature_count = stored[0]
    if (feature_count != len(snapshot.feature_rows)
            or label_count != len(snapshot.labels)
            or provenance_count != expected_provenance):
        raise RuntimeError("qualified PIT snapshot PostgreSQL read-back is incomplete")
    return {
        "feature_rows": feature_count,
        "label_rows": label_count,
        "provenance_rows": provenance_count,
    }


def _label_payload(row: LabelInterval) -> dict[str, object]:
    return {
        "target_id": row.target_id,
        "origin_session": row.origin_session.isoformat(),
        "label_start_session": row.label_start_session.isoformat(),
        "label_end_session": row.label_end_session.isoformat(),
        "mature_at": row.mature_at.isoformat(),
        "horizon_sessions": row.horizon_sessions,
        "value": _json_value(row.value),
    }


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return _utc(value, "snapshot value").isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
