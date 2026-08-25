"""Static integrity checks for V7 PostgreSQL migrations."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


REQUIRED_TABLES = {
    "research_run", "data_cycle", "research_generation", "source_registry",
    "collection_attempt", "raw_object", "receipt", "receipt_terminal_outcome",
    "observation_key", "observation_revision", "receipt_fact_link", "dataset_snapshot",
    "feature_definition", "feature_value_lineage", "label_interval", "task",
    "task_dependency", "task_event", "experiment", "prediction", "score",
    "gate_definition", "gate_evaluation", "budget_ledger", "promotion_proposal",
}
IMMUTABLE_TABLES = {
    "raw_object", "receipt", "receipt_terminal_outcome", "observation_revision",
    "receipt_fact_link", "dataset_snapshot", "feature_value_lineage", "label_interval",
    "task_event", "prediction", "score", "gate_definition", "gate_evaluation",
    "budget_ledger",
}


class MigrationContractError(ValueError):
    """A migration does not implement the frozen typed control plane."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_core_migration(path: Path) -> dict[str, Any]:
    sql = path.read_text(encoding="utf-8")
    lowered = sql.lower()
    tables = set(re.findall(r"create\s+table\s+timeseries_v7\.([a-z0-9_]+)", lowered))
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise MigrationContractError(f"missing typed tables: {missing}")
    if "create function timeseries_v7.reject_immutable_mutation" not in lowered:
        raise MigrationContractError("immutable mutation trigger function missing")
    trigger_array_match = re.search(
        r"foreach\s+table_name\s+in\s+array\s+array\[(.*?)\]\s+loop",
        lowered,
        re.DOTALL,
    )
    if not trigger_array_match:
        raise MigrationContractError("immutable trigger table registry missing")
    trigger_tables = set(re.findall(r"'([a-z0-9_]+)'", trigger_array_match.group(1)))
    missing_triggers = sorted(IMMUTABLE_TABLES - trigger_tables)
    if missing_triggers:
        raise MigrationContractError(f"missing immutable triggers: {missing_triggers}")
    required_fragments = (
        "before update or delete", "fencing_token bigint", "lease_expires_at timestamptz",
        "heartbeat_at timestamptz", "max_available_at <= origin_cutoff_at",
        "input_snapshot_hash char(64) not null", "result_artifact_uri text",
        "unique (run_id, cycle_id, generation_id, origin_id, horizon_sessions, role)",
    )
    missing_fragments = [fragment for fragment in required_fragments if fragment not in lowered]
    if missing_fragments:
        raise MigrationContractError(f"missing constraints: {missing_fragments}")
    return {
        "schema_version": 1,
        "migration_sha256": sha256_file(path),
        "table_count": len(tables),
        "tables": sorted(tables),
        "immutable_table_count": len(trigger_tables),
        "immutable_tables": sorted(trigger_tables),
        "pass": True,
    }
