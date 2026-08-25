from datetime import datetime, timedelta, timezone

import pytest

from ai_fc.timeseries_v6.feature_provenance import FeatureProvenanceError, log_change, materialize_feature
from ai_fc.timeseries_v6.pit import Origin, PitObservation, point_in_time_join


CUTOFF = datetime(2026, 8, 21, 20, 15, tzinfo=timezone.utc)


def _observation(version: str, value: float, *, available: datetime, revision: int = 0) -> PitObservation:
    return PitObservation(version, "fred_alfred", "NASDAQCOM", datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc), available, revision, value, "index_points")


def test_revision_is_invisible_before_available_at_and_visible_after() -> None:
    original = _observation("v0", 100.0, available=CUTOFF - timedelta(minutes=10))
    revision = _observation("v1", 101.0, available=CUTOFF + timedelta(days=1), revision=1)
    before = point_in_time_join([Origin("before", CUTOFF)], [original, revision], required_series=[("fred_alfred", "NASDAQCOM")])
    assert before.values[0].observation_version_id == "v0"
    after = point_in_time_join([Origin("after", CUTOFF + timedelta(days=2))], [original, revision], required_series=[("fred_alfred", "NASDAQCOM")])
    assert after.values[0].observation_version_id == "v1"


def test_missing_is_explicit_not_date_forward_filled() -> None:
    snapshot = point_in_time_join([Origin("origin", CUTOFF)], [], required_series=[("fred_alfred", "NASDAQCOM")])
    assert snapshot.values == ()
    assert snapshot.missing == (("origin", "fred_alfred", "NASDAQCOM"),)


def test_feature_hash_binds_exact_versions_and_rejects_cross_origin() -> None:
    prior = _observation("prior", 100.0, available=CUTOFF - timedelta(days=1))
    prior = PitObservation(**{**prior.__dict__, "observation_time": prior.observation_time - timedelta(days=1)})
    current = _observation("current", 102.0, available=CUTOFF - timedelta(minutes=1))
    joined = point_in_time_join(
        [Origin("origin", CUTOFF)], [prior, current], required_series=[("fred_alfred", "NASDAQCOM")]
    )
    current_value = joined.values[0]
    prior_value = current_value.__class__(**{**current_value.__dict__, "value": 100.0, "observation_version_id": "prior", "observation_time": current_value.observation_time - timedelta(days=1)})
    feature = materialize_feature(
        origin_id="origin", origin_cutoff_at=CUTOFF, feature_name="nasdaq_log_return",
        unit="signed_fraction", transformation_id="log_change_v1",
        inputs=[prior_value, current_value], transform=log_change,
    )
    assert feature.input_observation_version_ids == ("prior", "current")
    foreign = current_value.__class__(**{**current_value.__dict__, "origin_id": "foreign"})
    with pytest.raises(FeatureProvenanceError, match="cross origin"):
        materialize_feature(
            origin_id="origin", origin_cutoff_at=CUTOFF, feature_name="x", unit="x",
            transformation_id="identity", inputs=[foreign], transform=lambda values: values[0],
        )
