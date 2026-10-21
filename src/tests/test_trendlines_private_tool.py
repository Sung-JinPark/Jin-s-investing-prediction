"""Offline private-tool boundaries, with disposable HTML and checkout copies."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from ai_fc.trendlines import contracts as C, research as R, critical as K, representative as V, long_boundaries as B

REPOSITORY = Path(__file__).resolve().parents[2]
FETCHED = "2024-01-03T00:30:00+00:00"


@pytest.fixture
def tool(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("private_trendlines_tool", REPOSITORY / "tools/refresh_private_trendlines.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout = tmp_path / "checkout"
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE, K.POLICY_RELATIVE, V.POLICY_RELATIVE, B.POLICY_RELATIVE):
        target = checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, target)
    monkeypatch.setattr(module, "PROJECT", checkout)
    return module


def fixture_document(*, invalid=False):
    item = {"meta": {"symbol": "BTC-USD", "currency": "USD", "exchangeTimezoneName": "UTC",
                     "dataGranularity": "1d", "instrumentType": "CRYPTOCURRENCY",
                     "regularMarketTime": 1704240000, "regularMarketPrice": 102},
            "timestamp": [1704067200, 1704153600],
            "indicators": {"quote": [{"open": [100, 101], "high": [1 if invalid else 102, 103],
                                       "low": [99, 100], "close": [101, 102], "volume": [10, 12]}]}}
    envelope = {"status": 200, "body": json.dumps({"chart": {"result": [item], "error": None}})}
    raw = ('<script type="application/json" data-sveltekit-fetched '
           'data-url="https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1d">'
           + json.dumps(envelope) + '</script>').encode()
    note = {"url": "https://finance.yahoo.com/quote/BTC-USD/history/", "http_status": 200,
            "retrieved_at": FETCHED, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return raw, note


def options(tool, tmp_path, *, invalid=False):
    raw, note = fixture_document(invalid=invalid)
    raw_path, note_path = tmp_path / "input.html", tmp_path / "receipt.json"
    raw_path.write_bytes(raw)
    note_path.write_text(json.dumps(note), encoding="utf-8")
    return SimpleNamespace(asset="bitcoin", out=tool.PROJECT / "outputs/private", fetch=False,
                           raw=raw_path, receipt=note_path, allow_rejected_rows=False)


def source_bytes(project):
    return {path.relative_to(project).as_posix(): path.read_bytes()
            for path in (project / "data").rglob("*") if path.is_file()}


def directory_link(link, target):
    link.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("directory symlinks unavailable on this host")
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


@pytest.mark.parametrize("relative", ["site/private", "data/trendlines_research", "outputs/../site/private"])
def test_private_output_outside_ignored_outputs_is_rejected_before_network(tool, tmp_path, monkeypatch, relative):
    request = options(tool, tmp_path)
    request.fetch, request.raw, request.receipt = True, None, None
    request.out = tool.PROJECT / relative
    before = source_bytes(tool.PROJECT)
    monkeypatch.setattr(tool, "public_page", lambda *_: pytest.fail("network called before private output guard"))
    with pytest.raises(C.TrendlinesError, match="outputs directory"):
        tool.run(request)
    assert source_bytes(tool.PROJECT) == before
    assert not request.out.exists()


@pytest.mark.parametrize("relative", ["data/contracts", "data/trendlines", "data/trendlines_research", "data/trendlines_research/raw",
                                      "data/trendlines_research_full", "data/trendlines_research_full/exports",
                                      "data/trendlines_research_critical", "data/trendlines_research_critical/exports",
                                      "outputs/trendlines"])
def test_nested_redirected_contract_and_research_destinations_are_rejected(tool, tmp_path, relative):
    output = tool.PROJECT / "outputs/private"
    outside = tmp_path / "outside"
    directory_link(output / relative, outside)
    with pytest.raises(C.TrendlinesError, match="redirected data path"):
        tool.private_root(output)
    assert not list(outside.iterdir())


def test_redirected_outputs_container_cannot_redefine_the_private_boundary(tool, tmp_path):
    outside = tmp_path / "public-site"
    directory_link(tool.PROJECT / "outputs", outside)
    with pytest.raises(C.TrendlinesError, match="outputs|redirected"):
        tool.private_root(tool.PROJECT / "outputs/private")
    assert not list(outside.iterdir())


def test_raw_receipt_replay_never_calls_network_and_writes_only_private_outputs(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    before = source_bytes(tool.PROJECT)
    raw = request.raw.read_bytes()
    monkeypatch.setattr(tool, "public_page", lambda *_: pytest.fail("raw replay tried public acquisition"))
    monkeypatch.setattr(tool, "urlopen", lambda *_args, **_kwargs: pytest.fail("raw replay tried network"))
    result = tool.run(request)
    assert result["publication_scope"] == "private_only" and result["public_prices_published"] is False
    assert result["independent_replay"]["ok"] and result["bars"] == 2
    export = Path(result["browser_import_file"])
    assert export.is_relative_to(request.out.resolve()) and export.is_file()
    assert source_bytes(tool.PROJECT) == before and request.raw.read_bytes() == raw
    originals = list((request.out / R.ROOT / "raw").glob("*.bin"))
    assert len(originals) == 1 and originals[0].read_bytes() == raw
    assert result["critical"]["status"] == "ready"
    core = K.decode_envelope(K.load_detail(request.out, "bitcoin", now=FETCHED))
    assert core["reference_close"] == 102 and core["atr14"] is None
    assert len(core["projection_sessions"]) == 30
    assert all(not view["boundaries"] for views in core["analyses"].values() for view in views.values())
    assert tool.run(request)["changed"] is False


def test_invalid_capture_keeps_original_and_failure_only_in_private_output(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path, invalid=True)
    before = source_bytes(tool.PROJECT)
    monkeypatch.setattr(tool, "urlopen", lambda *_args, **_kwargs: pytest.fail("offline invalid capture tried network"))
    with pytest.raises(C.TrendlinesError, match="containment"):
        tool.run(request)
    assert source_bytes(tool.PROJECT) == before
    originals = list((request.out / R.ROOT / "raw").glob("*.bin"))
    assert len(originals) == 1 and originals[0].read_bytes() == request.raw.read_bytes()
    failures = list((request.out / R.ROOT / "failures").glob("*.json"))
    assert len(failures) == 1 and json.loads(failures[0].read_text())["numeric_input_allowed"] is False
    assert not (request.out / R.ROOT / "latest.json").exists()
    assert not (request.out / "bitcoin.trendlines.json").exists()


def test_acquisition_error_never_creates_public_or_price_exports(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    request.fetch, request.raw, request.receipt = True, None, None
    before = source_bytes(tool.PROJECT)
    def failed_acquisition(_asset):
        raise URLError("offline simulated public source unavailable")
    monkeypatch.setattr(tool, "public_page", failed_acquisition)
    with pytest.raises(URLError):
        tool.run(request)
    assert source_bytes(tool.PROJECT) == before
    assert not (request.out / R.ROOT).exists() and not (request.out / "bitcoin.trendlines.json").exists()


def test_full_calculation_failure_preserves_valid_current_export(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    def failed_full(*_args, **_kwargs):
        raise C.TrendlinesError("full_history_numeric_replay_failed")
    monkeypatch.setattr(tool.F, "refresh", failed_full)
    result = tool.run(request)
    assert result["full_history"]["status"] == "unavailable"
    assert result["critical"]["status"] == "unavailable"
    assert result["representative"]["status"] == "unavailable"
    assert result["independent_replay"]["ok"] is True
    current = R.decode_private_import(json.loads(Path(result["browser_import_file"]).read_text(encoding="utf-8")))
    assert len(current["bars"]) == 2 and current["official_forecast_write"] is False


def test_critical_failure_preserves_verified_current_and_full_results(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    monkeypatch.setattr(tool.F, "refresh", lambda *_args, **_kwargs: {"status": "ready", "changed": False})
    def failed_critical(*_args, **_kwargs):
        raise C.TrendlinesError("critical_numeric_replay_failed")
    monkeypatch.setattr(tool.K, "refresh", failed_critical)
    result = tool.run(request)
    assert result["critical"]["status"] == "unavailable"
    assert result["full_history"]["status"] == "ready"
    assert result["independent_replay"]["ok"] is True
    current = R.decode_private_import(json.loads(Path(result["browser_import_file"]).read_text(encoding="utf-8")))
    assert len(current["bars"]) == 2 and current["official_forecast_write"] is False


def test_source_corruption_during_critical_work_stops_delivery_publication(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    monkeypatch.setattr(tool.F, "refresh", lambda *_args, **_kwargs: {"status": "ready", "changed": False})
    def corrupted_critical(root, *_args, **_kwargs):
        raw_path = next((root / R.ROOT / "raw").glob("*.bin"))
        raw_path.write_bytes(raw_path.read_bytes() + b"corrupted disposable critical fixture")
        raise C.TrendlinesError("critical_source_integrity_failed")
    monkeypatch.setattr(tool.K, "refresh", corrupted_critical)
    with pytest.raises(C.TrendlinesError, match="original-to-chart replay failed"):
        tool.run(request)
    assert not (request.out / "bitcoin.trendlines.json").exists()


def test_source_corruption_during_full_work_stops_current_publication(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    def corrupted_full(root, *_args, **_kwargs):
        raw_path = next((root / R.ROOT / "raw").glob("*.bin"))
        raw_path.write_bytes(raw_path.read_bytes() + b"corrupted disposable fixture")
        raise C.TrendlinesError("full_history_source_integrity_failed")
    monkeypatch.setattr(tool.F, "refresh", corrupted_full)
    with pytest.raises(C.TrendlinesError, match="original-to-chart replay failed"):
        tool.run(request)
    assert not (request.out / "bitcoin.trendlines.json").exists()


def test_three_representative_refresh_runs_after_legacy_models_without_changing_official_files(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    before = source_bytes(tool.PROJECT)
    calls = []
    monkeypatch.setattr(tool.F, "refresh", lambda root, asset, **_kwargs: calls.append(("full", root, asset)) or {"status": "ready"})
    monkeypatch.setattr(tool.K, "refresh", lambda root, asset, **_kwargs: calls.append(("critical", root, asset)) or {"status": "ready"})
    monkeypatch.setattr(tool.V, "refresh", lambda root, asset, **_kwargs: calls.append(("representative", root, asset)) or
                        {"status": "ready", "changed": True, "snapshot_id": "representative-fixture"})
    monkeypatch.setattr(tool.B, "refresh", lambda root, asset, **_kwargs: calls.append(("long_boundaries", root, asset)) or {"status":"ready"})
    def publish(root, asset, envelope):
        assert envelope == R.export_private_import(root, asset)
        calls.append(("delivery", root, asset))
        return {"snapshot_id": "delivery-fixture"}
    monkeypatch.setattr(tool.D, "publish", publish)
    result = tool.run(request)
    assert [c[0] for c in calls] == ["full", "critical", "representative", "long_boundaries", "delivery"]
    assert all(c[1:] == (request.out.resolve(), "bitcoin") for c in calls)
    assert result["representative"]["status"] == "ready" and result["independent_replay"]["ok"]
    assert result["delivery_committed"] is True and result["delivery"]["snapshot_id"] == "delivery-fixture"
    assert result["public_prices_published"] is False and source_bytes(tool.PROJECT) == before


def test_long_boundaries_failure_preserves_existing_three_and_export(tool,tmp_path,monkeypatch):
    request=options(tool,tmp_path)
    monkeypatch.setattr(tool.D,'publish',lambda *_a,**_k:pytest.fail('Incomplete cohort was published'))
    for name in ('F','K','V'):
        monkeypatch.setattr(getattr(tool,name),'refresh',lambda *_a,**_k:{'status':'ready'})
    def failed(*_a,**_k):raise C.TrendlinesError('supplement fixture mismatch')
    monkeypatch.setattr(tool.B,'refresh',failed)
    result=tool.run(request)
    assert result['long_boundaries']['status']=='unavailable' and result['representative']['status']=='ready'
    assert result['independent_replay']['ok'] and Path(result['browser_import_file']).is_file()
    assert result['delivery_committed'] is False and result['delivery'] is None


def test_representative_failure_preserves_current_and_legacy_models(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    monkeypatch.setattr(tool.F, "refresh", lambda *_args, **_kwargs: {"status": "ready"})
    monkeypatch.setattr(tool.K, "refresh", lambda *_args, **_kwargs: {"status": "ready"})
    def failed(*_args, **_kwargs):
        raise C.TrendlinesError("representative fixture numeric mismatch")
    monkeypatch.setattr(tool.V, "refresh", failed)
    result = tool.run(request)
    assert result["representative"]["status"] == "unavailable"
    assert result["critical"]["status"] == result["full_history"]["status"] == "ready"
    assert result["independent_replay"]["ok"] and Path(result["browser_import_file"]).is_file()


def test_original_corruption_during_representative_work_blocks_delivery(tool, tmp_path, monkeypatch):
    request = options(tool, tmp_path)
    monkeypatch.setattr(tool.F, "refresh", lambda *_args, **_kwargs: {"status": "ready"})
    monkeypatch.setattr(tool.K, "refresh", lambda *_args, **_kwargs: {"status": "ready"})
    def corrupt(root, *_args, **_kwargs):
        raw_path = next((root / R.ROOT / "raw").glob("*.bin"))
        raw_path.write_bytes(raw_path.read_bytes() + b"disposable representative corruption")
        raise C.TrendlinesError("representative source hash mismatch")
    monkeypatch.setattr(tool.V, "refresh", corrupt)
    with pytest.raises(C.TrendlinesError, match="original-to-chart replay failed"):
        tool.run(request)
    assert not (request.out / "bitcoin.trendlines.json").exists()


def test_private_registry_gains_instruments_but_never_redefines_captured_ones(tool, tmp_path):
    import yaml
    output = tool.PROJECT / "outputs/private"
    target = output / C.ASSET_REGISTRY_RELATIVE
    registry = yaml.safe_load((REPOSITORY / C.ASSET_REGISTRY_RELATIVE).read_text(encoding="utf-8"))
    earlier = {key: value for key, value in registry.items() if key != "assets"}
    earlier["assets"] = {key: value for key, value in registry["assets"].items() if key not in {"kospi", "samsung", "nvidia", "micron"}}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(earlier, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tool.private_root(output)
    assert tuple(C.load_asset_registry(output)) == C.ASSET_IDS
    assert target.read_bytes() == (REPOSITORY / C.ASSET_REGISTRY_RELATIVE).read_bytes()
    redefined = yaml.safe_load(target.read_text(encoding="utf-8"))
    redefined["assets"]["sk-hynix"]["currency"] = "USD"
    target.write_text(yaml.safe_dump(redefined, allow_unicode=True, sort_keys=False), encoding="utf-8")
    before = target.read_bytes()
    with pytest.raises(C.TrendlinesError, match="existing definitions are immutable"):
        tool.private_root(output)
    assert target.read_bytes() == before
