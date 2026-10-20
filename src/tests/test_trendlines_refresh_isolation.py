"""Asset arithmetic isolation retains global original/lineage checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ai_fc.trendlines import contracts as C, engine as E, research as R, storage as S
from ai_fc.trendlines import full_history as F, critical as K, representative as V, long_boundaries as B
from test_trendlines_research import public_html, receipt, FETCHED
from test_trendlines_replay_cache import resign_archive
from test_trendlines_local_service import service, write_envelope, verified_report, NOW

REPO = Path(__file__).parents[2]


@pytest.fixture
def pair(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE,
                     K.POLICY_RELATIVE, V.POLICY_RELATIVE, B.POLICY_RELATIVE):
        target = tmp_path/relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO/relative, target)
    raw = public_html()
    R.capture_html(tmp_path, 'bitcoin', raw, receipt(raw), as_of=FETCHED)
    sessions = C.session_schedule('XNYS', '2024-01-01', '2024-07-01')[:100]
    prices = {key: [] for key in ('open','high','low','close','volume')}
    for i in range(len(sessions)):
        low = 100+i*.1+abs(i%20-10)*.6
        for key, value in zip(prices, (low+1,low+4,low,low+2,100)):
            prices[key].append(value)
    chart = {'chart': {'result': [{'meta': {'symbol':'^DJI','currency':'USD',
        'exchangeTimezoneName':'America/New_York','dataGranularity':'1d','instrumentType':'INDEX'},
        'timestamp':[int(opened.timestamp()) for _,opened,_ in sessions],
        'indicators':{'quote':[prices]},'events':{}}], 'error':None}}
    wrapper = {'status':200,'statusText':'OK','headers':{'content-type':'application/json'},'body':json.dumps(chart)}
    raw = ('<script type="application/json" data-sveltekit-fetched data-url="https://query1.finance.yahoo.com/v8/finance/chart/%5EDJI?interval=1d">'+json.dumps(wrapper)+'</script>').encode()
    stamp = '2024-07-02T01:00:00+00:00'
    rec = {'url':'https://finance.yahoo.com/quote/%5EDJI/history/','retrieved_at':stamp,
           'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'http_status':200}
    R.capture_html(tmp_path,'dow',raw,rec,as_of=stamp)
    return tmp_path


def all_bytes(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_scoped_replay_does_not_seed_unreplayed_math_and_default_audit_is_still_global(pair,monkeypatch):
    calls=[]; original=E.verify_research_asset_snapshot
    def counted(snapshot,bars,asset,**kw):
        calls.append((asset['asset_id'],kw['replay']))
        return original(snapshot,bars,asset,**kw)
    monkeypatch.setattr(E,'verify_research_asset_snapshot',counted)
    cache=R.VerifiedReplayCache();before=all_bytes(pair)
    with R.use_verified_replay_cache(cache):
        with R.use_asset_replay_scope('dow'):
            scoped=R.verify(pair);assert scoped['ok']
            assert scoped['replay_scope']['asset_id']=='dow'
            assert scoped['replay_scope']['store_integrity']=='all_originals_receipts_contracts_and_revision_links'
            assert R.verify(pair)['ok']
            assert calls.count(('dow',True))==1 and calls.count(('bitcoin',False))==1
            assert cache.entry_count==2  # One full proof and a separately named metadata proof.
        global_report=R.verify(pair)
        assert global_report=={'ok':True,'errors':[],'snapshots':2,'replay':True}
        assert calls.count(('bitcoin',True))==1 and calls.count(('dow',True))==1
        assert cache.entry_count==3  # Global replay cannot borrow the metadata-only proof.
    assert all_bytes(pair)==before


@pytest.mark.parametrize('attack',['raw','receipt','latest','revision'])
def test_foreign_original_or_lineage_corruption_still_stops_the_target(pair,attack):
    pointer=R._latest(pair);ref=pointer['assets']['bitcoin'];path=pair/ref['snapshot_path'];archive=R._checked(path)
    rec=R._checked(pair/archive['receipt_path'])
    if attack=='raw': (pair/rec['raw_path']).write_bytes(b'changed')
    elif attack=='receipt':
        rec['available_at']='2020-01-01T00:00:00+00:00'
        S.atomic_json(pair/archive['receipt_path'],R._hash(rec))
    elif attack=='latest':
        pointer['assets']['bitcoin']['snapshot_sha256']='0'*64
        S.atomic_json(pair/R.ROOT/'latest.json',R._hash(pointer))
    else:
        archive['supersedes_snapshot_id']='research-snapshot-'+'0'*64
        resign_archive(pair,path,archive,pointer)
    cache=R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache),R.use_asset_replay_scope('dow'):
        assert not R.verify(pair)['ok']
        assert cache.entry_count==0


def test_unrelated_numeric_failure_is_isolated_and_remains_visible_to_global_audit(pair):
    pointer=R._latest(pair);path=pair/pointer['assets']['bitcoin']['snapshot_path'];archive=R._checked(path)
    engine=deepcopy(archive['engine_snapshot'])
    line=next(line for views in engine['analyses'].values() for view in views.values() for line in view['lines'] if line['current_price'] is not None)
    line['current_price']+=1
    archive['engine_snapshot']=E._finish({k:v for k,v in engine.items() if k not in {'snapshot_id','content_hash'}})
    resign_archive(pair,path,archive,pointer)
    with R.use_asset_replay_scope('dow'):
        report=R.verify(pair)
        assert report['ok'] and report['replay_scope']['asset_id']=='dow'
    assert not R.verify(pair)['ok']


def test_scope_cannot_publish_another_asset_or_leak_after_exception(pair):
    before=all_bytes(pair)
    with pytest.raises(RuntimeError):
        with R.use_asset_replay_scope('dow'):
            for call in (lambda:R.export_private_import(pair,'bitcoin'),
                         lambda:R.load_asset_detail(pair,'bitcoin'),
                         *(lambda fn=fn:fn(pair,'bitcoin') for fn in (F.refresh,K.refresh,V.refresh,B.refresh)),
                         lambda:R.capture_html(pair,'bitcoin',b'invalid',{})):
                with pytest.raises(ValueError,match='replay_asset_mismatch'): call()
            with pytest.raises(ValueError,match='replay_asset_mismatch'):
                with R.use_asset_replay_scope('bitcoin'): pass
            raise RuntimeError('fixture failure')
    assert R._ACTIVE_REPLAY_ASSET.get() is None and all_bytes(pair)==before
    with pytest.raises(ValueError,match='not_registered'):
        with R.use_asset_replay_scope('mag7'): pass


def test_full_and_critical_scope_replays_only_target_without_using_newer_foreign_inputs(pair,monkeypatch):
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        for asset in ('bitcoin','dow'):
            F.refresh(pair,asset,now='2024-07-02T01:00:00+00:00')
            K.refresh(pair,asset,now='2024-07-02T01:00:00+00:00')
    before=all_bytes(pair);calls=[]
    for module in (F,K):
        original=module._calculate
        def counted(source,*args,_fn=original,_name=module.__name__,**kw):
            calls.append((_name,source['asset_id']))
            return _fn(source,*args,**kw)
        monkeypatch.setattr(module,'_calculate',counted)
    # Dow's July capture must not be treated as a future input to April's BTC.
    with R.use_asset_replay_scope('bitcoin'):
        report=K.verify(pair,now=FETCHED)
        assert report['ok'] and report['replay_scope']['asset_id']=='bitcoin'
    assert calls and {asset for _,asset in calls}=={'bitcoin'}
    calls.clear()
    with R.use_asset_replay_scope('dow'):
        assert K.verify(pair,now='2024-07-02T01:00:00+00:00')['ok']
    assert calls and {asset for _,asset in calls}=={'dow'}
    assert all_bytes(pair)==before


def test_scheduler_recovers_stale_dow_before_ready_assets_without_changing_registration(tmp_path):
    assets=tuple(R.SYMBOLS)
    for asset in assets: write_envelope(tmp_path,asset,asof=NOW.isoformat())
    write_envelope(tmp_path,'dow',asof='2026-10-09T22:00:00+00:00')
    calls=[];companion=service(tmp_path,assets=assets,callback=lambda asset:calls.append(asset) or verified_report())
    for asset in assets: companion._assets[asset]['last_success']=NOW.isoformat()
    companion._assets['dow']['last_success']='2026-10-09T22:00:00+00:00'
    before=all_bytes(tmp_path)
    assert companion._refresh_order()==('dow',)+tuple(asset for asset in assets if asset!='dow')
    assert companion.assets==assets and all_bytes(tmp_path)==before
    companion.start(scheduler=False)
    assert companion.wait_idle(10) and calls[0]=='dow' and set(calls)==set(assets)
    companion.stop()


def test_wrong_audit_scope_cannot_count_as_a_successful_refresh(tmp_path):
    before=write_envelope(tmp_path,'dow',asof=NOW.isoformat())
    report=verified_report();report['independent_replay']['replay_scope']={'kind':'asset','asset_id':'bitcoin',
        'store_integrity':'all_originals_receipts_contracts_and_revision_links'}
    companion=service(tmp_path,assets=('dow',),callback=lambda _:report)
    companion.start(scheduler=False)
    assert companion.wait_idle(10)
    row=next(row for row in companion.status()['assets'] if row['asset_id']=='dow')
    assert row['error']=='refresh_failed' and row['last_success'] is None
    assert (tmp_path/'dow.trendlines.json').read_bytes()==before
    companion.stop()


@pytest.mark.parametrize('replay',[True,False])
def test_scoped_success_requires_actual_target_scalar_replay(tmp_path,replay):
    write_envelope(tmp_path,'dow',asof=NOW.isoformat())
    report=verified_report();report['independent_replay'].update(replay=replay,replay_scope={
        'kind':'asset','asset_id':'dow','store_integrity':'all_originals_receipts_contracts_and_revision_links'})
    companion=service(tmp_path,assets=('dow',),callback=lambda _:report)
    companion.start(scheduler=False);assert companion.wait_idle(10)
    row=next(row for row in companion.status()['assets'] if row['asset_id']=='dow')
    assert bool(row['last_success'])==replay
    assert (row['error'] is None)==replay
    companion.stop()
