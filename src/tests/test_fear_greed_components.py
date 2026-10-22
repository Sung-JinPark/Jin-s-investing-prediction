from __future__ import annotations

import copy
import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc import fear_greed_components as fc

NOW = datetime(2026, 10, 22, 2, tzinfo=timezone.utc)
STAMP = datetime(2026, 10, 21, 23, tzinfo=timezone.utc)


def source():
    return {"asOf": STAMP.isoformat(), "dates": ["2026-10-20", "2026-10-21", "2026-10-21"],
            "values": [30, 31, 31.4], "indicators": {
                key: {"asOf": STAMP.timestamp() * 1000, "score": 30 + i, "rating": "fear",
                      "dates": ["2026-10-20", "2026-10-21", "2026-10-21"],
                      "values": [1000 + i, 1100 + i, 1101 + i]}
                for i, key in enumerate(fc.KEYS)}}


def encode(value):
    return json.dumps(value).encode()


def test_last_source_occurrence_is_explicit_and_raw_units_are_not_scores():
    got = fc.normalize(encode(source()), now=NOW)
    assert got["headline_at_source"] == 31.4
    assert got["headline_duplicate_session_updates"] == 1
    assert tuple(got["components"]) == fc.KEYS
    for i, row in enumerate(got["components"].values()):
        assert row["score"] == 30 + i and row["series"] == [1000 + i, 1101 + i]
        assert row["duplicate_session_updates"] == 1 and row["observed_at"] == STAMP.isoformat()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 101, True, "30"])
def test_invalid_score_is_rejected_without_clipping(bad):
    data = source(); data["indicators"][fc.KEYS[0]]["score"] = bad
    with pytest.raises(fc.ComponentsError):
        fc.normalize(encode(data), now=NOW)


@pytest.mark.parametrize("mutation", ["missing", "length", "order", "future", "stale", "stamp", "rating"])
def test_invalid_or_stale_component_blocks_entire_group(mutation):
    data = source(); row = data["indicators"][fc.KEYS[3]]
    if mutation == "missing":
        del data["indicators"][fc.KEYS[3]]
    elif mutation == "length":
        row["values"].pop()
    elif mutation == "order":
        row["dates"] = ["2026-10-21", "2026-10-20", "2026-10-21"]
    elif mutation == "future":
        row["dates"][-1] = "2026-10-23"
    elif mutation == "stale":
        row["asOf"] = (NOW - timedelta(days=5)).timestamp() * 1000
    elif mutation == "stamp":
        row["asOf"] = (NOW + timedelta(hours=1)).timestamp() * 1000
    else:
        row["rating"] = "unknown"
    with pytest.raises(fc.ComponentsError):
        fc.normalize(encode(data), now=NOW)


def test_idempotence_revision_and_no_false_historical_availability(tmp_path):
    raw = encode(source())
    first = fc.refresh(tmp_path, now=NOW, raw=raw)
    files = {p: p.read_bytes() for p in (tmp_path / fc.BASE).rglob('*') if p.is_file()}
    assert fc.refresh(tmp_path, now=NOW + timedelta(minutes=1), raw=raw) == first
    assert {p: p.read_bytes() for p in files} == files
    changed = copy.deepcopy(source()); changed["indicators"][fc.KEYS[0]]["score"] = 40
    second = fc.refresh(tmp_path, now=NOW + timedelta(minutes=2), raw=encode(changed))
    got = fc.projection(tmp_path, now=NOW + timedelta(minutes=3), strict=True)
    assert got["revision"] == 2 and got["supersedes"] == first["snapshot_id"]
    assert got["available_at"] == (NOW + timedelta(minutes=2)).isoformat()
    assert got["source_as_of"] == STAMP.isoformat() and first["snapshot_id"] != second["snapshot_id"]
    for p, body in files.items():
        if p.parent.name in {"raw", "receipts", "snapshots"}:
            assert p.read_bytes() == body


def test_failure_keeps_pointer_but_hides_old_scores_and_retry_recovers(tmp_path):
    first = fc.refresh(tmp_path, now=NOW, raw=encode(source()))
    with pytest.raises(fc.ComponentsError):
        fc.refresh(tmp_path, now=NOW + timedelta(minutes=1), raw=b'<html>error</html>')
    assert json.loads((tmp_path / fc.BASE / 'latest.json').read_bytes()) == first
    assert fc.projection(tmp_path, now=NOW)["components"] == {}
    fc.refresh(tmp_path, now=NOW + timedelta(minutes=2), raw=encode(source()))
    assert fc.projection(tmp_path, now=NOW + timedelta(minutes=3))["status"] == "live"
    assert fc.projection(tmp_path, now=NOW + timedelta(days=5))["components"] == {}


@pytest.mark.parametrize('target', ['snapshot', 'raw', 'receipt'])
def test_tampered_lineage_is_not_displayed(tmp_path, target):
    pointer = fc.refresh(tmp_path, now=NOW, raw=encode(source()))
    directory = tmp_path / fc.BASE
    if target == 'snapshot':
        (directory / 'snapshots' / (pointer['snapshot_id'] + '.json')).write_bytes(b'{}')
    elif target == 'raw':
        (directory / 'raw' / (pointer['raw_sha256'] + '.json.gz')).write_bytes(gzip.compress(b'{}'))
    else:
        (directory / 'receipts' / (pointer['raw_sha256'] + '.json')).write_bytes(b'{}')
    assert fc.projection(tmp_path, now=NOW)['components'] == {}


def test_no_seed_fallback_and_future_snapshot_is_not_usable(tmp_path):
    from ai_fc.fear_greed import components_projection, COMPONENTS_RELATIVE
    seed = tmp_path / COMPONENTS_RELATIVE
    seed.parent.mkdir(parents=True)
    seed.write_text(json.dumps({'dates': ['2026-09-15'], 'fng': [31],
                               'components': {'old': {'score': 31, 'series': [1]}}}))
    assert components_projection(tmp_path, now=NOW)['components'] == {}
    fc.refresh(tmp_path, now=NOW, raw=encode(source()))
    assert fc.projection(tmp_path, now=NOW - timedelta(days=2))['components'] == {}
    assert fc.projection(tmp_path, now=NOW - timedelta(minutes=1))['components'] == {}


def test_partial_pointer_failure_never_claims_success(tmp_path, monkeypatch):
    first = fc.refresh(tmp_path, now=NOW, raw=encode(source()))
    real = fc._atomic
    def fail_pointer(path, value):
        if path.name == 'latest.json':
            raise OSError('interrupted pointer exchange')
        real(path, value)
    monkeypatch.setattr(fc, '_atomic', fail_pointer)
    data = source(); data['indicators'][fc.KEYS[0]]['score'] = 40
    with pytest.raises(OSError):
        fc.refresh(tmp_path, now=NOW + timedelta(minutes=1), raw=encode(data))
    assert json.loads((tmp_path / fc.BASE / 'latest.json').read_bytes()) == first
    assert fc.projection(tmp_path, now=NOW)['components'] == {}


def test_both_automatic_paths_refresh_even_if_headline_already_recorded():
    import yaml
    root = Path(__file__).resolve().parents[2]
    for filename, job in [('market-mood-refresh.yml', 'refresh'), ('source-monitoring.yml', 'monitor')]:
        workflow = yaml.safe_load((root / '.github/workflows' / filename).read_text(encoding='utf-8'))
        assert workflow['permissions']['actions'] == 'write'
        config = workflow['jobs'][job]
        assert config['if'] == "github.ref == 'refs/heads/main'"
        component = next(s for s in config['steps'] if s.get('id') == 'components')
        assert 'already_recorded' not in component.get('if', '') and component['continue-on-error'] is True
        publish = next(s for s in config['steps'] if 'gh workflow run pages.yml' in s.get('run', ''))
        assert "steps.commit.outputs.committed == 'true'" in publish['if']
        assert any("steps.components.outcome == 'failure'" in s.get('if', '') for s in config['steps'])


def test_network_retries_are_bounded_and_use_the_documented_free_endpoint(tmp_path, monkeypatch):
    calls = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return encode(source())
    def open_source(request, timeout):
        calls.append(request)
        if len(calls) < 3: raise TimeoutError('temporary source delay')
        return Response()
    monkeypatch.setattr(fc.urllib.request, 'urlopen', open_source)
    monkeypatch.setattr(fc.time, 'sleep', lambda value: None)
    fc.refresh(tmp_path, now=NOW)
    assert len(calls) == 3
    assert all(r.full_url == fc.ENDPOINT for r in calls)
    assert all(r.get_header('User-agent') == 'JinsInvestingResearch/1.0' for r in calls)


def test_broken_predecessor_and_source_regression_do_not_replace_pointer(tmp_path):
    first = fc.refresh(tmp_path, now=NOW, raw=encode(source()))
    data = source(); data['asOf'] = (STAMP - timedelta(minutes=1)).isoformat()
    with pytest.raises(fc.ComponentsError, match='regressed'):
        fc.refresh(tmp_path, now=NOW + timedelta(minutes=1), raw=encode(data))
    path = tmp_path / fc.BASE / 'snapshots' / (first['snapshot_id'] + '.json')
    path.write_bytes(b'{}')
    with pytest.raises((fc.ComponentsError, KeyError)):
        fc.refresh(tmp_path, now=NOW + timedelta(minutes=2), raw=encode(source()))
    assert json.loads((tmp_path / fc.BASE / 'latest.json').read_bytes()) == first


def test_reappearing_old_bytes_are_a_new_revision_not_backdated(tmp_path):
    raw = encode(source())
    first = fc.refresh(tmp_path, now=NOW, raw=raw)
    changed = source(); changed['indicators'][fc.KEYS[0]]['score'] = 40
    second = fc.refresh(tmp_path, now=NOW + timedelta(minutes=1), raw=encode(changed))
    third = fc.refresh(tmp_path, now=NOW + timedelta(minutes=2), raw=raw)
    got = fc.projection(tmp_path, now=NOW + timedelta(minutes=2), strict=True)
    assert got['supersedes'] == second['snapshot_id'] and got['revision'] == 3
    assert got['available_at'] == (NOW + timedelta(minutes=2)).isoformat()
    assert got['raw_first_acquired_at'] == NOW.isoformat()
    assert third['raw_sha256'] == first['raw_sha256'] and third['snapshot_id'] != first['snapshot_id']
