"""Point-in-time snapshots shared by every V3 component."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


class SnapshotLeakageError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotFact:
    series_id: str
    observation_time: str
    available_at: str
    value: float
    source_id: str
    raw_sha256: str
    data_grade: str
    vintage_start: str | None = None
    vintage_end: str | None = None
    supersedes: str | None = None


@dataclass(frozen=True)
class OriginSnapshot:
    origin: str
    knowledge_cutoff: str
    facts: tuple[SnapshotFact, ...]
    features: dict[str, float]
    feature_available_at: dict[str, str]
    component_status: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        bad = [fact for fact in self.facts if fact.available_at > self.knowledge_cutoff]
        if bad:
            raise SnapshotLeakageError(
                f"{len(bad)} fact(s) became available after {self.knowledge_cutoff}"
            )
        late_features = {
            key: timestamp for key, timestamp in self.feature_available_at.items()
            if timestamp > self.knowledge_cutoff
        }
        if late_features:
            raise SnapshotLeakageError(f"feature availability leakage: {sorted(late_features)}")


def pit_snapshot(
    facts: Iterable[SnapshotFact], *, origin: str, knowledge_cutoff: str,
    features: dict[str, float] | None = None,
    feature_available_at: dict[str, str] | None = None,
) -> OriginSnapshot:
    selected = tuple(fact for fact in facts if fact.available_at <= knowledge_cutoff)
    snapshot = OriginSnapshot(
        origin=origin,
        knowledge_cutoff=knowledge_cutoff,
        facts=selected,
        features=dict(features or {}),
        feature_available_at=dict(feature_available_at or {}),
    )
    snapshot.validate()
    return snapshot
