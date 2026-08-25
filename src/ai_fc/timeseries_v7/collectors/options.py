"""Forward option aggregates with physical-calibration eligibility."""

from __future__ import annotations


def model_weight(*, captured_origins: int, physical_calibration_pass: bool) -> float:
    return 0.0 if captured_origins < 126 or not physical_calibration_pass else 1.0
