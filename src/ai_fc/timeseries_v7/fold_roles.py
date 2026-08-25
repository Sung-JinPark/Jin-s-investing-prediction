"""Disjoint origin and label-interval fold-role validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


ROLES = {"research_train", "candidate_selection", "stacking", "calibration", "outer_test"}


@dataclass(frozen=True)
class FoldAssignment:
    role: str
    origin_session: date
    label_start_session: date
    label_end_session: date

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError("unknown fold role")


def validate_disjoint_roles(rows: Iterable[FoldAssignment]) -> dict[str, object]:
    values = list(rows)
    violations: set[str] = set()
    origins: dict[date, str] = {}
    for row in values:
        previous = origins.setdefault(row.origin_session, row.role)
        if previous != row.role:
            violations.add(f"origin:{row.origin_session.isoformat()}:{previous}:{row.role}")
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            if left.role == right.role:
                continue
            overlaps = max(left.label_start_session, right.label_start_session) <= min(left.label_end_session, right.label_end_session)
            if overlaps:
                violations.add(f"interval:{left.role}:{right.role}:{left.origin_session}:{right.origin_session}")
    return {"assignment_count": len(values), "violation_count": len(violations), "violations": sorted(violations), "pass": not violations}
