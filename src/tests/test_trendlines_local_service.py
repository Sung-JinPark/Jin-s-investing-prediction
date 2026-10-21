"""Offline personal companion scheduling, original-byte delivery and boundaries."""

from __future__ import annotations

import hashlib
import http.client
import json
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, local_service as L, research as R, storage as S

REPOSITORY = Path(__file__).resolve().parents[2]
NOW = C.aware_time("2026-10-14T00:17:00+00:00")
ASOF = "2026-10-13T21:00:00+00:00"


class Clock:
    def __init__(self, value=NOW): self.value = value
    def __call__(self): return self.value


def envelope(asset_id="bitcoin", *, asof=ASOF, invalid=False):
    asset = deepcopy(C.load_asset_registry(REPOSITORY)[asset_id])
    asset.update({"provider_symbol": R.SYMBOLS[asset_id], "source_id": R.SOURCE,
                  "price_basis": C.RESEARCH_PRICE_BASIS, "enabled": True, "verified_source": False,
                  "rights_status": R.RIGHTS, "source_context": R.CONTEXT})
    last = C.latest_completed_session(asset, asof, buffer_minutes=15)
    sessions = C.session_schedule(asset["calendar_id"], (date.fromisoformat(last)-timedelta(days=10)).isoformat(), last)[-2:]
    bars = [{"session": day, "session_index": index, "open": 101.0, "high": 104.0, "low": 100.0,
             "close": 102.0, "bar_id": "research-bar-" + C.canonical_hash({"asset": asset_id, "day": day})}
            for index, (day, _opened, _closed) in enumerate(sessions)]
    if invalid: bars[-1]["high"] = 1.0
    body = {"schema_version": 1, "contract_id": "trendlines_research_display_v1", "asset_id": asset_id,
            "asset": asset, "status": "unverified_display", "publication_scope": "private_only",
            "publication_class": "research_source", "source_context": R.CONTEXT,
            "verified_source": False, "numbers_visible": True, "official_forecast_write": False,
            "adjustment_verified": False, "historical_signals_available": False,
            "guards": {"approved_free_ohlc": False}, "bars": bars,
            "as_of": asof, "knowledge_cutoff": asof, "retrieved_at": asof,
            "observation_through": last, "source_identity": {"source_id": R.SOURCE,
                "rights_status": R.RIGHTS, "price_basis": asset["price_basis"], "provider_symbol": asset["provider_symbol"],
                "calendar_id": asset["calendar_id"], "verified_source": False},
            "snapshot_id": "research-snapshot-" + C.canonical_hash({"asset": asset_id, "asof": asof})}
    body.update({"receipt_id": "research-receipt-" + C.canonical_hash({"fixture_receipt": asset_id}),
                 "raw_sha256": C.canonical_hash({"fixture_raw": asset_id}),
                 "research_archive_sha256": C.canonical_hash({"fixture_archive": asset_id}),
                 "source_snapshot_hash": C.canonical_hash({"fixture_engine": asset_id}),
                 "source_url": "https://finance.yahoo.com/quote/" + asset["provider_symbol"] + "/history/"})
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"schema_version": 1, "contract_id": "trendlines_private_import_v1", "publication_scope": "private_only",
            "asset_id": asset_id, "snapshot_id": body["snapshot_id"], "payload_json": payload,
            "payload_sha256": hashlib.sha256(payload.encode()).hexdigest()}


def write_envelope(root, asset_id="bitcoin", **options):
    value = envelope(asset_id, **options)
    raw = S.encode(value)
    (root / (asset_id + ".trendlines.json")).write_bytes(raw)
    return raw


def verified_report():
    return {"publication_scope": "private_only", "public_prices_published": False,
            "independent_replay": {"ok": True}, "changed": False}


def packed_envelope(asset_id="bitcoin"):
    original = envelope(asset_id)
    body = json.loads(original["payload_json"])
    packed = {key: value for key, value in body.items() if key != "bars"}
    packed["original_detail_sha256"] = original["payload_sha256"]
    packed["bars_packed"] = {"columns": list(R.PRIVATE_BAR_COLUMNS),
                             "rows": [[bar[key] for key in R.PRIVATE_BAR_COLUMNS] for bar in body["bars"]]}
    payload = json.dumps(packed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**original, "schema_version": 2, "contract_id": "trendlines_private_import_v2",
            "original_detail_sha256": original["payload_sha256"], "payload_json": payload,
            "payload_sha256": hashlib.sha256(payload.encode()).hexdigest()}


def service(root, *, callback=None, clock=None, startup=True, assets=("bitcoin",), preview=None):
    return L.LocalTrendlinesService(root, refresh_asset=callback or (lambda _asset: verified_report()),
        clock=clock or Clock(), assets=assets, startup_refresh=startup, build_preview=preview)


@pytest.fixture
def server(tmp_path):
    write_envelope(tmp_path)
    companion = service(tmp_path, startup=False)
    httpd = L.make_http_server(companion, port=0)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    yield companion, httpd
    httpd.shutdown(); httpd.server_close(); worker.join(2); companion.stop()


def request(server, route, *, origin=L.TRUSTED_ORIGIN, host=None, method="GET", headers=None, body=None):
    _companion, httpd = server
    connection = http.client.HTTPConnection(L.HOST, httpd.server_address[1], timeout=5)
    note = {"Host": host or httpd.expected_host}
    if origin is not None: note["Origin"] = origin
    note.update(headers or {})
    connection.request(method, route, body=body, headers=note)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def test_exact_validated_import_bytes_and_cors_are_delivered(server):
    companion, _httpd = server
    raw = (companion.root / "bitcoin.trendlines.json").read_bytes()
    status, headers, body = request(server, "/api/private-trendlines/bitcoin")
    assert status == 200 and body == raw
    assert headers["Access-Control-Allow-Origin"] == L.TRUSTED_ORIGIN
    assert headers["Access-Control-Allow-Private-Network"] == "true"
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    assert not companion._running and not companion._worker


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "https://sung-jinpark.github.io.evil.test",
                                    "http://sung-jinpark.github.io", "https://sung-jinpark.github.io/"])
def test_foreign_origins_receive_no_private_body_or_cors(server, origin):
    status, headers, body = request(server, "/api/private-trendlines/bitcoin", origin=origin)
    assert status == 403 and "Access-Control-Allow-Origin" not in headers
    assert "payload_json" not in body.decode()


@pytest.mark.parametrize("host", ["localhost:8878", "attacker.example:8878", "127.0.0.1", "127.0.0.1:8878.evil",
                                  "127.0.0.2:8878"])
def test_exact_host_blocks_dns_rebinding_and_aliases(server, host):
    assert request(server, "/api/private-trendlines/status", host=host)[0] == 403


def test_same_origin_and_local_no_origin_reads_are_allowed(server):
    _companion, httpd = server
    assert request(server, "/api/private-trendlines/bitcoin", origin=httpd.local_origin)[0] == 200
    status, headers, _body = request(server, "/api/private-trendlines/bitcoin", origin=None)
    assert status == 200 and "Access-Control-Allow-Origin" not in headers


@pytest.mark.parametrize("route", ["/api/private-trendlines/mag7", "/api/private-trendlines/__proto__",
    "/api/private-trendlines/bitcoin?refresh=1", "/api/private-trendlines/refresh", "/api/private-trendlines/../raw",
    "/data/trendlines_research/raw/file.bin", "/bitcoin.trendlines.json", "/local-service-state.json",
    "/api/private-trendlines/%62itcoin", "/favicon.ico"])
def test_only_fixed_read_routes_are_exposed(server, route):
    assert request(server, route)[0] == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD"])
def test_http_never_runs_refresh_or_writes(server, method):
    companion, _httpd = server
    before = {path.name: path.read_bytes() for path in companion.root.iterdir() if path.is_file()}
    assert request(server, "/api/private-trendlines/bitcoin", method=method, body="refresh")[0] == 405
    assert before == {path.name: path.read_bytes() for path in companion.root.iterdir() if path.is_file()}
    assert not companion._worker


def test_private_network_preflight_is_scoped_to_trusted_get(server):
    headers = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Private-Network": "true"}
    status, response, body = request(server, "/api/private-trendlines/status", method="OPTIONS", headers=headers)
    assert status == 204 and not body and response["Access-Control-Allow-Methods"] == "GET"
    assert response["Access-Control-Allow-Private-Network"] == "true"
    for changed in ({"Access-Control-Request-Method": "POST"}, {"Access-Control-Request-Headers": "Authorization"}):
        assert request(server, "/api/private-trendlines/status", method="OPTIONS", headers={**headers, **changed})[0] == 403


@pytest.mark.parametrize("attack", ["hash", "price", "scope", "approval", "identity", "future", "large"])
def test_corrupt_or_misqualified_delivery_file_is_rejected(server, attack):
    companion, _httpd = server
    value = envelope()
    detail = json.loads(value["payload_json"])
    if attack == "hash": value["payload_sha256"] = "0" * 64
    if attack == "price": detail["bars"][0]["high"] = 1
    if attack == "scope": detail["publication_scope"] = "public"
    if attack == "approval": detail["guards"]["approved_free_ohlc"] = True
    if attack == "identity": detail["asset"]["provider_symbol"] = "MAGS"
    if attack == "future": detail["as_of"] = detail["knowledge_cutoff"] = "2028-01-01T00:00:00+00:00"
    if attack == "large": value["payload_json"] = " " * (R.MAX_PRIVATE_PAYLOAD_BYTES + 1)
    elif attack != "hash":
        value["payload_json"] = json.dumps(detail, sort_keys=True, separators=(",", ":"))
        value["payload_sha256"] = hashlib.sha256(value["payload_json"].encode()).hexdigest()
    (companion.root / "bitcoin.trendlines.json").write_bytes(S.encode(value))
    status, _headers, body = request(server, "/api/private-trendlines/bitcoin")
    assert status == 503 and "payload_json" not in body.decode()


def test_startup_catchup_and_kst_daily_slots_run_once(tmp_path):
    clock = Clock(C.aware_time("2026-10-13T22:00:00+00:00"))  # 07:00 KST
    write_envelope(tmp_path)
    calls = []
    companion = service(tmp_path, clock=clock, callback=lambda asset: calls.append(asset) or verified_report())
    companion.start(scheduler=False)
    assert companion.wait_idle() and calls == ["bitcoin"]
    assert not companion.tick()
    for stamp in ("2026-10-13T22:17:00+00:00", "2026-10-14T00:17:00+00:00", "2026-10-14T07:17:00+00:00"):
        clock.value = C.aware_time(stamp)
        assert companion.tick() and companion.wait_idle()
        assert not companion.tick()
    assert len(calls) == 4
    assert companion.next_refresh() == "2026-10-15T07:17:00+09:00"
    companion.stop()


def test_no_startup_refresh_still_claims_next_schedule(tmp_path):
    clock = Clock(C.aware_time("2026-10-13T22:00:00+00:00"))
    calls = []
    companion = service(tmp_path, clock=clock, startup=False, callback=lambda asset: calls.append(asset) or verified_report())
    companion.start(scheduler=False)
    assert not calls and not companion.tick()
    clock.value = C.aware_time("2026-10-13T22:17:00+00:00")
    assert companion.tick() and companion.wait_idle() and calls == ["bitcoin"]
    companion.stop()


def test_missed_intervals_collapse_and_workers_never_overlap(tmp_path):
    clock = Clock(C.aware_time("2026-10-13T22:00:00+00:00"))
    entered, release = threading.Event(), threading.Event()
    calls, active, maximum = [], 0, 0
    lock = threading.Lock()
    write_envelope(tmp_path)
    def refresh(asset):
        nonlocal active, maximum
        with lock:
            active += 1; maximum = max(maximum, active); calls.append(asset)
        entered.set(); release.wait(2)
        with lock: active -= 1
        return verified_report()
    companion = service(tmp_path, clock=clock, callback=refresh)
    companion.start(scheduler=False)
    assert entered.wait(2)
    clock.value = C.aware_time("2026-10-15T07:20:00+00:00")
    assert companion.tick() and not companion.tick()
    release.set()
    assert companion.wait_idle() and len(calls) == 2 and maximum == 1
    companion.stop()


def test_failed_asset_preserves_last_good_bytes_and_does_not_stop_other_assets(tmp_path):
    before = write_envelope(tmp_path)
    write_envelope(tmp_path, "sk-hynix")
    calls = []
    def refresh(asset):
        calls.append(asset)
        if asset == "bitcoin":
            (tmp_path / "bitcoin.trendlines.json").write_text("invalid new file")
            raise ValueError("private prices must never enter HTTP error text")
        return verified_report()
    companion = service(tmp_path, callback=refresh, assets=("bitcoin", "sk-hynix"))
    companion.start(scheduler=False)
    assert companion.wait_idle()
    assert calls == ["bitcoin", "sk-hynix"] and (tmp_path / "bitcoin.trendlines.json").read_bytes() == before
    rows = {row["asset_id"]: row for row in companion.status()["assets"]}
    assert rows["bitcoin"]["error"] == "refresh_failed" and rows["bitcoin"]["status"] == "stale"
    assert rows["bitcoin"]["last_success"] is None and rows["sk-hynix"]["last_success"]
    assert "private prices" not in json.dumps(rows)
    companion.stop()


def test_status_freshness_uses_now_not_frozen_payload_quality(tmp_path):
    clock = Clock(C.aware_time("2026-10-13T23:59:00+00:00"))
    write_envelope(tmp_path)
    companion = service(tmp_path, clock=clock)
    row = next(row for row in companion.status()["assets"] if row["asset_id"] == "bitcoin")
    assert row["status"] == "ready" and not row["stale"]
    clock.value = NOW
    row = next(row for row in companion.status()["assets"] if row["asset_id"] == "bitcoin")
    assert row["status"] == "stale" and row["reason"] == "latest_completed_session_missing"
    assert row["source_asof"] == ASOF
    status = companion.status()
    assert len(S.encode(status)) < L.STATUS_BUDGET and len(status["assets"]) == len(C.ASSET_IDS)
    assert status["assets"][-1]["asset_id"] == "mag7" and status["assets"][-1]["status"] == "hold"


def test_last_attempt_success_survive_restart_without_a_new_capture(tmp_path):
    write_envelope(tmp_path)
    companion = service(tmp_path)
    companion.start(scheduler=False); assert companion.wait_idle(); companion.stop()
    state = companion.status()["assets"]
    restarted = service(tmp_path, startup=False)
    assert restarted.status()["assets"] == state


def test_preview_callback_and_static_whitelist_expose_no_receipts(server):
    companion, _httpd = server
    site = companion.root / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<html>private preview</html>")
    (site / "assets/trendlines.js").write_text("/* local chart */")
    (site / "raw.json").write_text("secret original")
    assert request(server, "/")[0] == 200
    assert request(server, "/assets/trendlines.js")[0] == 200
    assert request(server, "/raw.json")[0] == 404


def test_symlinked_delivery_cannot_escape_private_root(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.json")
    outside.write_bytes(S.encode(envelope()))
    try: (tmp_path / "bitcoin.trendlines.json").symlink_to(outside)
    except OSError: pytest.skip("symlink permission unavailable")
    with pytest.raises(ValueError, match="redirected"):
        service(tmp_path).read_asset_envelope("bitcoin")


def test_service_refuses_non_loopback_bind(tmp_path):
    with pytest.raises(ValueError, match="exact_loopback"):
        L.make_http_server(service(tmp_path), host="0.0.0.0", port=0)


def test_duplicate_host_or_origin_headers_are_rejected(server):
    _companion, httpd = server
    for duplicate in ("Host", "Origin"):
        connection = http.client.HTTPConnection(L.HOST, httpd.server_address[1], timeout=5)
        connection.putrequest("GET", "/api/private-trendlines/status", skip_host=True)
        connection.putheader("Host", httpd.expected_host)
        connection.putheader("Origin", L.TRUSTED_ORIGIN)
        connection.putheader(duplicate, httpd.expected_host if duplicate == "Host" else L.TRUSTED_ORIGIN)
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 403
        response.read(); connection.close()


def test_unapproved_refresh_report_restores_previous_export_even_if_new_body_is_valid(tmp_path):
    raw = write_envelope(tmp_path)
    def refresh(asset):
        write_envelope(tmp_path, asset, asof="2026-10-13T22:00:00+00:00")
        return {**verified_report(), "public_prices_published": True}
    companion = service(tmp_path, callback=refresh)
    companion.start(scheduler=False); assert companion.wait_idle(); companion.stop()
    assert (tmp_path / "bitcoin.trendlines.json").read_bytes() == raw
    assert next(row for row in companion.status()["assets"] if row["asset_id"] == "bitcoin")["error"] == "refresh_failed"


def test_preview_built_after_cycle_and_failure_is_bounded_metadata(tmp_path):
    write_envelope(tmp_path)
    previews = []
    companion = service(tmp_path, preview=lambda: previews.append("built"))
    companion.start(scheduler=False); assert companion.wait_idle(); companion.stop()
    assert previews == ["built"]
    def bad_preview(): raise ValueError("private prices")
    other = service(tmp_path, preview=bad_preview)
    other.start(scheduler=False); assert other.wait_idle(); other.stop()
    assert other.status()["preview_error"] is True
    assert "private prices" not in json.dumps(other.status())


def test_v2_exact_packed_bytes_are_served_while_validation_uses_lossless_original(server):
    companion, _httpd = server
    original = envelope()
    packed = packed_envelope()
    raw = S.encode(packed)
    (companion.root / "bitcoin.trendlines.json").write_bytes(raw)
    status, _headers, body = request(server, "/api/private-trendlines/bitcoin")
    assert status == 200 and body == raw
    expanded = L.validate_envelope(raw, "bitcoin", now=NOW)
    assert expanded == json.loads(original["payload_json"])
    assert C.canonical_hash(expanded) == packed["original_detail_sha256"]
    assert packed["payload_sha256"] != packed["original_detail_sha256"]


@pytest.mark.parametrize("attack", ["wire_sha", "original_sha", "price", "columns", "width", "extra", "both_forms"])
def test_v2_tamper_and_unpack_contract_fail_closed(server, attack):
    companion, _httpd = server
    value = packed_envelope()
    packed = json.loads(value["payload_json"])
    if attack == "wire_sha": value["payload_sha256"] = "0" * 64
    if attack == "original_sha": value["original_detail_sha256"] = packed["original_detail_sha256"] = "0" * 64
    if attack == "price": packed["bars_packed"]["rows"][0][2] += 1
    if attack == "columns": packed["bars_packed"]["columns"][3] = "close"
    if attack == "width": packed["bars_packed"]["rows"][0].append(100)
    if attack == "extra": packed["bars_packed"]["hidden"] = "metadata"
    if attack == "both_forms": packed["bars"] = json.loads(envelope()["payload_json"])["bars"]
    if attack != "wire_sha":
        value["payload_json"] = json.dumps(packed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        value["payload_sha256"] = hashlib.sha256(value["payload_json"].encode()).hexdigest()
    (companion.root / "bitcoin.trendlines.json").write_bytes(S.encode(value))
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 503


def test_validly_signed_v2_still_requires_atomic_ohlc_containment(server):
    companion, _httpd = server
    original = envelope(invalid=True)
    body = json.loads(original["payload_json"])
    value = packed_envelope()
    packed = json.loads(value["payload_json"])
    value["original_detail_sha256"] = packed["original_detail_sha256"] = original["payload_sha256"]
    packed["bars_packed"]["rows"] = [[bar[key] for key in R.PRIVATE_BAR_COLUMNS] for bar in body["bars"]]
    value["payload_json"] = json.dumps(packed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    value["payload_sha256"] = hashlib.sha256(value["payload_json"].encode()).hexdigest()
    (companion.root / "bitcoin.trendlines.json").write_bytes(S.encode(value))
    with pytest.raises(ValueError, match="containment"):
        L.validate_envelope(S.encode(value), "bitcoin", now=NOW)
    assert request(server, "/api/private-trendlines/bitcoin")[0] == 503


def test_start_warms_readonly_status_before_any_collection(tmp_path, monkeypatch):
    events = []
    companion = service(tmp_path, callback=lambda _asset: events.append("refresh") or verified_report())
    original = companion.status
    monkeypatch.setattr(companion, "status", lambda: events.append("warmup") or original())
    companion.start(scheduler=False); assert companion.wait_idle(); companion.stop()
    assert events == ["warmup", "warmup", "refresh"]  # Startup warmup, then fresh ordering.


def test_aborted_http_socket_is_closed_without_second_error_write(tmp_path):
    httpd = L.make_http_server(service(tmp_path), port=0)
    handler = object.__new__(httpd.RequestHandlerClass)
    calls = []
    def aborted(_code):
        calls.append("send")
        raise ConnectionAbortedError("client deadline")
    handler.send_response = aborted
    assert handler._reply(200, b"private response") is False
    assert handler.close_connection and calls == ["send"]
    httpd.server_close()
