"""Exact empirical E0 sample identity across the evaluation path.

Quantiles are report outputs only.  Evaluation consumers receive the immutable
sample vector and verify its content hash before doing any work.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable, Mapping

import numpy as np

from .integrity import canonical_json, sha256_bytes


E0_BLOCK_BOOTSTRAP_CONTRACT: Mapping[str, Any] = {
    "contract_id": "E0_historical_moving_block_bootstrap_v1",
    "algorithm": "historical_moving_block_bootstrap",
    "input": "one_session_log_return",
    "eligibility": "session_strictly_before_origin",
    "block_length": "horizon_sessions",
    "aggregation": "sum",
    "replacement": True,
    "seed_derivation": "sha256(contract_id,root_seed,origin_session,horizon_sessions)",
}


def _coordinate_seed(*, root_seed: int, origin_session: str,
                     horizon_sessions: int) -> int:
    payload = {
        "contract_id": E0_BLOCK_BOOTSTRAP_CONTRACT["contract_id"],
        "root_seed": root_seed,
        "origin_session": origin_session,
        "horizon_sessions": horizon_sessions,
    }
    return int.from_bytes(sha256(canonical_json(payload)).digest()[:8], "big")


def generate_e0_samples(*, origin_session: str, horizon_sessions: int,
                        sessions: Iterable[str],
                        one_session_returns: Iterable[float],
                        sample_count: int, root_seed: int) -> "E0SampleSet":
    """Generate the exact E0 vector from information available at the origin.

    Each draw selects, with replacement, one complete historical moving block.
    A block is never allowed to include the origin session or a later session.
    """
    session_values = tuple(str(value) for value in sessions)
    returns = np.asarray(tuple(one_session_returns), dtype=np.float64)
    if not origin_session or horizon_sessions <= 0 or sample_count <= 0:
        raise ValueError("valid origin, horizon, and sample count are required")
    if len(session_values) != returns.size:
        raise ValueError("sessions and returns must have the same length")
    if any(left >= right for left, right in zip(session_values, session_values[1:])):
        raise ValueError("sessions must be strictly increasing")

    eligible = returns[np.asarray(session_values) < origin_session]
    if eligible.size < horizon_sessions or not np.isfinite(eligible).all():
        raise ValueError("finite eligible history must contain one complete block")
    block_count = eligible.size - horizon_sessions + 1
    seed = _coordinate_seed(
        root_seed=root_seed,
        origin_session=origin_session,
        horizon_sessions=horizon_sessions,
    )
    starts = np.random.default_rng(seed).integers(0, block_count, size=sample_count)
    cumulative = np.concatenate(([0.0], np.cumsum(eligible, dtype=np.float64)))
    values = cumulative[starts + horizon_sessions] - cumulative[starts]
    return E0SampleSet.create(
        origin_session=origin_session,
        horizon_sessions=horizon_sessions,
        seed=seed,
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
