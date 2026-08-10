from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_fc.probability import (
    ProbabilityRecord,
    ProbabilitySpace,
    ProbabilityUnit,
    denormalize_probability,
    normalize_probability,
)


def test_explicit_units_normalize_without_heuristics() -> None:
    assert normalize_probability(22, source_unit="percent") == pytest.approx(0.22)
    assert normalize_probability(0.22, source_unit="fraction") == pytest.approx(0.22)
    assert denormalize_probability(0.22, target_unit="percent") == pytest.approx(22.0)


def test_invalid_fraction_is_rejected_instead_of_guessed() -> None:
    with pytest.raises(ValueError, match="outside"):
        normalize_probability(22, source_unit=ProbabilityUnit.FRACTION)


def test_record_preserves_semantics_and_conversion_receipt() -> None:
    record = ProbabilityRecord.from_raw(
        40,
        source_unit="percent",
        probability_space=ProbabilitySpace.PHYSICAL_EVENT,
        source_id="forecast:file",
        asof="2026-07-31T09:00:00",
    )
    assert record.probability == pytest.approx(0.4)
    assert record.source_unit is ProbabilityUnit.PERCENT
    assert record.probability_space is ProbabilitySpace.PHYSICAL_EVENT

    with pytest.raises(ValidationError, match="does not match"):
        ProbabilityRecord(
            probability=0.4,
            raw_value=0.4,
            source_unit="percent",
            probability_space="physical_event",
            source_id="broken",
        )
