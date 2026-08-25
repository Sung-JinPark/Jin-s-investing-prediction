"""Feature values with exact observation-version and transformation lineage."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

from .pit import OriginSeriesValue


class FeatureProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeatureValue:
    feature_id: str
    origin_id: str
    feature_name: str
    value: float
    unit: str
    transformation_id: str
    input_observation_version_ids: tuple[str, ...]
    max_input_available_at: str
    provenance_sha256: str


def materialize_feature(
    *,
    origin_id: str,
    origin_cutoff_at: datetime,
    feature_name: str,
    unit: str,
    transformation_id: str,
    inputs: Sequence[OriginSeriesValue],
    transform: Callable[[tuple[float, ...]], float],
) -> FeatureValue:
    if origin_cutoff_at.tzinfo is None or origin_cutoff_at.utcoffset() is None:
        raise FeatureProvenanceError("origin cutoff must be timezone-aware")
    if not inputs:
        raise FeatureProvenanceError("feature inputs must not be empty")
    cutoff = origin_cutoff_at.astimezone(timezone.utc)
    ordered = tuple(sorted(inputs, key=lambda row: (row.source_id, row.series_id, row.observation_time, row.observation_version_id)))
    if any(row.origin_id != origin_id for row in ordered):
        raise FeatureProvenanceError("feature inputs cross origin boundaries")
    if any(row.available_at.astimezone(timezone.utc) > cutoff for row in ordered):
        raise FeatureProvenanceError("feature contains future-available input")
    value = float(transform(tuple(row.value for row in ordered)))
    if not math.isfinite(value):
        raise FeatureProvenanceError("feature value must be finite")
    ids = tuple(row.observation_version_id for row in ordered)
    max_available = max(row.available_at for row in ordered).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    material = {
        "origin_id": origin_id,
        "feature_name": feature_name,
        "value": value,
        "unit": unit,
        "transformation_id": transformation_id,
        "input_observation_version_ids": ids,
        "max_input_available_at": max_available,
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return FeatureValue(
        feature_id=f"tsv6-feature-{digest[:24]}",
        origin_id=origin_id,
        feature_name=feature_name,
        value=value,
        unit=unit,
        transformation_id=transformation_id,
        input_observation_version_ids=ids,
        max_input_available_at=max_available,
        provenance_sha256=digest,
    )


def log_change(values: tuple[float, ...]) -> float:
    if len(values) != 2 or min(values) <= 0:
        raise FeatureProvenanceError("log change requires two positive inputs")
    return math.log(values[1] / values[0])
