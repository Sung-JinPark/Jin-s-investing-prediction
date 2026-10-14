"""Lossless private supplements on disposable, captured source fixtures."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, engine as E, full_history as F, research as R, storage as S

REPOSITORY = Path(__file__).resolve().parents[2]
FIRST = datetime(2022, 7, 1, tzinfo=timezone.utc)


def raw_history(count=850, gap=None, extra=0.0):
    quotes = {key: [] for key in ("open", "high", "low", "close", "volume")}
    for i in range(count):
        low = 100 + i * .1 + abs(i % 100 - 50) * .6 + extra
        values = (low + 1, low + 4, low, low + 2, 100)
        for key, value in zip(quotes, values):
            quotes[key].append(None if i == gap else value)
    body = {"chart": {"result": [{"meta": {"symbol": "BTC-USD", "currency": "USD",
            "exchangeTimezoneName": "UTC", "dataGranularity": "1d", "instrumentType": "CRYPTOCURRENCY"},
            "timestamp": [int((FIRST + timedelta(days=i)).timestamp()) for i in range(count)],
            "indicators": {"quote": [quotes]}, "events": {}}], "error": None}}
    wrapper = {"status": 200, "statusText": "OK", "headers": {"content-type": "application/json"}, "body": json.dumps(body)}
    return ('<html><script type="application/json" data-sveltekit-fetched '
            'data-url="https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1d">'
            + json.dumps(wrapper) + '</script></html>').encode()


def capture(root, count=850, gap=None, extra=0.0, stamp=None):
    raw = raw_history(count, gap, extra)
    stamp = stamp or (FIRST + timedelta(days=count, hours=1)).isoformat()
    receipt = {"url": "https://finance.yahoo.com/quote/BTC-USD/history/", "retrieved_at": stamp,
               "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "http_status": 200}
    return R.capture_html(root, "bitcoin", raw, receipt, as_of=stamp), stamp


@pytest.fixture
def store(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, target)
    return tmp_path


def original_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in (root / R.ROOT).rglob("*") if path.is_file()}


def test_full_captured_history_preserves_current_and_lossless_chunks(store):
    source, stamp = capture(store)
    before = original_bytes(store)
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        result = F.refresh(store, "bitcoin", now=stamp)
        assert F.verify(store)["ok"]
        second = F.refresh(store, "bitcoin", now=stamp)
    assert result["changed"] and not second["changed"]
    assert result["full_snapshot_id"] == second["full_snapshot_id"]
    assert before == original_bytes(store)
    manifest = F.decode_envelope(F.load_manifest(store, "bitcoin", now=stamp), F.MANIFEST_CONTRACT)
    assert manifest["source_snapshot_id"] == source["snapshot_id"]
    assert manifest["bar_count"] == 850 and manifest["full_scope"] == F.SCOPE
    assert manifest["full_parameters"] == {"bars": 850, "minimum_bars": 771, "left": 10, "right": 10, "min_anchor_gap": 60}
    assert manifest["points_encoding"] == "equations" and len(manifest["chunks"]) == 2
    bars = []
    for pin in manifest["chunks"]:
        envelope = F.load_chunk(store, "bitcoin", result["full_snapshot_id"], pin["chunk_index"], now=stamp)
        assert hashlib.sha256(S.encode(envelope)).hexdigest() == pin["envelope_sha256"]
        assert len(envelope["payload_json"].encode()) <= R.MAX_PRIVATE_PAYLOAD_BYTES
        bars.extend(F._unpack(F.decode_envelope(envelope)))
    assert C.canonical_hash(bars) == manifest["bars_sha256"]
    current = R._load_verified_detail(store, "bitcoin", now=stamp)
    assert bars[-756:] == current["bars"]
    assert manifest["source_engine_content_hash"] == current["source_snapshot_hash"]
    snapshot = S.read_json(store / F.ROOT / "snapshots" / (result["full_snapshot_id"] + ".json"))
    assert snapshot["independent_validation"]["checked_lines"] > 0
    assert snapshot["shadow"]["baseline_input_hash"] == snapshot["shadow"]["candidate_input_hash"]
    assert snapshot["shadow"]["status"] == "new_supplemental_not_promoted"
    assert set(current["analyses"]["linear"]) == {"63", "252", "756"}
    for axis in manifest["analyses"].values():
        assert axis["full"]["window"] == 850 and axis["full"]["events"] == []
        assert axis["full"]["pivots"] == []
        for line in axis["full"]["lines"]:
            assert "contacts" not in line and line["state"] == "research_reference"
    assert not list((store / S.ROOT).rglob("*.jsonl"))


def test_short_history_has_candles_and_line_hold(store):
    _, stamp = capture(store, 100)
    result = F.refresh(store, "bitcoin", now=stamp)
    manifest = F.decode_envelope(F.load_manifest(store, "bitcoin", now=stamp))
    assert result["bar_count"] == 100
    for windows in manifest["analyses"].values():
        assert windows["full"]["status"] == "hold"
        assert windows["full"]["reason_codes"] == ["insufficient_history"]
        assert not windows["full"]["lines"]


def test_gaps_keep_calendar_ordinals_and_block_cross_gap_formation(store):
    _, stamp = capture(store, gap=400)
    result = F.refresh(store, "bitcoin", now=stamp)
    snapshot = S.read_json(store / F.ROOT / "snapshots" / (result["full_snapshot_id"] + ".json"))
    assert len(snapshot["bars"]) == 849 and snapshot["bars"][400]["session_index"] == 401
    for line in snapshot["audit_lines"]:
        assert not line["first_anchor"]["index"] < 400 < line["second_anchor"]["index"]
    assert F.verify(store)["ok"]


@pytest.mark.parametrize("attack", ["payload", "prefix", "column", "row", "price", "suffix", "index", "identity", "nan"])
def test_chunk_tampering_rejected_at_transport_boundary(store, attack):
    _, stamp = capture(store, 100)
    result = F.refresh(store, "bitcoin", now=stamp)
    envelope = F.load_chunk(store, "bitcoin", result["full_snapshot_id"], 0, now=stamp)
    body = json.loads(envelope["payload_json"])
    if attack == "payload":
        envelope["payload_json"] += " "
    else:
        packed = body["bars_packed"]
        if attack == "prefix": packed["bar_id_prefix"] = "fake-"
        elif attack == "column": packed["columns"][-1] = "id"
        elif attack == "row": packed["rows"][0].pop()
        elif attack == "price": packed["rows"][0][3] = 1
        elif attack == "suffix": packed["rows"][0][-1] = "0"
        elif attack == "index": packed["rows"][0][1] = True
        elif attack == "identity": body["asset_id"] = "soxx"
        elif attack == "nan": packed["rows"][0][2] = float("nan")
        envelope["payload_json"] = json.dumps(body, separators=(",", ":"))
        envelope["payload_sha256"] = hashlib.sha256(envelope["payload_json"].encode()).hexdigest()
    with pytest.raises(ValueError):
        F.decode_envelope(envelope)


@pytest.mark.parametrize("attack", ["raw", "receipt", "archive", "manifest", "chunk"])
def test_source_and_export_tampering_fails_closed(store, attack):
    _, stamp = capture(store, 100)
    result = F.refresh(store, "bitcoin", now=stamp)
    if attack == "raw": path = next((store / R.ROOT / "raw").glob("*"))
    elif attack == "receipt": path = next((store / R.ROOT / "receipts").glob("*"))
    elif attack == "archive": path = next((store / R.ROOT / "snapshots").glob("*"))
    elif attack == "manifest": path = store / result["manifest_path"]
    else: path = store / result["chunks"][0]
    path.write_bytes(path.read_bytes() + b" ")
    audit = F.verify(store)
    assert audit["ok"] is False


def test_independent_scalar_rejects_equation_corruption_and_nonpositive_extension(store):
    _, stamp = capture(store)
    archive, _ = F._source(store, "bitcoin", stamp)
    calculated = F._calculate(archive)
    rows, future = F._normalize(archive)
    audits = deepcopy(calculated["audit_lines"])
    audits[0]["slope"] += .01
    with pytest.raises(ValueError, match="scalar_slope"):
        F._scalar_verify(rows, archive["asset"], archive["config"], calculated["full_config"]["parameters"],
                         calculated["full_config_sha256"], calculated["analyses"], audits, future)
    line = {"axis": "linear", "first_anchor": {"index": 0, "price": 2}, "second_anchor": {"index": 1, "price": 1}}
    assert F._scalar_price(line, 2) is None
    line["axis"] = "log"
    line["second_anchor"]["price"] = 1e308
    assert F._scalar_price(line, 100) is None


def test_new_capture_keeps_pinned_old_chunks_and_no_future_read(store):
    _, stamp = capture(store, 100)
    old = F.refresh(store, "bitcoin", now=stamp)
    with pytest.raises(ValueError, match="cutoff"):
        F.load_manifest(store, "bitcoin", now=(FIRST + timedelta(days=99)).isoformat())
    capture(store, 101, extra=1, stamp=(FIRST + timedelta(days=101, hours=1)).isoformat())
    assert F.load_chunk(store, "bitcoin", old["full_snapshot_id"], 0)["snapshot_id"] == old["full_snapshot_id"]
    assert F.load_manifest(store, "bitcoin")["snapshot_id"] == old["full_snapshot_id"]
    new = F.refresh(store, "bitcoin")
    assert new["full_snapshot_id"] != old["full_snapshot_id"]
    assert F.verify(store)["ok"]


def test_failed_export_does_not_move_pointer_and_retry_recovers(store, monkeypatch):
    _, stamp = capture(store, 100)
    F.refresh(store, "bitcoin", now=stamp)
    pointer = (store / F.ROOT / "latest.json").read_bytes()
    capture(store, 101, extra=1, stamp=(FIRST + timedelta(days=101, hours=1)).isoformat())
    actual = S.atomic_json
    def fail_manifest(path, value, **kwargs):
        if path.name == "manifest.json":
            raise OSError("disposable_export_failure")
        return actual(path, value, **kwargs)
    monkeypatch.setattr(S, "atomic_json", fail_manifest)
    with pytest.raises(OSError, match="export_failure"):
        F.refresh(store, "bitcoin")
    assert pointer == (store / F.ROOT / "latest.json").read_bytes()
    monkeypatch.setattr(S, "atomic_json", actual)
    assert F.refresh(store, "bitcoin")["changed"]
    assert F.verify(store)["ok"]


def test_limit_and_bad_route_ids_reject_without_truncation(store):
    with pytest.raises(ValueError, match="no_truncation"):
        F._config({"config": C.default_config()}, 4097)
    for index in (-1, 8, True, "0"):
        with pytest.raises(ValueError, match="index"):
            F.load_chunk(store, "bitcoin", "../anything", index)
    assert F.refresh(store, "bitcoin")["status"] == "hold"
    with pytest.raises(ValueError, match="source"):
        F.refresh(store, "mag7")


def test_duplicate_payload_keys_rejected_even_with_matching_sha(store):
    _, stamp = capture(store, 100)
    F.refresh(store, "bitcoin", now=stamp)
    envelope = F.load_manifest(store, "bitcoin", now=stamp)
    envelope["payload_json"] = envelope["payload_json"].replace('"asset_id":"bitcoin"',
        '"asset_id":"soxx","asset_id":"bitcoin"', 1)
    envelope["payload_sha256"] = hashlib.sha256(envelope["payload_json"].encode()).hexdigest()
    with pytest.raises(ValueError, match="duplicate_key"):
        F.decode_envelope(envelope)


def test_only_opt_in_successful_exact_full_proofs_skip_arithmetic(store, monkeypatch):
    _, stamp = capture(store, 100)
    F.refresh(store, "bitcoin", now=stamp)
    original = F._calculate
    calls = []
    def counted(archive):
        calls.append(archive["snapshot_id"])
        return original(archive)
    monkeypatch.setattr(F, "_calculate", counted)
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        assert F.verify(store)["ok"]
        assert len(calls) == 1
        assert F.verify(store)["ok"]
        assert len(calls) == 1
        raw = next((store / R.ROOT / "raw").glob("*"))
        saved = raw.read_bytes()
        raw.write_bytes(saved + b"invalid")
        assert not F.verify(store)["ok"]
        raw.write_bytes(saved)
        assert F.verify(store)["ok"]
        assert len(calls) == 1
        capture(store, 101, extra=1, stamp=(FIRST + timedelta(days=101, hours=1)).isoformat())
        F.refresh(store, "bitcoin")
        assert len(calls) == 2
        assert F.verify(store)["ok"]
        assert len(calls) == 3
        assert F.verify(store)["ok"] and len(calls) == 3
    assert F.verify(store)["ok"] and len(calls) == 5
    assert F.verify(store)["ok"] and len(calls) == 7


def test_full_readers_check_original_raw_without_full_replay(store, monkeypatch):
    _, stamp = capture(store, 100)
    result = F.refresh(store, "bitcoin", now=stamp)
    def forbidden(*args, **kwargs):
        raise AssertionError("reader must not replay all source archives")
    monkeypatch.setattr(R, "verify", forbidden)
    assert F.load_manifest(store, "bitcoin", now=stamp)
    assert F.load_chunk(store, "bitcoin", result["full_snapshot_id"], 0, now=stamp)
    raw = next((store / R.ROOT / "raw").glob("*"))
    raw.write_bytes(raw.read_bytes() + b"invalid")
    with pytest.raises(ValueError, match="raw_binding"):
        F.load_manifest(store, "bitcoin", now=stamp)


def test_independent_full_candidate_enumeration_detects_producer_omission(store, monkeypatch):
    _, stamp = capture(store)
    archive, _ = F._source(store, "bitcoin", stamp)
    original = E._analyze
    def omit_candidate(*args, **kwargs):
        analysis, events, candidates = original(*args, **kwargs)
        if args[4]["bars"] > 756 and candidates:
            removed = candidates[-1]["line_id"]
            candidates = candidates[:-1]
            analysis["candidate_count"] -= 1
            analysis["lines"] = [line for line in analysis["lines"] if line["line_id"] != removed]
            for side in analysis["borders"]:
                analysis["borders"][side] = [border for border in analysis["borders"][side] if border["line_id"] != removed]
        return analysis, events, candidates
    monkeypatch.setattr(E, "_analyze", omit_candidate)
    with pytest.raises(ValueError, match="candidate_completeness"):
        F._calculate(archive)
