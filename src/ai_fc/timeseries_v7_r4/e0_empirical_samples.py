"""Exact empirical E0 sample identity across the evaluation path.

Quantiles are report outputs only.  Evaluation consumers receive the immutable
sample vector and verify its content hash before doing any work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np

from .integrity import canonical_json, sha256_bytes


E0_EXACT_EMPIRICAL_CONTRACT: Mapping[str, Any] = {
    "contract_id": "E0_exact_empirical_anchor_v1",
    "algorithm": "exact_empirical_anchor",
    "input": "matured_direct_horizon_training_labels",
    "eligibility": "available_at_on_or_before_as_of",
    "sampling": "none",
}


def fit_exact_empirical_anchor(*, origin_session: str, horizon_sessions: int,
                               labels: Iterable[Mapping[str, Any]]) -> "E0SampleSet":
    """Bind all and only matured direct-horizon labels at an evaluation origin."""
    if not origin_session or horizon_sessions <= 0:
        raise ValueError("valid origin and horizon are required")
    eligible: list[tuple[str, float]] = []
    for label in labels:
        label_horizon = int(label.get("horizon_sessions", horizon_sessions))
        label_origin = str(label.get("origin_session", ""))
        value = label.get("value", label.get(f"h{horizon_sessions}"))
        available_at = label.get(
            "available_at", label.get(f"h{horizon_sessions}_label_end_session"),
        )
        if label_horizon != horizon_sessions or value is None or available_at is None:
            continue
        # A date-only label end becomes usable on the next forecasting session;
        # an explicit timestamp obeys the inclusive available_at contract.
        available = str(available_at)
        matured = available <= origin_session if "T" in available else available < origin_session
        if label_origin < origin_session and matured:
            eligible.append((label_origin, float(value)))
    eligible.sort(key=lambda item: item[0])
    values = tuple(value for _, value in eligible)
    if not values or not np.isfinite(np.asarray(values)).all():
        raise ValueError("finite matured direct-horizon training labels are required")
    return E0SampleSet.create(
        origin_session=origin_session,
        horizon_sessions=horizon_sessions,
        seed=0,
        values=values,
    )


def empirical_crps(samples: Iterable[float], actual: float) -> float:
    values = np.sort(np.asarray(tuple(samples), dtype=np.float64))
    if values.size == 0 or not np.isfinite(values).all() or not np.isfinite(actual):
        raise ValueError("CRPS requires finite empirical samples and actual")
    n = values.size
    first = float(np.mean(np.abs(values - actual)))
    coefficients = 2 * np.arange(1, n + 1) - n - 1
    return first - float(np.sum(coefficients * values) / (n * n))


@dataclass(frozen=True)
class E0SampleSet:
    origin_session: str
    horizon_sessions: int
    seed: int
    values: tuple[float, ...]
    sample_set_hash: str

    @staticmethod
    def _payload(origin_session: str, horizon_sessions: int, seed: int,
                 values: tuple[float, ...]) -> dict[str, Any]:
        return {
            "distribution": "E0_empirical_samples_v1",
            "origin_session": origin_session,
            "horizon_sessions": horizon_sessions,
            "seed": seed,
            "values": values,
        }

    @classmethod
    def create(cls, *, origin_session: str, horizon_sessions: int, seed: int,
               values: Iterable[float]) -> "E0SampleSet":
        exact = tuple(float(value) for value in values)
        if not origin_session or horizon_sessions <= 0 or not exact:
            raise ValueError("sample coordinates and non-empty values are required")
        if not np.isfinite(np.asarray(exact)).all():
            raise ValueError("empirical samples must be finite")
        payload = cls._payload(origin_session, horizon_sessions, seed, exact)
        return cls(origin_session, horizon_sessions, seed, exact,
                   sha256_bytes(canonical_json(payload)))

    @classmethod
    def from_receipt(cls, receipt: Mapping[str, Any]) -> "E0SampleSet":
        if receipt.get("distribution") != "E0_empirical_samples_v1":
            raise ValueError("receipt is not an exact E0 empirical sample set")
        result = cls.create(
            origin_session=str(receipt["origin_session"]),
            horizon_sessions=int(receipt["horizon_sessions"]),
            seed=int(receipt["seed"]),
            values=receipt["values"],
        )
        if result.sample_set_hash != receipt.get("sample_set_hash"):
            raise ValueError("sample-set hash mismatch in receipt")
        return result

    @classmethod
    def from_quantiles(cls, **_: Any) -> "E0SampleSet":
        raise ValueError("quantiles cannot reconstruct an empirical sample set")

    def receipt(self) -> dict[str, Any]:
        payload = self._payload(
            self.origin_session, self.horizon_sessions, self.seed, self.values,
        )
        return {**payload, "sample_set_hash": self.sample_set_hash}


@dataclass(frozen=True)
class EvaluationArtifact:
    stage: str
    sample_set_hash: str
    sample_count: int
    value: float | None = None
    samples: tuple[float, ...] = ()


@dataclass(frozen=True)
class EvaluationPath:
    sample_set: E0SampleSet

    @classmethod
    def bind(cls, sample_set: E0SampleSet) -> "EvaluationPath":
        return cls(sample_set)

    def _require(self, candidate: E0SampleSet | None) -> E0SampleSet:
        selected = candidate or self.sample_set
        if selected.sample_set_hash != self.sample_set.sample_set_hash:
            raise ValueError("sample-set hash mismatch across evaluation path")
        return selected

    def _artifact(self, stage: str, candidate: E0SampleSet | None = None,
                  value: float | None = None) -> EvaluationArtifact:
        selected = self._require(candidate)
        return EvaluationArtifact(stage, selected.sample_set_hash,
                                  len(selected.values), value, selected.values)

    def score(self, *, actual: float,
              sample_set: E0SampleSet | None = None) -> EvaluationArtifact:
        selected = self._require(sample_set)
        return self._artifact("scoring", selected,
                              empirical_crps(selected.values, actual))

    def stacking_input(self, *, sample_set: E0SampleSet | None = None) -> EvaluationArtifact:
        return self._artifact("stacking", sample_set)

    def calibration_input(self, *, sample_set: E0SampleSet | None = None) -> EvaluationArtifact:
        return self._artifact("calibration", sample_set)

    def forecast(self, *, sample_set: E0SampleSet | None = None) -> EvaluationArtifact:
        return self._artifact("forecast", sample_set)
