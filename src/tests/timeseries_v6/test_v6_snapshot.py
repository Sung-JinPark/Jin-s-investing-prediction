from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ai_fc.timeseries_v6.object_store import LocalContentAddressedStore
from ai_fc.timeseries_v6.snapshot import (
    SnapshotError,
    build_dataset_snapshot,
    persist_snapshot_manifest,
    verify_dataset_snapshot,
)


NOW = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)


def _partition(path: Path, *, available_at: datetime = NOW, value: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "observation_version_id": ["v1"],
            "source_id": ["fred_alfred"],
            "observation_time": [datetime(2026, 8, 21, tzinfo=timezone.utc)],
            "available_at": [available_at],
            "value_numeric": [value],
        }
    )
    pq.write_table(table, path)
    return path


def test_snapshot_is_deterministic_and_persisted_content_addressed(tmp_path: Path) -> None:
    first = _partition(tmp_path / "series=A" / "year=2026" / "part.parquet")
    second = _partition(tmp_path / "series=B" / "year=2026" / "part.parquet", value=2.0)
    one = build_dataset_snapshot(tmp_path, [second, first], contract_hash="a" * 64, knowledge_cutoff=NOW, created_at=NOW)
    two = build_dataset_snapshot(tmp_path, [first, second], contract_hash="a" * 64, knowledge_cutoff=NOW, created_at=NOW)
    assert one == two
    assert one.source_count == 1
    assert one.observation_version_count == 2
    assert verify_dataset_snapshot(tmp_path, one)["pass"] is True
    metadata = persist_snapshot_manifest(LocalContentAddressedStore(tmp_path / "objects"), one)
    assert metadata.object_sha256 != one.partition_manifest_sha256


def test_snapshot_rejects_future_available_row(tmp_path: Path) -> None:
    partition = _partition(tmp_path / "future.parquet", available_at=NOW + timedelta(seconds=1))
    with pytest.raises(SnapshotError, match="future-available"):
        build_dataset_snapshot(tmp_path, [partition], contract_hash="a" * 64, knowledge_cutoff=NOW, created_at=NOW)


def test_snapshot_verification_detects_partition_tamper(tmp_path: Path) -> None:
    partition = _partition(tmp_path / "part.parquet")
    manifest = build_dataset_snapshot(tmp_path, [partition], contract_hash="a" * 64, knowledge_cutoff=NOW, created_at=NOW)
    _partition(partition, value=9.0)
    with pytest.raises(SnapshotError, match="changed"):
        verify_dataset_snapshot(tmp_path, manifest)


def test_snapshot_rejects_partition_outside_root_and_duplicates(tmp_path: Path) -> None:
    outside = _partition(tmp_path.parent / "outside-v6.parquet")
    with pytest.raises(SnapshotError, match="inside"):
        build_dataset_snapshot(tmp_path, [outside], contract_hash="a" * 64, knowledge_cutoff=NOW, created_at=NOW)
    inside = _partition(tmp_path / "inside.parquet")
    with pytest.raises(SnapshotError, match="unique"):
        build_dataset_snapshot(tmp_path, [inside, inside], contract_hash="a" * 64, knowledge_cutoff=NOW, created_at=NOW)
    outside.unlink()
