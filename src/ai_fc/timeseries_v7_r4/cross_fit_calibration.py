"""Leakage-safe, asymmetric calibration for empirical predictive samples."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    case_id: str
    role: str
    predictive_samples: tuple[float, ...]
    outcome: float


@dataclass(frozen=True, slots=True)
class CrossFitCalibrator:
    location_shift: float
    central_scale: float
    negative_tail_scale: float
    positive_tail_scale: float
    fitted_case_ids: tuple[str, ...]

    def calibrate_quantiles(self, quantiles: Sequence[float]) -> tuple[float, ...]:
        values = _validated_values(quantiles, "quantiles")
        if tuple(sorted(values)) != values:
            raise ValueError("quantiles must be nondecreasing")
        centre = median(values)
        lower_hinge = _quantile(values, 0.25)
        upper_hinge = _quantile(values, 0.75)
        calibrated: list[float] = []
        for value in values:
            if value < lower_hinge:
                central_hinge = centre + self.central_scale * (lower_hinge - centre)
                transformed = central_hinge + self.negative_tail_scale * (value - lower_hinge)
            elif value > upper_hinge:
                central_hinge = centre + self.central_scale * (upper_hinge - centre)
                transformed = central_hinge + self.positive_tail_scale * (value - upper_hinge)
            else:
                transformed = centre + self.central_scale * (value - centre)
            calibrated.append(transformed + self.location_shift)
        return tuple(calibrated)


def fit_cross_fit_calibrator(cases: Iterable[CalibrationCase]) -> CrossFitCalibrator:
    """Fit all calibration components exclusively from the calibration role.

    Role validation precedes every outcome read, making outer and prospective
    outcomes fail closed at the fit boundary.
    """
    rows = tuple(cases)
    if not rows:
        raise ValueError("at least one calibration case is required")
    if any(row.role != "calibration" for row in rows):
        raise ValueError("fit accepts calibration role cases only")
    if any(not row.case_id for row in rows) or len({row.case_id for row in rows}) != len(rows):
        raise ValueError("case_id must be present and unique")

    samples = [_validated_values(row.predictive_samples, "predictive_samples") for row in rows]
    if any(tuple(sorted(values)) != values for values in samples):
        raise ValueError("predictive_samples must be nondecreasing")
    outcomes = tuple(float(row.outcome) for row in rows)
    if not all(isfinite(value) for value in outcomes):
        raise ValueError("outcomes must be finite")

    centres = tuple(median(values) for values in samples)
    residuals = tuple(outcome - centre for outcome, centre in zip(outcomes, centres))
    location = median(residuals)
    centred_residuals = tuple(value - location for value in residuals)
    predicted_central = tuple(max(_quantile(v, .75) - _quantile(v, .25), 1e-12) for v in samples)
    observed_central = _quantile(tuple(abs(v) for v in centred_residuals), .75) * 2.0
    central_scale = _positive_ratio(observed_central, median(predicted_central))

    negative_excess = tuple(-value for value in centred_residuals if value < 0)
    positive_excess = tuple(value for value in centred_residuals if value > 0)
    predicted_negative = median(tuple(max(median(v) - v[0], 1e-12) for v in samples))
    predicted_positive = median(tuple(max(v[-1] - median(v), 1e-12) for v in samples))
    negative_scale = _tail_scale(negative_excess, predicted_negative, central_scale)
    positive_scale = _tail_scale(positive_excess, predicted_positive, central_scale)
    return CrossFitCalibrator(location, central_scale, negative_scale, positive_scale,
                              tuple(row.case_id for row in rows))


def cross_fit_quantiles(cases: Iterable[CalibrationCase]) -> dict[str, tuple[float, ...]]:
    """Return leave-one-out calibrated sample quantiles for calibration cases."""
    rows = tuple(cases)
    if len(rows) < 2:
        raise ValueError("cross-fit calibration requires at least two cases")
    # Validate all roles before constructing a fold that could consume outcomes.
    if any(row.role != "calibration" for row in rows):
        raise ValueError("cross-fit accepts calibration role cases only")
    return {
        row.case_id: fit_cross_fit_calibrator(rows[:index] + rows[index + 1:]).calibrate_quantiles(
            row.predictive_samples
        )
        for index, row in enumerate(rows)
    }


def one_sided_hit_rates(*, outcomes: Sequence[float], lower: Sequence[float],
                        upper: Sequence[float]) -> tuple[float, float]:
    """Return lower-tail ``y < lower`` and upper-tail ``y > upper`` rates."""
    if not outcomes or len(outcomes) != len(lower) or len(outcomes) != len(upper):
        raise ValueError("outcomes and bounds must have the same non-zero length")
    triples = tuple(zip(outcomes, lower, upper))
    if any(not all(isfinite(float(value)) for value in row) for row in triples):
        raise ValueError("outcomes and bounds must be finite")
    if any(lo > hi for _, lo, hi in triples):
        raise ValueError("lower bound must not exceed upper bound")
    count = len(triples)
    return (sum(y < lo for y, lo, _ in triples) / count,
            sum(y > hi for y, _, hi in triples) / count)


def _validated_values(values: Sequence[float], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or not all(isfinite(value) for value in result):
        raise ValueError(f"{name} must contain finite values")
    return result


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    fraction = position - lower
    if lower == len(ordered) - 1:
        return ordered[lower]
    return ordered[lower] * (1.0 - fraction) + ordered[lower + 1] * fraction


def _positive_ratio(numerator: float, denominator: float) -> float:
    if numerator <= 0:
        return 1.0
    return max(numerator / denominator, 1e-12)


def _tail_scale(excesses: Sequence[float], predicted_width: float, fallback: float) -> float:
    if not excesses:
        return fallback
    return _positive_ratio(_quantile(excesses, .9), predicted_width)
