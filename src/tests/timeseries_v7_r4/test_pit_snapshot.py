from datetime import datetime, timezone
import os
from pathlib import Path
import uuid

import psycopg
import pytest

from ai_fc.timeseries_v7_r4.pit_snapshot import (
    TargetObservation,
    materialize_pit_snapshot,
    persist_pit_snapshot,
)
from ai_fc.timeseries_v7_r4.xnas_sessions import XnasSessionCalendar


@pytest.fixture
def calendar():
    return XnasSessionCalendar.from_rows(
        version="xnas-test-v1",
        rows=[
            {"session_date": "2024-01-02", "close_time": "16:00"},
            {"session_date": "2024-01-03", "close_time": "16:00"},
            {"session_date": "2024-01-04", "close_time": "16:00"},
        ],
    )


def test_materializes_hashed_snapshot_and_canonical_label_intervals(calendar):
    targets = [
        TargetObservation(
            target_id="target-1",
            origin_session="2024-01-02",
            label_end_session="2024-01-04",
            value=0.25,
            available_at=datetime(2024, 1, 4, 21, 5, tzinfo=timezone.utc),
        )
    ]

    first = materialize_pit_snapshot(
        calendar=calendar,
        as_of=datetime(2024, 1, 5, tzinfo=timezone.utc),
        targets=targets,
        feature_rows=[],
    )
    second = materialize_pit_snapshot(
        calendar=calendar,
        as_of=datetime(2024, 1, 5, tzinfo=timezone.utc),
        targets=targets,
        feature_rows=[],
    )

    assert first.snapshot_hash == second.snapshot_hash
    assert len(first.snapshot_hash) == 64
    assert first.labels[0].origin_session.isoformat() == "2024-01-02"
    assert first.labels[0].label_start_session.isoformat() == "2024-01-03"
    assert first.labels[0].label_end_session.isoformat() == "2024-01-04"
    assert first.labels[0].horizon_sessions == 2
    assert first.labels[0].mature_at == targets[0].available_at


def test_target_is_retained_when_unrelated_feature_source_is_missing(calendar):
    result = materialize_pit_snapshot(
        calendar=calendar,
        as_of=datetime(2024, 1, 5, tzinfo=timezone.utc),
        targets=[
            TargetObservation(
                target_id="target-1",
                origin_session="2024-01-02",
                label_end_session="2024-01-03",
                value=-0.1,
                available_at=datetime(2024, 1, 3, 22, tzinfo=timezone.utc),
            )
        ],
        feature_rows=[{"origin_session": "2024-01-04", "feature_id": "other"}],
    )

    assert [label.target_id for label in result.labels] == ["target-1"]


def test_rejects_noncanonical_or_immature_target_sessions(calendar):
    with pytest.raises(ValueError, match="canonical XNAS session"):
        materialize_pit_snapshot(
            calendar=calendar,
            as_of=datetime(2024, 1, 5, tzinfo=timezone.utc),
            targets=[
                TargetObservation(
                    target_id="bad",
                    origin_session="2024-01-01",
                    label_end_session="2024-01-03",
                    value=1,
                    available_at=datetime(2024, 1, 3, 22, tzinfo=timezone.utc),
                )
            ],
            feature_rows=[],
        )

    immature = materialize_pit_snapshot(
        calendar=calendar,
        as_of=datetime(2024, 1, 3, 21, tzinfo=timezone.utc),
        targets=[
            TargetObservation(
                target_id="future",
                origin_session="2024-01-02",
                label_end_session="2024-01-03",
                value=1,
                available_at=datetime(2024, 1, 3, 22, tzinfo=timezone.utc),
            )
        ],
        feature_rows=[],
    )
    assert immature.labels == ()


def test_persists_snapshot_and_every_label_atomically_to_postgres(calendar):
    admin_url = os.getenv(
        "RALPH_V7_R4_TEST_ADMIN_URL",
        "postgresql://postgres@127.0.0.1:55432/postgres",
    )
    database = "v7r4_pit_" + uuid.uuid4().hex[:12]
    try:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(f'CREATE DATABASE "{database}"')
    except psycopg.OperationalError as exc:
        pytest.skip(f"disposable PostgreSQL unavailable: {exc}")
    database_url = f"postgresql://postgres@127.0.0.1:55432/{database}"
    try:
        migration = Path(__file__).resolve().parents[3] / "migrations/timeseries_v7_r4/002_pit_snapshots.sql"
        with psycopg.connect(database_url) as connection:
            connection.execute("CREATE SCHEMA timeseries_v7_r4")
            connection.execute(migration.read_text(encoding="utf-8"))
        snapshot = materialize_pit_snapshot(
            calendar=calendar,
            as_of=datetime(2024, 1, 5, tzinfo=timezone.utc),
            targets=[
                TargetObservation("one", "2024-01-02", "2024-01-03", 1,
                                  datetime(2024, 1, 3, 22, tzinfo=timezone.utc)),
                TargetObservation("two", "2024-01-02", "2024-01-04", 2,
                                  datetime(2024, 1, 4, 22, tzinfo=timezone.utc)),
            ],
            feature_rows=[],
        )

        assert persist_pit_snapshot(database_url, snapshot) is True
        assert persist_pit_snapshot(database_url, snapshot) is False
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM timeseries_v7_r4.pit_snapshots"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT target_id FROM timeseries_v7_r4.label_intervals ORDER BY target_id"
            ).fetchall() == [("one",), ("two",)]
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                (database,),
            )
            connection.execute(f'DROP DATABASE "{database}"')
