"""Append-only candidate registration and feature-budget controls for V8R."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA = "v8r_candidate_registry_v1"
GENESIS_HASH = "0" * 64


class RegistryIntegrityError(RuntimeError):
    """Raised when the append-only registry hash chain is invalid."""


class UnregisteredCandidateError(RuntimeError):
    """Raised when an unregistered candidate tries to enter qualification."""


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _parse_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("registered_at must include an explicit timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class CandidateRegistry:
    """Minimal JSONL hash-chain registry.

    Rows are appended and never updated. Qualification consumers must call
    :meth:`require_registered` before accepting any result.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def rows(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, object]] = []
        previous = GENESIS_HASH
        for line_number, line in enumerate(
                self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("schema") != SCHEMA:
                raise RegistryIntegrityError(f"row {line_number}: wrong schema")
            if row.get("previous_record_sha256") != previous:
                raise RegistryIntegrityError(f"row {line_number}: broken previous hash")
            claimed = row.get("record_sha256")
            body = {key: value for key, value in row.items()
                    if key != "record_sha256"}
            actual = hashlib.sha256(_canonical(body)).hexdigest()
            if claimed != actual:
                raise RegistryIntegrityError(f"row {line_number}: record hash mismatch")
            previous = actual
            rows.append(row)
        return rows

    def register(
        self,
        *,
        candidate_id: str,
        hypothesis: str,
        expected_effect: str,
        feature_ids: Iterable[str] = (),
        registered_at: str,
        candidate_kind: str = "feature",
    ) -> dict[str, object]:
        if not candidate_id.strip() or not hypothesis.strip() or not expected_effect.strip():
            raise ValueError("candidate_id, hypothesis, and expected_effect are required")
        existing = self.rows()
        if any(row["candidate_id"] == candidate_id for row in existing):
            raise ValueError(f"candidate_id already registered: {candidate_id}")
        features = sorted(set(feature_ids))
        if len(features) > 8:
            raise ValueError("V8R round feature hard cap is 8")
        body: dict[str, object] = {
            "schema": SCHEMA,
            "candidate_id": candidate_id,
            "candidate_kind": candidate_kind,
            "hypothesis": hypothesis,
            "expected_effect": expected_effect,
            "feature_ids": features,
            "registered_at": _parse_timestamp(registered_at),
            "status": "REGISTERED_NOT_EVALUATED",
            "previous_record_sha256": (
                str(existing[-1]["record_sha256"]) if existing else GENESIS_HASH
            ),
        }
        row = dict(body)
        row["record_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n")
        return row

    def require_registered(self, candidate_id: str) -> dict[str, object]:
        for row in self.rows():
            if row["candidate_id"] == candidate_id:
                return row
        raise UnregisteredCandidateError(
            f"qualification result rejected; candidate is not registered: {candidate_id}"
        )

    def snapshot_sha256(self) -> str:
        self.rows()
        return hashlib.sha256(
            self.path.read_bytes() if self.path.exists() else b""
        ).hexdigest()


def feature_budget_limit(*, origins: int, horizon: int, hard_cap: int = 8) -> int:
    """Return min(hard cap, max(3, floor(n_eff / 150)))."""
    if origins <= 0 or horizon <= 0 or hard_cap < 3:
        raise ValueError("origins and horizon must be positive; hard_cap must be >= 3")
    n_eff = origins / (2.0 * horizon)
    return min(hard_cap, max(3, math.floor(n_eff / 150.0)))


@dataclass(frozen=True)
class CorrelationDecision:
    accepted: bool
    maximum_absolute_correlation: float
    conflicting_feature: str | None
    threshold: float
    role: str


def _paired_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    pairs = [
        (float(a), float(b)) for a, b in zip(left, right, strict=True)
        if math.isfinite(float(a)) and math.isfinite(float(b))
    ]
    if len(pairs) < 3:
        raise ValueError("at least three finite paired research_train rows are required")
    mean_left = sum(a for a, _ in pairs) / len(pairs)
    mean_right = sum(b for _, b in pairs) / len(pairs)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in pairs)
    left_ss = sum((a - mean_left) ** 2 for a, _ in pairs)
    right_ss = sum((b - mean_right) ** 2 for _, b in pairs)
    if left_ss == 0 or right_ss == 0:
        raise ValueError("correlation is undefined for a constant feature")
    return numerator / math.sqrt(left_ss * right_ss)


def evaluate_feature_correlation(
    candidate: Sequence[float],
    existing: Mapping[str, Sequence[float]],
    *,
    role: str,
    threshold: float = 0.85,
) -> CorrelationDecision:
    """Reject a feature correlated above the frozen threshold on train only."""
    if role != "research_train":
        raise ValueError("feature correlation may be calculated on research_train only")
    if not 0 < threshold < 1:
        raise ValueError("threshold must be in (0, 1)")
    if not existing:
        return CorrelationDecision(True, 0.0, None, threshold, role)
    correlations = {
        name: abs(_paired_correlation(candidate, values))
        for name, values in existing.items()
    }
    conflict, maximum = max(correlations.items(), key=lambda item: item[1])
    return CorrelationDecision(maximum <= threshold, maximum,
                               None if maximum <= threshold else conflict,
                               threshold, role)
