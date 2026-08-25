"""Per-origin feature-value PIT lineage proofs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class FeatureValueLineage:
    origin_id: str
    feature_id: str
    value: float | None
    origin_cutoff_at: datetime
    max_available_at: datetime | None
    source_revision_ids: tuple[str, ...]
    transformation_hash: str
    imputation_policy: str
    missing: bool
    active: bool = True


def prove_feature_pit(rows: Iterable[FeatureValueLineage]) -> dict[str, object]:
    values = list(rows)
    violations: list[str] = []
    active = [row for row in values if row.active]
    for row in active:
        key = f"{row.origin_id}:{row.feature_id}"
        if row.missing:
            if row.value is not None:
                violations.append(f"{key}:missing_with_value")
        else:
            if row.value is None or row.max_available_at is None or not row.source_revision_ids:
                violations.append(f"{key}:incomplete_lineage")
        if row.max_available_at is not None and row.max_available_at > row.origin_cutoff_at:
            violations.append(f"{key}:future_available_at")
        if not row.transformation_hash or not row.imputation_policy:
            violations.append(f"{key}:missing_transform_policy")
    return {
        "active_feature_value_count": len(active), "violation_count": len(violations),
        "violations": sorted(violations), "coverage": 1.0 if active and not violations else (0.0 if active else None),
        "pass": bool(active) and not violations,
    }
