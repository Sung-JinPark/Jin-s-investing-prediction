"""Distribution calibration and mandatory conditional tables."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def monotone_quantiles(levels: np.ndarray, values: np.ndarray) -> dict[float, float]:
    probabilities = np.asarray(levels, dtype=float)
    quantiles = np.asarray(values, dtype=float)
    if np.any(np.diff(probabilities) <= 0):
        raise ValueError("quantile levels must be strictly increasing")
    corrected = np.maximum.accumulate(quantiles)
    return {float(level): float(value) for level, value in zip(probabilities, corrected, strict=True)}


def wilson_interval(successes: int, total: int, z: float = 1.6448536269514722) -> tuple[float, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("valid binomial counts required")
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


@dataclass(frozen=True)
class GroupConformalScale:
    multipliers: dict[str, dict[int, float]]
    minimum_rows: int = 30

    @classmethod
    def fit(
        cls, actuals: dict[int, np.ndarray], medians: dict[int, np.ndarray],
        half_widths: dict[int, np.ndarray], groups: np.ndarray, *, minimum_rows: int = 30,
    ) -> "GroupConformalScale":
        labels = np.asarray(groups).astype(str)
        multipliers: dict[str, dict[int, float]] = {}
        for group in sorted(set(labels)):
            mask = labels == group
            if mask.sum() < minimum_rows:
                continue
            multipliers[group] = {}
            for horizon in actuals:
                denominator = np.maximum(np.asarray(half_widths[horizon])[mask], 1e-8)
                scores = np.abs(np.asarray(actuals[horizon])[mask] - np.asarray(medians[horizon])[mask]) / denominator
                multipliers[group][horizon] = float(np.clip(np.quantile(scores, 0.80), 0.5, 2.5))
        return cls(multipliers, minimum_rows)

    def apply(self, samples: np.ndarray, *, group: str, horizon: int) -> np.ndarray:
        array = np.asarray(samples, dtype=float)
        multiplier = self.multipliers.get(group, {}).get(horizon, 1.0)
        center = float(np.median(array))
        return center + multiplier * (array - center)


def coverage_table(
    actual: np.ndarray, lower: np.ndarray, upper: np.ndarray, groups: np.ndarray,
) -> dict[str, dict[str, float | int]]:
    actual = np.asarray(actual, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    labels = np.asarray(groups).astype(str)
    output: dict[str, dict[str, float | int]] = {}
    for group in sorted(set(labels)):
        mask = (labels == group) & np.isfinite(actual) & np.isfinite(lower) & np.isfinite(upper)
        count = int(mask.sum())
        if not count:
            continue
        hits = int(np.sum((actual[mask] >= lower[mask]) & (actual[mask] <= upper[mask])))
        low, high = wilson_interval(hits, count)
        output[group] = {
            "count": count, "hits": hits, "coverage": hits / count,
            "wilson90_low": low, "wilson90_high": high,
            "mean_width": float(np.mean(upper[mask] - lower[mask])),
        }
    return output
