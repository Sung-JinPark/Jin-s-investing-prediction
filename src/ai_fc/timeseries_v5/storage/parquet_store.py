"""Deterministic partitioned Parquet analytical views."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from ..identifiers import content_hash


def export_partition(rows: list[dict[str, Any]], target: Path, *, sort_keys: list[str]) -> dict[str, Any]:
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc: raise RuntimeError("install ai-fc[timeseries-v5] for Parquet") from exc
    ordered = sorted(rows, key=lambda row: tuple(str(row.get(key, "")) for key in sort_keys)); target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.parquet"); table = pa.Table.from_pylist(ordered)
    pq.write_table(table, temporary, compression="zstd", use_dictionary=True); temporary.replace(target)
    return {"uri": target.as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "rows": len(ordered), "schema_hash": content_hash(str(table.schema))}


def write_manifest(path: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"files": sorted(files, key=lambda row: row["uri"]), "row_count": sum(int(row["rows"]) for row in files)}; payload["content_hash"] = content_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"); return payload
