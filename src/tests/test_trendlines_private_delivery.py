"""Pinned private charts survive partial calculation and interrupted publication."""
from datetime import timedelta
import json
from pathlib import Path
import shutil

import pytest

from ai_fc.trendlines import contracts as C, research as R, storage as S, delivery as D
from ai_fc.trendlines import full_history as F, critical as K, representative as V, long_boundaries as B
from ai_fc.trendlines.local_service import LocalTrendlinesService
from test_trendlines_critical import capture, REPOSITORY


@pytest.fixture(scope='module')
def initial(tmp_path_factory):
    root=tmp_path_factory.mktemp('private-delivery-base')
    for relative in (C.CONTRACT_RELATIVE,C.ASSET_REGISTRY_RELATIVE,C.SOURCE_POLICY_RELATIVE,
                     K.POLICY_RELATIVE,V.POLICY_RELATIVE,B.POLICY_RELATIVE):
        dest=root/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(REPOSITORY/relative,dest)
    _,stamp=capture(root,count=300)
    K.refresh(root,'bitcoin',now=stamp);V.refresh(root,'bitcoin',now=stamp);B.refresh(root,'bitcoin',now=stamp)
    S.atomic_json(root/'bitcoin.trendlines.json',R.export_private_import(root,'bitcoin'))
    return root,stamp


@pytest.fixture
def store(initial,tmp_path):
    root,stamp=initial
    shutil.copytree(root,tmp_path,dirs_exist_ok=True)
    return tmp_path,stamp


def reader(root,stamp):
    return LocalTrendlinesService(root,refresh_asset=lambda _:pytest.fail('GET collected data'),
        startup_refresh=False,clock=lambda:C.aware_time(stamp)+timedelta(days=2))


def check_all(root,stamp,source):
    service=reader(root,stamp)
    current=R.decode_private_import(json.loads(service.read_asset_envelope('bitcoin')))
    assert current['snapshot_id']==source
    for method,module in ((service.read_full_manifest,F),(service.read_critical_detail,K),
                          (service.read_representative_detail,V),(service.read_long_boundaries_detail,B)):
        envelope=json.loads(method('bitcoin'))
        body=F.decode_envelope(envelope,F.MANIFEST_CONTRACT) if module is F else module.decode_envelope(envelope)
        assert body['source_snapshot_id']==source and body['as_of']==current['as_of']


def test_partial_refresh_and_failed_candidate_preserve_previous_complete_chart(store,monkeypatch):
    root,stamp=store
    old=R.decode_private_import(S.read_json(root/'bitcoin.trendlines.json'))['snapshot_id']
    D.freeze_previous(root,'bitcoin')
    pointer=D.selection_path(root,'bitcoin');before=pointer.read_bytes()
    old_selected=D.load_selected(root,'bitcoin')
    check_all(root,stamp,old)
    result,new_stamp=capture(root,count=301,extra=1)
    # Source and full pointers are now new; the current UI must stay coherent.
    check_all(root,new_stamp,old)
    with pytest.raises(ValueError,match='cohort_mismatch'):
        D.publish(root,'bitcoin',R.export_private_import(root,'bitcoin'))
    assert pointer.read_bytes()==before
    K.refresh(root,'bitcoin',now=new_stamp);V.refresh(root,'bitcoin',now=new_stamp)
    check_all(root,new_stamp,old)
    with pytest.raises(ValueError,match='cohort_mismatch'):
        D.publish(root,'bitcoin',R.export_private_import(root,'bitcoin'))
    B.refresh(root,'bitcoin',now=new_stamp)
    D.publish(root,'bitcoin',R.export_private_import(root,'bitcoin'))
    # Even before the replaceable legacy file moves, every route sees the new cohort.
    check_all(root,new_stamp,result['snapshot_id'])
    assert R.decode_private_import(S.read_json(root/'bitcoin.trendlines.json'))['snapshot_id']==old
    assert len(list((root/D.ROOT/'snapshots').glob('*.json')))==2
    # One request keeps its initial selection even after the selector advances.
    calls=[];original_load=D.load_selected
    def read_once(*args,**kwargs):
        calls.append(True)
        return old_selected if len(calls)==1 else original_load(*args,**kwargs)
    with monkeypatch.context() as scope:
        scope.setattr(D,'load_selected',read_once)
        envelope=json.loads(reader(root,new_stamp).read_representative_detail('bitcoin'))
        assert V.decode_envelope(envelope)['source_snapshot_id']==old
    assert len(calls)==1
    # The mutable selector is read once, so an atomic replacement cannot cause
    # a false hash mismatch between two reads of different valid generations.
    original_bytes=Path.read_bytes;reads=[]
    def replace_during_read(path):
        if path==pointer:
            reads.append(True)
            return before if len(reads)==1 else original_bytes(path)
        return original_bytes(path)
    with monkeypatch.context() as scope:
        scope.setattr(Path,'read_bytes',replace_during_read)
        assert D.load_selected(root,'bitcoin')['source_snapshot_id']==old
    assert len(reads)==1


def test_idempotent_selection_never_rewrites_source_or_model_history(store):
    root,stamp=store
    before={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    first=D.freeze_previous(root,'bitcoin');second=D.freeze_previous(root,'bitcoin')
    again=D.publish(root,'bitcoin',S.read_json(root/'bitcoin.trendlines.json'))
    assert first==second==again['snapshot_id']
    assert all((root/p).read_bytes()==raw for p,raw in before.items())
    assert len(list((root/D.ROOT/'snapshots').glob('*.json')))==1


@pytest.mark.parametrize('target',['pointer','bundle','source','receipt','full_export','representative_export','policy'])
def test_tampering_is_rejected_without_falling_back_to_live_pointers(store,target):
    root,stamp=store;D.freeze_previous(root,'bitcoin');selected=D.load_selected(root,'bitcoin')
    source=R._checked(S.safe_path(root,R._latest(root)['assets']['bitcoin']['snapshot_path']))
    receipt=R._checked(S.safe_path(root,source['receipt_path']))
    paths={'pointer':D.selection_path(root,'bitcoin'),
           'bundle':S.safe_path(root,S.read_json(D.selection_path(root,'bitcoin'))['snapshot_path']),
           'source':S.safe_path(root,receipt['raw_path']),'receipt':S.safe_path(root,source['receipt_path']),
           'full_export':S.safe_path(root,selected['models']['full']['manifest_path']),
           'representative_export':S.safe_path(root,selected['models']['representative']['detail_path']),
           'policy':root/V.POLICY_RELATIVE}
    path=paths[target];path.write_bytes(path.read_bytes()+b' ')
    if target=='policy':
        # YAML whitespace is valid; change the actual contract instead.
        path.write_text(path.read_text(encoding='utf-8').replace('observations: 200','observations: 199'),encoding='utf-8')
    with pytest.raises((ValueError,OSError,KeyError)):
        reader(root,stamp).read_representative_detail('bitcoin')


def test_get_never_recalculates_or_collects_and_keeps_pinned_read_during_pointer_change(store,monkeypatch):
    root,stamp=store;D.freeze_previous(root,'bitcoin')
    source=D.load_selected(root,'bitcoin')['source_snapshot_id']
    for module in (F,K,V,B):
        monkeypatch.setattr(module,'_calculate',lambda *_a,**_k:pytest.fail('GET calculated'))
    before={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    check_all(root,stamp,source)
    assert all((root/p).read_bytes()==raw for p,raw in before.items())
    assert len(before)==sum(p.is_file() for p in root.rglob('*'))


def test_publication_failure_never_advances_selection(store,monkeypatch):
    root,stamp=store;D.freeze_previous(root,'bitcoin')
    pointer=D.selection_path(root,'bitcoin');before=pointer.read_bytes();original=S.atomic_json
    def fail_selected(path,value,**kwargs):
        if path==pointer: raise OSError('simulated interrupted publication')
        return original(path,value,**kwargs)
    monkeypatch.setattr(S,'atomic_json',fail_selected)
    with pytest.raises(OSError,match='interrupted'):
        D.publish(root,'bitcoin',S.read_json(root/'bitcoin.trendlines.json'))
    assert pointer.read_bytes()==before
    check_all(root,stamp,D.load_selected(root,'bitcoin')['source_snapshot_id'])


def test_explicit_read_cutoff_and_asset_identity_are_preserved(store):
    root,stamp=store;D.freeze_previous(root,'bitcoin')
    with pytest.raises(ValueError):D.load_selected(root,'mag7')
    with pytest.raises(ValueError):D.load_selected(root,'bitcoin',now=C.aware_time(stamp)-timedelta(seconds=1))
    assert D.load_selected(root,'dow') is None
