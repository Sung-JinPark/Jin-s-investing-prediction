from datetime import date, datetime, timezone

import pytest

from ai_fc.timeseries_v7_r4.five_role_validation import (
    ROLE_ORDER,
    RoleFold,
    build_five_role_fold,
    validate_interval_disjointness,
)
from ai_fc.timeseries_v7_r4.pit_snapshot import LabelInterval
from ai_fc.timeseries_v7_r4.xnas_sessions import XnasSessionCalendar


def _calendar(days):
    return XnasSessionCalendar.from_rows(
        version="test-v1",
        rows=[{"session_date": day, "close_time": "16:00"} for day in days],
    )


def _label(name, origin, start, end):
    return LabelInterval(
        target_id=name,
        origin_session=date.fromisoformat(origin),
        label_start_session=date.fromisoformat(start),
        label_end_session=date.fromisoformat(end),
        mature_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        horizon_sessions=1,
        value=0.0,
    )


def test_five_roles_are_disjoint_by_closed_label_interval():
    days = [f"2024-01-{day:02d}" for day in range(2, 20)]
    calendar = _calendar(days)
    labels = [
        _label("train-safe", days[0], days[1], days[2]),
        # Its origin is in train, but its label crosses into selection.
        _label("train-leak", days[2], days[3], days[6]),
        _label("selection", days[6], days[7], days[7]),
        _label("stacking", days[9], days[10], days[10]),
        _label("calibration", days[12], days[13], days[13]),
        _label("outer", days[15], days[16], days[16]),
    ]
    fold = build_five_role_fold(
        labels=labels,
        calendar=calendar,
        role_origin_sessions={
            "train": days[:4], "selection": days[6:8], "stacking": days[9:11],
            "calibration": days[12:14], "outer": days[15:17],
        },
        purge_sessions=1,
        embargo_sessions=1,
    )

    assert tuple(fold.labels_by_role) == ROLE_ORDER
    assert "train-leak" in fold.excluded_target_ids
    assert validate_interval_disjointness(fold) is None


def test_purge_and_embargo_count_calendar_sessions_not_sparse_rows():
    # Weekly-looking rows surround daily sessions. A row-count implementation
    # would retain `too-close`; the session-distance contract must reject it.
    days = [f"2024-01-{day:02d}" for day in range(2, 16)]
    calendar = _calendar(days)
    fold = build_five_role_fold(
        labels=[
            _label("too-close", days[0], days[1], days[7]),
            _label("selection", days[9], days[10], days[10]),
        ],
        calendar=calendar,
        role_origin_sessions={
            "train": [days[0]], "selection": [days[9]], "stacking": [],
            "calibration": [], "outer": [],
        },
        purge_sessions=2,
        embargo_sessions=1,
    )
    assert fold.excluded_target_ids["too-close"] == "purge_or_embargo_overlap:selection"


def test_adversarial_overlap_validator_rejects_touching_intervals():
    shared = _label("a", "2024-01-02", "2024-01-03", "2024-01-05")
    touching = _label("b", "2024-01-08", "2024-01-05", "2024-01-09")
    fold = RoleFold(
        labels_by_role={role: (() if role not in ("train", "selection") else
                               ((shared,) if role == "train" else (touching,)))
                        for role in ROLE_ORDER},
        excluded_target_ids={}, calendar_version="test-v1",
        purge_sessions=0, embargo_sessions=0,
    )
    with pytest.raises(ValueError, match="label interval overlap"):
        validate_interval_disjointness(fold)
