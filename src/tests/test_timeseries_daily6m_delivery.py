"""Daily research sidecars stay bounded, pinned and independent of V8."""
import copy
import hashlib
import json
import socketserver
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ai_fc import dashboard


def _projection():
    return {
        "schema_version": 1, "model_id": "shadow.daily6m_v1",
        "status": "research_preview", "numbers_visible": True,
        "probability_unit": "fraction", "run_id": "daily-fixture",
        "as_of": "2026-10-09T22:00:00+00:00", "anchor_date": "2026-10-09",
        "content_hash": "fixture-ledger-hash", "end_date": "2027-04-09",
        "anchor": {"date": "2026-10-09", "value": 100},
        "gate": {"preview_ready": True},
        "dates": ["2026-10-12"],
        "records": [{"date": "2026-10-12", "median_index": 101,
                     "band_index": {"p10": 90, "p25": 95, "p75": 105, "p90": 110},
                     "probability_up_from_previous": 0.55}],
        "sample_paths": [{"path_id": "one", "values": [101]}],
        "history": {"dates": ["2026-10-09"], "index": [100]},
        "realized": {"dates": [], "index": []},
    }


def test_split_preserves_source_and_pins_exact_bytes():
    model = {"timeseries": {"status": "hold"}, "timeseries_daily": _projection()}
    before = copy.deepcopy(model)
    base, sidecar = dashboard.split_timeseries_daily_data(model)
    assert model == before
    assert base["timeseries"] == model["timeseries"]
    assert "records" not in base["timeseries_daily"]
    assert "history" not in base["timeseries_daily"]
    assert sidecar["data"]["timeseries_daily"] == model["timeseries_daily"]
    raw = json.dumps(sidecar, ensure_ascii=False, default=str, separators=(",", ":")).encode()
    metadata = base["timeseries_daily"]["deferred_data"]
    assert metadata["payload_sha256"] == hashlib.sha256(raw).hexdigest()
    for key in ("run_id", "as_of", "anchor_date", "content_hash"):
        assert metadata[key] == model["timeseries_daily"][key]
    changed = raw.replace(b'0.55', b'0.95')
    assert hashlib.sha256(changed).hexdigest() != metadata["payload_sha256"]
    assert dashboard.split_timeseries_daily_data(base) == (base, None)


def test_hold_never_creates_a_numeric_sidecar():
    model = {"timeseries_daily": {"status": "hold", "numbers_visible": False,
                                 "gate": {"reasons": ["stale"]}}}
    assert dashboard.split_timeseries_daily_data(model) == (model, None)


def test_daily_payload_size_is_a_hard_gate():
    projection = _projection()
    projection["records"] = [{"large": "x" * dashboard.TIMESERIES_DAILY_BUDGET_BYTES}]
    with pytest.raises(ValueError, match="timeseries daily budget exceeded"):
        dashboard.split_timeseries_daily_data({"timeseries_daily": projection})


@pytest.mark.parametrize("mode,url", [
    ("embed", "timeseries_daily.json"), ("pages", "timeseries_daily.json"),
    ("fetch", "/api/timeseries-daily"),
])
def test_each_delivery_mode_has_explicit_daily_url(mode, url):
    html = dashboard.render_html({}, mode=mode)
    assert f'window.__TIMESERIES_DAILY_URL__ = "{url}"' in html


@pytest.mark.parametrize("writer", ["embed", "pages"])
def test_static_writers_serialize_the_pinned_sidecar(tmp_path, monkeypatch, writer):
    model = {"timeseries_daily": _projection()}
    monkeypatch.setattr(dashboard, "build_read_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(dashboard, "_write_og_image", lambda *args, **kwargs: None)
    if writer == "embed":
        target = dashboard.write_dashboard(None, tmp_path)
        html = target.read_text(encoding="utf-8")
        assert "fixture-ledger-hash" in html
    else:
        target = dashboard.write_pages(None, tmp_path / "site", tmp_path)
    raw = (target.parent / dashboard.TIMESERIES_DAILY_FILENAME).read_bytes()
    base, _ = dashboard.split_timeseries_daily_data(model)
    assert hashlib.sha256(raw).hexdigest() == base["timeseries_daily"]["deferred_data"]["payload_sha256"]
    assert json.loads(raw)["data"]["timeseries_daily"]["records"][0]["probability_up_from_previous"] == 0.55


def test_read_only_server_delivers_the_same_pinned_daily_snapshot(tmp_path, monkeypatch):
    model = {"timeseries_daily": _projection()}
    monkeypatch.setattr(dashboard, "build_read_model", lambda *args, **kwargs: model)
    available = threading.Event()
    instances = []
    original = socketserver.ThreadingTCPServer

    class CapturingServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)
            available.set()

    monkeypatch.setattr(socketserver, "ThreadingTCPServer", CapturingServer)
    worker = threading.Thread(target=dashboard.serve, args=(tmp_path, "127.0.0.1", 0), daemon=True)
    worker.start()
    assert available.wait(10), "local read-only server did not start"
    server = instances[0]
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base_url + "/api/data", timeout=10) as response:
            base = json.load(response)
        with urlopen(base_url + "/api/timeseries-daily", timeout=10) as response:
            raw = response.read()
        assert hashlib.sha256(raw).hexdigest() == base["timeseries_daily"]["deferred_data"]["payload_sha256"]
        assert json.loads(raw)["data"]["timeseries_daily"]["run_id"] == "daily-fixture"
        with pytest.raises(HTTPError) as rejected:
            urlopen(Request(base_url + "/api/timeseries-daily", data=b"{}", method="POST"), timeout=10)
        assert rejected.value.code == 405
    finally:
        server.shutdown()
        worker.join(10)
        server.server_close()
