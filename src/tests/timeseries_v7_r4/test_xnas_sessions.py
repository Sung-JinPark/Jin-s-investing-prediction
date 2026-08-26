from datetime import datetime, timezone

import pytest

from ai_fc.timeseries_v7_r4.xnas_sessions import (
    XnasSessionCalendar,
    resolve_origin_session,
)


@pytest.fixture
def calendar():
    return XnasSessionCalendar.from_rows(
        version="xnas-test-v1",
        rows=[
            {"session_date": "2024-03-08", "close_time": "16:00"},
            {"session_date": "2024-03-11", "close_time": "16:00"},
            {"session_date": "2024-11-29", "close_time": "13:00"},
        ],
    )


def test_normal_close_and_dst_are_converted_to_utc(calendar):
    assert calendar.session("2024-03-08").cutoff_utc.isoformat() == "2024-03-08T21:00:00+00:00"
    assert calendar.session("2024-03-11").cutoff_utc.isoformat() == "2024-03-11T20:00:00+00:00"


def test_early_close_is_a_completed_session_at_its_real_close(calendar):
    assert calendar.session("2024-11-29").cutoff_utc.isoformat() == "2024-11-29T18:00:00+00:00"
    assert calendar.latest_completed(datetime(2024, 11, 29, 18, tzinfo=timezone.utc)).session_date.isoformat() == "2024-11-29"


def test_origin_cutoff_ignores_target_available_at(calendar):
    as_of = datetime(2024, 3, 11, 19, 59, tzinfo=timezone.utc)
    early_target = datetime(2024, 3, 8, 21, tzinfo=timezone.utc)
    late_target = datetime(2024, 3, 12, 12, tzinfo=timezone.utc)
    assert resolve_origin_session(calendar, as_of=as_of, target_available_at=early_target).session_date.isoformat() == "2024-03-08"
    assert resolve_origin_session(calendar, as_of=as_of, target_available_at=late_target).session_date.isoformat() == "2024-03-08"


def test_training_backtest_and_live_share_session_identity(calendar):
    as_of = datetime(2024, 3, 11, 20, tzinfo=timezone.utc)
    identities = {
        resolve_origin_session(calendar, as_of=as_of, mode=mode).identity
        for mode in ("training", "backtest", "live")
    }
    assert identities == {"XNAS:2024-03-11@xnas-test-v1"}


def test_rows_must_be_explicit_and_versioned():
    with pytest.raises(ValueError, match="version"):
        XnasSessionCalendar.from_rows(version="", rows=[])
    with pytest.raises(ValueError, match="close_time"):
        XnasSessionCalendar.from_rows(version="v1", rows=[{"session_date": "2024-03-11"}])
