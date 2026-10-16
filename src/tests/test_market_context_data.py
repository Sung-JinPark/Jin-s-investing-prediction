"""Temporary-only integrity and calendar tests for current-conditions inputs."""
from __future__ import annotations

import gzip
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ai_fc.market_context import collectors as K, contracts as C, features as F, ledger as L


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    original = Path(__file__).resolve().parents[2] / C.CONTRACT_RELATIVE
    destination = tmp_path / C.CONTRACT_RELATIVE
    destination.parent.mkdir(parents=True)
    destination.write_bytes(original.read_bytes())
    return tmp_path


def event(root: Path, *, revision="r1", acquired="2026-10-14T14:00:00+00:00", published="2026-10-14T12:30:00+00:00", supersedes=None):
    receipt = L.persist_raw(root, source_id="bls_cpi", url="https://www.bls.gov/feed/cpi.rss",
                            body=revision.encode(), retrieved_at=acquired)
    return {"event_id": "cpi-oct", "revision_id": revision, "supersedes": supersedes,
            "family": "cpi_release", "axis": "inflation", "kind": "economic_release", "title": "CPI release",
            "reference_period": "2026-09", "metric": "headline_cpi_mom", "published_at": published, "available_at": published,
            "retrieved_at": acquired, "source_id": "bls_cpi", "source_url": "https://www.bls.gov/cpi/",
            "source_sha256": receipt["source_sha256"], "raw_path": receipt["raw_path"], "dedupe_key": revision,
            "actual": .3, "expectation": .2, "standardization_scale": .1,
            "unit_metadata": {"actual": "percentage_points", "expectation": "percentage_points"},
            "expectation_kind": "market_consensus", "expectation_available_at": "2026-10-13T12:00:00+00:00",
            "scale_as_of": "2026-10-13T12:00:00+00:00", "scale_sample_count": 30,
            "surprise_z": 1., "numerical_eligible": True, "reason": "test_fixture"}


def test_future_acquisition_and_superseder_do_not_erase_earlier_fact(repo):
    first = event(repo)
    assert L.append_event(repo, first)
    correction = event(repo, revision="r2", acquired="2026-10-16T14:00:00+00:00",
                       published="2026-10-16T12:30:00+00:00", supersedes="r1")
    assert L.append_event(repo, correction)
    assert L.read_events(repo, as_of="2026-10-14T13:00:00+00:00") == []
    assert [row["revision_id"] for row in L.read_events(repo, as_of="2026-10-15T14:00:00+00:00")] == ["r1"]
    assert [row["revision_id"] for row in L.read_events(repo, as_of="2026-10-17T14:00:00+00:00")] == ["r2"]
    assert len(L.read_jsonl(repo / L.EVENTS)) == 2


def test_event_retry_is_idempotent_and_conflicting_revision_rejected(repo):
    row = event(repo)
    assert L.append_event(repo, row)
    before = (repo / L.EVENTS).read_bytes()
    assert not L.append_event(repo, row)
    conflicting = {**row, "title": "changed"}
    with pytest.raises(C.MarketContextError, match="append-only"):
        L.append_event(repo, conflicting)
    assert before == (repo / L.EVENTS).read_bytes()


def test_republished_duplicate_is_not_a_second_shock(repo):
    row = event(repo)
    assert L.append_event(repo, row)
    duplicate = {**row, "event_id": "second-copy", "revision_id": "copy"}
    assert not L.append_event(repo, duplicate)
    assert len(L.read_events(repo, as_of="2026-10-15T14:00:00+00:00")) == 1


@pytest.mark.parametrize("changes,match", [
    ({"unit_metadata": {"actual": "fraction", "expectation": "percent"}}, "units"),
    ({"standardization_scale": 0}, "positive"),
    ({"surprise_z": 5}, "reconcile"),
    ({"actual": float("nan")}, "finite"),
    ({"published_at": "2026-10-14T12:00:00"}, "timezone"),
    ({"expectation_available_at": "2026-10-14T12:31:00+00:00"}, "predate"),
    ({"metric": None}, "fact identity"),
    ({"reference_period": None}, "fact identity"),
    ({"supersedes": "absent"}, "first event"),
])
def test_bad_event_has_auditable_rejection_and_no_append(repo, changes, match):
    row = {**event(repo), **changes}
    with pytest.raises(C.MarketContextError, match=match):
        L.append_event(repo, row)
    assert not (repo / L.EVENTS).exists()


def test_raw_hash_and_receipt_are_required(repo):
    row = event(repo)
    (repo / row["raw_path"]).write_bytes(gzip.compress(b"tampered"))
    with pytest.raises(C.MarketContextError, match="hash mismatch"):
        L.append_event(repo, row)


def test_raw_storage_rejects_credentials(repo):
    with pytest.raises(C.MarketContextError, match="credentials"):
        L.persist_raw(repo, source_id="bad", url="https://example.org/?api_key=credential",
                      body=b"x", retrieved_at="2026-10-15T00:00:00+00:00")


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        stamp = datetime(2026, 10, 15, 5, 20, tzinfo=timezone.utc)
        return stamp.astimezone(tz) if tz is not None else stamp


def _sources(root, sources):
    path = root / C.CONTRACT_RELATIVE
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    contract["sources"] = sources
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")


def test_public_collection_preserves_metadata_failure_and_deduplication(repo, monkeypatch):
    monkeypatch.setattr(K, "datetime", FrozenDateTime)
    _sources(repo, [
        {"id": "bls_cpi", "url": "https://www.bls.gov/feed/cpi.rss", "format": "rss", "family": "cpi_release", "axis": "inflation"},
        {"id": "broken", "url": "https://example.org/broken", "format": "rss"},
    ])
    xml = b'<rss><channel><item><title>Consumer Price Index release</title><link>https://www.bls.gov/cpi/release.htm</link><pubDate>Wed, 14 Oct 2026 12:30:00 GMT</pubDate></item></channel></rss>'
    def fetch(url):
        if "broken" in url:
            raise TimeoutError("fixture unavailable")
        return xml
    first = K.collect_context(repo, fetcher=fetch)
    assert first["status"] == "degraded"
    assert first["counts"]["events_appended"] == 1
    assert first["sources"][1]["status"] == "failed"
    second = K.collect_context(repo, fetcher=fetch)
    assert second["counts"]["events_appended"] == 0
    rows = L.read_events(repo, as_of="2026-10-15T06:00:00+00:00")
    assert len(rows) == 1
    assert not rows[0]["numerical_eligible"]
    assert rows[0]["published_at"] == "2026-10-14T12:30:00+00:00"
    assert rows[0]["retrieved_at"] == "2026-10-15T05:20:00+00:00"
    verification = L.verify_store(repo)
    assert verification["ok"] and len(verification["source_failures"]) == 1


def test_current_csv_is_forward_capture_with_explicit_revisions(repo, monkeypatch):
    monkeypatch.setattr(K, "datetime", FrozenDateTime)
    _sources(repo, [{"id": "fred_nasdaq", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM", "format": "fred_csv", "series_id": "NASDAQCOM"}])
    body = b"observation_date,NASDAQCOM\n2026-10-13,100\n2026-10-14,101\n"
    assert K.collect_context(repo, fetcher=lambda _: body)["counts"]["observations_appended"] == 2
    assert K.collect_context(repo, fetcher=lambda _: body)["counts"]["observations_appended"] == 0
    changed = body.replace(b"101", b"102")
    assert K.collect_context(repo, fetcher=lambda _: changed)["counts"]["observations_appended"] == 1
    rows = L.read_jsonl(repo / L.OBSERVATIONS)
    assert rows[-1]["supersedes"] == rows[1]["observation_id"]
    assert not rows[-1]["historical_pit_eligible"]
    assert not F.read_market_rows(repo, as_of="2026-10-14T23:59:59+00:00")
    assert F.read_market_rows(repo, as_of="2026-10-15T06:00:00+00:00")[-1]["value"] == 102


def _panel(root, ending="2026-11-27"):
    import exchange_calendars as xcals
    import pyarrow as pa
    import pyarrow.parquet as pq
    calendar = xcals.get_calendar("XNAS", start="2024-01-01", end="2028-12-31")
    labels = calendar.sessions_in_range("2024-01-02", ending)[-253:]
    rows = [{"source_id": "alfred", "series_id": "NASDAQCOM", "observation_time": label.date().isoformat(),
             "value": 100. + index / 10, "value_status": "ok", "available_at": "2026-11-27T18:05:00+00:00",
             "vintage_start": "2026-11-27T18:05:00+00:00", "vintage_end": None,
             "retrieved_at": "2026-11-27T18:10:00+00:00", "source_hash": "a" * 64}
            for index, label in enumerate(labels)]
    path = root / "data/timeseries/facts/observations.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return rows


def test_real_exchange_half_day_after_close_event_waits_until_next_close(repo):
    import exchange_calendars as xcals
    rows = _panel(repo)
    row = event(repo, acquired="2026-11-27T18:01:00+00:00", published="2026-11-27T17:00:00+00:00")
    L.append_event(repo, row)
    bundle = F.load_inputs(repo, as_of="2026-11-27T18:30:00+00:00")
    assert bundle["gate"]["pass"]
    assert bundle["anchor_date"] == "2026-11-27"
    assert bundle["future_dates"][0] == "2026-11-30"
    assert len(bundle["future_dates"]) == 252
    assert bundle["events"][0]["effective_session"] == "2026-11-30"
    assert bundle["lineage"]["calendar"]["requested"] == "XNAS"
    assert bundle["lineage"]["calendar"]["library_version"] == xcals.__version__
    assert bundle["lineage"]["calendar"]["future_dates_sha256"] == L.digest(bundle["future_dates"])
    assert bundle["lineage"]["calendar"]["completed_dates_sha256"] == L.digest(bundle["session_dates"])
    assert bundle["lineage"]["calendar"]["history_dates_sha256"] == L.digest(bundle["dates"])
    assert bundle["history"]["index"] == [row["value"] for row in rows]


def test_missing_current_session_and_late_native_capture_hold(repo):
    _panel(repo)
    unavailable = F.load_inputs(repo, as_of="2026-11-27T18:06:00+00:00")
    assert not unavailable["gate"]["pass"]
    assert unavailable["closes"] == []
    stale = F.load_inputs(repo, as_of="2026-11-30T22:00:00+00:00")
    assert not stale["gate"]["pass"]
    assert "stale_or_missing_index_anchor" in stale["gate"]["reasons"]


def test_first_capture_does_not_manufacture_historical_model_expectations():
    rows = [{"series_id": "VIXCLS", "value": 10. + index * .1 + (index % 3) * .01,
             "observation_time": f"2026-09-{index % 28 + 1:02}", "available_at": "2026-10-15T05:00:00+00:00",
             "retrieved_at": "2026-10-15T05:00:00+00:00", "source_id": "fred_vix",
             "source_sha256": "a" * 64, "data_grade": "captured_current_vintage"} for index in range(40)]
    events = F._innovation_events(rows)
    assert len(events) == 1
    assert not events[0]["numerical_eligible"]
    assert events[0]["surprise_z"] is None
    assert events[0]["expectation_kind"] == "model_innovation"


def test_next_day_capture_preserves_prior_availability_and_same_story_age(repo, monkeypatch):
    monkeypatch.setattr(K, "datetime", FrozenDateTime)
    _sources(repo, [{"id": "fred_vix", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
                     "format": "fred_csv", "series_id": "VIXCLS"}])
    import exchange_calendars as xcals
    labels = xcals.get_calendar("XNAS", start="2026-01-01", end="2026-12-31").sessions_in_range("2026-06-01", "2026-10-13")[-40:]
    lines = [f"{label.date().isoformat()},{10 + i * .1 + (i % 3) * .01}" for i, label in enumerate(labels)]
    body = ("observation_date,VIXCLS\n" + "\n".join(lines) + "\n").encode()
    K.collect_context(repo, fetcher=lambda _: body)
    original = L.read_jsonl(repo / L.OBSERVATIONS)
    class NextDay(FrozenDateTime):
        @classmethod
        def now(cls, tz=None):
            stamp = datetime(2026, 10, 16, 5, 20, tzinfo=timezone.utc)
            return stamp.astimezone(tz) if tz is not None else stamp
    monkeypatch.setattr(K, "datetime", NextDay)
    new_body = body + b"2026-10-14,15\n"
    result = K.collect_context(repo, fetcher=lambda _: new_body)
    assert result["counts"]["observations_appended"] == 1
    assert result["counts"]["events_appended"] == 1
    appended = L.read_jsonl(repo / L.OBSERVATIONS)
    assert appended[:-1] == original
    state = F._innovation_events(F.read_market_rows(repo, as_of="2026-10-16T06:00:00+00:00"), as_of="2026-10-16T06:00:00+00:00")
    assert len(state) == 1 and state[0]["numerical_eligible"]
    assert state[0]["computed_at"] == "2026-10-16T06:00:00+00:00"
    assert state[0]["expectation_information_cutoff"] == "2026-10-15T05:20:00+00:00"
    identity, available = state[0]["event_id"], state[0]["available_at"]
    assert K.collect_context(repo, fetcher=lambda _: new_body)["counts"]["observations_appended"] == 0
    replay = F._innovation_events(F.read_market_rows(repo, as_of="2026-10-17T06:00:00+00:00"))
    assert replay[0]["event_id"] == identity and replay[0]["available_at"] == available
    assert L.verify_store(repo)["ok"]
    frozen = L.read_events(repo, as_of="2026-10-17T06:00:00+00:00")
    assert frozen[0]["computed_at"] == "2026-10-16T05:20:00+00:00"


def test_verify_checks_unissued_future_raw_artifacts(repo):
    row = event(repo, acquired="2026-11-01T14:00:00+00:00", published="2026-11-01T13:00:00+00:00")
    L.append_event(repo, row)
    assert L.read_events(repo, as_of="2026-10-15T14:00:00+00:00") == []
    assert L.verify_store(repo)["ok"]
    (repo / row["raw_path"]).write_bytes(gzip.compress(b"changed after ingestion"))
    result = L.verify_store(repo)
    assert not result["ok"] and "hash mismatch" in result["errors"][0]


def test_capture_window_is_declared_and_invalid_excluded_history_is_not_hidden(repo, monkeypatch):
    import exchange_calendars as xcals
    monkeypatch.setattr(K, "datetime", FrozenDateTime)
    _sources(repo, [{"id": "fred_nasdaq", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
                     "format": "fred_csv", "series_id": "NASDAQCOM"}])
    calendar = xcals.get_calendar("XNAS", start="2013-01-01", end="2026-10-16")
    labels = calendar.sessions_in_range("2013-01-02", "2026-10-14")[:3002]
    lines = [f"{label.date().isoformat()},{100 + index / 100}" for index, label in enumerate(labels)]
    body = ("observation_date,NASDAQCOM\n" + "\n".join(lines) + "\n").encode()
    result = K.collect_context(repo, fetcher=lambda _: body)
    assert result["status"] == "ok"
    assert result["sources"][0]["capture_window"] == {"appended": 3000, "parsed_observations": 3002,
                "eligible_observations": 3002, "rejected_observations": 0, "rejections_appended": 0,
                "selected_observations": 3000, "excluded_by_declared_window": 2, "provisional_excluded": 0, "window_limit": 3000}
    assert len(L.read_jsonl(repo / L.OBSERVATIONS)) == 3000
    bad = body.replace(f"{labels[0].date().isoformat()},100.0".encode(), f"{labels[0].date().isoformat()},nan".encode())
    failed = K.collect_context(repo, fetcher=lambda _: bad)
    assert failed["status"] == "degraded"
    assert "finite" in failed["sources"][0]["reason"]
    assert len(L.read_jsonl(repo / L.OBSERVATIONS)) == 3000


def test_monthly_release_uses_prebatch_prior_vintage_when_previous_month_is_revised(repo, monkeypatch):
    import numpy as np
    monkeypatch.setattr(K, "datetime", FrozenDateTime)
    _sources(repo, [{"id": "fred_cpi", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
                     "format": "fred_csv", "series_id": "CPIAUCSL"}])
    periods = [f"{2023 + index // 12}-{index % 12 + 1:02}-01" for index in range(40)]
    original = [100 + index * .3 + (index % 3) * .02 for index in range(40)]
    body = ("observation_date,CPIAUCSL\n" + "\n".join(f"{day},{value}" for day, value in zip(periods, original)) + "\n").encode()
    K.collect_context(repo, fetcher=lambda _: body)
    class NextDay(FrozenDateTime):
        @classmethod
        def now(cls, tz=None):
            stamp = datetime(2026, 10, 16, 5, 20, tzinfo=timezone.utc)
            return stamp.astimezone(tz) if tz is not None else stamp
    monkeypatch.setattr(K, "datetime", NextDay)
    revised = body.replace(f"{periods[-1]},{original[-1]}".encode(), f"{periods[-1]},999".encode())
    release = revised + b"2026-05-01,150\n"
    outcome = K.collect_context(repo, fetcher=lambda _: release)
    assert outcome["status"] == "ok"
    events = L.read_events(repo, as_of="2026-10-16T06:00:00+00:00")
    actual = next(row for row in events if row["reference_period"] == "2026-05-01")
    assert actual["numerical_eligible"]
    assert actual["expectation"] == pytest.approx(original[-1] + np.diff(original).mean())
    assert actual["expectation_information_cutoff"] == "2026-10-15T05:20:00+00:00"
    assert actual["expectation"] < 200  # Today's newly revised 999 was unavailable to this expectation.
    frozen_before = L.read_jsonl(repo / L.EVENTS)
    assert K.collect_context(repo, fetcher=lambda _: release)["counts"]["events_appended"] == 0
    assert L.read_jsonl(repo / L.EVENTS) == frozen_before
    assert L.verify_store(repo)["ok"]


def test_provisional_index_capture_is_skipped_and_equal_final_value_is_certified(repo, monkeypatch):
    _sources(repo, [{"id": "fred_nasdaq", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
                     "format": "fred_csv", "series_id": "NASDAQCOM"}])
    class BeforeClose(FrozenDateTime):
        @classmethod
        def now(cls, tz=None):
            stamp = datetime(2026, 10, 15, 19, tzinfo=timezone.utc)
            return stamp.astimezone(tz) if tz is not None else stamp
    monkeypatch.setattr(K, "datetime", BeforeClose)
    body = b"observation_date,NASDAQCOM\n2026-10-15,333\n"
    first = K.collect_context(repo, fetcher=lambda _: body)
    assert first["status"] == "ok"
    assert first["counts"]["observations_appended"] == 0
    assert first["sources"][0]["capture_window"]["provisional_excluded"] == 1
    assert not L.read_jsonl(repo / L.OBSERVATIONS)
    # Preserve and supersede a provisional row left by an older importer.
    receipt = L.read_jsonl(repo / L.RECEIPTS)[0]
    prior = {"series_id": "NASDAQCOM", "observation_time": "2026-10-15", "value": 333.,
             "available_at": receipt["retrieved_at"], "retrieved_at": receipt["retrieved_at"],
             "source_id": "fred_nasdaq", "source_sha256": receipt["source_sha256"], "raw_path": receipt["raw_path"],
             "data_grade": "captured_current_vintage", "historical_pit_eligible": False, "supersedes": None}
    prior["observation_id"] = L.digest(prior)
    L.append_unique(repo / L.OBSERVATIONS, prior, "observation_id")
    class AfterClose(FrozenDateTime):
        @classmethod
        def now(cls, tz=None):
            stamp = datetime(2026, 10, 15, 21, tzinfo=timezone.utc)
            return stamp.astimezone(tz) if tz is not None else stamp
    monkeypatch.setattr(K, "datetime", AfterClose)
    final = K.collect_context(repo, fetcher=lambda _: body)
    assert final["counts"]["observations_appended"] == 1
    rows = L.read_jsonl(repo / L.OBSERVATIONS)
    assert rows[0] == prior and rows[1]["supersedes"] == prior["observation_id"]
    assert rows[1]["value"] == prior["value"]
    assert rows[1]["final_close_capture"] is True
    assert rows[1]["session_close"] == "2026-10-15T20:00:00+00:00"
    assert L.verify_store(repo)["ok"]


def test_historical_revision_batch_does_not_manufacture_thirty_new_releases(repo, monkeypatch):
    _sources(repo, [{"id": "fred_cpi", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
                     "format": "fred_csv", "series_id": "CPIAUCSL"}])
    periods = [f"{2018 + index // 12}-{index % 12 + 1:02}-01" for index in range(100)]
    values = [100 + index * .3 + (index % 3) * .02 for index in range(100)]
    def body(levels):
        return ("observation_date,CPIAUCSL\n" + "\n".join(f"{day},{value}" for day, value in zip(periods, levels)) + "\n").encode()
    monkeypatch.setattr(K, "datetime", FrozenDateTime)
    K.collect_context(repo, fetcher=lambda _: body(values))
    class NextDay(FrozenDateTime):
        @classmethod
        def now(cls, tz=None):
            stamp = datetime(2026, 10, 16, 5, 20, tzinfo=timezone.utc)
            return stamp.astimezone(tz) if tz is not None else stamp
    monkeypatch.setattr(K, "datetime", NextDay)
    revised = body([value + .2 for value in values]) + b"2026-05-01,150\n"
    result = K.collect_context(repo, fetcher=lambda _: revised)
    assert result["status"] == "ok"
    assert result["counts"]["events_appended"] == 1
    original = L.read_jsonl(repo / L.EVENTS)[0]
    assert original["reference_period"] == "2026-05-01"
    class ThirdDay(FrozenDateTime):
        @classmethod
        def now(cls, tz=None):
            stamp = datetime(2026, 10, 17, 5, 20, tzinfo=timezone.utc)
            return stamp.astimezone(tz) if tz is not None else stamp
    monkeypatch.setattr(K, "datetime", ThirdDay)
    later = revised.replace(b"2026-05-01,150", b"2026-05-01,151") + b"2026-06-01,155\n"
    result = K.collect_context(repo, fetcher=lambda _: later)
    assert result["counts"]["events_appended"] == 2  # One known correction and one new release.
    history = L.read_jsonl(repo / L.EVENTS)
    assert history[0] == original
    correction = next(row for row in history if row.get("supersedes") == original["revision_id"])
    assert correction["event_id"] == original["event_id"]
    assert correction["published_at"] == original["published_at"]
    assert correction["available_at"] > original["available_at"]
    active = L.read_events(repo, as_of="2026-10-17T06:00:00+00:00")
    assert len({row["event_id"] for row in active}) == 2
    assert L.verify_store(repo)["ok"]


def test_non_session_index_rows_are_rejected_with_evidence_and_quality_status(repo, monkeypatch):
    monkeypatch.setattr(K, "datetime", FrozenDateTime)
    _sources(repo, [{"id": "fred_nasdaq", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
                     "format": "fred_csv", "series_id": "NASDAQCOM"}])
    body = b"observation_date,NASDAQCOM\n2019-04-18,7998.060\n2019-04-19,7998.063\n2019-04-22,8015.270\n"
    result = K.collect_context(repo, fetcher=lambda _: body)
    assert result["status"] == "degraded"
    assert result["counts"]["failed_sources"] == 0
    assert result["counts"]["quality_degraded_sources"] == 1
    assert result["sources"][0]["status"] == "quality_degraded"
    assert result["sources"][0]["capture_window"]["rejected_observations"] == 1
    rejected = L.read_jsonl(repo / L.REJECTIONS)
    assert len(rejected) == 1
    assert rejected[0]["observation_time"] == "2019-04-19"
    assert rejected[0]["reason"] == "non_session_index_observation"
    assert rejected[0]["calendar_requested"] == "XNAS"
    assert gzip.decompress((repo / rejected[0]["raw_path"]).read_bytes()) == body
    assert [row["observation_time"] for row in L.read_jsonl(repo / L.OBSERVATIONS)] == ["2019-04-18", "2019-04-22"]
    assert K.collect_context(repo, fetcher=lambda _: body)["sources"][0]["capture_window"]["rejections_appended"] == 0
    verification = L.verify_store(repo)
    assert verification["ok"] and verification["counts"]["rejected_observations"] == 1


def test_html_publication_unknown_is_distinct_from_first_acquisition(repo, monkeypatch):
    monkeypatch.setattr(K, "datetime", FrozenDateTime)
    _sources(repo, [{"id": "anthropic_news", "url": "https://www.anthropic.com/news", "format": "html_links",
                     "family": "anthropic_public_disclosure", "axis": "ai_demand"},
                    {"id": "bls_cpi", "url": "https://www.bls.gov/feed/cpi.rss", "enabled": False}])
    body = b'<html><a href="/news/enterprise-growth">Enterprise customers expand AI investment</a></html>'
    result = K.collect_context(repo, fetcher=lambda _: body)
    assert result["status"] == "ok"
    row = L.read_events(repo, as_of="2026-10-15T06:00:00+00:00")[0]
    assert row["published_at"] is None and row["publication_time_status"] == "unknown"
    assert row["available_at"] == row["retrieved_at"] == "2026-10-15T05:20:00+00:00"
    assert not row["numerical_eligible"] and "unknown_publication" in row["reason"]
    assert K._publication("2026-10-14", row["retrieved_at"]) is None
    assert L.verify_store(repo)["ok"]
    numeric = {**event(repo), "published_at": None, "publication_time_status": "unknown"}
    with pytest.raises(C.MarketContextError, match="reference-only"):
        L.append_event(repo, numeric)


@pytest.mark.parametrize("requested", [None, "2020-01-01T00:00:00+00:00"])
def test_collection_returns_completion_cutoff_after_acquisition_without_backdating(repo, monkeypatch, requested):
    from datetime import timedelta
    class AdvancingDateTime(FrozenDateTime):
        calls = 0
        @classmethod
        def now(cls, tz=None):
            stamp = datetime(2026, 10, 15, 5, 20, tzinfo=timezone.utc) + timedelta(seconds=cls.calls)
            cls.calls += 1
            return stamp.astimezone(tz) if tz is not None else stamp
    monkeypatch.setattr(K, "datetime", AdvancingDateTime)
    _sources(repo, [{"id": "bls_cpi", "url": "https://www.bls.gov/feed/cpi.rss", "format": "rss",
                     "family": "cpi_release", "axis": "inflation"}])
    body = b'<rss><channel><item><title>Consumer Price Index release</title><link>https://www.bls.gov/cpi/release.htm</link><pubDate>Wed, 14 Oct 2026 12:30:00 GMT</pubDate></item></channel></rss>'
    result = K.collect_context(repo, as_of=requested, fetcher=lambda _: body)
    rows = L.read_events(repo, as_of=result["as_of"])
    assert len(rows) == 1
    assert C.aware(result["as_of"]) > C.aware(rows[0]["retrieved_at"])
    assert result["completed_at"] == result["as_of"]
    assert result["requested_as_of"] == (requested or "2026-10-15T05:20:00+00:00")
    if requested:
        assert rows[0]["retrieved_at"].startswith("2026-10-15")


def test_cross_url_duplicate_fact_has_one_shock_and_preserves_original_rows(repo):
    from ai_fc.market_context.model import score_state
    first = {**event(repo), "metric": "headline_cpi_mom"}
    assert L.append_event(repo, first)
    second = {**event(repo, revision="r2", acquired="2026-10-14T14:30:00+00:00"),
              "event_id": "different-url-same-fact", "metric": "headline_cpi_mom",
              "title": "A different headline repeats the same CPI value",
              "source_url": "https://www.bls.gov/cpi/another-report.htm"}
    assert not L.append_event(repo, second)
    # Emulate duplicates already present before the grouping policy existed.
    L.append_unique(repo / L.EVENTS, second, "revision_id")
    original_bytes = (repo / L.EVENTS).read_bytes()
    read = L.read_events(repo, as_of="2026-10-15T14:00:00+00:00")
    assert len(read) == 2 and read[0]["incident_group_id"] == read[1]["incident_group_id"]
    duplicate = next(row for row in read if row["incident_group_status"] == "duplicate")
    assert duplicate["duplicate_of_revision_id"] == "r1"
    assert duplicate["original_surprise_z"] == 1. and duplicate["surprise_z"] is None
    assert duplicate["reason"] == "duplicate_incident_no_additional_shock"
    assert not duplicate["numerical_eligible"]
    direct = score_state([first, second], as_of="2026-10-15T14:00:00+00:00",
                         session_dates=["2026-10-13", "2026-10-14"], eligible_families={"cpi_release"})
    assert sum(direct["numerical_vector"]) == pytest.approx(3.)
    assert sum(direct["reference_vector"]) == pytest.approx(3.)
    duplicate_receipt = next(row for row in direct["events"] if row.get("incident_group_status") == "duplicate")
    assert duplicate_receipt["exclusion_reason"] == "duplicate_incident_no_additional_shock"
    assert duplicate_receipt["original_surprise_z"] == 1.
    assert (repo / L.EVENTS).read_bytes() == original_bytes


def test_same_headline_new_structured_facts_stay_independent_and_hash_must_reconcile():
    common = {"family": "issuer_disclosure", "title": "Quarterly business update", "reference_period": "2026Q3",
              "numerical_eligible": True, "surprise_z": 1., "available_at": "2026-10-14T14:00:00+00:00"}
    first_payload = {"metric": "revenue", "actual": 100, "unit": "million_usd"}
    second_payload = {"metric": "guidance", "actual": 120, "unit": "million_usd"}
    first = {**common, "revision_id": "one", "fact_payload": first_payload, "fact_sha256": L.digest(first_payload)}
    second = {**common, "revision_id": "two", "fact_payload": second_payload, "fact_sha256": L.digest(second_payload)}
    annotated = L.annotate_incident_groups([first, second])
    assert annotated[0]["incident_group_id"] != annotated[1]["incident_group_id"]
    assert all(row["numerical_eligible"] for row in annotated)
    with pytest.raises(C.MarketContextError, match="payload/hash"):
        L.incident_group_id({**first, "fact_sha256": "0" * 64})
    # No actual/metric/unit/period evidence: a shared title is insufficient to
    # decide that two independent numerical model inputs are the same fact.
    unstructured = [{**common, "revision_id": "a"}, {**common, "revision_id": "b"}]
    assert all(row["numerical_eligible"] for row in L.annotate_incident_groups(unstructured))


def test_reference_reposts_group_without_losing_audit_evidence():
    common = {"family": "memory_issuer_disclosure", "title": "Inside Research NAND update", "reference_period": None,
              "numerical_eligible": False, "surprise_z": None, "available_at": "2026-10-14T14:00:00+00:00"}
    rows = L.annotate_incident_groups([{**common, "revision_id": "one", "source_url": "https://example.org/ep2"},
                                     {**common, "revision_id": "two", "source_url": "https://example.org/ep6"}])
    assert len(rows) == 2 and len({row["incident_group_id"] for row in rows}) == 1
    assert sum(row["incident_group_status"] == "duplicate" for row in rows) == 1
    monthly = L.annotate_incident_groups([{**common, "revision_id": "month-one", "published_at": "2026-09-16T18:00:00+00:00"},
                                         {**common, "revision_id": "month-two", "published_at": "2026-10-28T18:00:00+00:00"}])
    assert len({row["incident_group_id"] for row in monthly}) == 2
