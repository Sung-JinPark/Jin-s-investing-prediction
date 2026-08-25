from datetime import datetime, timedelta, timezone

import pytest

from ai_fc.timeseries_v6.availability import AvailabilityError, AvailabilityPolicy, age_since_release, eligible_at
from ai_fc.timeseries_v6.sessions import last_completed_xnas_session, missing_completed_sessions


def test_native_pit_requires_published_timestamp_and_forward_uses_capture() -> None:
    observation = datetime(2026, 8, 1, tzinfo=timezone.utc)
    capture = datetime(2026, 8, 7, 12, 30, tzinfo=timezone.utc)
    native = AvailabilityPolicy("alfred_v1", "native_pit", timedelta(0), "challenger_or_prospective_only")
    with pytest.raises(AvailabilityError, match="require"):
        native.available_at(observation_time=observation, published_at=None, captured_at=capture)
    assert native.available_at(observation_time=observation, published_at=capture, captured_at=capture) == capture
    forward = AvailabilityPolicy("event_v1", "captured_forward", timedelta(0), "challenger_or_prospective_only")
    assert forward.available_at(observation_time=observation, published_at=None, captured_at=capture) == capture


def test_pit_boundary_is_inclusive_and_age_rejects_future() -> None:
    cutoff = datetime(2026, 8, 7, 12, 30, tzinfo=timezone.utc)
    assert eligible_at(available_at=cutoff, origin_cutoff_at=cutoff)
    assert age_since_release(available_at=cutoff - timedelta(days=1), origin_cutoff_at=cutoff) == timedelta(days=1)
    with pytest.raises(AvailabilityError, match="future"):
        age_since_release(available_at=cutoff + timedelta(seconds=1), origin_cutoff_at=cutoff)


def test_xnas_completed_session_handles_weekend_and_early_close_without_off_by_one() -> None:
    saturday = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    session = last_completed_xnas_session(saturday)
    assert session.session_label == "2026-08-21"
    assert missing_completed_sessions(last_observed_session="2026-08-20", as_of=saturday) == 1
    assert missing_completed_sessions(last_observed_session="2026-08-21", as_of=saturday) == 0
    early_close = last_completed_xnas_session(datetime(2025, 11, 28, 19, 0, tzinfo=timezone.utc))
    assert early_close.session_label == "2025-11-28"
    assert early_close.close_at.hour == 18
