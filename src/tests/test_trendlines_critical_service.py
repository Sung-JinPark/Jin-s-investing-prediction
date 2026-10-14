"""Read-only critical-boundary delivery, source pinning and failure isolation.

Numerical/source replay belongs to the critical engine tests. These offline
tests mock only immutable loaders/transport decoding and never collect data.
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
NOW = HELPERS["NOW"]
Clock = HELPERS["Clock"]
write_envelope, verified_report = HELPERS["write_envelope"], HELPERS["verified_report"]
service, request = HELPERS["service"], HELPERS["request"]
FULL_ID = "research-full-snapshot-" + "1" * 64
CORE_ID = "research-critical-snapshot-" + "2" * 64
CORE_ROUTE = "/api/private-trendlines/bitcoin/critical"
DETAIL_CONTRACT = "trendlines_private_critical_v1"
TRANSPORT_CONTRACT = "trendlines_private_critical_transport_v1"


def wrap(body, *, transport=TRANSPORT_CONTRACT):
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {"schema_version": 1, "contract_id": transport,
            "publication_scope": "private_only", "payload_json": payload,
            "payload_sha256": hashlib.sha256(payload.encode()).hexdigest()}


class CriticalStore:
    """Loader seam: exact bytes/hash/contract; service owns source bindings."""

    def __init__(self, current):
        self.detail = wrap({"schema_version": 1, "contract_id": DETAIL_CONTRACT,
            "publication_scope": "private_only", "asset_id": "bitcoin", "snapshot_id": CORE_ID,
            "policy_version": "critical_v1", "source_snapshot_id": current["snapshot_id"],
            "source_full_snapshot_id": FULL_ID, "source_engine_content_hash": current["source_snapshot_hash"],
            "as_of": current["as_of"], "reference_session": current["observation_through"],
            "reference_index": current["bars"][-1]["session_index"], "reference_close": current["bars"][-1]["close"],
            "atr14": 4.0, "analyses": {"linear": {}, "log": {}}, "fixture_only": True})
        self.full = wrap({"schema_version": 1, "contract_id": "trendlines_private_full_manifest_v1",
            "publication_scope": "private_only", "asset_id": "bitcoin", "snapshot_id": FULL_ID,
            "source_snapshot_id": current["snapshot_id"], "as_of": current["as_of"]},
            transport="trendlines_private_full_transport_v1")
        self.calls = []
        self.error = None

    def load_detail(self, root, asset_id, *, now):
        self.calls.append(("critical", root, asset_id, now))
        if self.error:
            raise self.error
        return deepcopy(self.detail)

    def load_manifest(self, root, asset_id, *, now):
        self.calls.append(("full", root, asset_id, now))
        return deepcopy(self.full)

    def decode_envelope(self, value, expected_contract=None):
        raw = value["payload_json"].encode()
        if (len(raw) > 256 * 1024 or len(S.encode(value)) > 512 * 1024
                or hashlib.sha256(raw).hexdigest() != value["payload_sha256"]):
            raise ValueError("fixture transport hash/size invalid")
        body = json.loads(raw)
        if expected_contract is None:
            expected_contract = DETAIL_CONTRACT
        if body["contract_id"] != expected_contract or body["publication_scope"] != "private_only":
            raise ValueError("fixture detail contract invalid")
        return body


@pytest.fixture
def critical_server(tmp_path, monkeypatch):
    original = write_envelope(tmp_path, asof=NOW.isoformat())
    current = json.loads(json.loads(original)["payload_json"])
    store = CriticalStore(current)
    for name, functions in (("critical", ("load_detail", "decode_envelope")),
                            ("full_history", ("load_manifest", "decode_envelope"))):
        module = types.ModuleType("ai_fc.trendlines." + name)
        for function in functions:
            setattr(module, function, getattr(store, function))
        if name == "critical":
            module.DETAIL_CONTRACT = DETAIL_CONTRACT
            module.TRANSPORT_CONTRACT = TRANSPORT_CONTRACT
        monkeypatch.setitem(sys.modules, module.__name__, module)
        monkeypatch.setattr(package, name, module, raising=False)
    refresh_calls = []
    companion = service(tmp_path, startup=False,
        callback=lambda asset: refresh_calls.append(asset) or verified_report())
    httpd = L.make_http_server(companion, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield (companion, httpd), store, refresh_calls
    httpd.shutdown()
    httpd.server_close()
    thread.join(2)
    companion.stop()


def test_critical_get_is_a_pinned_private_read_and_never_runs_collection(critical_server):
    server, store, refresh_calls = critical_server
    companion, _httpd = server
    before = companion.read_asset_envelope("bitcoin")
    status, headers, body = request(server, CORE_ROUTE)
    assert status == 200 and body == S.encode(store.detail)
    assert headers["Access-Control-Allow-Origin"] == L.TRUSTED_ORIGIN
    assert headers["Access-Control-Allow-Private-Network"] == "true"
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    assert ("critical", companion.root, "bitcoin", NOW) in store.calls
    assert ("full", companion.root, "bitcoin", NOW) in store.calls
    assert refresh_calls == [] and companion._worker is None and not companion._running
    assert companion.read_asset_envelope("bitcoin") == before


@pytest.mark.parametrize("field,value", [
    ("source_snapshot_id", "research-snapshot-" + "3" * 64),
    ("source_full_snapshot_id", "research-full-snapshot-" + "3" * 64),
    ("as_of", "2026-10-13T21:00:00+00:00"),
    ("asset_id", "sk-hynix"),
    ("reference_session", "2026-10-01"),
    ("reference_close", 999.0),
    ("source_engine_content_hash", "3" * 64),
])
def test_critical_cannot_cross_current_full_or_reference_capture(critical_server, field, value):
    server, store, _calls = critical_server
    body = json.loads(store.detail["payload_json"])
    body[field] = value
    store.detail = wrap(body)
    status, _headers, raw = request(server, CORE_ROUTE)
    assert status == 503 and json.loads(raw) == {"error": "local_private_request_rejected"}
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


def test_missing_critical_is_404_without_hiding_verified_candles(critical_server):
    server, store, _calls = critical_server
    store.detail = None
    assert request(server, CORE_ROUTE)[0] == 404
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


@pytest.mark.parametrize("error", [ValueError("corrupt immutable source fixture"),
    OSError("source fixture unreadable"), KeyError("snapshot fixture missing")])
def test_source_failure_is_isolated_and_does_not_disclose_evidence(critical_server, error):
    server, store, _calls = critical_server
    store.error = error
    status, _headers, raw = request(server, CORE_ROUTE)
    assert status == 503 and json.loads(raw) == {"error": "local_private_request_rejected"}
    assert "fixture" not in raw.decode() and "snapshot" not in raw.decode()
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


def test_tampered_transport_is_rejected_without_hiding_candles(critical_server):
    server, store, _calls = critical_server
    store.detail["payload_json"] += " "
    assert request(server, CORE_ROUTE)[0] == 503
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


@pytest.mark.parametrize("route", [CORE_ROUTE + "?refresh=1", CORE_ROUTE + "/", CORE_ROUTE + "/latest",
    CORE_ROUTE.replace("bitcoin", "mag7"), CORE_ROUTE.replace("bitcoin", "__proto__"),
    CORE_ROUTE.replace("bitcoin", "%62itcoin"), CORE_ROUTE + "/../raw",
    "/data/trendlines_research_critical/latest.json"])
def test_unregistered_critical_paths_do_not_reach_loaders(critical_server, route):
    server, store, refresh_calls = critical_server
    assert request(server, route)[0] == 404
    assert store.calls == [] and refresh_calls == []


@pytest.mark.parametrize("origin", ["null", "https://attacker.example", "https://sung-jinpark.github.io.evil"])
def test_critical_prices_never_escape_to_foreign_origins(critical_server, origin):
    server, store, _calls = critical_server
    status, headers, raw = request(server, CORE_ROUTE, origin=origin)
    assert status == 403 and "Access-Control-Allow-Origin" not in headers
    assert "payload_json" not in raw.decode() and store.calls == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD"])
def test_critical_is_not_a_mutation_or_refresh_endpoint(critical_server, method):
    server, store, refresh_calls = critical_server
    companion, _httpd = server
    before = {path.name: path.read_bytes() for path in companion.root.iterdir() if path.is_file()}
    assert request(server, CORE_ROUTE, method=method, body="refresh")[0] == 405
    assert store.calls == [] and refresh_calls == []
    assert before == {path.name: path.read_bytes() for path in companion.root.iterdir() if path.is_file()}


def test_critical_preflight_only_allows_trusted_read(critical_server):
    server, store, _calls = critical_server
    headers = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "Accept",
               "Access-Control-Request-Private-Network": "true"}
    status, response, raw = request(server, CORE_ROUTE, method="OPTIONS", headers=headers)
    assert status == 204 and raw == b"" and response["Access-Control-Allow-Origin"] == L.TRUSTED_ORIGIN
    assert response["Access-Control-Allow-Private-Network"] == "true"
    assert request(server, CORE_ROUTE, method="OPTIONS", headers={**headers,"Access-Control-Request-Method":"POST"})[0] == 403
    assert request(server, CORE_ROUTE, method="OPTIONS", headers={**headers,"Access-Control-Request-Headers":"Authorization"})[0] == 403
    assert store.calls == []


def test_missing_full_source_is_404_without_hiding_current_candles(critical_server):
    server, store, _calls = critical_server
    store.full = None
    assert request(server, CORE_ROUTE)[0] == 404
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


@pytest.mark.parametrize("field,value", [("source_snapshot_id", "research-snapshot-" + "3" * 64),
    ("as_of", "2026-10-13T21:00:00+00:00")])
def test_full_source_must_itself_match_current_capture(critical_server, field, value):
    server, store, _calls = critical_server
    body = json.loads(store.full["payload_json"])
    body[field] = value
    store.full = wrap(body, transport="trendlines_private_full_transport_v1")
    assert request(server, CORE_ROUTE)[0] == 503
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 200


def test_critical_failure_keeps_successful_current_export_and_only_its_own_error(tmp_path):
    before = write_envelope(tmp_path)
    clock = Clock()
    calls = []

    def callback(asset):
        calls.append(asset)
        write_envelope(tmp_path, asof=NOW.isoformat())
        return {**verified_report(), "changed": True, "full_history": {"status": "ready"},
                "critical": {"status": "unavailable", "reason": "fixture private evidence stays private"}}

    companion = service(tmp_path, callback=callback, clock=clock)
    companion.start(scheduler=False)
    try:
        assert companion.wait_idle(5) and calls == ["bitcoin"]
        current = companion.read_asset_envelope("bitcoin")
        assert current != before
        row = next(row for row in companion.status()["assets"] if row["asset_id"] == "bitcoin")
        assert row["status"] == "ready" and row["stale"] is False and row["error"] is None
        assert row["full_error"] is None and row["critical_error"] == "critical_refresh_failed"
        assert row["last_success"] == NOW.isoformat() and "fixture private" not in json.dumps(companion.status())
        state = json.loads((tmp_path / "local-service-state.json").read_bytes())
        assert state["assets"]["bitcoin"]["critical_error"] == "critical_refresh_failed"
    finally:
        companion.stop()
    restarted = service(tmp_path, clock=clock, startup=False)
    row = next(row for row in restarted.status()["assets"] if row["asset_id"] == "bitcoin")
    assert row["critical_error"] == "critical_refresh_failed" and row["error"] is None and row["stale"] is False
    assert restarted.read_asset_envelope("bitcoin") == current


def test_later_success_clears_only_critical_error_without_changing_candles(tmp_path):
    raw = write_envelope(tmp_path, asof=NOW.isoformat())
    state = {"schema_version": 1, "contract_id": "trendlines_local_worker_state_v1", "assets": {
        "bitcoin": {"last_attempt": NOW.isoformat(), "last_success": NOW.isoformat(),
                    "error": None, "full_error": None, "critical_error": "critical_refresh_failed"}}}
    (tmp_path / "local-service-state.json").write_bytes(S.encode(state))
    companion = service(tmp_path, callback=lambda _asset: {**verified_report(), "critical": {"status": "ready"}})
    companion.start(scheduler=False)
    try:
        assert companion.wait_idle(5)
        row = next(row for row in companion.status()["assets"] if row["asset_id"] == "bitcoin")
        assert row["error"] is None and row["critical_error"] is None and row["stale"] is False
        assert companion.read_asset_envelope("bitcoin") == raw
        persisted = json.loads((tmp_path / "local-service-state.json").read_bytes())
        assert persisted["assets"]["bitcoin"]["critical_error"] is None
    finally:
        companion.stop()
