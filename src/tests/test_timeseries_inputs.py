"""Temporary capture/replay fixtures for the bounded operational source batch."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from ai_fc import timeseries_inputs as I
from ai_fc.timeseries import ledger as N

NOW = datetime.fromisoformat("2026-10-13T04:00:00+00:00")
VALUES = {"NASDAQCOM": 20100.0, "VIXCLS": 15.0, "DGS2": 4.75, "T10Y2Y": 0.44, "DTWEXBGS": 120.0}


def _seed(root: Path):
    for sid, number in VALUES.items():
        payload = json.dumps({"output_type": 3, "count": 1, "offset": 0, "observations": [{"date": "2026-10-09", sid + "_20261009": number}]}).encode()
        stamp = "2026-10-10T08:00:00+00:00"
        N.persist_response(root, series_id=sid, status=200, payload=payload, retrieved_at=stamp, request_url="https://api.stlouisfed.org/fred/series/observations?series_id=" + sid)
        N.append_facts(root, N.normalize_alfred(payload, series_id=sid, retrieved_at=stamp))


def _capture(root: Path, out: Path, *, now=NOW, empty_inventory=None, bad_inventory=False, truncated=False, fail_observations=None, latency=0, empty_native=False, future_value=None):
    time = [now]
    requests = []
    def native(spec):
        query = parse_qs(urlsplit(spec.url).query)
        sid = query["series_id"][0]
        requests.append(query)
        time[0] += timedelta(seconds=latency)
        if urlsplit(spec.url).path.endswith("vintagedates"):
            empty = sid == empty_inventory or bad_inventory
            payload = {"count": 1 if bad_inventory else 0 if empty else 1, "offset": 0, "vintage_dates": [] if empty else ["2026-10-12"]}
        else:
            if sid == fail_observations:
                return 503, b"temporarily unavailable"
            payload = {"output_type": 3, "count": 2 if truncated else 1, "offset": 0, "observations": [{"date": "2026-10-12", sid + "_20261012": VALUES[sid]}]}
            if empty_native:
                payload.update(count=0, observations=[])
            if future_value is not None:
                payload["observations"].append({"date": "2026-10-13", sid + "_20261012": future_value})
                payload["count"] = len(payload["observations"])
        return 200, json.dumps(payload).encode()
    def market(url):
        time[0] += timedelta(seconds=latency)
        if "cboe" in url:
            return 200, b"DATE,OPEN,HIGH,LOW,CLOSE\n10/12/2026,15,15,15,15\n", "text/csv"
        return 200, b"<feed><properties><NEW_DATE>2026-10-09T00:00:00</NEW_DATE><BC_2YEAR>4.8</BC_2YEAR><BC_10YEAR>5.24</BC_10YEAR></properties></feed>", "application/xml"
    def fred(url, **_kwargs):
        time[0] += timedelta(seconds=latency)
        sid = parse_qs(urlsplit(url).query)["series_id"][0]
        return json.dumps({"observations": [{"date": "2026-10-12", "value": str(VALUES[sid])}]})
    report = I.capture_timeseries_inputs(root, output_dir=out, now=now, clock=lambda: time[0], api_key="fixture-runtime-credential",
                                      native_fetcher=native, market_fetcher=market, fred_fetch_text=fred)
    return report, requests


def _snapshot(root: Path):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "data").rglob("*") if p.is_file() and p.relative_to(root) != I.STATE_RELATIVE}


def _rehash(bundle: Path, mutate):
    path = bundle / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    body = {k: v for k, v in value.items() if k not in {"content_hash", "bundle_id"}}
    body["bundle_id"] = "ts-inputs-" + I.canonical_hash(body)[:24]
    value = {**body, "content_hash": I.canonical_hash(body)}
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def test_capture_uses_series_specific_overlap_and_response_completion(tmp_path):
    root = tmp_path / "repo"
    _seed(root)
    before = _snapshot(root)
    result, queries = _capture(root, tmp_path / "capture", latency=1)
    assert result["status"] == "captured" and _snapshot(root) == before
    manifest = json.loads((Path(result["bundle_path"]) / "manifest.json").read_text())
    assert set(manifest["native_windows"].values()) == {"2026-10-03"}
    assert all(q["realtime_end"] == ["9999-12-31"] for q in queries if "limit" in q)
    assert all(datetime.fromisoformat(r["retrieved_at"]) > datetime.fromisoformat(r["requested_at"]) for r in manifest["receipts"])
    assert "fixture-runtime-credential" not in json.dumps(manifest)
    assert all("api_key" not in r["source_uri"] and "fredgraph" not in r["source_uri"] for r in manifest["receipts"])
    with pytest.raises(I.TimeSeriesInputsError, match="immutable"):
        _capture(root, tmp_path / "capture")


def test_unchanged_poll_does_not_append_receipts_or_fan_out_for_model_ack(tmp_path):
    root = tmp_path / "repo"
    _seed(root)
    first, _ = _capture(root, tmp_path / "first")
    initial = I.apply_timeseries_inputs(root, bundle_dir=first["bundle_path"], now=NOW + timedelta(minutes=5))
    assert initial["changed"] and initial["publication_allowed"]
    before = _snapshot(root)
    pointer = root / "data/timeseries_daily6m/latest.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"run_id": "completed-model-ack", "status": "research_preview", "numbers_visible": True}))
    before[pointer.relative_to(root).as_posix()] = pointer.read_bytes()
    repeat, _ = _capture(root, tmp_path / "repeat", now=NOW + timedelta(minutes=30))
    result = I.apply_timeseries_inputs(root, bundle_dir=repeat["bundle_path"], now=NOW + timedelta(minutes=35))
    assert result["changed"] is result["semantic_changed"] is result["eligibility_changed"] is False
    assert result["state_changed"] is True and _snapshot(root) == before
    assert len((root / I.STATE_RELATIVE).read_bytes()) <= I.MAX_REPORT_BYTES


def test_empty_inventory_and_failed_observations_do_not_advance_native_watermark(tmp_path):
    root = tmp_path / "repo"
    _seed(root)
    first, _ = _capture(root, tmp_path / "first")
    I.apply_timeseries_inputs(root, bundle_dir=first["bundle_path"], now=NOW + timedelta(minutes=5))
    original = json.loads((root / I.STATE_RELATIVE).read_text())["native_watermarks"]["DGS2"]
    empty, _ = _capture(root, tmp_path / "empty", now=NOW + timedelta(minutes=30), empty_inventory="DGS2")
    assert empty["status"] == "captured"
    I.apply_timeseries_inputs(root, bundle_dir=empty["bundle_path"], now=NOW + timedelta(minutes=35))
    assert json.loads((root / I.STATE_RELATIVE).read_text())["native_watermarks"]["DGS2"] == original
    failed, _ = _capture(root, tmp_path / "failed", now=NOW + timedelta(hours=1), fail_observations="DGS2")
    applied = I.apply_timeseries_inputs(root, bundle_dir=failed["bundle_path"], now=NOW + timedelta(hours=1, minutes=5))
    assert not applied["publication_allowed"] and applied["source_failures"]
    assert any(r.get("http_status") == 503 for r in applied["source_failures"])
    assert json.loads((root / I.STATE_RELATIVE).read_text())["native_watermarks"]["DGS2"] == original


@pytest.mark.parametrize("failure", ["empty_page", "truncated_observations"])
def test_incomplete_api_pagination_is_not_a_successful_native_capture(tmp_path, failure):
    root = tmp_path / "repo"
    _seed(root)
    result, _ = _capture(root, tmp_path / "capture", bad_inventory=failure == "empty_page", truncated=failure == "truncated_observations")
    assert result["status"] == "partial" and result["source_failures"]
    applied = I.apply_timeseries_inputs(root, bundle_dir=result["bundle_path"], now=NOW + timedelta(minutes=5))
    assert applied["publication_allowed"] is False
    assert applied["native"]["appended"] == 0


@pytest.mark.parametrize("tamper", ["path", "source", "auth", "sha", "clock", "missing_observations"])
def test_rehashed_bad_bundle_is_rejected_before_source_mutation(tmp_path, tamper):
    root = tmp_path / "repo"
    _seed(root)
    result, _ = _capture(root, tmp_path / "capture")
    bundle = Path(result["bundle_path"])
    before = _snapshot(root)
    def mutate(m):
        r = m["receipts"][0]
        if tamper == "path":
            r["raw_path"] = "../escaped.gz"
        elif tamper == "source":
            r["source_uri"] = r["source_uri"].replace("api.stlouisfed.org", "example.com")
            r["request_sha256"] = I._sha(r["source_uri"])
        elif tamper == "auth":
            r["source_uri"] += "&api_key=REDACTED"
            r["request_sha256"] = I._sha(r["source_uri"])
        elif tamper == "sha":
            r["request_sha256"] = "a" * 64
        elif tamper == "clock":
            r["retrieved_at"] = (NOW + timedelta(hours=1)).isoformat()
        else:
            m["receipts"] = [x for x in m["receipts"] if not (x["kind"] == "native_observations" and x["series_id"] == "NASDAQCOM")]
    _rehash(bundle, mutate)
    with pytest.raises(I.TimeSeriesInputsError):
        I.apply_timeseries_inputs(root, bundle_dir=bundle, now=NOW + timedelta(minutes=5))
    assert _snapshot(root) == before and not (root / I.STATE_RELATIVE).exists()


def test_unseeded_series_never_triggers_a_historical_bootstrap(tmp_path):
    root = tmp_path / "repo"
    result, requests = _capture(root, tmp_path / "capture")
    assert not requests and result["status"] == "partial"
    assert len([f for f in result["source_failures"] if f["stage"] == "bootstrap"]) == len(I.NATIVE_SERIES)


def test_empty_new_and_revised_native_response_is_a_valid_no_op(tmp_path):
    root = tmp_path / "repo"
    _seed(root)
    initial, _ = _capture(root, tmp_path / "initial")
    I.apply_timeseries_inputs(root, bundle_dir=initial["bundle_path"], now=NOW + timedelta(minutes=5))
    before = _snapshot(root)
    no_new, _ = _capture(root, tmp_path / "no-new", now=NOW + timedelta(minutes=30), empty_native=True)
    assert no_new["status"] == "captured" and no_new["source_failures"] == []
    result = I.apply_timeseries_inputs(root, bundle_dir=no_new["bundle_path"], now=NOW + timedelta(minutes=35))
    assert result["publication_allowed"] is True and result["changed"] is False
    assert result["native"] == {"appended": 0, "corrected": 0}
    assert _snapshot(root) == before


def test_future_missing_placeholder_stays_in_raw_but_future_number_rejects(tmp_path):
    root = tmp_path / "repo"
    _seed(root)
    captured, _ = _capture(root, tmp_path / "missing", future_value=".")
    assert captured["status"] == "captured"
    result = I.apply_timeseries_inputs(root, bundle_dir=captured["bundle_path"], now=NOW + timedelta(minutes=5))
    assert result["publication_allowed"] is True
    assert not any(f.observation_time == "2026-10-13" for f in N.read_facts(root))
    receipts = N._jsonl(root / "data/timeseries/ledgers/raw_receipts.jsonl")
    newest = next(r for r in receipts if r["retrieved_at"] == NOW.isoformat())
    raw = json.loads(gzip.decompress((root / newest["raw_path"]).read_bytes()))
    assert raw["observations"][-1]["date"] == "2026-10-13"
    assert list(raw["observations"][-1].values())[-1] == "."
    invalid, _ = _capture(root, tmp_path / "future-number", now=NOW + timedelta(minutes=30), future_value=100)
    assert invalid["status"] == "partial" and invalid["source_failures"]
