"""Append-only PIT macro-event snapshots and path-local branch shocks."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .contracts import canonical_hash


@dataclass(frozen=True)
class EventSnapshot:
    event_id: str
    event_type: str
    scheduled_at: str
    snapshot_at: str
    source_id: str
    consensus_mean: float | None
    consensus_median: float | None
    consensus_dispersion: float | None
    model_nowcast: float | None
    prior_actual: float | None
    market_implied_move: float | None
    fedwatch_probability_vector: tuple[float, ...]
    actual: float | None
    actual_available_at: str | None
    revision_of: str | None
    raw_sha256: str

    @property
    def snapshot_id(self) -> str:
        return "tsv3-event-" + canonical_hash(asdict(self))[:24]

    def validate(self) -> None:
        if self.snapshot_at > self.scheduled_at and self.actual is None:
            # A post-event snapshot may omit actual while parsing, but cannot be used numerically.
            return
        if self.actual is not None:
            if not self.actual_available_at:
                raise ValueError("event actual requires actual_available_at")
            if self.actual_available_at < self.scheduled_at:
                raise ValueError("event actual cannot be available before the event")
        probabilities = np.asarray(self.fedwatch_probability_vector, dtype=float)
        if probabilities.size and (
            np.any((probabilities < 0) | (probabilities > 1)) or abs(float(probabilities.sum()) - 1.0) > 1e-6
        ):
            raise ValueError("FedWatch vector must contain fractions summing to one")


def append_event_snapshot(path: Path, snapshot: EventSnapshot) -> bool:
    snapshot.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = read_event_snapshots(path)
    existing = {row.snapshot_id for row in stored}
    if snapshot.snapshot_id in existing:
        return False
    if snapshot.revision_of is not None and snapshot.revision_of not in existing:
        raise ValueError("event revision_of must name an existing immutable snapshot")
    line = json.dumps({"snapshot_id": snapshot.snapshot_id, **asdict(snapshot)}, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def read_event_snapshots(path: Path) -> list[EventSnapshot]:
    if not path.is_file():
        return []
    rows: list[EventSnapshot] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        payload.pop("snapshot_id", None)
        payload["fedwatch_probability_vector"] = tuple(payload.get("fedwatch_probability_vector", ()))
        rows.append(EventSnapshot(**payload))
    return rows


def snapshots_available_at(rows: Iterable[EventSnapshot], cutoff: str) -> list[EventSnapshot]:
    selected = [row for row in rows if row.snapshot_at <= cutoff]
    for row in selected:
        if row.actual is not None and (not row.actual_available_at or row.actual_available_at > cutoff):
            raise ValueError("future event actual leakage")
    return selected


def standardized_surprise(row: EventSnapshot) -> float:
    if row.actual is None or row.consensus_mean is None or not row.consensus_dispersion:
        raise ValueError("actual, pre-release consensus and nonzero dispersion required")
    if not row.actual_available_at or row.actual_available_at < row.scheduled_at:
        raise ValueError("invalid event actual availability")
    return float((row.actual - row.consensus_mean) / row.consensus_dispersion)


def pre_event_branch_probabilities(row: EventSnapshot) -> dict[str, float]:
    gap = 0.0
    if row.model_nowcast is not None and row.consensus_mean is not None and row.consensus_dispersion:
        gap = (row.model_nowcast - row.consensus_mean) / row.consensus_dispersion
    logits = np.array([-0.7 * gap, -0.5 * abs(gap), 0.7 * gap])
    logits -= logits.max()
    values = np.exp(logits)
    values /= values.sum()
    return dict(zip(("soft_dovish", "near_consensus", "hot_hawkish"), map(float, values), strict=True))


def apply_local_event_shock(
    paths: np.ndarray, *, event_session: int, branch_probabilities: dict[str, float],
    mean_shocks: dict[str, float], volatility_multipliers: dict[str, float],
    effect_sessions: int, rng: np.random.Generator,
) -> np.ndarray:
    output = np.asarray(paths, dtype=float).copy()
    if event_session < 0 or event_session >= output.shape[1]:
        return output
    labels = tuple(branch_probabilities)
    probabilities = np.array([branch_probabilities[label] for label in labels], dtype=float)
    probabilities /= probabilities.sum()
    selected = rng.choice(len(labels), size=output.shape[0], p=probabilities)
    end = min(output.shape[1], event_session + effect_sessions)
    for index, label in enumerate(labels):
        mask = selected == index
        if not mask.any():
            continue
        segment = output[mask, event_session:end]
        center = segment.mean(axis=0, keepdims=True)
        output[mask, event_session:end] = (
            center + (segment - center) * volatility_multipliers[label]
            + mean_shocks[label] / max(1, end - event_session)
        )
    return output
