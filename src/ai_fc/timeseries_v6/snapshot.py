"""Immutable Parquet dataset snapshots used by V6 training and replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .object_store import LocalContentAddressedStore, RawObjectMetadata


class SnapshotError(RuntimeError):
    """Raised when a dataset snapshot cannot be proven immutable and PIT-safe."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotError("snapshot timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _utc(value).isoformat().replace("+00:00", "Z")


def _relative(root: Path, path: Path) -> str:
    try:
        value = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise SnapshotError("partition must be inside the snapshot root") from exc
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise SnapshotError("unsafe partition path")
    return pure.as_posix()


@dataclass(frozen=True)
class PartitionManifest:
    path: str
    sha256: str
    byte_count: int
    row_count: int
    schema_sha256: str
    source_ids: tuple[str, ...]
    min_observation_time: str | None
    max_observation_time: str | None
    min_available_at: str | None
    max_available_at: str | None


@dataclass(frozen=True)
class DatasetSnapshotManifest:
    schema_version: int
    dataset_snapshot_id: str
    contract_hash: str
    knowledge_cutoff: str
    created_at: str
    source_count: int
    observation_version_count: int
    partitions: tuple[PartitionManifest, ...]
    partition_manifest_sha256: str

    def payload_without_identity(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_hash": self.contract_hash,
            "knowledge_cutoff": self.knowledge_cutoff,
            "created_at": self.created_at,
            "source_count": self.source_count,
            "observation_version_count": self.observation_version_count,
            "partitions": [asdict(partition) for partition in self.partitions],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.payload_without_identity(),
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "partition_manifest_sha256": self.partition_manifest_sha256,
        }


def _timestamp_bounds(table: Any, column: str) -> tuple[str | None, str | None]:
    if column not in table.column_names or table.num_rows == 0:
        return None, None
    import pyarrow.compute as pc

    values = table[column]
    minimum = pc.min(values).as_py()
    maximum = pc.max(values).as_py()
    return _iso(minimum), _iso(maximum)


def inspect_parquet_partition(root: Path, path: Path) -> PartitionManifest:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise SnapshotError("pyarrow is required to inspect V6 snapshots") from exc
    relative = _relative(root, path)
    if path.suffix.lower() != ".parquet" or not path.is_file():
        raise SnapshotError(f"snapshot partition is not a Parquet file: {relative}")
    raw = path.read_bytes()
    table = pq.read_table(path)
    schema_sha = _sha256(table.schema.serialize().to_pybytes())
    source_ids: tuple[str, ...] = ()
    if "source_id" in table.column_names:
        source_ids = tuple(sorted({str(value) for value in table["source_id"].to_pylist() if value is not None}))
    observation_bounds = _timestamp_bounds(table, "observation_time")
    available_bounds = _timestamp_bounds(table, "available_at")
    return PartitionManifest(
        path=relative,
        sha256=_sha256(raw),
        byte_count=len(raw),
        row_count=table.num_rows,
        schema_sha256=schema_sha,
        source_ids=source_ids,
        min_observation_time=observation_bounds[0],
        max_observation_time=observation_bounds[1],
        min_available_at=available_bounds[0],
        max_available_at=available_bounds[1],
    )


def build_dataset_snapshot(
    root: Path,
    partitions: Iterable[Path],
    *,
    contract_hash: str,
    knowledge_cutoff: datetime,
    created_at: datetime,
) -> DatasetSnapshotManifest:
    if len(contract_hash) != 64 or any(character not in "0123456789abcdef" for character in contract_hash):
        raise SnapshotError("contract hash must be lowercase SHA-256")
    cutoff = _utc(knowledge_cutoff)
    inspected = sorted((inspect_parquet_partition(root, path) for path in partitions), key=lambda row: row.path)
    paths = [row.path for row in inspected]
    if not inspected or len(paths) != len(set(paths)):
        raise SnapshotError("snapshot must contain unique Parquet partitions")
    for row in inspected:
        if row.max_available_at and datetime.fromisoformat(row.max_available_at.replace("Z", "+00:00")) > cutoff:
            raise SnapshotError(f"partition contains future-available rows: {row.path}")
    sources = sorted({source for row in inspected for source in row.source_ids})
    base = {
        "schema_version": 1,
        "contract_hash": contract_hash,
        "knowledge_cutoff": _iso(cutoff),
        "created_at": _iso(_utc(created_at)),
        "source_count": len(sources),
        "observation_version_count": sum(row.row_count for row in inspected),
        "partitions": [asdict(row) for row in inspected],
    }
    digest = _sha256(_canonical(base))
    return DatasetSnapshotManifest(
        schema_version=1,
        dataset_snapshot_id=f"tsv6-snapshot-{digest[:24]}",
        contract_hash=contract_hash,
        knowledge_cutoff=base["knowledge_cutoff"],
        created_at=base["created_at"],
        source_count=base["source_count"],
        observation_version_count=base["observation_version_count"],
        partitions=tuple(inspected),
        partition_manifest_sha256=digest,
    )


def verify_dataset_snapshot(root: Path, manifest: DatasetSnapshotManifest) -> dict[str, Any]:
    expected = _sha256(_canonical(manifest.payload_without_identity()))
    if expected != manifest.partition_manifest_sha256:
        raise SnapshotError("dataset snapshot manifest hash mismatch")
    if manifest.dataset_snapshot_id != f"tsv6-snapshot-{expected[:24]}":
        raise SnapshotError("dataset snapshot identity mismatch")
    rebuilt = build_dataset_snapshot(
        root,
        [root / partition.path for partition in manifest.partitions],
        contract_hash=manifest.contract_hash,
        knowledge_cutoff=datetime.fromisoformat(manifest.knowledge_cutoff.replace("Z", "+00:00")),
        created_at=datetime.fromisoformat(manifest.created_at.replace("Z", "+00:00")),
    )
    if rebuilt != manifest:
        raise SnapshotError("dataset snapshot partition bytes or metadata changed")
    return {
        "dataset_snapshot_id": manifest.dataset_snapshot_id,
        "partition_count": len(manifest.partitions),
        "row_count": manifest.observation_version_count,
        "pass": True,
    }


def persist_snapshot_manifest(
    store: LocalContentAddressedStore,
    manifest: DatasetSnapshotManifest,
) -> RawObjectMetadata:
    verify_payload = manifest.as_dict()
    raw = _canonical(verify_payload)
    return store.put(raw, compression="gzip", license_class="internal_derived_manifest")
