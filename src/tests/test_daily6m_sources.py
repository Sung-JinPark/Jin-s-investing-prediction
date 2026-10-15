"""Disposable source bundles exercise raw replay, PIT, and append-only revisions."""
import gzip
import json
from datetime import datetime, timedelta, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ai_fc import daily6m_sources as S

NOW = datetime(2026, 10, 15, 2, 15, tzinfo=timezone.utc)
NASDAQ = {"2026-10-06": 27599.89, "2026-10-07": 27538.69, "2026-10-08": 27193.34, "2026-10-09": 27366.17, "2026-10-12": 27245.90, "2026-10-13": 27204.38}
YIELDS = {"2026-10-01": 4.7, "2026-10-02": 4.71, "2026-10-05": 4.72, "2026-10-06": 4.79, "2026-10-07": 4.77, "2026-10-08": 4.75, "2026-10-09": 4.80}


@pytest.fixture
def root(tmp_path):
    rows = []
    for sid, levels in (("NASDAQCOM", NASDAQ), ("DGS2", YIELDS), ("VIXCLS", {"2026-10-13": 15.27})):
        for day, value in levels.items():
            rows.append({"source_id": "alfred", "series_id": sid, "observation_time": day, "value": value, "value_status": "ok", "available_at": "2026-10-14T00:00:00+00:00", "vintage_start": "2026-10-14T00:00:00+00:00", "vintage_end": None, "retrieved_at": "2026-10-14T00:00:01+00:00", "source_hash": "a" * 64})
    path = tmp_path / "data/timeseries/facts/observations.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return tmp_path


def payloads(*, close=26692.87, treasury=4.82):
    info = {"data": {"symbol": "COMP", "exchange": "Index", "assetClass": "INDEX", "marketStatus": "Closed", "primaryData": {"lastTradeTimestamp": "Oct 14, 2026", "isRealTime": False, "lastSalePrice": str(close), "netChange": str(round(close - 27204.38, 2))}, "keyStats": {"previousclose": {"value": "27,204.38"}}}, "status": {"rCode": 200}}
    history = {"data": {"symbol": "COMP", "totalRecords": len(NASDAQ), "tradesTable": {"headers": {"close": "Close/Last"}, "rows": [{"date": datetime.strptime(day, "%Y-%m-%d").strftime("%m/%d/%Y"), "close": str(value)} for day, value in NASDAQ.items()]}}, "status": {"rCode": 200}}
    xml = '<feed xmlns:m="urn:m" xmlns:d="urn:d">' + ''.join(f'<m:properties><d:NEW_DATE>{day}T00:00:00</d:NEW_DATE><d:BC_2YEAR>{value}</d:BC_2YEAR><d:BC_10YEAR>5.0</d:BC_10YEAR></m:properties>' for day, value in {**YIELDS, "2026-10-13": 4.79, "2026-10-14": treasury}.items()) + '</feed>'
    return {"nasdaq_info": json.dumps(info).encode(), "nasdaq_history": json.dumps(history).encode(), "cboe": b"DATE,OPEN,HIGH,LOW,CLOSE\n10/13/2026,15,16,14,15.27\n10/14/2026,16,18,15,16.87\n", "treasury": xml.encode()}


def capture(root, name="bundle", *, raw=None, now=NOW):
    raw = payloads() if raw is None else raw
    urls = {url: kind for kind, (_, url) in S._urls(now).items()}
    def fetch(url):
        value = raw[urls[url]]
        if isinstance(value, Exception):
            raise value
        return 200, value
    report = S.capture_daily6m_sources(root, output_dir=name, now=now, clock=lambda: now, fetcher=fetch)
    return root / name, report


def test_capture_replay_holiday_bridge_and_noop(root):
    native = (root / "data/timeseries/facts/observations.parquet").read_bytes()
    bundle, report = capture(root)
    assert report["status"] == "captured" and report["observations"] == 4
    assert not (root / S.OBSERVATIONS).exists()
    first = S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)
    assert first["appended"] == 4 and first["changed"]
    rows = S.load_verified_source_observations(root, as_of=NOW)
    assert {(r["series_id"], r["observation_time"]) for r in rows} == {("NASDAQCOM", "2026-10-14"), ("VIX", "2026-10-14"), ("DGS2", "2026-10-13"), ("DGS2", "2026-10-14")}
    assert all(r["receipt_verified"] and r["available_at"] == r["retrieved_at"] == r["vintage_start"] for r in rows)
    treasury = next(r for r in rows if r["series_id"] == "DGS2")
    assert treasury["validation"]["closed_sessions"] == ["2026-10-12"]
    assert treasury["native_overlap_count"] == 7
    before = {str(path.relative_to(root)): path.read_bytes() for path in (root / S.STORE).rglob("*") if path.is_file()}
    second, result = capture(root, "repeat", now=NOW + timedelta(minutes=1))
    assert result["changed"] is False
    applied = S.apply_daily6m_sources(root, bundle_dir=second, now=NOW + timedelta(minutes=1))
    assert not applied["changed"] and applied["receipts"] == applied["appended"] == 0
    assert before == {str(path.relative_to(root)): path.read_bytes() for path in (root / S.STORE).rglob("*") if path.is_file()}
    assert native == (root / "data/timeseries/facts/observations.parquet").read_bytes()
    assert not (root / "data/timeseries_v2").exists()


def test_correction_supersedes_and_older_bundle_cannot_revert(root):
    first, _ = capture(root)
    S.apply_daily6m_sources(root, bundle_dir=first, now=NOW)
    prefix = (root / S.OBSERVATIONS).read_bytes()
    second, _ = capture(root, "revision", raw=payloads(close=26690.0, treasury=4.83), now=NOW + timedelta(minutes=1))
    result = S.apply_daily6m_sources(root, bundle_dir=second, now=NOW + timedelta(minutes=1))
    assert result["appended"] == 2
    assert (root / S.OBSERVATIONS).read_bytes().startswith(prefix)
    rows = S._rows(root / S.OBSERVATIONS)
    assert all(row["revision_seq"] == 2 and row["supersedes"] in {r["observation_id"] for r in rows[:4]} for row in rows[4:])
    replay = S.apply_daily6m_sources(root, bundle_dir=first, now=NOW + timedelta(minutes=2))
    assert replay["stale_ignored"] == 2 and replay["appended"] == 0
    assert len(S.load_verified_source_observations(root, as_of=NOW)) == 4
    assert len(S.load_verified_source_observations(root, as_of=NOW + timedelta(minutes=1))) == 6


@pytest.mark.parametrize("mutation", ["previous", "realtime", "date", "identity", "overlap", "history_short", "treasury_gap", "nan", "cboe_html"])
def test_invalid_source_is_audited_and_independent_sources_progress(root, mutation):
    raw = payloads()
    if mutation in {"previous", "realtime", "date", "identity"}:
        info = json.loads(raw["nasdaq_info"])
        if mutation == "previous": info["data"]["keyStats"]["previousclose"]["value"] = "1"
        if mutation == "realtime": info["data"]["primaryData"]["isRealTime"] = True
        if mutation == "date": info["data"]["primaryData"]["lastTradeTimestamp"] = "Oct 15, 2026"
        if mutation == "identity": info["data"]["symbol"] = "NDX"
        raw["nasdaq_info"] = json.dumps(info).encode()
    elif mutation in {"overlap", "history_short"}:
        data = json.loads(raw["nasdaq_history"])
        if mutation == "overlap": data["data"]["tradesTable"]["rows"][0]["close"] = "1"
        else:
            data["data"]["tradesTable"]["rows"] = data["data"]["tradesTable"]["rows"][:4]
            data["data"]["totalRecords"] = 4
        raw["nasdaq_history"] = json.dumps(data).encode()
    elif mutation == "treasury_gap": raw["treasury"] = raw["treasury"].replace(b"2026-10-13", b"2026-10-12")
    elif mutation == "nan": raw["treasury"] = raw["treasury"].replace(b">4.82<", b">NaN<")
    else: raw["cboe"] = b"<html>Access denied</html>"
    bundle, report = capture(root, raw=raw)
    assert report["status"] == "partial" and report["source_failures"]
    applied = S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)
    assert applied["status"] == "partial" and 0 < applied["appended"] < 4
    assert all(row["source_id"] != ("us_treasury_yield_archive" if mutation in {"treasury_gap", "nan"} else "cboe_vix_archive" if mutation == "cboe_html" else "nasdaq_comp_official") for row in S.load_verified_source_observations(root, as_of=NOW))


@pytest.mark.parametrize("mutation", ["raw", "candidate", "clock", "path", "failure"])
def test_bundle_tamper_blocks_every_append(root, mutation):
    bundle, _ = capture(root)
    manifest = json.loads((bundle / "manifest.json").read_text())
    if mutation == "raw":
        path = bundle / manifest["receipts"][0]["raw_path"]
        path.write_bytes(gzip.compress(b"{}"))
    elif mutation == "candidate": manifest["candidates"][0]["value"] = 1.0
    elif mutation == "clock": manifest["receipts"][0]["retrieved_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif mutation == "path": manifest["receipts"][0]["raw_path"] = "../escape.gz"
    else:
        manifest["source_failures"] = [{"kind": "nasdaq_info", "reason": "claimed"}]
        manifest["candidates"] = [r for r in manifest["candidates"] if r["source_id"] != "nasdaq_comp_official"]
    manifest["bundle_id"] = "daily6m-source-bundle-" + S._hash({k: v for k, v in manifest.items() if k not in {"content_hash", "bundle_id"}})[:32]
    manifest["content_hash"] = S._hash({k: v for k, v in manifest.items() if k != "content_hash"})
    (bundle / "manifest.json").write_bytes(S._json(manifest))
    with pytest.raises((S.Daily6mSourcesError, ValueError)):
        S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)
    assert not (root / S.OBSERVATIONS).exists() and not (root / S.RECEIPTS).exists()


def test_future_completion_and_immutable_output_rejected(root):
    bundle, _ = capture(root)
    with pytest.raises(S.Daily6mSourcesError, match="completion"):
        S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW - timedelta(microseconds=1))
    with pytest.raises(S.Daily6mSourcesError, match="empty"):
        capture(root)


def test_invalid_existing_revision_chain_blocks_write(root):
    bundle, _ = capture(root)
    S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)
    rows = S._rows(root / S.OBSERVATIONS)
    rows[0]["supersedes"] = "invented"
    rows[0]["observation_id"] = "daily6m-observation-" + S._hash({k: v for k, v in rows[0].items() if k != "observation_id"})[:32]
    (root / S.OBSERVATIONS).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    with pytest.raises(S.Daily6mSourcesError, match="revision"):
        S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)


@pytest.mark.parametrize("kind,body", [("nasdaq_info", {"status": None, "data": {}}), ("nasdaq_info", {"status": {"rCode": 200}, "data": {"symbol": "COMP", "primaryData": []}}), ("nasdaq_history", {"status": {"rCode": 200}, "data": {"symbol": "COMP", "tradesTable": []}}), ("treasury", "<broken")])
def test_malformed_success_response_remains_auditable_partial(root, kind, body):
    raw = payloads()
    raw[kind] = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    bundle, report = capture(root, raw=raw)
    assert report["status"] == "partial" and report["source_failures"]
    assert S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)["status"] == "partial"


def test_transport_failure_preserves_independent_valid_sources(root):
    raw = payloads()
    raw["nasdaq_info"] = OSError("public endpoint temporarily unavailable")
    bundle, report = capture(root, raw=raw)
    assert report["status"] == "partial" and report["transport_failures"]
    applied = S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)
    assert applied["appended"] == 3 and applied["source_failures"]


def test_native_gap_cannot_be_backfilled_by_nasdaq_tail(root):
    path = root / "data/timeseries/facts/observations.parquet"
    rows = [r for r in pq.read_table(path).to_pylist() if not (r["series_id"] == "NASDAQCOM" and r["observation_time"] == "2026-10-13")]
    pq.write_table(pa.Table.from_pylist(rows), path)
    _, report = capture(root)
    assert report["status"] == "partial"
    assert "native previous-session close" in report["source_failures"][0]["reason"]


def test_uncompleted_daily_quote_is_rejected_before_session_close(root):
    noon = datetime(2026, 10, 14, 16, tzinfo=timezone.utc)
    _, report = capture(root, now=noon)
    assert report["status"] == "partial"
    assert any("latest completed" in r["reason"] for r in report["source_pending"])


def test_later_same_vintage_native_correction_cannot_change_old_receipt_replay(root):
    from ai_fc.timeseries import ledger as N
    path = root / "data/timeseries/facts/observations.parquet"
    baseline = pq.read_table(path).to_pylist()
    preserved = [{**r, "observation_id": S._hash(r), "revision_seq": 0, "supersedes_observation_id": None} for r in baseline]
    ledger = root / N.LEDGER_RELATIVE / N.OBSERVATIONS_NAME
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("\n".join(json.dumps(r) for r in preserved) + "\n")
    bundle, _ = capture(root)
    S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)
    old = next(r for r in preserved if r["series_id"] == "NASDAQCOM" and r["observation_time"] == "2026-10-13")
    correction = {**old, "value": 27200.0, "retrieved_at": (NOW + timedelta(minutes=1)).isoformat(), "revision_seq": 1, "supersedes_observation_id": old["observation_id"]}
    correction["observation_id"] = S._hash(correction)
    with ledger.open("a") as handle:
        handle.write(json.dumps(correction) + "\n")
    # The disposable current view no longer contains the original revision.
    pq.write_table(pa.Table.from_pylist([{**r, "value": 27200.0, "retrieved_at": correction["retrieved_at"]} if r["series_id"] == "NASDAQCOM" and r["observation_time"] == "2026-10-13" else r for r in baseline]), path)
    verified = S.load_verified_source_observations(root, as_of=NOW + timedelta(minutes=2))
    assert len(verified) == 4
    assert next(r for r in verified if r["series_id"] == "NASDAQCOM")["validation"]["previous_native_close"] == 27204.38


def test_exact_directed_cboe_redirect_and_unknown_redirects():
    import urllib.request
    request = urllib.request.Request(S.CBOE_URL)
    result = S._Redirect().redirect_request(request, None, 307, "Temporary Redirect", {}, S.CBOE_RESPONSE_URL)
    assert result.full_url == S.CBOE_RESPONSE_URL
    for target, status in ((S.CBOE_RESPONSE_URL, 302), (S.CBOE_RESPONSE_URL + "?other=1", 307), (S.CBOE_RESPONSE_URL.replace("VIX_History", "OTHER"), 307), (S.CBOE_RESPONSE_URL.replace("https:", "http:"), 307), ("https://unregistered.example/VIX_History.csv", 307)):
        with pytest.raises(S.Daily6mSourcesError, match="redirect"):
            S._Redirect().redirect_request(request, None, status, "Redirect", {}, target)
    with pytest.raises(S.Daily6mSourcesError):
        S._Redirect().redirect_request(urllib.request.Request(S.NASDAQ_INFO), None, 307, "Redirect", {}, S.CBOE_RESPONSE_URL)


def test_transport_records_registered_response_uri_in_receipt_and_reader(root, monkeypatch):
    import urllib.request
    raw = payloads()
    urls = {url: kind for kind, (_, url) in S._urls(NOW).items()}
    class Response:
        status = 200
        def __init__(self, uri):
            self.requested = uri
            self.url = S.CBOE_RESPONSE_URL if uri == S.CBOE_URL else uri
            self.headers = {"Content-Type": "text/csv" if uri == S.CBOE_URL else "application/json"}
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, size): return raw[urls[self.requested]][:size]
    class Opener:
        def open(self, req, timeout):
            assert timeout == 20 and req.get_header("User-agent") == S.USER_AGENT
            return Response(req.full_url)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: Opener())
    S.capture_daily6m_sources(root, output_dir="redirect", now=NOW, clock=lambda: NOW)
    S.apply_daily6m_sources(root, bundle_dir="redirect", now=NOW)
    vix = next(r for r in S.load_verified_source_observations(root, as_of=NOW) if r["series_id"] == "VIX")
    assert vix["receipt_source_uri"] == S.CBOE_URL
    assert vix["receipt_response_uri"] == S.CBOE_RESPONSE_URL and vix["receipt_response_uri_recorded"]
    receipts = S._rows(root / S.RECEIPTS)
    row = next(r for r in receipts if r["kind"] == "cboe")
    row["response_uri"] = "https://unregistered.example/close.csv"
    (root / S.RECEIPTS).write_text("\n".join(json.dumps(r) for r in receipts) + "\n")
    with pytest.raises(S.Daily6mSourcesError, match="response URI"):
        S.load_verified_source_observations(root, as_of=NOW)


@pytest.mark.parametrize("state", ["Open", "Pre-Market", "archive_unpublished"])
def test_registered_nonfinal_market_state_is_pending_not_source_failure(root, state):
    raw = payloads()
    if state == "archive_unpublished":
        raw["cboe"] = raw["cboe"].split(b"10/14/2026")[0]
        raw["treasury"] = raw["treasury"].replace(b'<m:properties><d:NEW_DATE>2026-10-14T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.82</d:BC_2YEAR><d:BC_10YEAR>5.0</d:BC_10YEAR></m:properties>', b'')
    else:
        info = json.loads(raw["nasdaq_info"])
        info["data"]["marketStatus"] = state
        info["data"]["primaryData"]["isRealTime"] = True
        raw["nasdaq_info"] = json.dumps(info).encode()
    bundle, report = capture(root, raw=raw)
    assert report["status"] == "captured" and report["source_pending"] and report["source_failures"] == []
    applied = S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)
    assert applied["status"] == "applied" and applied["source_pending"] == report["source_pending"]


def test_nonfinal_market_does_not_hide_malformed_history(root):
    raw = payloads()
    info = json.loads(raw["nasdaq_info"])
    info["data"]["marketStatus"] = "Open"
    raw["nasdaq_info"] = json.dumps(info).encode()
    raw["nasdaq_history"] = b"{}"
    _, report = capture(root, raw=raw)
    assert report["status"] == "partial" and report["source_failures"]


def test_legacy_direct_receipt_identity_preserved_without_invented_final_uri(root):
    bundle, _ = capture(root)
    S.apply_daily6m_sources(root, bundle_dir=bundle, now=NOW)
    receipts, observations = S._rows(root / S.RECEIPTS), S._rows(root / S.OBSERVATIONS)
    replacements = {}
    for row in receipts:
        original = row["receipt_id"]
        row.pop("response_uri")
        seed = {k: v for k, v in row.items() if k not in {"receipt_id", "raw_path"}}
        row["receipt_id"] = "daily6m-receipt-" + S._hash(seed)[:32]
        replacements[original] = row["receipt_id"]
    for row in observations:
        row["receipt_id"] = replacements[row["receipt_id"]]
        row["validation_receipt_ids"] = [replacements[r] for r in row["validation_receipt_ids"]]
        row["observation_id"] = "daily6m-observation-" + S._hash({k: v for k, v in row.items() if k != "observation_id"})[:32]
    (root / S.RECEIPTS).write_text("\n".join(json.dumps(r) for r in receipts) + "\n")
    (root / S.OBSERVATIONS).write_text("\n".join(json.dumps(r) for r in observations) + "\n")
    prefix = (root / S.RECEIPTS).read_bytes()
    verified = S.load_verified_source_observations(root, as_of=NOW)
    assert len(verified) == 4 and all(r["receipt_response_uri"] is None and r["receipt_response_uri_recorded"] is False for r in verified)
    assert (root / S.RECEIPTS).read_bytes() == prefix
