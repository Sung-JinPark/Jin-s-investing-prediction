"""GRAPH02 research delivery is bounded, separately pinned, and read-only."""
import copy
import hashlib
import json
import socketserver
import threading
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ai_fc import dashboard


def _projection():
    dates = []
    cursor = date(2026, 10, 9)
    while len(dates) < 252:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            dates.append(cursor.isoformat())
    quantiles = ("p05", "p10", "p25", "p50", "p75", "p90", "p95")
    records = []
    for step, day in enumerate(dates, 1):
        middle = 100 + .05 * step
        records.append({
            "date": day, "index_quantiles": dict(zip(quantiles, [middle + v for v in (-15, -10, -5, 0, 5, 10, 15)])),
            "daily_return_quantiles": dict(zip(quantiles, [-.03, -.02, -.01, .0005, .01, .02, .03])),
            "drawdown_quantiles": dict(zip(quantiles, [-.25, -.20, -.15, -.10, -.05, -.02, -.01])),
            "probability_up_from_previous": .55, "probability_down_from_previous": .44,
            "probability_up_from_origin": .60,
        })
    return {
        "schema_version": 1, "model_id": "research.nasdaq_market_context_v1", "model_version": 1,
        "status": "research_preview", "as_of": "2026-10-09T22:00:00+00:00",
        "anchor_date": "2026-10-09", "anchor": 100.0, "forecast_end_date": dates[-1],
        "forecast_id": "market-context-fixture", "input_hash": "1" * 64,
        "contract_hash": "2" * 64, "coefficient_hash": "not_fitted",
        "probability_unit": "fraction", "predictive_validation": "not_established",
        "numerical_context_applied": False, "score": None,
        "gate": {"pass": True, "reasons": []}, "records": records,
        "representative": {"status": "ok", "path_id": "path-12", "values": [100.0] + [
            100 + .05 * step + (1 if step % 2 else -1) for step in range(1, 253)
        ]},
        "baseline_median": [100.0] + [row["index_quantiles"]["p50"] for row in records],
        "history": {"dates": ["2026-10-08", "2026-10-09"], "index": [99, 100]},
        "attribution": {"inflation": {"5": 0, "21": 0, "63": 0}},
        "state_summary": {"axes": [{"axis": "inflation", "label": "물가", "score": .2,
                                     "applied": False, "reason": "계수 검증 대기"}],
                          "events": [{"title": "중국 메모리 이슈", "used_numerically": False,
                                      "source_url": "https://example.org/source", "reason": "연결 근거 대기"}]},
        "footnote": "가상 입력 · 실제 시장 전망이 아님",
    }


def test_sidecar_does_not_mutate_source_or_existing_future_contract():
    model = {"market_context": _projection(), "scenario_v5_2": {"status": "hold"}, "timeseries_daily": {"status": "hold"}}
    before = copy.deepcopy(model)
    base, sidecar = dashboard.split_market_context_data(model)
    assert model == before
    assert base["scenario_v5_2"] == model["scenario_v5_2"]
    assert base["timeseries_daily"] == model["timeseries_daily"]
    assert not {"records", "history", "representative", "baseline_median", "attribution", "state_summary"} & base["market_context"].keys()
    raw = json.dumps(sidecar, ensure_ascii=False, default=str, separators=(",", ":")).encode()
    metadata = base["market_context"]["deferred_data"]
    assert metadata["payload_sha256"] == hashlib.sha256(raw).hexdigest()
    for key in ("forecast_id", "as_of", "anchor_date", "input_hash", "contract_hash", "coefficient_hash"):
        assert metadata[key] == model["market_context"][key]
    assert dashboard.split_market_context_data(base) == (base, None)


def test_hold_has_no_numeric_sidecar_and_large_sidecar_is_rejected():
    hold = {"market_context": {"status": "hold", "gate": {"pass": False, "reasons": ["stale"]}}}
    assert dashboard.split_market_context_data(hold) == (hold, None)
    projection = _projection()
    projection["extra"] = "x" * dashboard.MARKET_CONTEXT_BUDGET_BYTES
    with pytest.raises(ValueError, match="market context budget exceeded"):
        dashboard.split_market_context_data({"market_context": projection})


@pytest.mark.parametrize("mode,url", [("embed", "market_context.json"), ("pages", "market_context.json"), ("fetch", "/api/market-context")])
def test_every_delivery_mode_declares_its_own_url(mode, url):
    assert f'window.__MARKET_CONTEXT_URL__ = "{url}"' in dashboard.render_html({}, mode=mode)


@pytest.mark.parametrize("mode", ["embed", "pages"])
def test_static_writers_emit_exact_pinned_bytes(tmp_path, monkeypatch, mode):
    model = {"market_context": _projection()}
    monkeypatch.setattr(dashboard, "build_read_model", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(dashboard, "_write_og_image", lambda *_args, **_kwargs: None)
    target = dashboard.write_dashboard(None, tmp_path) if mode == "embed" else dashboard.write_pages(None, tmp_path / "site", tmp_path)
    raw = (target.parent / dashboard.MARKET_CONTEXT_FILENAME).read_bytes()
    base, _ = dashboard.split_market_context_data(model)
    assert hashlib.sha256(raw).hexdigest() == base["market_context"]["deferred_data"]["payload_sha256"]
    assert json.loads(raw)["data"]["market_context"]["representative"]["values"] == model["market_context"]["representative"]["values"]


def test_server_sidecar_is_read_only_and_pinned_to_summary(tmp_path, monkeypatch):
    model = {"market_context": _projection()}
    monkeypatch.setattr(dashboard, "build_read_model", lambda *_args, **_kwargs: model)
    ready, instances = threading.Event(), []
    original = socketserver.ThreadingTCPServer

    class CapturingServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)
            ready.set()

    monkeypatch.setattr(socketserver, "ThreadingTCPServer", CapturingServer)
    worker = threading.Thread(target=dashboard.serve, args=(tmp_path, "127.0.0.1", 0), daemon=True)
    worker.start()
    assert ready.wait(10)
    server = instances[0]
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base_url + "/api/data", timeout=10) as response:
            base = json.load(response)
        with urlopen(base_url + "/api/market-context", timeout=10) as response:
            raw = response.read()
        assert hashlib.sha256(raw).hexdigest() == base["market_context"]["deferred_data"]["payload_sha256"]
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base_url + "/api/market-context", data=b"{}", method="POST"), timeout=10)
        assert error.value.code == 405
    finally:
        server.shutdown()
        worker.join(10)
        server.server_close()
