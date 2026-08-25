from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from ai_fc.timeseries_v7.collectors.base import Request, Response, collect, schema_fingerprint
from ai_fc.timeseries_v7.collectors.cboe import after_close_available_at, normalize_close
from ai_fc.timeseries_v7.collectors.cftc import CftcSnapshot, independent_snapshot_count as cftc_count
from ai_fc.timeseries_v7.collectors.events import EventSnapshot, independent_resolved_event_count
from ai_fc.timeseries_v7.collectors.fed_probability import RateProbabilitySnapshot, independent_snapshot_count as rate_count
from ai_fc.timeseries_v7.collectors.fred_alfred import parse_vintages
from ai_fc.timeseries_v7.collectors.liquidity import freshness
from ai_fc.timeseries_v7.collectors.macro_official import OfficialRelease, validate_releases
from ai_fc.timeseries_v7.collectors.options import model_weight
from ai_fc.timeseries_v7.collectors.reports import ReportEvidence, cluster_count, evidence_hash
from ai_fc.timeseries_v7.collectors.sec import FilingFact, facts_as_of
from ai_fc.timeseries_v7.data_gate import decide_data_gate
from ai_fc.timeseries_v7.features import materialize
from ai_fc.timeseries_v7.feature_lineage import prove_feature_pit
from ai_fc.timeseries_v7.lineage import ReceiptOutcome
from ai_fc.timeseries_v7.reconcile import reconcile
from ai_fc.timeseries_v7.schema_drift import decide_schema


UTC = timezone.utc


class MemoryStore:
    def __init__(self): self.values = {}
    def put_if_absent(self, key, body):
        created = key not in self.values; self.values.setdefault(key, body); return created


def test_collector_retries_pages_etag_and_is_idempotent() -> None:
    bodies = [json.dumps([{"a": 1}]).encode(), json.dumps([{"a": 2}]).encode()]
    calls = []
    def transport(request):
        calls.append(request.page_token)
        if len(calls) == 1: raise TimeoutError
        index = 0 if request.page_token is None else 1
        return Response(200, bodies[index], {"etag": "v1", "last-modified": "now"}, "p2" if index == 0 else None)
    store = MemoryStore(); request = Request("s", "https://example.invalid", datetime.now(UTC))
    first = collect(request, transport, store, max_attempts=3)
    assert first.outcome == "parsed_new" and first.attempts == 3 and len(first.object_hashes) == 2
    calls.clear(); second = collect(request, transport, store, max_attempts=3)
    assert second.outcome == "unchanged" and len(store.values) == 2


def test_schema_change_is_quarantined_before_parse() -> None:
    body = b'[{"new":1}]'; observed = schema_fingerprint(body)
    assert decide_schema("s", observed, "0" * 64).state == "schema_quarantine"
    result = collect(Request("s", "x", datetime.now(UTC)), lambda _: Response(200, body, {}), MemoryStore(), known_schema="0" * 64)
    assert result.outcome == "quarantined" and not result.object_hashes


def test_alfred_two_vintages_are_reconstructed() -> None:
    rows = parse_vintages("PAYEMS", [
        {"date": "2020-01-01", "realtime_start": "2020-02-07", "realtime_end": "2020-03-05", "value": "1"},
        {"date": "2020-01-01", "realtime_start": "2020-03-06", "realtime_end": "9999-12-31", "value": "2"},
    ], ingested_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert [row["value"] for row in rows] == [1.0, 2.0]
    assert all(row["data_grade"] == "native_pit" for row in rows)


def test_cboe_after_close_handles_dst() -> None:
    winter = after_close_available_at(date(2026, 1, 5)); summer = after_close_available_at(date(2026, 7, 6))
    assert winter.hour == 21 and summer.hour == 20
    with pytest.raises(ValueError, match="before"):
        normalize_close("VIX", date(2026, 7, 6), 20, fetched_at=summer - timedelta(seconds=1))


def test_liquidity_stale_never_silently_carries() -> None:
    cutoff = datetime(2026, 8, 25, tzinfo=UTC)
    report = freshness("OFR_FSI", cutoff - timedelta(days=5), cutoff)
    assert report["state"] == "stale" and report["eligible"] is False and report["carry_forward"] is False


def test_macro_release_revision_chain_and_late_revision() -> None:
    first = OfficialRelease("BLS", "PAYEMS", "2026-07", "r0", datetime(2026, 8, 7, 12, 30, tzinfo=UTC), 100, 0)
    second = OfficialRelease("BLS", "PAYEMS", "2026-07", "r1", datetime(2026, 9, 4, 12, 30, tzinfo=UTC), 90, 1, "r0")
    validate_releases([first, second])


def test_cftc_expanded_rows_do_not_inflate_snapshot_count() -> None:
    snap = CftcSnapshot(date(2026, 8, 18), datetime(2026, 8, 21, 19, 30, tzinfo=UTC), "209742", ({"long": 1}, {"short": 2}))
    assert cftc_count([snap, snap]) == 1


def test_sec_filing_is_unavailable_before_accepted_at() -> None:
    accepted = datetime(2026, 8, 10, 20, tzinfo=UTC)
    fact = FilingFact("acc", "1", accepted, "2026Q2", "Revenue", 1)
    assert facts_as_of([fact], accepted - timedelta(seconds=1)) == []
    assert facts_as_of([fact], accepted) == [fact]


def test_event_count_requires_pre_event_snapshot_and_resolved_actual() -> None:
    scheduled = datetime(2026, 8, 7, 12, 30, tzinfo=UTC)
    pre = EventSnapshot("jobs-1", scheduled, scheduled - timedelta(hours=1), 100, 10)
    actual = EventSnapshot("jobs-1", scheduled, scheduled + timedelta(minutes=1), 100, 10, 80, scheduled + timedelta(minutes=1))
    duplicate = EventSnapshot("jobs-1", scheduled, scheduled - timedelta(days=1), 99, 11)
    assert independent_resolved_event_count([pre, actual, duplicate], scheduled + timedelta(days=1)) == 1


def test_rate_vector_snapshot_count_and_entropy() -> None:
    snap = RateProbabilitySnapshot("s1", datetime.now(UTC), (("2026-09", (0.25, 0.75)), ("2026-12", (0.5, 0.5))))
    assert rate_count([snap, snap]) == 1 and snap.entropy() > 0
    with pytest.raises(ValueError): RateProbabilitySnapshot("bad", datetime.now(UTC), (("m", (0.8, 0.8)),))


def test_uncalibrated_options_have_zero_weight() -> None:
    assert model_weight(captured_origins=125, physical_calibration_pass=True) == 0
    assert model_weight(captured_origins=126, physical_calibration_pass=False) == 0
    assert model_weight(captured_origins=126, physical_calibration_pass=True) == 1


def test_report_duplicates_cluster_and_cannot_carry_return_number() -> None:
    digest = evidence_hash("AI capex accelerates")
    row = ReportEvidence("report", datetime.now(UTC), datetime.now(UTC), "12m", "NASDAQ", "1", "capex", digest)
    assert cluster_count([row, row]) == 1
    assert not hasattr(row, "forecast_return")


def test_reconciliation_partition_is_deterministic() -> None:
    one = reconcile(["r"], [ReceiptOutcome("r", "parsed_new", 1)], [], [{"b": 2, "a": 1}])
    two = reconcile(["r"], [ReceiptOutcome("r", "parsed_new", 1)], [], [{"a": 1, "b": 2}])
    assert one["pass"] and one["partition_logical_sha256"] == two["partition_logical_sha256"]


def test_feature_materializer_preserves_origins_and_explicit_missingness() -> None:
    cutoff = datetime(2026, 8, 25, tzinfo=UTC)
    rows = materialize([("o1", cutoff), ("o2", cutoff)], ["f"], lambda feature, at: None if feature == "f" else None, transformation_hashes={"f": "h"})
    assert len(rows) == 2 and all(row.missing for row in rows)
    assert prove_feature_pit(rows)["pass"]


def test_data_gate_blocks_invalid_and_waits_without_new_evidence() -> None:
    assert decide_data_gate(pit_pass=False, receipt_pass=True, freshness_pass=True, missingness_rate=0, missingness_max=.1, new_evidence=True, drift_alert=False)["state"] == "BLOCKED_INVALID_SNAPSHOT"
    assert decide_data_gate(pit_pass=True, receipt_pass=True, freshness_pass=True, missingness_rate=0, missingness_max=.1, new_evidence=False, drift_alert=False)["state"] == "WAIT_DATA"
