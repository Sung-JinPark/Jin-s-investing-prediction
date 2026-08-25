"""Exact empirical E0 comparator sample object."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ExactEmpiricalAnchor:
    origin_id: str
    horizon_sessions: int
    samples: tuple[float, ...]
    sample_hash: str

    @classmethod
    def create(cls, origin_id: str, horizon_sessions: int, samples: tuple[float, ...] | list[float]) -> "ExactEmpiricalAnchor":
        values = tuple(float(value) for value in samples)
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("E0 requires non-empty finite exact samples")
        body = json.dumps({"origin_id": origin_id, "horizon_sessions": horizon_sessions, "samples": values}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return cls(origin_id, horizon_sessions, values, hashlib.sha256(body).hexdigest())

    def cdf(self, value: float) -> float:
        return sum(sample <= value for sample in self.samples) / len(self.samples)

    def quantile(self, probability: float) -> float:
        if not 0 <= probability <= 1:
            raise ValueError("probability must be fraction in [0,1]")
        values = sorted(self.samples)
        if len(values) == 1:
            return values[0]
        position = probability * (len(values) - 1)
        lower = int(math.floor(position)); upper = int(math.ceil(position))
        weight = position - lower
        return values[lower] * (1 - weight) + values[upper] * weight


def assert_comparator_identity(anchor: ExactEmpiricalAnchor, stage_hashes: dict[str, str]) -> None:
    mismatches = {stage: value for stage, value in stage_hashes.items() if value != anchor.sample_hash}
    if mismatches:
        raise ValueError(f"E0 comparator identity mismatch: {mismatches}")
