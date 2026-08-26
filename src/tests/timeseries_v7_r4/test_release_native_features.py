from datetime import date, datetime, timezone

import pytest

from ai_fc.timeseries_v7_r4.release_native_features import (
    FEATURE_SCHEMA_HASH,
    TRANSFORM_HASH,
    MacroRevision,
    build_release_native_features,
)


UTC = timezone.utc


def _at(day: int) -> datetime:
    return datetime(2024, 3, day, 13, 30, tzinfo=UTC)


REVISIONS = (
    MacroRevision("CPI", date(2024, 1, 1), "jan-1", 3.0, _at(1)),
    MacroRevision("CPI", date(2024, 1, 1), "jan-2", 3.2, _at(2)),
    MacroRevision("CPI", date(2024, 2, 1), "feb-1", 3.5, _at(8)),
    MacroRevision("CPI", date(2024, 2, 1), "feb-2", 3.4, _at(9)),
    MacroRevision("CPI", date(2024, 2, 1), "future", 9.9, _at(20)),
)


def test_release_revision_surprise_age_and_innovation_are_distinct():
    row = build_release_native_features(
        REVISIONS, origin_cutoff_at=_at(12), expected_release_value=3.3,
        factor_loading=0.5, factor_innovation=0.2,
    )
    assert row.first_release_value == 3.5
    assert row.latest_known_at_origin == 3.4
    assert row.revision_amount == pytest.approx(-0.1)
    assert row.revision_count == 1
    assert row.revision_volatility == pytest.approx(0.1)
    assert row.change_since_previous_release == pytest.approx(0.3)
    assert row.release_surprise == pytest.approx(0.2)
    assert row.release_age_seconds == 4 * 86400
    assert row.revision_age_seconds == 3 * 86400
    assert row.filtered_factor_innovation == pytest.approx(0.2)
    assert row.source_revision_ids == ("feb-1", "feb-2")


def test_carry_forward_origin_does_not_manufacture_a_release():
    first = build_release_native_features(REVISIONS, origin_cutoff_at=_at(12))
    carried = build_release_native_features(REVISIONS, origin_cutoff_at=_at(15))
    assert first.release_observation_date == carried.release_observation_date
    assert first.release_count == carried.release_count == 2
    assert first.latest_known_at_origin == carried.latest_known_at_origin
    assert carried.release_age_seconds == first.release_age_seconds + 3 * 86400


def test_feature_schema_and_transform_hashes_are_frozen():
    assert FEATURE_SCHEMA_HASH == "46ad1485ee6cbfbbb027a0d21bb50ce4bca707def7ef075d770512c2b5d8cd43"
    assert TRANSFORM_HASH == "46b16a1c76ab9fcf12343fb62af91c102a362fa2155dc05930feb72293f803b0"
