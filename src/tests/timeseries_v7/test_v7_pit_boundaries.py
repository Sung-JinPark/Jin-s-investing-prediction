from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


from ai_fc.timeseries_v7.artifact_identity import identify_jsonl, verify_physical
from ai_fc.timeseries_v7.feature_lineage import FeatureValueLineage, prove_feature_pit
from ai_fc.timeseries_v7.fold_roles import FoldAssignment, validate_disjoint_roles
from ai_fc.timeseries_v7.folds import eligible_training_labels
from ai_fc.timeseries_v7.labels import label_interval
from ai_fc.timeseries_v7.lineage import ReceiptOutcome, reconcile_receipts
from ai_fc.timeseries_v7.revisions import ObservationRevision, reconstruct_as_of, validate_revision_chain


UTC = timezone.utc


def business_days(start: date, count: int) -> list[date]:
    values = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def test_logical_hash_cross_os_and_physical_verification() -> None:
    rows = [{"b": 2, "a": 1}, {"a": 3}]
    lf = b'{"a":1,"b":2}\n{"a":3}\n'
    crlf = lf.replace(b"\n", b"\r\n")
    linux = identify_jsonl(rows, lf, newline="lf")
    windows = identify_jsonl(rows, crlf, newline="crlf")
    assert linux.logical_rows_sha256 == windows.logical_rows_sha256
    assert linux.physical_artifact_sha256 != windows.physical_artifact_sha256
    assert verify_physical(linux, lf) and verify_physical(windows, crlf)


def test_every_receipt_has_exactly_one_terminal_outcome() -> None:
    assert reconcile_receipts(["r1", "r2"], [ReceiptOutcome("r1", "parsed_new", 2), ReceiptOutcome("r2", "empty_valid", 0)])["pass"]
    report = reconcile_receipts(["r1", "r2"], [ReceiptOutcome("r1", "parsed_new", 2)])
    assert report["orphan_receipts"] == ["r2"] and not report["pass"]


def revision(seq: int, available: int, supersedes: str | None, valid_to: int | None) -> ObservationRevision:
    return ObservationRevision(
        f"r{seq}", "key", seq, float(seq), datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2020, 1, available, tzinfo=UTC), datetime(2020, 1, available, 1, tzinfo=UTC),
        datetime(2020, 1, available, tzinfo=UTC),
        datetime(2020, 1, valid_to, tzinfo=UTC) if valid_to else None,
        "parser-v1", "a" * 64, supersedes,
    )


def test_revision_chain_and_asof_reconstruction() -> None:
    rows = [revision(0, 2, None, 5), revision(1, 5, "r0", None)]
    assert validate_revision_chain(rows) == tuple(rows)
    assert reconstruct_as_of(rows, datetime(2020, 1, 4, tzinfo=UTC)).revision_id == "r0"
    assert reconstruct_as_of(rows, datetime(2020, 1, 6, tzinfo=UTC)).revision_id == "r1"


def test_feature_lineage_blocks_future_available_at() -> None:
    cutoff = datetime(2026, 1, 2, 21, tzinfo=UTC)
    good = FeatureValueLineage("o", "f", 1.0, cutoff, cutoff - timedelta(hours=1), ("r",), "h", "none", False)
    assert prove_feature_pit([good])["pass"]
    bad = FeatureValueLineage("o", "f", 1.0, cutoff, cutoff + timedelta(seconds=1), ("r",), "h", "none", False)
    assert prove_feature_pit([bad])["violations"] == ["o:f:future_available_at"]


def test_session_labels_and_h63_purge_exclude_about_fourteen_weekly_origins() -> None:
    sessions = business_days(date(2024, 1, 2), 260)
    weekly_indices = list(range(0, 180, 5))
    labels = [label_interval(sessions, i, 63, mature_at=datetime(2025, 1, 1, tzinfo=UTC)) for i in weekly_indices]
    validation_origin = sessions[140]
    eligible = eligible_training_labels(labels, validation_origin, sessions, embargo_sessions=5)
    raw_before = [row for row in labels if row.origin_session < validation_origin]
    excluded = len(raw_before) - len(eligible)
    assert 13 <= excluded <= 15
    assert excluded != 68


def test_holiday_gap_still_uses_sessions_not_days() -> None:
    sessions = business_days(date(2024, 12, 2), 90)
    sessions.remove(date(2024, 12, 25))
    row = label_interval(sessions, 0, 63, mature_at=datetime(2025, 3, 1, tzinfo=UTC))
    validation = sessions[69]
    assert eligible_training_labels([row], validation, sessions, embargo_sessions=5) == [row]


def test_fold_roles_reject_same_origin_and_overlapping_intervals() -> None:
    left = FoldAssignment("candidate_selection", date(2020, 1, 1), date(2020, 1, 2), date(2020, 2, 1))
    right = FoldAssignment("stacking", date(2020, 1, 1), date(2020, 1, 15), date(2020, 2, 15))
    report = validate_disjoint_roles([left, right])
    assert not report["pass"] and report["violation_count"] == 2


def test_fold_roles_accept_separated_intervals() -> None:
    left = FoldAssignment("candidate_selection", date(2020, 1, 1), date(2020, 1, 2), date(2020, 2, 1))
    right = FoldAssignment("stacking", date(2020, 3, 1), date(2020, 3, 2), date(2020, 4, 1))
    assert validate_disjoint_roles([left, right])["pass"]
