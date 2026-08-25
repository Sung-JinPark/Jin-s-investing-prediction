"""Source-specific freshness without silent carry-forward."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class FreshnessPolicy:
    source_id: str
    maximum_age: timedelta
    carry_forward: bool = False


POLICIES = {
    "OFR_FSI": FreshnessPolicy("OFR_FSI", timedelta(days=4)),
    "DTWEXBGS": FreshnessPolicy("DTWEXBGS", timedelta(days=4)),
    "M2SL": FreshnessPolicy("M2SL", timedelta(days=45)),
}


def freshness(source_id: str, available_at: datetime, cutoff: datetime) -> dict[str, object]:
    policy = POLICIES[source_id]
    age = cutoff - available_at
    if age.total_seconds() < 0:
        return {"source_id": source_id, "eligible": False, "state": "future_observation", "age_seconds": age.total_seconds()}
    fresh = age <= policy.maximum_age
    return {"source_id": source_id, "eligible": fresh, "state": "fresh" if fresh else "stale", "age_seconds": age.total_seconds(), "carry_forward": False}
