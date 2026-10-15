"""Independent source validation, exact aliases and isolated supplement polling."""
from copy import deepcopy
import hashlib
import json
import pytest

from ai_fc.trendlines import contracts as C, long_boundaries as B, representative as V
from test_trendlines_representative import rows
from test_trendlines_ui import (run, representative_ui_fixture, full_history_fixture,
                               private_import_envelope, representative_transport, local_browser_stub)


@pytest.fixture
def fixture(representative_ui_fixture):
    f=deepcopy(representative_ui_fixture)
    bars=[{**r,'session':r['session_date']} for r in rows()]
    f['full'].update(bars=bars,gaps=[],observation_through=bars[-1]['session'],intraday_quote=None,input_hash=C.canonical_hash(bars))
    f['current'].update(bars=deepcopy(bars[-63:]),gaps=[],observation_through=bars[-1]['session'],intraday_quote=None,config_sha256=C.canonical_hash(C.default_config()))
    source={'snapshot_id':f['current']['snapshot_id'],'asset':f['current']['asset'],'config':C.default_config()}
    source['asset'].update(kind='crypto',calendar_id='24/7')
    computation=V._calculate(source,f['full'])
    for windows in f['current']['analyses'].values():
        for view in windows.values():
            view['projection_sessions']=[deepcopy(computation['projection_sessions'][p['offset']-1]) for p in view.get('projection_sessions',[])]
    f['body'].update({k:v for k,v in computation.items() if k not in {'policy','candidate_audits'}})
    envelope=json.loads(representative_transport(f['body']))
    body={k:deepcopy(f['body'][k]) for k in B.REFERENCE_FIELDS}
    body.update(schema_version=1,policy_version=B.POLICY_VERSION,publication_scope='private_only',verified_source=False,
                verified_boundary=False,official_forecast_write=False,historical_signals_available=False,events=[],
                source_representative_snapshot_id=f['body']['snapshot_id'],source_representative_content_hash='a'*64,
                source_representative_payload_sha256=envelope['payload_sha256'],representative_lines_sha256=C.canonical_hash(f['body']['analyses']),
                snapshot_id=B.SNAPSHOT_PREFIX+'e'*64,**B._calculate(source,f['full'],computation))
    f['long']=B.decode_envelope(B._export(body))
    f['raw_v']=representative_transport(f['body'])
    f['raw_long']=json.dumps(B._export(body),ensure_ascii=False)
    return f


def setup(f):
    return "globalThis.crypto=require('node:crypto').webcrypto;const f="+json.dumps(f)+";"


@pytest.mark.parametrize('axis',['linear','log'])
def test_extra_two_validate_ohlc_equations_and_keep_original_three(tmp_path,fixture,axis):
    out=run(tmp_path,setup(fixture)+'const axis='+json.dumps(axis)+r''';
(async()=>{const before=JSON.stringify(f),v=await parseTrendRepresentativeTransport(f.raw_v,f.current,f.full),l=await parseTrendLongTransport(f.raw_long,f.current,f.full,v);TREND_REPRESENTATIVE_DETAILS.set('bitcoin',v);TREND_LONG_DETAILS.set('bitcoin',l);const all=trendRepresentativeAnalysis(f.current,f.full,axis),pair=trendRepresentativeAnalysis(f.current,f.full,axis,'long_boundaries'),m=trendPlotModel(f.full,all,trendRepresentativeViewport(f.full,all),axis,390),html=trendSvg(f.full,m,{currency:'USD'}),prices=l.analyses[axis].boundaries.map(line=>({slot:line.slot,price:line.current_price,eq:trendLinePrice(line,l.reference_index,axis)}));process.stdout.write(JSON.stringify({original:v.analyses[axis].representatives.length,extra:all.long_boundaries.length,visible:all.lines.length,pair:pair.lines.map(p=>p.slot),lineCount:(html.match(/data-trend-line=/g)||[]).length,prices,unchanged:before===JSON.stringify(f),rows:trendLongBoundaryRows(all,{currency:'USD'})}));})();''')
    assert out['original']==3 and out['extra']==2 and 3<=out['visible']<=5
    assert out['pair']==list(B.SLOTS) and out['lineCount']==out['visible']
    assert all(p['price']==pytest.approx(p['eq'],rel=1e-10,abs=1e-6) for p in out['prices']) and out['unchanged']
    assert '장기 고점 연결선' in out['rows'] and '장기 저점 연결선' in out['rows']


@pytest.mark.parametrize('problem',['price','source','representative','policy','contact','state','alias','future_date','ohlc','role','config','duplicate_key'])
def test_bad_additional_payload_never_removes_verified_base_three(tmp_path,fixture,problem):
    f=deepcopy(fixture);e=json.loads(f['raw_long']);body=json.loads(e['payload_json']);line=body['analyses']['linear']['boundaries'][0]
    if problem=='price':line['current_price']+=1
    elif problem=='source':body['source_snapshot_id']='other'
    elif problem=='representative':body['source_representative_snapshot_id']='representative-snapshot-'+'0'*64
    elif problem=='policy':body['policy_sha256']='0'*64
    elif problem=='contact':line['contacts'][0]['price']+=1
    elif problem=='state':line['structural_state']='broken' if line['structural_state']!='broken' else 'active'
    elif problem=='alias':line['equivalent_to_line_ids']=['nonexistent']
    elif problem=='future_date':line['projections'][0]['session']='2030-01-01'
    elif problem=='ohlc':line['projections'][0]['close']=123
    elif problem=='role':line['role']='support'
    elif problem=='config':body['calculation_settings_json']='{}'
    payload=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if problem=='duplicate_key':payload=payload[:-1]+',"asset_id":"bitcoin"}'
    e['payload_json']=payload;e['payload_sha256']=hashlib.sha256(payload.encode()).hexdigest();f['raw_long']=json.dumps(e)
    out=run(tmp_path,setup(f)+r''';(async()=>{const v=await parseTrendRepresentativeTransport(f.raw_v,f.current,f.full);TREND_REPRESENTATIVE_DETAILS.set('bitcoin',v);let rejected=false;try{await parseTrendLongTransport(f.raw_long,f.current,f.full,v);}catch(error){rejected=true;}process.stdout.write(JSON.stringify({rejected,base:trendRepresentativeAnalysis(f.current,f.full,'linear').lines.length}));})();''')
    assert out=={'rejected':True,'base':3}


def test_only_selected_exact_geometry_aliases_are_merged(tmp_path,fixture):
    out=run(tmp_path,setup(fixture)+r''';
const low=f.long.analyses.linear.boundaries[1],major={...low,slot:'major_structure',line_id:'older-major'},near={...low,line_id:'nearby',intercept:low.intercept+1};const merged=trendMergeSelectedLines([major,low]),alone=trendMergeSelectedLines([low]);process.stdout.write(JSON.stringify({merged:merged.length,aliases:merged[0].alias_slots,alone:alone.length,slot:alone[0].slot,near:trendMergeSelectedLines([major,near]).length}));''')
    assert out=={'merged':1,'aliases':['major_structure','long_lower'],'alone':1,'slot':'long_lower','near':2}


@pytest.mark.parametrize('reverse',[False,True])
def test_merged_reference_keeps_its_warning_without_mutating_original_line(tmp_path,fixture,reverse):
    out=run(tmp_path,setup(fixture)+'const reverse='+json.dumps(reverse)+r''';
const low={...f.long.analyses.linear.boundaries[1],classification:'reference_structure'},major={...low,slot:'major_structure',line_id:'older-major'};delete major.classification;const merged=trendMergeSelectedLines(reverse?[low,major]:[major,low]);process.stdout.write(JSON.stringify({count:merged.length,reference:merged[0].classification,name:trendRepresentativeName(merged[0]),original:Object.hasOwn(major,'classification')}));''')
    assert out['count']==1 and out['reference']=='reference_structure' and not out['original']
    assert '구조 참고선' in out['name'] and '장기 저점 연결선' in out['name'] and '장기 주요 고저점' in out['name']


@pytest.mark.parametrize('axis',['linear','log'])
def test_anchor_view_and_enlarged_hover_use_selected_first_anchor(tmp_path,fixture,axis):
    out=run(tmp_path,setup(fixture)+'const axis='+json.dumps(axis)+r''';(async()=>{const v=await parseTrendRepresentativeTransport(f.raw_v,f.current,f.full),l=await parseTrendLongTransport(f.raw_long,f.current,f.full,v);TREND_REPRESENTATIVE_DETAILS.set('bitcoin',v);TREND_LONG_DETAILS.set('bitcoin',l);const a=trendRepresentativeAnalysis(f.current,f.full,axis,'long_boundaries'),bars=trendRepresentativeViewport(f.full,a,'anchors'),start=Math.min(...a.lines.map(p=>p.first_anchor.index)),m=trendPlotModel(f.full,a,bars,axis,1280),line=m.lines[0],index=m.sourceLast+5,price=trendLinePrice(line,index,axis),hit=trendHoverAt(m,m.x(index),m.y(price),{scale:axis});process.stdout.write(JSON.stringify({first:bars[0].session_index,expected:Math.max(0,start-10),kind:hit.kind,price:hit.row.price,expectedPrice:price,future:hit.future,text:trendHoverText(hit,{currency:'USD'}),baseSource:f.body.snapshot_id}));})();''')
    assert out['first']==out['expected'] and out['kind']=='line' and out['future']
    assert out['price']==pytest.approx(out['expectedPrice'],abs=1e-6,rel=1e-10)
    assert '추세선 연장값' in out['text'] and '실제 종가 없음' in out['text']


@pytest.mark.parametrize('completion',['valid','404','corrupt','late_source','route_leave'])
def test_supplement_poll_is_scoped_and_never_clears_base(tmp_path,fixture,completion):
    out=run(tmp_path,local_browser_stub()+setup(fixture)+'const completion='+json.dumps(completion)+r''';
(async()=>{const v=await parseTrendRepresentativeTransport(f.raw_v,f.current,f.full);TREND_REPRESENTATIVE_DETAILS.set('bitcoin',v);TREND_PRIVATE_DETAILS.set('bitcoin',f.current);TREND_FULL_DETAILS.set('bitcoin',f.full);TREND_LOCAL_ENABLED=false;const session=bindTrendLocalConnection(root,{asset:'bitcoin'});await Promise.resolve();session.longMounted=true;session.representativeMounted=true;session.onRepresentativeData=()=>{};TREND_LOCAL_ENABLED=true;let release;const requests=[];globalThis.fetch=async(url,options)=>{requests.push({url,method:options.method,credentials:options.credentials});return new Promise(resolve=>release=()=>resolve(response(completion==='corrupt'?'{}':f.raw_long,completion==='404'?404:200)));};const pending=refreshTrendLongSession(session);if(completion==='late_source')TREND_FULL_DETAILS.set('bitcoin',{...f.full,snapshot_id:'different'});if(completion==='route_leave')stopTrendLocalSession();release();await pending;const base=TREND_REPRESENTATIVE_DETAILS.get('bitcoin').snapshot_id,extra=TREND_LONG_DETAILS.has('bitcoin');stopTrendLocalSession();process.stdout.write(JSON.stringify({requests,base,extra}));})();''')
    assert out['base']==fixture['body']['snapshot_id'] and out['extra']==(completion=='valid')
    assert out['requests']==[{'url':'http://127.0.0.1:8878/api/private-trendlines/bitcoin/long-boundaries','method':'GET','credentials':'omit'}]


def test_mag7_is_hidden_without_changing_registered_source_catalog(tmp_path):
    out=run(tmp_path,"process.stdout.write(JSON.stringify({registered:TREND_ASSETS.length,visible:TREND_VISIBLE_ASSETS.map(p=>p[0])}));")
    assert out['registered']==7 and out['visible']==['sk-hynix','soxx','nasdaq','sp500','bitcoin','dow']
