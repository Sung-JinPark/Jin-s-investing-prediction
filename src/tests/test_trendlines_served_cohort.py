"""A pending raw capture cannot hide an unchanged, verified delivered cohort."""
import http.client
import json
from pathlib import Path
import shutil
import threading

import pytest

from ai_fc.trendlines import contracts as C, full_history as F, representative as V
from ai_fc.trendlines import long_boundaries as B, local_service as L, research as R, storage as S
from test_trendlines_critical import capture

REPOSITORY = Path(__file__).parents[2]


def all_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def published(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE,
                     V.POLICY_RELATIVE, B.POLICY_RELATIVE):
        target = tmp_path/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY/relative, target)
    _, stamp = capture(tmp_path, count=270)
    V.refresh(tmp_path, 'bitcoin', now=stamp)
    B.refresh(tmp_path, 'bitcoin', now=stamp)
    delivery = R.export_private_import(tmp_path, 'bitcoin')
    (tmp_path/'bitcoin.trendlines.json').write_bytes(S.encode(delivery))
    companion = L.LocalTrendlinesService(tmp_path, refresh_asset=lambda _: pytest.fail('GET collected data'),
        clock=lambda: C.aware_time(stamp), assets=('bitcoin',), startup_refresh=False)
    return tmp_path, stamp, delivery['snapshot_id'], companion


def pending_capture(root, monkeypatch):
    # Simulate interruption after original capture and before full calculation.
    with monkeypatch.context() as patch:
        patch.setattr(F, 'refresh', lambda *args, **kwargs: None)
        return capture(root, count=270, extra=2)[1]


def test_pending_capture_keeps_identical_read_only_served_overlays_and_strict_promotion(published, monkeypatch):
    root, stamp, sid, companion = published
    old_v = companion.read_representative_detail('bitcoin')
    old_b = companion.read_long_boundaries_detail('bitcoin')
    pending_capture(root, monkeypatch)
    before = all_bytes(root)
    for loader in (V.load_detail, B.load_detail):
        with pytest.raises(ValueError, match='not_current_source'):
            loader(root, 'bitcoin', now=stamp)
    assert companion.read_representative_detail('bitcoin') == old_v
    assert companion.read_long_boundaries_detail('bitcoin') == old_b
    assert S.encode(V.load_detail(root, 'bitcoin', now=stamp, source_snapshot_id=sid)) == old_v
    assert all_bytes(root) == before


def test_http_reads_recover_without_starting_a_worker(published, monkeypatch):
    root, _, _, companion = published
    expected = {suffix: read('bitcoin') for suffix, read in (
        ('representative', companion.read_representative_detail),
        ('long-boundaries', companion.read_long_boundaries_detail))}
    pending_capture(root, monkeypatch)
    before = all_bytes(root)
    server = L.make_http_server(companion, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for suffix, payload in expected.items():
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            conn.request('GET', '/api/private-trendlines/bitcoin/'+suffix)
            response = conn.getresponse()
            assert response.status == 200
            assert response.read() == payload
            conn.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(5)
    assert companion._worker is None and all_bytes(root) == before


def test_expected_delivery_cannot_select_another_source_or_future_cutoff(published):
    root, stamp, _, companion = published
    before = all_bytes(root)
    for loader in (V.load_detail, B.load_detail):
        with pytest.raises(ValueError, match='served_cohort'):
            loader(root, 'bitcoin', now=stamp, source_snapshot_id='research-snapshot-'+'0'*64)
        with pytest.raises(ValueError):
            loader(root, 'bitcoin', now='2020-01-01T00:00:00+00:00',
                   source_snapshot_id=R._latest(root)['assets']['bitcoin']['snapshot_id'])
    assert all_bytes(root) == before


@pytest.mark.parametrize('target', ['raw', 'manifest', 'representative', 'long'])
def test_pinned_read_still_rejects_corruption(published, monkeypatch, target):
    root, stamp, sid, companion = published
    representative, source, _ = V._read_snapshot(root, V._latest(root)['assets']['bitcoin']['snapshot_id'], now=stamp)
    if target == 'raw':
        receipt = R._checked(S.safe_path(root, source['receipt_path']))
        path = S.safe_path(root, receipt['raw_path'])
    elif target == 'manifest':
        path = S.safe_path(root, F._latest(root)['assets']['bitcoin']['manifest_path'])
    else:
        module = V if target == 'representative' else B
        path = S.safe_path(root, module._latest(root)['assets']['bitcoin']['detail_path'])
    pending_capture(root, monkeypatch)
    path.write_bytes(path.read_bytes()+b' ')
    before = all_bytes(root)
    read = companion.read_long_boundaries_detail if target == 'long' else companion.read_representative_detail
    with pytest.raises(ValueError):
        read('bitcoin')
    assert all_bytes(root) == before


def test_partial_full_promotion_is_rejected_then_complete_cohort_converges(published, monkeypatch):
    root, stamp, _, companion = published
    pending_capture(root, monkeypatch)
    F.refresh(root, 'bitcoin', now=stamp)
    with pytest.raises(ValueError, match='served_cohort'):
        companion.read_representative_detail('bitcoin')
    V.refresh(root, 'bitcoin', now=stamp)
    B.refresh(root, 'bitcoin', now=stamp)
    with pytest.raises(ValueError, match='served_cohort'):
        companion.read_representative_detail('bitcoin')
    (root/'bitcoin.trendlines.json').write_bytes(S.encode(R.export_private_import(root, 'bitcoin')))
    detail = V.decode_envelope(json.loads(companion.read_representative_detail('bitcoin')))
    assert detail['source_snapshot_id'] == R._latest(root)['assets']['bitcoin']['snapshot_id']
    assert B.decode_envelope(json.loads(companion.read_long_boundaries_detail('bitcoin')))['source_snapshot_id'] == detail['source_snapshot_id']
