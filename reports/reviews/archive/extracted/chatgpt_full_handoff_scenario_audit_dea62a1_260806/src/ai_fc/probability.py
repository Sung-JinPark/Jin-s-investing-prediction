"""Canonical probability semantics.

Legacy forecast files intentionally keep their human-readable 0..100 values.  Every
new analytical surface uses this module to convert them to the canonical 0..1 space
with an explicit source unit; magnitude-based guessing is prohibited.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProbabilityUnit(StrEnum):
    FRACTION = "fraction"
    PERCENT = "percent"
    BPS = "bps"
    PRICE = "price"


class ProbabilitySpace(StrEnum):
    PHYSICAL_EVENT = "physical_event"
    RISK_NEUTRAL_TERMINAL = "risk_neutral_terminal"
    PATH_TOUCH = "path_touch"
    SCENARIO_CONDITIONAL = "scenario_conditional"
    REFERENCE_ONLY = "reference_only"


def normalize_probability(value: float | int, *, source_unit: ProbabilityUnit | str) -> float:
    """Return a 0..1 probability using an explicitly declared input unit."""
    unit = ProbabilityUnit(source_unit)
    raw = float(value)
    if unit is ProbabilityUnit.PRICE:
        raise ValueError("price requires an explicit instrument-specific mapping to probability")
    canonical = (
        raw / 100.0 if unit is ProbabilityUnit.PERCENT
        else raw / 10_000.0 if unit is ProbabilityUnit.BPS
        else raw
    )
    if not 0.0 <= canonical <= 1.0:
        raise ValueError(
            f"probability {raw!r} ({unit.value}) is outside the canonical [0, 1] range"
        )
    return canonical


def denormalize_probability(value: float, *, target_unit: ProbabilityUnit | str) -> float:
    """Convert a validated canonical probability to a declared display/storage unit."""
    canonical = normalize_probability(value, source_unit=ProbabilityUnit.FRACTION)
    unit = ProbabilityUnit(target_unit)
    if unit is ProbabilityUnit.PRICE:
        raise ValueError("probability cannot be converted to price without an instrument mapping")
    if unit is ProbabilityUnit.PERCENT:
        return canonical * 100.0
    if unit is ProbabilityUnit.BPS:
        return canonical * 10_000.0
    return canonical


class ProbabilityRecord(BaseModel):
    """Auditable probability value used by new DB/read-model surfaces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    probability: float = Field(ge=0.0, le=1.0)
    raw_value: float
    source_unit: ProbabilityUnit
    probability_space: ProbabilitySpace
    source_id: str = Field(min_length=1)
    asof: str | None = None

    @model_validator(mode="after")
    def validate_declared_conversion(self) -> "ProbabilityRecord":
        converted = normalize_probability(self.raw_value, source_unit=self.source_unit)
        if abs(converted - self.probability) > 1e-12:
            raise ValueError("probability does not match raw_value/source_unit")
        return self

    @classmethod
    def from_raw(
        cls,
        value: float | int,
        *,
        source_unit: ProbabilityUnit | str,
        probability_space: ProbabilitySpace | str,
        source_id: str,
        asof: str | None = None,
    ) -> "ProbabilityRecord":
        unit = ProbabilityUnit(source_unit)
        return cls(
            probability=normalize_probability(value, source_unit=unit),
            raw_value=float(value),
            source_unit=unit,
            probability_space=ProbabilitySpace(probability_space),
            source_id=source_id,
            asof=asof,
        )
