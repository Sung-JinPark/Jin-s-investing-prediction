"""Independent temporal regressions for the source-only refresh batch."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ai_fc import timeseries_inputs as inputs
from ai_fc.facts import ObservationFact
from ai_fc.timeseries import ledger


REPO = Path(__file__).resolve().parents[2]
BOUNDARY = "2026-10-13T03:59:59+00:00"


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _root(path: Path) -> Path:
    target = path / "repo"
    contracts = target / "data/contracts"
    contracts.mkdir(parents=True)
    for name in ("multivariate_timeseries_v1.yaml", "multivariate_timeseries_v2.yaml", "timeseries_inputs_refresh.yaml"):
        source = REPO / "data/contracts" / name
        if source.exists():
            shutil.copy2(source, contracts / name)
    return target


def _fact(
    sid: str, day: str, value: float, *, available: str = "2026-10-10T03:59:59+00:00",
    captured: str = "2026-10-10T08:00:00+00:00",
) -> ObservationFact:
    semantic = json.dumps([sid, day, value, available]).encode()
    return ObservationFact(
        source_id="alfred", series_id=sid, observation_time=day, value=value,
        available_at=available, vintage_start=available, vintage_end=None,
        retrieved_at=captured, source_hash=hashlib.sha256(semantic).hexdigest(),
        source_revision_id=sid + ":" + available, parser_version="independent-fixture-v1",
        timezone="America/New_York", calendar_id="US_FED",
    )


def _seed(root: Path) -> None:
    facts = []
    for sid, value in (("NASDAQCOM", 20000.0), ("VIXCLS", 15.0), ("DGS2", 4.0),
                       ("T10Y2Y", 0.5), ("DTWEXBGS", 120.0)):
        payload = json.dumps({"output_type": 3, "observations": [
            {"date": "2026-10-09", sid + "_20261009": value},
        ]}).encode()
        stamp = "2026-10-10T08:00:00+00:00"
        ledger.persist_response(root, series_id=sid, status=200, payload=payload,
                                retrieved_at=stamp, request_url="https://api.stlouisfed.org/fred/series/observations?series_id=" + sid)
        facts.extend(ledger.normalize_alfred(payload, series_id=sid, retrieved_at=stamp))
    ledger.append_facts(root, facts)


def _signature(root: Path, when: str) -> str:
    result = inputs.eligibility_signature(root, now=_time(when))
    return result["eligibility_hash"]


def test_native_cutoff_becomes_eligible_without_a_second_append(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    ledger.append_facts(root, [_fact("NASDAQCOM", "2026-10-12", 20100.0,
                                   available=BOUNDARY, captured="2026-10-13T03:35:00+00:00")])
    before = _signature(root, "2026-10-13T03:59:58+00:00")
    after = _signature(root, BOUNDARY)
    assert before != after, "a captured native vintage becoming available must launch the chain"


def test_age_hours_alone_does_not_change_eligibility_signature(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    assert _signature(root, "2026-10-13T04:00:00+00:00") == _signature(root, "2026-10-13T04:01:00+00:00")


def test_unchanged_raw_recapture_does_not_launch_the_chain(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    before = _signature(root, "2026-10-13T04:00:00+00:00")
    ledger.persist_response(
        root, series_id="NASDAQCOM", status=200,
        payload=json.dumps({"observations": [{"date": "2026-10-09", "value": "20000.0"}]}).encode(),
        retrieved_at="2026-10-13T04:00:30+00:00",
        request_url="https://api.stlouisfed.org/fred/series/observations?series_id=NASDAQCOM",
    )
    assert before == _signature(root, "2026-10-13T04:01:00+00:00")


def test_historical_revision_cutoff_is_seen_when_latest_date_stays_fixed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    ledger.append_facts(root, [
        _fact("NASDAQCOM", "2026-09-01", 19000.0,
              available="2026-09-02T03:59:59+00:00", captured="2026-09-02T08:00:00+00:00"),
        _fact("NASDAQCOM", "2026-09-01", 19001.0,
              available=BOUNDARY, captured="2026-10-13T03:35:00+00:00"),
    ])
    assert _signature(root, "2026-10-13T03:59:58+00:00") != _signature(root, BOUNDARY), \
        "a historical correction affects training even when each series' latest observation is unchanged"


def test_future_captured_fact_cannot_enter_the_eligible_set(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    before = _signature(root, "2026-10-13T04:30:00+00:00")
    ledger.append_facts(root, [_fact("NASDAQCOM", "2026-10-12", 20100.0,
                                   available=BOUNDARY, captured="2026-10-13T05:00:00+00:00")])
    unavailable = inputs.eligibility_signature(root, now=_time("2026-10-13T04:30:00+00:00"))
    assert unavailable["eligibility_hash"] == before or unavailable.get("status") == "hold", \
        "a fact captured after the cutoff must be excluded or explicitly rejected"
    assert before != _signature(root, "2026-10-13T05:00:00+00:00")


def _capture(
    root: Path, output: Path, when: str, *, nasdaq: float = 20100.0,
    fail_cboe: bool = False, native_dgs2: float = 4.75,
    native_day: str = "2026-10-12", invalid_cboe: bool = False,
    fail_native_observation: str | None = None, requests: list | None = None,
    clock_override=None,
) -> dict:
    """Synthetic official formats; no network or runtime credential is used."""
    def native(spec):
        query = parse_qs(urlparse(spec.url).query)
        sid = query["series_id"][0]
        if requests is not None:
            requests.append({"path": urlparse(spec.url).path, "series_id": sid,
                             "realtime_start": query["realtime_start"][0]})
        if urlparse(spec.url).path.endswith("vintagedates"):
            payload = {"count": 1, "offset": 0, "limit": 10000, "vintage_dates": ["2026-10-12"]}
        else:
            if sid == fail_native_observation:
                return 503, b"native observation source unavailable"
            value = {"NASDAQCOM": nasdaq, "VIXCLS": 15.0, "DGS2": native_dgs2,
                     "T10Y2Y": 0.44, "DTWEXBGS": 120.0}.get(sid, 100.0)
            payload = {"output_type": 3, "observations": [{"date": native_day, sid + "_20261012": value}]}
        return 200, json.dumps(payload).encode()

    def market(url):
        if "cboe" in url:
            if invalid_cboe:
                return 200, b"not the registered CBOE data schema\n", "text/csv"
            return (503, b"temporarily unavailable", "text/plain") if fail_cboe else \
                (200, b"DATE,OPEN,HIGH,LOW,CLOSE\n10/12/2026,15,15,15,15\n", "text/csv")
        if "treasury" in url:
            return 200, b"<feed><properties><NEW_DATE>2026-10-09T00:00:00</NEW_DATE><BC_2YEAR>4.8</BC_2YEAR><BC_10YEAR>5.24</BC_10YEAR></properties></feed>", "application/xml"
        raise AssertionError("unregistered synthetic market request: " + url)

    def fred_text(url, **kwargs):
        query = parse_qs(urlparse(url).query)
        sid = query.get("series_id", query.get("id", [None]))[0]
        value = nasdaq if sid == "NASDAQCOM" else 120.0
        return json.dumps({"observations": [{"date": "2026-10-12", "value": str(value)}]})

    return inputs.capture_timeseries_inputs(
        root, output_dir=output, now=_time(when), api_key="unused-synthetic-fixture",
        native_fetcher=native, market_fetcher=market, fred_fetch_text=fred_text,
        clock=clock_override or (lambda: _time(when)),
    )


def _bundle(result: dict) -> Path:
    path = Path(result["bundle_path"])
    return path.parent if path.name == "manifest.json" else path


def test_failed_source_blocks_dispatch_and_unchanged_recovery_reopens_it(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    first = _capture(root, tmp_path / "first", "2026-10-13T04:00:00+00:00")
    initial = inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(first), now=_time("2026-10-13T04:05:00+00:00"))
    assert initial["publication_allowed"] is True
    partial = _capture(root, tmp_path / "partial", "2026-10-13T04:30:00+00:00", fail_cboe=True)
    failed = inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(partial), now=_time("2026-10-13T04:35:00+00:00"))
    assert failed["publication_allowed"] is False and failed["source_failures"]
    recovered = _capture(root, tmp_path / "recovered", "2026-10-13T05:00:00+00:00")
    ready = inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(recovered), now=_time("2026-10-13T05:05:00+00:00"))
    assert ready["publication_allowed"] is True and ready["changed"] is True
    assert ready["semantic_changed"] is False, "clearing source failure must work without fabricating a numerical change"


def test_older_capture_cannot_revert_a_later_same_vintage_correction(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    older = _capture(root, tmp_path / "older", "2026-10-13T04:00:00+00:00", nasdaq=20100.0)
    newer = _capture(root, tmp_path / "newer", "2026-10-13T05:00:00+00:00", nasdaq=20101.0)
    inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(newer), now=_time("2026-10-13T05:05:00+00:00"))
    before = [(row.observation_time, row.value, row.vintage_start, row.retrieved_at)
              for row in ledger.read_facts(root) if row.series_id == "NASDAQCOM"]
    inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(older), now=_time("2026-10-13T05:10:00+00:00"))
    after = [(row.observation_time, row.value, row.vintage_start, row.retrieved_at)
             for row in ledger.read_facts(root) if row.series_id == "NASDAQCOM"]
    assert after == before and after[-1][1] == 20101.0


def test_raw_artifact_tampering_is_rejected_before_canonical_append(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    before = (root / "data/timeseries/ledgers/observation_chunks.jsonl").read_bytes()
    captured = _capture(root, tmp_path / "tampered", "2026-10-13T04:00:00+00:00")
    bundle = _bundle(captured)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    payload = bundle / manifest["receipts"][0]["raw_path"]
    payload.write_bytes(b"this is not the immutable raw response")
    import pytest
    with pytest.raises((ValueError, RuntimeError, OSError)):
        inputs.apply_timeseries_inputs(root, bundle_dir=bundle, now=_time("2026-10-13T04:05:00+00:00"))
    assert (root / "data/timeseries/ledgers/observation_chunks.jsonl").read_bytes() == before
    assert not (root / "data/timeseries_v2/ledgers/market_observations.jsonl").exists()


def test_capture_bundle_contains_no_runtime_credential_or_canonical_writes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    before = (root / "data/timeseries/ledgers/observation_chunks.jsonl").read_bytes()
    captured = _capture(root, tmp_path / "keyless", "2026-10-13T04:00:00+00:00")
    bundle = _bundle(captured)
    assert "unused-synthetic-fixture" not in (bundle / "manifest.json").read_text(encoding="utf-8")
    assert "unused-synthetic-fixture" not in json.dumps(captured)
    assert (root / "data/timeseries/ledgers/observation_chunks.jsonl").read_bytes() == before
    assert not (root / "data/timeseries_v2/ledgers/market_raw_receipts.jsonl").exists()


def test_nonfinite_native_response_is_rejected_before_canonical_append(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    captured = _capture(root, tmp_path / "nonfinite", "2026-10-13T04:00:00+00:00", native_dgs2=float("nan"))
    assert captured["status"] != "captured" and captured["source_failures"]
    applied = inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(captured), now=_time("2026-10-13T04:05:00+00:00"))
    assert applied["publication_allowed"] is False
    assert [(row.observation_time, row.value) for row in ledger.read_facts(root) if row.series_id == "DGS2"] == [("2026-10-09", 4.0)]


def test_invalid_native_date_cannot_enter_the_daily_fact_history(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    before = (root / "data/timeseries/ledgers/observation_chunks.jsonl").read_bytes()
    captured = _capture(root, tmp_path / "invalid-date", "2026-10-13T04:00:00+00:00", native_day="2026-02-30")
    assert captured["status"] != "captured" and captured["source_failures"]
    inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(captured), now=_time("2026-10-13T04:05:00+00:00"))
    assert (root / "data/timeseries/ledgers/observation_chunks.jsonl").read_bytes() == before


def test_http_200_with_wrong_cboe_schema_is_a_failed_source(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    captured = _capture(root, tmp_path / "invalid-cboe", "2026-10-13T04:00:00+00:00", invalid_cboe=True)
    assert captured["status"] != "captured" and captured["source_failures"]
    applied = inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(captured), now=_time("2026-10-13T04:05:00+00:00"))
    assert applied["publication_allowed"] is False


def test_failed_native_observation_keeps_its_own_retry_window(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    initial = _capture(root, tmp_path / "watermark-initial", "2026-10-13T04:00:00+00:00")
    inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(initial), now=_time("2026-10-13T04:05:00+00:00"))
    partial = _capture(root, tmp_path / "watermark-partial", "2026-10-14T04:00:00+00:00", fail_native_observation="DGS2")
    failed = inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(partial), now=_time("2026-10-14T04:05:00+00:00"))
    assert failed["publication_allowed"] is False
    state = json.loads((root / inputs.STATE_RELATIVE).read_text(encoding="utf-8"))
    assert state["native_watermarks"]["DGS2"] == "2026-10-13T04:00:00+00:00"
    assert state["native_watermarks"]["NASDAQCOM"] == "2026-10-14T04:00:00+00:00"
    requests = []
    _capture(root, tmp_path / "watermark-retry", "2026-10-15T04:00:00+00:00", requests=requests)
    starts = {r["series_id"]: r["realtime_start"] for r in requests if r["path"].endswith("vintagedates")}
    assert starts["DGS2"] == "2026-10-06"
    assert starts["NASDAQCOM"] == "2026-10-07"


def test_actual_response_completion_time_is_preserved_for_each_capture(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root)
    base = _time("2026-10-13T04:00:00+00:00")
    ticks = iter(base + timedelta(seconds=index) for index in range(100))
    captured = _capture(root, tmp_path / "completion-clock", base.isoformat(), clock_override=lambda: next(ticks))
    manifest = json.loads((_bundle(captured) / "manifest.json").read_text(encoding="utf-8"))
    assert all(_time(r["retrieved_at"]) > _time(r["requested_at"]) for r in manifest["receipts"])
    assert len({r["retrieved_at"] for r in manifest["receipts"]}) == len(manifest["receipts"])
    inputs.apply_timeseries_inputs(root, bundle_dir=_bundle(captured), now=_time("2026-10-13T04:05:00+00:00"))
    from ai_fc.timeseries_v2.market_archive import read_market_observations
    rows = {row.series_id: row for row in read_market_observations(root)}
    cboe = next(r for r in manifest["receipts"] if r["kind"] == "market_cboe")
    assert rows["VIX"].available_at == cboe["retrieved_at"]
    assert rows["VIX"].vintage_start == cboe["retrieved_at"]
