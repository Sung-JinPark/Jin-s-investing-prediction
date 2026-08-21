"""Optional structured analyst signals; free-text numeric shifts are impossible here."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .contracts import canonical_hash


@dataclass(frozen=True)
class ReportSignal:
    report_id: str
    provider: str
    published_at: str
    available_at: str
    asset_scope: str
    forecast_horizon: str
    target_type: str
    numeric_value: float | None
    prior_numeric_value: float | None
    direction: str
    confidence_language: str
    cited_data_cutoff: str
    extraction_model: str
    extraction_schema_version: int
    raw_sha256: str
    duplicate_cluster_id: str
    revision_of: str | None = None

    @property
    def signal_id(self) -> str:
        return "tsv3-report-" + canonical_hash(asdict(self))[:24]

    def validate(self) -> None:
        if not self.published_at or not self.available_at or self.available_at < self.published_at:
            raise ValueError("report publication and availability timestamps are required")
        if self.direction not in {"up", "down", "neutral"}:
            raise ValueError("report direction must be structured")
        if not self.raw_sha256 or not self.duplicate_cluster_id:
            raise ValueError("report receipt and duplicate cluster are required")


def append_report_signal(path: Path, row: ReportSignal) -> bool:
    row.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = read_report_signals(path)
    existing = {item.signal_id for item in stored}
    if row.signal_id in existing:
        return False
    if row.revision_of is not None and row.revision_of not in existing:
        raise ValueError("report revision_of must name an existing immutable signal")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"signal_id": row.signal_id, **asdict(row)}, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def read_report_signals(path: Path) -> list[ReportSignal]:
    if not path.is_file():
        return []
    output: list[ReportSignal] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        payload.pop("signal_id", None)
        output.append(ReportSignal(**payload))
    return output


def aggregate_report_signal(
    rows: list[ReportSignal], *, cutoff: str, provider_reliability: dict[str, float],
) -> tuple[float, int]:
    eligible = [row for row in rows if row.available_at <= cutoff]
    # Same underlying consensus or syndicated note counts only once.
    deduplicated: dict[str, ReportSignal] = {}
    for row in eligible:
        current = deduplicated.get(row.duplicate_cluster_id)
        if current is None or row.available_at > current.available_at:
            deduplicated[row.duplicate_cluster_id] = row
    weighted: list[float] = []
    weights: list[float] = []
    for row in deduplicated.values():
        if row.numeric_value is None:
            continue
        direction = {"down": -1.0, "neutral": 0.0, "up": 1.0}[row.direction]
        reliability = float(np.clip(provider_reliability.get(row.provider, 0.0), 0.0, 1.0))
        weighted.append(direction * float(row.numeric_value))
        weights.append(reliability)
    if not weights or sum(weights) <= 0:
        return 0.0, 0
    return float(np.average(weighted, weights=weights)), len(weights)
