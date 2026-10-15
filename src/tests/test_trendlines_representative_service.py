"""Representative delivery guards; source arithmetic is tested independently."""
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

H = runpy.run_path(str(Path(__file__).with_name("test_trendlines_local_service.py")))
NOW, Clock = H["NOW"], H["Clock"]
write_envelope, verified_report, service, request = (H[k] for k in
    ("write_envelope", "verified_report", "service", "request"))
ROUTE = "/api/private-trendlines/bitcoin/representative"
DETAIL = "trendlines_private_representative_v1"


def wrap(body, contract="trendlines_private_representative_transport_v1"):
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {"schema_version": 1, "contract_id": contract, "publication_scope": "private_only",
            "payload_json": payload, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest()}


class RepresentativeStore:
    def __init__(self, current):
        self.full = wrap({"schema_version": 1, "contract_id": "trendlines_private_full_manifest_v1",
            "publication_scope": "private_only", "asset_id": "bitcoin",
            "snapshot_id": "research-full-snapshot-" + "1" * 64,
            "source_snapshot_id": current["snapshot_id"], "as_of": current["as_of"]},
            "trendlines_private_full_transport_v1")
        self.detail = wrap({"schema_version": 1, "contract_id": DETAIL,
            "publication_scope": "private_only", "asset_id": "bitcoin", "policy_version": "representative_v1",
            "source_snapshot_id": current["snapshot_id"], "source_full_snapshot_id": "research-full-snapshot-" + "1" * 64,
            "source_engine_content_hash": current["source_snapshot_hash"], "as_of": current["as_of"],
            "source_archive_sha256": current.get("research_archive_sha256"),
            "source_engine_snapshot_id": current.get("engine_snapshot_id"),
            "full_manifest_payload_sha256": self.full["payload_sha256"],
            "reference_session": current["observation_through"], "reference_index": current["bars"][-1]["session_index"],
            "reference_close": current["bars"][-1]["close"], "fixture_only": True})
        self.calls = []
        self.error = None

    def load_detail(self, root, asset_id, *, now):
        self.calls.append(("representative", root, asset_id, now))
        if self.error:
            raise self.error
        return deepcopy(self.detail)

    def load_manifest(self, root, asset_id, *, now):
        self.calls.append(("full", root, asset_id, now))
        return deepcopy(self.full)

    def decode_envelope(self, envelope, expected_contract=DETAIL):
        raw = envelope["payload_json"].encode()
        if hashlib.sha256(raw).hexdigest() != envelope["payload_sha256"]:
            raise ValueError("fixture payload modified")
        body = json.loads(raw)
        if body["contract_id"] != expected_contract or body["publication_scope"] != "private_only":
            raise ValueError("fixture wrong contract")
        return body


@pytest.fixture
def representative_server(tmp_path, monkeypatch):
    original = write_envelope(tmp_path, asof=NOW.isoformat())
    store = RepresentativeStore(json.loads(json.loads(original)["payload_json"]))
    for name, functions in (("representative", ("load_detail", "decode_envelope")),
                            ("full_history", ("load_manifest", "decode_envelope"))):
        module = types.ModuleType("ai_fc.trendlines." + name)
        for function in functions:
            setattr(module, function, getattr(store, function))
        monkeypatch.setitem(sys.modules, module.__name__, module)
        monkeypatch.setattr(package, name, module, raising=False)
    calls = []
    companion = service(tmp_path, startup=False, callback=lambda asset: calls.append(asset) or verified_report())
    httpd = L.make_http_server(companion, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield (companion, httpd), store, calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(2)
        companion.stop()


def test_representative_is_only_a_pinned_read(representative_server):
    server, store, calls = representative_server
    companion, _httpd = server
    before = companion.read_asset_envelope("bitcoin")
    code, headers, raw = request(server, ROUTE)
    assert code == 200 and raw == S.encode(store.detail)
    assert headers["Cache-Control"] == "no-store"
    assert headers["Access-Control-Allow-Origin"] == L.TRUSTED_ORIGIN
    assert ("representative", companion.root, "bitcoin", NOW) in store.calls
    assert not calls and companion._worker is None
    assert companion.read_asset_envelope("bitcoin") == before


@pytest.mark.parametrize("field,value", [
    ("asset_id", "sk-hynix"), ("source_snapshot_id", "other-source"),
    ("source_full_snapshot_id", "other-full"), ("source_engine_content_hash", "2" * 64),
    ("as_of", "2026-10-01T00:00:00+00:00"), ("reference_session", "2026-10-01"),
    ("reference_index", 999), ("reference_close", 999), ("full_manifest_payload_sha256", "3" * 64),
    ("source_archive_sha256", "4" * 64), ("source_engine_snapshot_id", "another-engine"),
])
def test_cross_capture_or_reference_is_rejected(representative_server, field, value):
    server, store, _calls = representative_server
    body = json.loads(store.detail["payload_json"])
    body[field] = value
    store.detail = wrap(body)
    code, _headers, raw = request(server, ROUTE)
    assert code == 503 and json.loads(raw) == {"error": "local_private_request_rejected"}
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


def test_unavailable_or_corrupt_overlay_does_not_hide_candles(representative_server):
    server, store, _calls = representative_server
    original = deepcopy(store.detail)
    store.detail = None
    assert request(server, ROUTE)[0] == 404
    store.detail = original
    store.detail["payload_sha256"] = "0" * 64
    assert request(server, ROUTE)[0] == 503
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


@pytest.mark.parametrize("route", [ROUTE + "?refresh=1", ROUTE + "/", ROUTE + "/raw",
    ROUTE.replace("bitcoin", "mag7"), ROUTE.replace("bitcoin", "%62itcoin")])
def test_unregistered_paths_never_reach_overlay_loader(representative_server, route):
    server, store, calls = representative_server
    assert request(server, route)[0] == 404
    assert not store.calls and not calls


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT", "PATCH", "HEAD"])
def test_overlay_route_never_starts_collection_or_writes(representative_server, method):
    server, store, calls = representative_server
    assert request(server, ROUTE, method=method, body="refresh")[0] == 405
    assert not calls and not store.calls


def test_foreign_origin_cannot_read_representatives(representative_server):
    server, store, _calls = representative_server
    code, headers, _raw = request(server, ROUTE, origin="https://attacker.example")
    assert code == 403 and "Access-Control-Allow-Origin" not in headers and not store.calls


def test_representative_failure_is_separate_and_persists_across_restart(tmp_path):
    raw = write_envelope(tmp_path, asof=NOW.isoformat())
    companion = service(tmp_path, callback=lambda _asset: {**verified_report(),
        "full_history": {"status": "ready"}, "critical": {"status": "ready"},
        "representative": {"status": "unavailable", "error": "private fixture details"}})
    companion.start(scheduler=False)
    try:
        assert companion.wait_idle(5)
        row = next(a for a in companion.status()["assets"] if a["asset_id"] == "bitcoin")
        assert row["representative_error"] == "representative_refresh_failed"
        assert row["error"] is None and row["critical_error"] is None and row["full_error"] is None
        assert companion.read_asset_envelope("bitcoin") == raw
        assert "fixture details" not in json.dumps(companion.status())
    finally:
        companion.stop()
    restarted = service(tmp_path)
    row = next(a for a in restarted.status()["assets"] if a["asset_id"] == "bitcoin")
    assert row["representative_error"] == "representative_refresh_failed"
    restarted.refresh_asset = lambda _asset: {**verified_report(), "representative": {"status": "ready"}}
    restarted.start(scheduler=False)
    try:
        assert restarted.wait_idle(5)
        row = next(a for a in restarted.status()["assets"] if a["asset_id"] == "bitcoin")
        assert row["representative_error"] is None
    finally:
        restarted.stop()
