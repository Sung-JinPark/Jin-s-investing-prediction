"""Separate long-side geometry, independent replay and append-only publication."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ai_fc.trendlines import contracts as C, long_boundaries as B, representative as V, storage as S
from test_trendlines_representative import rows, inputs, capture, original_bytes, REPOSITORY


@pytest.fixture
def store(tmp_path):
    from ai_fc.trendlines import research as R
    for relative in (C.CONTRACT_RELATIVE,C.ASSET_REGISTRY_RELATIVE,C.SOURCE_POLICY_RELATIVE,V.POLICY_RELATIVE,B.POLICY_RELATIVE):
        target=tmp_path/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(REPOSITORY/relative,target)
    return tmp_path


def calculation(observations=None):
    source,full=inputs(observations or rows())
    representative=V._calculate(source,full)
    return source,full,representative,B._calculate(source,full,representative)


def test_exact_policy_and_two_real_sides_are_separate_from_original_three(store):
    assert B.load_policy(store)==B.POLICY
    source,full,v,result=calculation()
    before=deepcopy(v)
    assert result['independent_validation']['independent_candidate_completeness_and_rank']
    for axis,view in result['analyses'].items():
        assert [p['slot'] for p in view['boundaries']]==list(B.SLOTS)
        assert all(p['kind']=='pivot_structure' and p['status']=='ready' for p in view['boundaries'])
        upper,lower=view['boundaries']
        assert upper['origin_role']=='resistance' and lower['origin_role']=='support'
        assert upper['current_price']>=source['asset'].get('unused',full['bars'][-1]['close'])
        assert lower['current_price']<=full['bars'][-1]['close']
        assert all(p['verified_boundary'] is False for p in view['boundaries'])
    assert v==before and len(v['analyses']['linear']['representatives'])==3


def test_no_pivots_produces_only_explicit_holds_without_ols():
    observations=rows()
    for row in observations: row.update(low=row['close']-2,high=row['close']+2)
    *_,result=calculation(observations)
    for view in result['analyses'].values():
        assert all(p['status']=='hold' and p['current_price'] is None and not p['points'] for p in view['boundaries'])


def test_old_pivots_unconfirmed_tail_and_missing_confirmation_are_not_candidates():
    observations=rows(1100,gaps=(1080,))
    *_,result=calculation(observations)
    for view in result['analyses'].values():
        assert all(p['status']=='hold' for p in view['boundaries'])


def test_scalar_rank_detects_a_reordered_production_selection(monkeypatch):
    monkeypatch.setattr(B,'_rank',lambda line:(line['line_id'],))
    with pytest.raises(ValueError,match='scalar_candidate_completeness_or_rank'):
        calculation()


def test_reference_classification_and_no_role_flip_are_explicit():
    observations=rows()
    observations[70]['high']=500
    source,_=inputs(observations);atr=V.E._atr(observations,14,segmented=True);pivots=V._pivots(observations,10,10)
    first=next(p for p in pivots if p['index']==45 and p['side']=='resistance')
    second=next(p for p in pivots if p['index']==135 and p['side']=='resistance')
    upper=B._candidate(first,second,pivots,observations,atr,source['asset'],source['config'],'linear',V._future(observations,source['asset']),'long_upper')
    assert upper['formation_penetration']>1 and not upper['formation_valid']
    assert upper['classification']=='reference_structure' and upper['role']=='direction_only'
    assert 'formation_penetration' in upper['reference_reasons']


def test_nonpositive_far_or_unconfirmed_geometry_is_not_eligible():
    observations=rows();source,_=inputs(observations);atr=V.E._atr(observations,14,segmented=True);future=V._future(observations,source['asset'])
    pivots=V._pivots(observations,10,10);a=next(p for p in pivots if p['index']==45 and p['side']=='resistance');b=next(p for p in pivots if p['index']==135 and p['side']=='resistance')
    assert B._eligible(a,b,observations,atr,'linear',future)
    assert not B._eligible({**a,'price':10000},{**b,'price':10000},observations,atr,'linear',future)
    assert not B._eligible({**a,'price':200},{**b,'price':100},observations,atr,'linear',future)
    assert not B._eligible(a,{**b,'index':80},observations,atr,'linear',future)


def test_intact_candidates_outrank_closer_references():
    _,_,_,result=calculation()
    intact=deepcopy(result['analyses']['linear']['boundaries'][1])
    reference=deepcopy(intact);reference.update(classification='reference_structure',distance_atr=0.0)
    assert B._rank(intact)<B._rank(reference)


def test_refresh_idempotent_source_and_representative_snapshots_unchanged(store):
    _,stamp=capture(store,count=300)
    V.refresh(store,'bitcoin',now=stamp)
    before={str(p.relative_to(store)):p.read_bytes() for p in store.rglob('*') if p.is_file()}
    first=B.refresh(store,'bitcoin',now=stamp);second=B.refresh(store,'bitcoin',now=stamp)
    assert first['changed'] and not second['changed']
    assert first['long_boundaries_snapshot_id']==second['long_boundaries_snapshot_id']
    assert all((store/name).read_bytes()==raw for name,raw in before.items())
    assert B.verify(store,now=stamp)['ok']
    envelope=B.load_detail(store,'bitcoin',now=stamp);body=B.decode_envelope(envelope)
    representative=V.decode_envelope(V.load_detail(store,'bitcoin',now=stamp))
    assert body['source_representative_snapshot_id']==representative['snapshot_id']
    assert body['events']==[] and all(body[k] is False for k in ('verified_source','verified_boundary','official_forecast_write','historical_signals_available'))
    assert len(envelope['payload_json'].encode())<=262144


@pytest.mark.parametrize('target',['source','representative','snapshot','export','pointer','policy'])
def test_corruption_never_replaces_public_pointer(store,target):
    _,stamp=capture(store,count=270);V.refresh(store,'bitcoin',now=stamp);B.refresh(store,'bitcoin',now=stamp)
    pointer=store/B.ROOT/'latest.json';before=pointer.read_bytes()
    if target=='source': path=next((store/'data/trendlines_research/raw').glob('*'))
    elif target=='representative': path=next((store/V.ROOT/'snapshots').glob('*.json'))
    elif target=='snapshot': path=next((store/B.ROOT/'snapshots').glob('*.json'))
    elif target=='export': path=next((store/B.ROOT/'exports').rglob('detail.json'))
    elif target=='policy': path=store/B.POLICY_RELATIVE
    else: path=pointer
    raw=path.read_bytes();path.write_bytes(raw.replace(b'maximum_distance_atr: 8.0',b'maximum_distance_atr: 7.0') if target=='policy' else raw+b' ')
    with pytest.raises(ValueError): B.refresh(store,'bitcoin',now=stamp)
    assert pointer.read_bytes()==(before+b' ' if target=='pointer' else before)


def test_payload_tampering_even_with_new_payload_hash_is_rejected(store):
    _,stamp=capture(store,count=270);V.refresh(store,'bitcoin',now=stamp);B.refresh(store,'bitcoin',now=stamp)
    envelope=B.load_detail(store,'bitcoin',now=stamp);body=B.decode_envelope(envelope)
    line=body['analyses']['linear']['boundaries'][0]
    if line['status']=='ready':line['current_price']+=1
    else:line['current_price']=1
    envelope['payload_json']=json.dumps(body,sort_keys=True,separators=(',',':'))
    envelope['payload_sha256']=hashlib.sha256(envelope['payload_json'].encode()).hexdigest()
    with pytest.raises(ValueError):B.decode_envelope(envelope)


def test_new_revision_preserves_old_snapshot_and_replays_both(store):
    _,stamp=capture(store,count=270);V.refresh(store,'bitcoin',now=stamp);first=B.refresh(store,'bitcoin',now=stamp)
    old_path=store/B.ROOT/'snapshots'/(first['long_boundaries_snapshot_id']+'.json');before=old_path.read_bytes()
    _,stamp=capture(store,count=270,extra=2);V.refresh(store,'bitcoin',now=stamp);second=B.refresh(store,'bitcoin',now=stamp)
    assert first['long_boundaries_snapshot_id']!=second['long_boundaries_snapshot_id']
    assert old_path.read_bytes()==before and B.verify(store,now=stamp)['snapshots']==2


def test_source_race_leaves_previous_public_pointer_intact(store,monkeypatch):
    _,stamp=capture(store,count=270);V.refresh(store,'bitcoin',now=stamp);B.refresh(store,'bitcoin',now=stamp)
    before=(store/B.ROOT/'latest.json').read_bytes()
    _,stamp=capture(store,count=271);V.refresh(store,'bitcoin',now=stamp)
    original=B._context;calls=[]
    def changing(*args,**kwargs):
        value=original(*args,**kwargs);calls.append(1)
        if len(calls)>1:
            changed=deepcopy(value);changed[0]['content_hash']='f'*64;return changed
        return value
    monkeypatch.setattr(B,'_context',changing)
    with pytest.raises(ValueError,match='source_changed_during_calculation'):B.refresh(store,'bitcoin',now=stamp)
    assert (store/B.ROOT/'latest.json').read_bytes()==before
