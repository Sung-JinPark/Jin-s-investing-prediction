"""Honest source-registry coverage for the V6 research archive.

The 37-source preregistration is a catalogue, not a claim that every source is
materialized in every model run.  This module keeps those concepts separate and
fails closed only when a source/series required by the active research profile
is absent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .public_archive import PublicSeriesSpec
from .source_registry import SourceDefinition, load_source_registry


def build_source_coverage(
    registry_path: Path,
    manifest_path: Path,
    required_specs: Iterable[PublicSeriesSpec],
) -> dict[str, Any]:
    registry = load_source_registry(registry_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipts = {
        (str(row["source_id"]), str(row["series_id"])): row
        for row in manifest.get("receipts", [])
    }
    required = {(spec.source_id, spec.series_id) for spec in required_specs}
    missing_required = sorted(
        {f"{source_id}:{series_id}" for source_id, series_id in required if (source_id, series_id) not in receipts}
    )
    materialized_source_ids = {source_id for source_id, _ in receipts}
    rows: list[dict[str, Any]] = []
    for source_id, definition in sorted(registry.items()):
        series_ids = sorted(series for candidate_source, series in receipts if candidate_source == source_id)
        required_series = sorted(series for candidate_source, series in required if candidate_source == source_id)
        if series_ids:
            status = "materialized"
        elif definition.adapter_status == "forward_capture":
            status = "forward_capture_pending"
        elif definition.adapter_status in {"licensed_unavailable", "blocked_no_history"}:
            status = definition.adapter_status
        elif definition.adapter_status == "retired":
            status = "retired"
        else:
            status = "implemented_not_materialized"
        rows.append({
            "source_id": source_id,
            "provider": definition.provider,
            "adapter_status": definition.adapter_status,
            "data_grade": definition.data_grade,
            "runtime_status": status,
            "materialized_series_ids": series_ids,
            "required_series_ids": required_series,
            "used_by_active_archive": bool(required_series),
        })
    unknown_receipts = sorted(materialized_source_ids - set(registry))
    return {
        "schema_version": 1,
        "registry_source_count": len(registry),
        "materialized_source_count": len(materialized_source_ids),
        "materialized_series_count": len(receipts),
        "required_series_count": len(required),
        "required_series_coverage": 0.0 if not required else (len(required) - len(missing_required)) / len(required),
        "missing_required_series": missing_required,
        "unknown_receipt_sources": unknown_receipts,
        "full_registry_materialization_is_not_claimed": True,
        "model_required_pass": not missing_required and not unknown_receipts,
        "sources": rows,
    }
