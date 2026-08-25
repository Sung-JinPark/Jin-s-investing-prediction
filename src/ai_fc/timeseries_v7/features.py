"""PIT feature materializer that never drops target sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .feature_lineage import FeatureValueLineage


def materialize(origins: list[tuple[str, datetime]], feature_ids: list[str], resolver: Callable[[str, datetime], tuple[float, datetime, tuple[str, ...]] | None], *, transformation_hashes: dict[str, str]) -> list[FeatureValueLineage]:
    rows = []
    for origin_id, cutoff in origins:
        for feature_id in feature_ids:
            result = resolver(feature_id, cutoff)
            if result is None:
                rows.append(FeatureValueLineage(origin_id, feature_id, None, cutoff, None, (), transformation_hashes[feature_id], "explicit_missing_no_imputation", True))
            else:
                value, available, revisions = result
                if available > cutoff:
                    raise ValueError("resolver returned future observation")
                rows.append(FeatureValueLineage(origin_id, feature_id, value, cutoff, available, revisions, transformation_hashes[feature_id], "none", False))
    return rows
