"""Foundation models are isolated challengers and carry zero weight by default."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FoundationChallengerStatus:
    component_id: str
    enabled: bool = False
    weight: float = 0.0
    reason: str = "not_evaluated_on_identical_pit_cutoffs"


def default_challengers() -> tuple[FoundationChallengerStatus, ...]:
    return (
        FoundationChallengerStatus("timesfm"),
        FoundationChallengerStatus("chronos"),
    )
