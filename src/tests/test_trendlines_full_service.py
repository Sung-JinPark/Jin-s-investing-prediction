"""Offline boundaries for supplemental full-history delivery and partial failure.

The full-history loader is an isolated, typed seam here. Its numerical/source
replay is exercised separately; these tests never collect or change evidence.
"""
from __future__ import annotations

import hashlib
import json
import runpy
import sys
import threading
import types
from copy import deepcopy
from pathlib import Path

import pytest

import ai_fc.trendlines as package
from ai_fc.trendlines import local_service as L, storage as S

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_trendlines_local_service.py")))
NOW, Clock = HELPERS["NOW"], HELPERS["Clock"]
write_envelope, verified_report = HELPERS["write_envelope"], HELPERS["verified_report"]
service, request = HELPERS["service"], HELPERS["request"]
FULL_ID = "research-full-snapshot-" + "1" * 64
FULL_ROUTE = "/api/private-trendlines/bitcoin/full"
CHUNK_ROUTE = FULL_ROUTE + "/" + FULL_ID + "/bars/0"


def wrap(body):
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {"schema_version": 1, "contract_id": "trendlines_private_full_transport_v1",
            "publication_scope": "private_only", "payload_json": payload,
            "payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()}


class FullStore:
    """Only envelope decoding and the immutable loader-call contract are mocked."""

    def __init__(self, current):
        self.manifest = wrap({"schema_version": 1, "contract_id": "trendlines_private_full_manifest_v1",
            "publication_scope": "private_only", "fixture_only": True, "asset_id": "bitcoin",
            "snapshot_id": FULL_ID, "source_snapshot_id": current["snapshot_id"], "as_of": current["as_of"]})
        self.chunks = {index: wrap({"schema_version": 1, "contract_id": "trendlines_private_full_bars_v1",
            "publication_scope": "private_only", "fixture_only": True, "asset_id": "bitcoin",
            "snapshot_id": FULL_ID, "chunk_index": index}) for index in (0, 7)}
        self.calls = []

    def load_manifest(self, root, asset_id, *, now):
        self.calls.append(("manifest", root, asset_id, now))
        return deepcopy(self.manifest)

    def load_chunk(self, root, asset_id, snapshot_id, chunk_index, *, now):
        self.calls.append(("chunk", root, asset_id, snapshot_id, chunk_index, now))
        if snapshot_id != FULL_ID or chunk_index not in self.chunks:
            raise FileNotFoundError("fixture full chunk missing")
        return deepcopy(self.chunks[chunk_index])

    def decode_envelope(self, value, *, expected_contract):
        payload = value["payload_json"].encode("utf-8")
        if (len(payload) > 256 * 1024 or len(S.encode(value)) > 512 * 1024
                or hashlib.sha256(payload).hexdigest() != value["payload_sha256"]):
            raise ValueError("fixture full payload hash/size rejected")
        body = json.loads(payload)
        if body["contract_id"] != expected_contract or body["publication_scope"] != "private_only":
            raise ValueError("fixture full contract rejected")
        return body


@pytest.fixture
def full_server(tmp_path, monkeypatch):
    raw = write_envelope(tmp_path, asof=NOW.isoformat())
    current = json.loads(json.loads(raw)["payload_json"])
    store = FullStore(current)
    module = types.ModuleType("ai_fc.trendlines.full_history")
    for name in ("load_manifest", "load_chunk", "decode_envelope"):
        setattr(module, name, getattr(store, name))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(package, "full_history", module, raising=False)
    refresh_calls = []
    companion = service(tmp_path, startup=False,
                        callback=lambda asset: refresh_calls.append(asset) or verified_report())
    httpd = L.make_http_server(companion, port=0)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    yield (companion, httpd), store, refresh_calls
    httpd.shutdown()
    httpd.server_close()
    worker.join(2)
    companion.stop()


def test_full_gets_are_pinned_private_reads_without_triggering_collection(full_server):
    server, store, refresh_calls = full_server
    companion, _httpd = server
    current_bytes = companion.read_asset_envelope("bitcoin")
    for route, expected in ((FULL_ROUTE, store.manifest), (CHUNK_ROUTE, store.chunks[0])):
        status, headers, body = request(server, route)
        assert status == 200 and body == S.encode(expected)
        assert headers["Access-Control-Allow-Origin"] == L.TRUSTED_ORIGIN
        assert headers["Access-Control-Allow-Private-Network"] == "true"
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
    assert store.calls[0] == ("manifest", companion.root, "bitcoin", NOW)
    assert store.calls[1] == ("chunk", companion.root, "bitcoin", FULL_ID, 0, NOW)
    assert refresh_calls == [] and companion._worker is None and not companion._running
    assert companion.read_asset_envelope("bitcoin") == current_bytes


@pytest.mark.parametrize("field,value", [
    ("source_snapshot_id", "research-snapshot-" + "2" * 64),
    ("as_of", "2026-10-13T21:00:00+00:00"),
])
def test_manifest_from_a_different_current_capture_is_rejected(full_server, field, value):
    server, store, _calls = full_server
    body = json.loads(store.manifest["payload_json"])
    body[field] = value
    store.manifest = wrap(body)
    status, _headers, raw = request(server, FULL_ROUTE)
    assert status == 503 and json.loads(raw) == {"error": "local_private_request_rejected"}
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


def test_missing_full_result_is_404_and_current_result_stays_available(full_server):
    server, store, _calls = full_server
    store.manifest = None
    assert request(server, FULL_ROUTE)[0] == 404
    assert request(server, FULL_ROUTE + "/" + FULL_ID + "/bars/1")[0] == 404
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


@pytest.mark.parametrize("route,which", [(FULL_ROUTE, "manifest"), (CHUNK_ROUTE, "chunk")])
def test_tampered_full_wire_is_503_without_price_or_evidence_error_text(full_server, route, which):
    server, store, _calls = full_server
    value = store.manifest if which == "manifest" else store.chunks[0]
    value["payload_json"] += " "
    status, _headers, raw = request(server, route)
    assert status == 503 and json.loads(raw) == {"error": "local_private_request_rejected"}
    assert "fixture" not in raw.decode() and "payload_json" not in raw.decode()
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


@pytest.mark.parametrize("which", ["manifest", "chunk"])
@pytest.mark.parametrize("budget", ["payload", "envelope"])
def test_oversized_full_delivery_is_not_served_even_with_a_valid_wire_hash(full_server, which, budget):
    server, store, _calls = full_server
    value = store.manifest if which == "manifest" else store.chunks[0]
    if budget == "payload":
        body = json.loads(value["payload_json"])
        body["fixture_payload"] = "x" * (256 * 1024)
        replacement = wrap(body)
    else:
        replacement = {**value, "fixture_envelope_padding": "x" * (512 * 1024)}
    if which == "manifest":
        store.manifest = replacement
    else:
        store.chunks[0] = replacement
    assert request(server, FULL_ROUTE if which == "manifest" else CHUNK_ROUTE)[0] == 503
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


@pytest.mark.parametrize("field,value", [
    ("asset_id", "sk-hynix"), ("snapshot_id", "research-full-snapshot-" + "2" * 64),
    ("chunk_index", 1),
])
def test_chunk_body_cannot_cross_asset_snapshot_or_index(full_server, field, value):
    server, store, _calls = full_server
    body = json.loads(store.chunks[0]["payload_json"])
    body[field] = value
    store.chunks[0] = wrap(body)
    assert request(server, CHUNK_ROUTE)[0] == 503


def test_last_bounded_chunk_index_is_forwarded_exactly(full_server):
    server, store, _calls = full_server
    companion, _httpd = server
    assert request(server, FULL_ROUTE + "/" + FULL_ID + "/bars/7")[0] == 200
    assert store.calls == [("chunk", companion.root, "bitcoin", FULL_ID, 7, NOW)]


@pytest.mark.parametrize("route", [
    FULL_ROUTE + "?refresh=1", FULL_ROUTE + "/", FULL_ROUTE.replace("bitcoin", "mag7"),
    FULL_ROUTE.replace("bitcoin", "__proto__"), FULL_ROUTE + "/" + FULL_ID + "/bars/8",
    FULL_ROUTE + "/" + FULL_ID + "/bars/-1", FULL_ROUTE + "/" + FULL_ID + "/bars/00",
    FULL_ROUTE + "/" + FULL_ID + "/bars/0/extra", FULL_ROUTE + "/" + FULL_ID + "/bars/%30",
    FULL_ROUTE + "/research-snapshot-" + "1" * 64 + "/bars/0",
    FULL_ROUTE + "/research-full-snapshot-" + "A" * 64 + "/bars/0",
    FULL_ROUTE + "/../raw", "/data/trendlines_research_full/latest.json",
])
def test_unregistered_full_paths_never_reach_the_loader(full_server, route):
    server, store, refresh_calls = full_server
    assert request(server, route)[0] == 404
    assert store.calls == [] and refresh_calls == []


@pytest.mark.parametrize("origin", ["null", "https://attacker.example", "https://sung-jinpark.github.io.evil"])
def test_full_prices_are_not_exposed_to_foreign_origins(full_server, origin):
    server, store, _calls = full_server
    status, headers, raw = request(server, FULL_ROUTE, origin=origin)
    assert status == 403 and "Access-Control-Allow-Origin" not in headers
    assert "payload_json" not in raw.decode() and store.calls == []


@pytest.mark.parametrize("host", ["localhost:8878", "127.0.0.1:8878.evil", "attacker.example:8878"])
def test_full_routes_keep_the_exact_loopback_host_guard(full_server, host):
    server, store, _calls = full_server
    assert request(server, CHUNK_ROUTE, host=host)[0] == 403 and store.calls == []


def test_full_preflight_allows_only_trusted_get(full_server):
    server, store, _calls = full_server
    headers = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "Accept",
               "Access-Control-Request-Private-Network": "true"}
    status, response, raw = request(server, CHUNK_ROUTE, method="OPTIONS", headers=headers)
    assert status == 204 and raw == b"" and response["Access-Control-Allow-Origin"] == L.TRUSTED_ORIGIN
    assert request(server, CHUNK_ROUTE, method="OPTIONS", headers={**headers, "Access-Control-Request-Method": "POST"})[0] == 403
    assert request(server, CHUNK_ROUTE, method="OPTIONS", headers={**headers, "Access-Control-Request-Headers": "Authorization"})[0] == 403
    assert store.calls == []


@pytest.mark.parametrize("route", [FULL_ROUTE, CHUNK_ROUTE])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_full_http_routes_cannot_write_or_start_work(full_server, route, method):
    server, store, refresh_calls = full_server
    assert request(server, route, method=method, body="refresh")[0] == 405
    assert store.calls == [] and refresh_calls == []


def test_full_failure_keeps_successful_current_export_and_persists_only_its_own_error(tmp_path):
    before = write_envelope(tmp_path)
    clock = Clock()
    calls = []

    def callback(asset):
        calls.append(asset)
        write_envelope(tmp_path, asof=NOW.isoformat())
        return {**verified_report(), "changed": True,
                "full_history": {"status": "unavailable", "reason": "fixture private detail must stay private"}}

    companion = service(tmp_path, callback=callback, clock=clock)
    companion.start(scheduler=False)
    try:
        assert companion.wait_idle(5) and calls == ["bitcoin"]
        current = companion.read_asset_envelope("bitcoin")
        assert current != before
        row = next(row for row in companion.status()["assets"] if row["asset_id"] == "bitcoin")
        assert row["status"] == "ready" and row["stale"] is False and row["error"] is None
        assert row["full_error"] == "full_refresh_failed" and row["last_success"] == NOW.isoformat()
        assert "fixture private" not in json.dumps(companion.status())
        state = json.loads((tmp_path / "local-service-state.json").read_bytes())
        assert state["assets"]["bitcoin"]["full_error"] == "full_refresh_failed"
    finally:
        companion.stop()
    restarted = service(tmp_path, clock=clock, startup=False)
    row = next(row for row in restarted.status()["assets"] if row["asset_id"] == "bitcoin")
    assert row["full_error"] == "full_refresh_failed" and row["error"] is None and row["stale"] is False
    assert restarted.read_asset_envelope("bitcoin") == current


def test_later_success_clears_full_error_without_changing_current_chart(tmp_path):
    raw = write_envelope(tmp_path, asof=NOW.isoformat())
    state = {"schema_version": 1, "contract_id": "trendlines_local_worker_state_v1", "assets": {
        "bitcoin": {"last_attempt": NOW.isoformat(), "last_success": NOW.isoformat(),
                    "error": None, "full_error": "full_refresh_failed"}}}
    (tmp_path / "local-service-state.json").write_bytes(S.encode(state))
    companion = service(tmp_path, callback=lambda _asset: {**verified_report(), "full_history": {"status": "ready"}})
    companion.start(scheduler=False)
    try:
        assert companion.wait_idle(5)
        row = next(row for row in companion.status()["assets"] if row["asset_id"] == "bitcoin")
        assert row["error"] is None and row["full_error"] is None and row["stale"] is False
        assert companion.read_asset_envelope("bitcoin") == raw
        persisted = json.loads((tmp_path / "local-service-state.json").read_bytes())
        assert persisted["assets"]["bitcoin"]["full_error"] is None
    finally:
        companion.stop()
