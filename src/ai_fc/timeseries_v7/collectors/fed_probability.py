"""Fed meeting probability snapshot vectors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math


@dataclass(frozen=True)
class RateProbabilitySnapshot:
    snapshot_id: str
    captured_at: datetime
    meeting_probabilities: tuple[tuple[str, tuple[float, ...]], ...]

    def __post_init__(self) -> None:
        for _, vector in self.meeting_probabilities:
            if not vector or any(value < 0 or value > 1 for value in vector) or not math.isclose(sum(vector), 1.0, abs_tol=1e-9):
                raise ValueError("meeting probability vector must be fractions summing to one")

    def entropy(self) -> float:
        values = [value for _, vector in self.meeting_probabilities for value in vector if value > 0]
        return -sum(value * math.log(value) for value in values)


def independent_snapshot_count(rows: list[RateProbabilitySnapshot]) -> int:
    return len({row.snapshot_id for row in rows})
