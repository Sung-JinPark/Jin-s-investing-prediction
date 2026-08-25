from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.timeseries_v7.migrations import (
    IMMUTABLE_TABLES,
    REQUIRED_TABLES,
    MigrationContractError,
    inspect_core_migration,
)


REPO = Path(__file__).resolve().parents[3]
UP = REPO / "migrations/timeseries_v7/0001_core.sql"
DOWN = REPO / "migrations/timeseries_v7/0001_core.down.sql"


def test_core_migration_has_all_typed_tables_and_immutable_triggers() -> None:
    report = inspect_core_migration(UP)
    assert report["pass"] is True
    assert report["table_count"] == len(REQUIRED_TABLES) == 25
    assert report["immutable_table_count"] == len(IMMUTABLE_TABLES) == 14


def test_down_migration_is_scoped_to_v7_schema() -> None:
    sql = DOWN.read_text(encoding="utf-8").lower()
    assert "drop schema if exists timeseries_v7 cascade" in sql
    assert "timeseries_v6" not in sql


def test_missing_table_fails_closed(tmp_path: Path) -> None:
    value = UP.read_text(encoding="utf-8").replace(
        "CREATE TABLE timeseries_v7.score", "CREATE TABLE timeseries_v7.score_missing", 1
    )
    path = tmp_path / "bad.sql"
    path.write_text(value, encoding="utf-8")
    with pytest.raises(MigrationContractError, match="missing typed tables"):
        inspect_core_migration(path)


def test_task_identity_and_lease_coordinates_are_typed() -> None:
    sql = UP.read_text(encoding="utf-8").lower()
    assert "primary key (run_id, cycle_id, generation_id, task_key)" in sql
    assert "idempotency_key char(64) not null unique" in sql
    assert "lease_owner text" in sql
    assert "fencing_token bigint not null default 0" in sql
    assert "input_snapshot_hash char(64) not null" in sql
    assert "result_artifact_uri text" in sql
