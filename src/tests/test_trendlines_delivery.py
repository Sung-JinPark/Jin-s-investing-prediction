"""Asset sidecars preserve exact snapshots and never substitute held data."""
from __future__ import annotations

import copy
import base64
import hashlib
import json
import runpy
import socketserver
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from ai_fc import dashboard

PREVIEW = Path(__file__).parents[2] / 'tools/preview_trendlines.py'


def projection():
    return runpy.run_path(str(PREVIEW))['fixture_projection']()


def test_split_preserves_input_and_pins_exact_asset_bytes():
    model = {'trendlines': projection(), 'daily_flow': {'status': 'unchanged'}}
    original = copy.deepcopy(model)
    base, assets = dashboard.split_trendlines_data(model)
    assert model == original
    assert base['daily_flow'] == model['daily_flow']
    assert 'details' not in base['trendlines']
    assert set(assets) == {'sk-hynix'}
    raw = json.dumps(assets['sk-hynix'], ensure_ascii=False, default=str, separators=(',', ':'), allow_nan=False).encode()
    pin = base['trendlines']['assets'][0]['deferred_data']
    assert pin['payload_sha256'] == hashlib.sha256(raw).hexdigest()
    assert assets['sk-hynix']['data']['trendlines'] == model['trendlines']['details']['sk-hynix']
    assert dashboard.split_trendlines_data(base) == (base, {})


def test_hold_does_not_create_numeric_files():
    data = projection()
    data['assets'][0].update(status='hold', reason_codes=['missing_approved_ohlc'])
    data['details'] = {}
    base, assets = dashboard.split_trendlines_data({'trendlines': data})
    assert assets == {}
    assert len(base['trendlines']['assets']) == 7
    assert all('deferred_data' not in row for row in base['trendlines']['assets'])


def test_stale_preserves_pinned_historical_chart_and_reason():
    data = projection()
    data['assets'][0].update(status='stale', reason_codes=['latest_completed_session_missing'])
    data['details']['sk-hynix']['status'] = 'stale'
    base, assets = dashboard.split_trendlines_data({'trendlines': data})
    assert base['trendlines']['assets'][0]['status'] == 'stale'
    assert assets['sk-hynix']['data']['trendlines']['status'] == 'stale'
    assert assets['sk-hynix']['data']['trendlines']['bars'] == data['details']['sk-hynix']['bars']


def test_renderer_and_style_sri_pin_actual_delivered_bytes(tmp_path):
    metadata = json.loads(dashboard._trendlines_assets_metadata('assets/trendlines').removeprefix('window.__TRENDLINES_ASSETS__ = ').removesuffix(';'))
    dashboard._write_trendlines_sidecars({}, tmp_path)
    for suffix in ('js', 'css'):
        raw = (tmp_path / metadata[suffix]['url']).read_bytes()
        assert metadata[suffix]['integrity'] == 'sha256-' + base64.b64encode(hashlib.sha256(raw).digest()).decode()


@pytest.mark.parametrize('problem', ['metadata', 'identity', 'duplicate', 'nan', 'asset_budget', 'summary_budget'])
def test_invalid_or_oversized_delivery_is_rejected(problem):
    data = projection()
    if problem == 'metadata':
        data['details']['sk-hynix']['snapshot_id'] = 'other'
    elif problem == 'identity':
        data['assets'][0]['asset_id'] = '../secret'
    elif problem == 'duplicate':
        data['assets'][1]['asset_id'] = 'sk-hynix'
    elif problem == 'nan':
        data['details']['sk-hynix']['bars'][0]['close'] = float('nan')
    elif problem == 'asset_budget':
        data['details']['sk-hynix']['oversized'] = 'x' * dashboard.TRENDLINES_ASSET_BUDGET_BYTES
    else:
        data['assets'][0]['oversized'] = 'x' * dashboard.TRENDLINES_SUMMARY_BUDGET_BYTES
    with pytest.raises(ValueError):
        dashboard.split_trendlines_data({'trendlines': data})


@pytest.mark.parametrize('writer', ['embed', 'pages'])
def test_static_writers_deliver_identical_pinned_bytes(tmp_path, monkeypatch, writer):
    model = {'trendlines': projection()}
    monkeypatch.setattr(dashboard, 'build_read_model', lambda *args, **kwargs: model)
    monkeypatch.setattr(dashboard, '_write_og_image', lambda *args, **kwargs: None)
    target = dashboard.write_dashboard(None, tmp_path) if writer == 'embed' else dashboard.write_pages(None, tmp_path / 'site', tmp_path)
    raw = (target.parent / 'trendlines/sk-hynix.json').read_bytes()
    base, _ = dashboard.split_trendlines_data(model)
    assert hashlib.sha256(raw).hexdigest() == base['trendlines']['assets'][0]['deferred_data']['payload_sha256']
    assert 'window.__TRENDLINES_URL__ = "trendlines/"' in target.read_text(encoding='utf-8')
    assert not (target.parent / 'trendlines/soxx.json').exists()


@pytest.mark.parametrize('writer', ['embed', 'pages'])
def test_reused_output_removes_only_held_public_asset_after_revocation(tmp_path, monkeypatch, writer):
    model = {'trendlines': projection()}
    monkeypatch.setattr(dashboard, 'build_read_model', lambda *args, **kwargs: model)
    monkeypatch.setattr(dashboard, '_write_og_image', lambda *args, **kwargs: None)
    archive = tmp_path / 'data/trendlines/archive/audit-original.json'
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b'original immutable audit snapshot')
    write = lambda: dashboard.write_dashboard(None, tmp_path) if writer == 'embed' else dashboard.write_pages(None, tmp_path / 'site', tmp_path)
    target = write()
    obsolete = target.parent / 'trendlines/sk-hynix.json'
    assert obsolete.is_file()
    model['trendlines']['assets'][0].update(status='hold', reason_codes=['source_rights_pending'])
    model['trendlines']['details'] = {}
    write()
    assert not obsolete.exists()
    assert (target.parent / 'assets/trendlines.js').exists()
    assert archive.read_bytes() == b'original immutable audit snapshot'


def test_read_only_server_delivers_exact_pinned_asset_and_rejects_invalid_paths(tmp_path, monkeypatch):
    model = {'trendlines': projection()}
    monkeypatch.setattr(dashboard, 'build_read_model', lambda *args, **kwargs: model)
    available, instances = threading.Event(), []
    original = socketserver.ThreadingTCPServer
    class CapturingServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)
            available.set()
    monkeypatch.setattr(socketserver, 'ThreadingTCPServer', CapturingServer)
    worker = threading.Thread(target=dashboard.serve, args=(tmp_path, '127.0.0.1', 0), daemon=True)
    worker.start()
    assert available.wait(10)
    server = instances[0]
    origin = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with urlopen(origin + '/api/data', timeout=10) as response:
            summary = json.load(response)['trendlines']['assets'][0]
        with urlopen(origin + '/api/trendlines/sk-hynix', timeout=10) as response:
            raw = response.read()
        assert hashlib.sha256(raw).hexdigest() == summary['deferred_data']['payload_sha256']
        for suffix in ('unknown', '../secret', 'soxx', 'sk-hynix?other=1'):
            with pytest.raises(HTTPError) as error:
                urlopen(origin + '/api/trendlines/' + suffix, timeout=10)
            assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            urlopen(Request(origin + '/api/trendlines/sk-hynix', data=b'{}', method='POST'), timeout=10)
        assert error.value.code == 405
    finally:
        server.shutdown()
        worker.join(10)
        server.server_close()
