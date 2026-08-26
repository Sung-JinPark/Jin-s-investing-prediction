from datetime import date, datetime, timezone

import pytest

from ai_fc.timeseries_v7_r4.feature_provenance import (
    FeatureProvenanceMatrix,
    FeatureValueProvenance,
)


def _instant(day: int, hour: int = 20) -> datetime:
    return datetime(2024, 3, day, hour, tzinfo=timezone.utc)


def _row(**overrides):
    values = {
        "origin_id": "XNAS:2024-03-11@xnas-test-v1",
        "origin_session": date(2024, 3, 11),
        "origin_cutoff_at": _instant(11),
        "feature_id": "GDP.latest_known",
        "feature_value": 1.1,
        "source_observation_ids": ("GDP:2023-12-01",),
        "source_revision_ids": ("GDP:2024-03-08",),
        "source_available_at": (_instant(8, 13),),
        "max_available_at": _instant(8, 13),
        "transformation_hash": "a" * 64,
        "age_seconds": 284400.0,
        "missing_policy": "reject",
        "data_grade": "official",
    }
    values.update(overrides)
    return FeatureValueProvenance(**values)


def test_every_active_value_requires_complete_revision_provenance():
    with pytest.raises(ValueError, match="source_revision_ids"):
        _row(source_revision_ids=())
    with pytest.raises(ValueError, match="same length"):
        _row(source_available_at=(_instant(8), _instant(9)))
    with pytest.raises(ValueError, match="max_available_at"):
        _row(max_available_at=_instant(7))


def test_matrix_checks_pit_invariant_for_every_active_feature():
    matrix = FeatureProvenanceMatrix([_row(), _row(feature_id="CPI.latest")])
    report = matrix.validate_active()
    assert report == {"active_features": 2, "pit_passed": 2, "pit_pass_rate": 1.0}

    with pytest.raises(ValueError, match="PIT invariant"):
        FeatureProvenanceMatrix([_row(source_available_at=(_instant(12),),
                                            max_available_at=_instant(12))])


def test_date_only_vintage_cannot_enter_its_same_session():
    with pytest.raises(ValueError, match="next eligible session"):
        _row(date_only_vintage_dates=(date(2024, 3, 11),))

    accepted = _row(date_only_vintage_dates=(date(2024, 3, 8),))
    assert FeatureProvenanceMatrix([accepted]).validate_active()["pit_pass_rate"] == 1.0


def test_origin_feature_coordinate_is_unique():
    with pytest.raises(ValueError, match="duplicate active origin-feature"):
        FeatureProvenanceMatrix([_row(), _row()])
