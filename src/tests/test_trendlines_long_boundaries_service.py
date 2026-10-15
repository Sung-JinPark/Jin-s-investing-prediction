"""The additive endpoint inherits the existing loopback and read-only guards."""
from copy import deepcopy
import json
import sys
import types
import pytest

import ai_fc.trendlines as package
from ai_fc.trendlines import storage as S, local_service as L
from test_trendlines_representative_service import representative_server, request, wrap, NOW

ROUTE='/api/private-trendlines/bitcoin/long-boundaries'


@pytest.fixture
def server(representative_server,monkeypatch):
    original,store,calls=representative_server
    body=json.loads(store.detail['payload_json']);body.update(contract_id='trendlines_private_long_boundaries_v1')
    supplement={'value':wrap(body,'trendlines_private_long_boundaries_transport_v1'),'error':None,'loads':[]}
    def load(root,asset_id,*,now):
        supplement['loads'].append((root,asset_id,now))
        if supplement['error']:raise supplement['error']
        return deepcopy(supplement['value'])
    module=types.ModuleType('ai_fc.trendlines.long_boundaries');module.load_detail=load;module.decode_envelope=store.decode_envelope
    # The service's decoder takes no expected-contract keyword.
    module.decode_envelope=lambda envelope:store.decode_envelope(envelope,'trendlines_private_long_boundaries_v1')
    monkeypatch.setitem(sys.modules,module.__name__,module);monkeypatch.setattr(package,'long_boundaries',module,raising=False)
    return original,store,supplement,calls


def test_endpoint_is_readonly_and_additive(server):
    original,store,supplement,calls=server;companion,_=original
    before=companion.read_asset_envelope('bitcoin')
    code,headers,raw=request(original,ROUTE)
    assert code==200 and raw==S.encode(supplement['value']) and headers['Cache-Control']=='no-store'
    assert supplement['loads']==[(companion.root,'bitcoin',NOW)] and not calls and companion._worker is None
    assert companion.read_asset_envelope('bitcoin')==before


@pytest.mark.parametrize('field,value',[('asset_id','soxx'),('source_snapshot_id','different'),('reference_index',999),('reference_close',999),('as_of','2026-10-01T00:00:00+00:00'),('source_archive_sha256','f'*64)])
def test_wrong_capture_only_removes_additional_two(server,field,value):
    original,store,supplement,calls=server;body=json.loads(supplement['value']['payload_json']);body[field]=value
    supplement['value']=wrap(body,'trendlines_private_long_boundaries_transport_v1')
    assert request(original,ROUTE)[0]==503
    assert request(original,'/api/private-trendlines/bitcoin/representative')[0]==200
    assert request(original,'/api/private-trendlines/bitcoin')[0]==200 and not calls


@pytest.mark.parametrize('failure',['missing','hash','error'])
def test_supplement_failure_preserves_three_and_candles(server,failure):
    original,store,supplement,calls=server
    if failure=='missing':supplement['value']=None
    elif failure=='hash':supplement['value']['payload_sha256']='0'*64
    else:supplement['error']=ValueError('invalid source')
    assert request(original,ROUTE)[0]==(404 if failure=='missing' else 503)
    assert request(original,'/api/private-trendlines/bitcoin/representative')[0]==200 and not calls


@pytest.mark.parametrize('route',[ROUTE+'?refresh=1',ROUTE+'/',ROUTE+'/raw',ROUTE.replace('bitcoin','mag7'),ROUTE.replace('bitcoin','%62itcoin')])
def test_unknown_paths_never_read_private_supplement(server,route):
    original,_store,supplement,calls=server;assert request(original,route)[0]==404
    assert not supplement['loads'] and not calls


@pytest.mark.parametrize('method',['POST','PUT','PATCH','DELETE','HEAD'])
def test_mutations_are_rejected(server,method):
    original,_store,supplement,calls=server;assert request(original,ROUTE,method=method,body='refresh')[0]==405
    assert not supplement['loads'] and not calls


def test_foreign_origin_is_rejected(server):
    original,_store,supplement,calls=server;code,headers,_=request(original,ROUTE,origin='https://attacker.example')
    assert code==403 and 'Access-Control-Allow-Origin' not in headers and not supplement['loads'] and not calls
