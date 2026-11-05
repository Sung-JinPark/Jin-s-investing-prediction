"""Second chart batch: types, indicators, formulas, scale modes, compare, replay rows, alerts, intraday, shapes."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

import pytest

from ai_fc.trendlines import local_service as L
from ai_fc.trendlines import symbol_lookup as Y
from test_trendlines_manual_ui import FIXTURE, run
from test_trendlines_symbol_lookup import StubService, get, segment

BUNDLE = Path(__file__).resolve().parents[1] / 'ai_fc' / 'dashboard_parts' / 'trendlines.js'

WALK = r'''
let seed=7;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;let last=100;
const rows=Array.from({length:400},(_,i)=>{const open=last,close=Math.max(1,open*(1+(rnd()-.48)*.04)),high=Math.max(open,close)*(1+rnd()*.01),low=Math.min(open,close)*(1-rnd()*.01);last=close;return {session:new Date(Date.UTC(2024,0,1+i)).toISOString().slice(0,10),session_index:i,open,high,low,close,volume:1000+Math.floor(rnd()*500)};});
'''

SESSIONS = r'''
const state=trendManualState('soxx');await state.loading;state.drawingScale='linear';
const sessions=trendManualSessions(detail,analysis),at=(i,price)=>({session:sessions[i].session,price});
'''


# ---- indicators
def test_every_indicator_stays_finite_and_aligned_on_a_realistic_series(tmp_path):
    out = run(tmp_path, WALK + r'''
const report={};for(const [key] of TREND_WS_INDICATORS){const data=trendWsIndicator(rows,key),series=[data.line,data.upper,data.lower,data.signal,data.hist,...(data.lines||[]).map(item=>item.values)].filter(Boolean);report[key]={aligned:series.every(column=>column.length===rows.length),finite:series.every(column=>column.every(value=>value===null||Number.isFinite(value))),filled:data.line.filter(value=>value!==null).length};}
process.stdout.write(JSON.stringify({report,count:TREND_WS_INDICATORS.length}));
''', FIXTURE)
    assert out['count'] == 30
    for key, row in out['report'].items():
        assert row['aligned'] and row['finite'], key
        assert row['filled'] > 150, key


def test_indicators_match_hand_arithmetic_on_a_steady_rise(tmp_path):
    out = run(tmp_path, r'''
const rows=Array.from({length:60},(_,i)=>({session:'2026-01-01',session_index:i,open:100+i,high:101+i,low:99+i,close:100+i,volume:10}));
const get=key=>trendWsIndicator(rows,key);
process.stdout.write(JSON.stringify({stoch:get('stoch').line.at(-1),willr:get('willr').line.at(-1),atr:get('atr').line.at(-1),roc:get('roc').line.at(-1),mom:get('mom').line.at(-1),obv:get('obv').line.at(-1),mfi:get('mfi').line.at(-1),wma:get('wma20').line.at(-1),donUp:get('donchian').upper.at(-1),donLow:get('donchian').lower.at(-1),spanA:get('ichimoku').lines[1].shift,lagging:get('ichimoku').lines[3].shift,sarBelow:get('psar').line.at(-1)<rows.at(-1).low,superUp:get('supertrend').lines[0].values.at(-1)<rows.at(-1).close,superDown:get('supertrend').lines[1].values.at(-1),adxUp:get('adx').lines[0].values.at(-1),adxDown:get('adx').lines[1].values.at(-1)}));
''', FIXTURE)
    # Close sits one below the 14-bar high, 2 ranges wide per bar.
    assert out['stoch'] == pytest.approx((159 - 145) / (160 - 145) * 100)
    assert out['willr'] == pytest.approx(-1 / 15 * 100)
    assert out['atr'] == pytest.approx(2, abs=.01)
    assert out['roc'] == pytest.approx((159 / 147 - 1) * 100)
    assert out['mom'] == 10
    assert out['obv'] == 590
    assert out['mfi'] == 100
    assert out['wma'] == pytest.approx(159 - 19 / 3)
    assert (out['donUp'], out['donLow']) == (160, 139)
    assert (out['spanA'], out['lagging']) == (26, -26)
    assert out['sarBelow'] and out['superUp'] and out['superDown'] is None
    assert out['adxUp'] == pytest.approx(50, abs=1) and out['adxDown'] == 0


def test_vwap_restarts_per_session_intraday_and_per_year_above_it(tmp_path):
    out = run(tmp_path, r'''
const intraday=[['2026-01-05','09:30',10],['2026-01-05','09:35',20],['2026-01-06','09:30',30]].map(([session,time,close],i)=>({session,time,session_index:i,open:close,high:close,low:close,close,volume:10}));
const daily=[['2025-12-30',10],['2025-12-31',20],['2026-01-02',40]].map(([session,close],i)=>({session,session_index:i,open:close,high:close,low:close,close,volume:10}));
const a=trendWsIndicator(intraday,'vwap'),b=trendWsIndicator(daily,'vwap');
process.stdout.write(JSON.stringify({a:a.line,b:b.line,drawnA:a.lines[0].values,drawnB:b.lines[0].values}));
''', FIXTURE)
    assert out['a'] == [10, 15, 30] and out['b'] == [10, 15, 40]
    # The restart is a gap in the drawn line, not a vertical stroke.
    assert out['drawnA'] == [10, 15, None] and out['drawnB'] == [10, 15, None]


# ---- formulas
def test_formula_matches_arithmetic_and_accepts_pine_prefixes(tmp_path):
    out = run(tmp_path, r'''
const rows=[10,20,30,40].map((close,i)=>({session_index:i,open:close,high:close+1,low:close-1,close,volume:i?100:null}));
const run_=text=>trendWsFormulaEval(trendWsFormulaParse(text),rows);
process.stdout.write(JSON.stringify({ratio:run_('(close/sma(close,2)-1)*100'),prefix:run_('ta.sma(close,2)'),nested:run_('ema(sma(close,2),2)'),power:run_('2^3+-1'),order:run_('1+2*3'),zero:run_('close/(close-close)'),volume:run_('volume'),cmp:run_('close>25'),bare:run_('rsi(2)'),highest:run_('highest(high,2)'),minOf:run_('min(close,15)')}));
''', FIXTURE)
    assert out['ratio'][0] is None and out['ratio'][1] == pytest.approx((20 / 15 - 1) * 100)
    assert out['prefix'] == [None, 15, 25, 35]
    assert out['nested'][:2] == [None, None] and out['nested'][2] == pytest.approx(20)
    assert out['power'] == [7, 7, 7, 7] and out['order'] == [7, 7, 7, 7]
    assert out['zero'] == [None] * 4
    assert out['volume'] == [None, 100, 100, 100]
    assert out['cmp'] == [0, 0, 1, 1]
    assert out['highest'] == [None, 21, 31, 41] and out['minOf'] == [10, 15, 15, 15]


@pytest.mark.parametrize('text', ['constructor', '__proto__', 'process.exit(1)', 'close.constructor', 'globalThis', 'fetch(close)', 'sma(close)(1)', 'sma(close,0)', 'sma(close,2001)', 'sma(close,close)', 'close,1', '(close', '', 'a' * 201, 'close;1', '`x`', "'x'", 'close[1]', 'hasOwnProperty'])
def test_formula_refuses_anything_outside_its_own_names(tmp_path, text):
    out = run(tmp_path, r'''
const rows=[10,20,30].map((close,i)=>({session_index:i,open:close,high:close,low:close,close}));let error=null,value=null;
try{value=trendWsFormulaEval(trendWsFormulaParse(TEXT),rows);}catch(e){error=e.message;}
process.stdout.write(JSON.stringify({error,value}));
'''.replace('TEXT', repr(text)), FIXTURE)
    assert out['error'], out


def test_formula_code_never_reaches_a_dynamic_evaluator():
    source = BUNDLE.read_text(encoding='utf-8')
    start, end = source.index('function trendWsFormulaParse'), source.index('function trendWsIndicator(rows,key)')
    body = source[start:end]
    assert 'eval(' not in body and 'Function(' not in body and 'import(' not in body


def test_bad_custom_formula_shows_its_error_instead_of_breaking_the_chart(tmp_path):
    out = run(tmp_path, WALK + r'''
TREND_WS_CUSTOM.set('custom:x',{id:'custom:x',name:'<b>x</b>',expr:'nope(close)',pane:true,color:'#7056a3'});
const data=trendWsIndicator(rows,'custom:x'),m2={W:800,R:60,L:4,first:0,end:399,x:i=>i*2,y:p=>p};
process.stdout.write(JSON.stringify({error:data.error,empty:data.line.every(value=>value===null),pane:trendWsPaneMarkup('custom:x',m2,rows,0,400,80).includes('알 수 없는 함수')}));
''', FIXTURE)
    assert '알 수 없는 함수' in out['error'] and out['empty'] and out['pane']


# ---- chart types and scale modes
@pytest.mark.parametrize('kind', ['hollow', 'volcandle', 'highlow', 'linemark', 'step', 'hlcarea', 'baseline', 'column'])
def test_each_new_chart_type_draws_rows_on_the_axis(tmp_path, kind):
    out = run(tmp_path, WALK + r'''
const model={wsSeries:rows.slice(0,50),wsType:KIND,wsClip:'ws1',W:800,H:400,L:4,R:60,T:10,B:26,first:0,end:49,x:i=>4+i*15,y:p=>400-p};
const html=trendWsSeriesMarkup(model);
process.stdout.write(JSON.stringify({length:html.length,clip:html.includes('ws1-base'),nan:html.includes('NaN')||html.includes('undefined')}));
'''.replace('KIND', repr(kind)), FIXTURE)
    assert out['length'] > 100 and not out['nan']
    assert out['clip'] == (kind == 'baseline')


def test_inverted_axis_reads_the_price_back_from_the_same_pixel(tmp_path):
    out = run(tmp_path, r'''
const model={H:500,T:20,B:40,ticks:[100,200],invert:true,y:p=>20+(p-100)/100*440};
process.stdout.write(JSON.stringify({low:trendManualPriceAt(model,model.y(120),'linear'),high:trendManualPriceAt(model,model.y(190),'linear')}));
''', FIXTURE)
    assert out['low'] == pytest.approx(120) and out['high'] == pytest.approx(190)


def test_prefs_refuse_junk_and_keep_old_preferences_working(tmp_path):
    out = run(tmp_path, r'''
const save=value=>memory.set(TREND_WS_PREFS_KEY,JSON.stringify(value));
save({type:'candle',interval:'W',percent:true,indicators:['ma20']});const old=trendWsPrefs();
save({type:'<x>',interval:'9q',layout:9,indexed:'yes',indicators:['nope','rsi','custom:zz'],compare:[{symbol:'../x'},{symbol:'MSFT',name:'M'.repeat(200)}],custom:[{id:'bad id',name:'a',expr:'close',pane:true,color:'#123456'},{id:'custom:ok',name:'ok',expr:'close',pane:false,color:'#123456'},{id:'custom:bad',name:'b',expr:'x'.repeat(999),pane:true,color:'#123456'}]});const junk=trendWsPrefs();
memory.set(TREND_WS_PREFS_KEY,'{not json');const broken=trendWsPrefs();save({interval:'5m',percent:true,indexed:true});const mixed=trendWsPrefs();
process.stdout.write(JSON.stringify({old,junk,broken,mixed}));
''', FIXTURE)
    assert out['old']['interval'] == 'W' and out['old']['percent'] is True and out['old']['indicators'] == ['ma20'] and out['old']['layout'] == 1
    junk = out['junk']
    assert junk['type'] == 'candle' and junk['interval'] == 'D' and junk['layout'] == 1 and junk['indexed'] is False
    assert junk['indicators'] == ['rsi'] and [row['id'] for row in junk['custom']] == ['custom:ok']
    assert [row['symbol'] for row in junk['compare']] == ['MSFT'] and len(junk['compare'][0]['name']) == 80
    assert out['broken']['interval'] == 'D'
    assert out['mixed']['interval'] == '5m' and out['mixed']['percent'] is True and out['mixed']['indexed'] is False


# ---- compare
def test_compare_starts_level_with_the_first_visible_row_and_carries_the_last_close(tmp_path):
    out = run(tmp_path, r'''
const rows=[['2026-01-05',100],['2026-01-06',110],['2026-01-07',121],['2026-01-08',133]].map(([session,close],i)=>({session,session_index:i,close}));
TREND_SYMBOL_DETAILS.set('MSFT',{bars:[{session:'2026-01-05',close:50},{session:'2026-01-07',close:60}]});TREND_SYMBOL_DETAILS.set('OLD',{bars:[{session:'2026-01-07',close:10}]});
const dateOf=row=>row.session,series=trendWsCompareSeries({compare:[{symbol:'MSFT',name:'M'},{symbol:'OLD',name:'O'},{symbol:'NONE',name:'N'}]},rows,1,4,dateOf);
process.stdout.write(JSON.stringify(series));
''', FIXTURE)
    assert len(out) == 2  # A symbol whose rows have not arrived is simply absent.
    assert out[0]['symbol'] == 'MSFT' and out[0]['scaled'][1] == pytest.approx(110)
    assert out[0]['scaled'][2] == pytest.approx(60 * 110 / 50) and out[0]['scaled'][3] == out[0]['scaled'][2]
    assert out[0]['change'] == pytest.approx(20)
    # A later listing starts at its own first row, never backfilled.
    assert out[1]['scaled'][:2] == [None, None] and out[1]['scaled'][2] == pytest.approx(121)


# ---- alerts
def test_alert_fires_once_on_a_real_cross_and_never_from_its_first_observation(tmp_path):
    out = run(tmp_path, r'''
const make=(id,price,dir,last)=>({id,asset:'sym:A',price,dir,active:true,last});
const rows=[make('up',100,'above',90),make('down',100,'below',110),make('any',100,'cross',90),make('fresh',100,'cross',undefined),make('wrong',100,'above',110)];rows.push({...make('other',100,'cross',90),asset:'sym:B'});
const first=trendWsAlertEvaluate(rows,'sym:A',105,'t1').map(row=>row.id),second=trendWsAlertEvaluate(rows,'sym:A',95,'t2').map(row=>row.id),third=trendWsAlertEvaluate(rows,'sym:A',105,'t3').map(row=>row.id);
trendWsAlertsSave(rows);memory.set(TREND_WS_ALERTS_KEY,JSON.stringify([...JSON.parse(memory.get(TREND_WS_ALERTS_KEY)),{id:'x',asset:'a',price:-1,dir:'cross'},{id:'y',asset:'a',price:1,dir:'sideways'},null]));
process.stdout.write(JSON.stringify({first,second,third,firedAt:rows[0].fired_at,other:rows.at(-1).active,kept:trendWsAlerts().map(row=>row.id)}));
''', FIXTURE)
    assert out['first'] == ['up', 'any']
    # 'wrong' sat above its level and only ever moved below it, so an upward-only alert stays quiet.
    assert out['second'] == ['down', 'fresh']
    assert out['firedAt'] == 't1' and out['other'] is True
    assert 'x' not in out['kept'] and 'y' not in out['kept']


def test_fresh_alert_with_price_above_level_ignores_a_rise_when_set_to_above(tmp_path):
    out = run(tmp_path, r'''
const rows=[{id:'a',asset:'A',price:100,dir:'above',active:true,last:110}];const hits=[105,120].map(price=>trendWsAlertEvaluate(rows,'A',price,'t').length);
process.stdout.write(JSON.stringify(hits));
''', FIXTURE)
    assert out == [0, 0]


# ---- intraday axis and anchors
INTRADAY = r'''
const sessionRows=[{index:10,session:'2026-11-03'},{index:11,session:'2026-11-04'}];
const raw=[['2026-11-02','09:30',1],['2026-11-03','09:30',2],['2026-11-03','09:35',3],['2026-11-03','09:40',4],['2026-11-04','09:30',5]].map(([session,time,close])=>({session,time,open:close,high:close,low:close,close,volume:1}));
const view=trendWsIntradayRows(raw,sessionRows);
'''


def test_intraday_rows_stay_inside_their_sessions_slot(tmp_path):
    out = run(tmp_path, INTRADAY + r'''
process.stdout.write(JSON.stringify({slot:view.slot,rows:view.rows.map(row=>[row.session,row.time,row.session_index,row.first,row.last]),found:trendWsRowAt(view.rows,view.rows[1].session_index),gap:trendWsRowAt(view.rows,10.45)}));
''', FIXTURE)
    assert out['slot'] == pytest.approx(1 / 3)
    # The unknown session is dropped, not squeezed onto another day.
    assert [row[0] for row in out['rows']] == ['2026-11-03'] * 3 + ['2026-11-04']
    centres = [row[2] for row in out['rows']]
    assert centres[1] == pytest.approx(10) and centres == sorted(centres)
    for session, time, centre, first, last in out['rows']:
        base = 10 if session == '2026-11-03' else 11
        assert base - .5 <= first < last <= base + .5 and first < centre < last
    assert out['found'] == 1 and out['gap'] == 2


def test_daily_records_are_unchanged_and_intraday_anchors_validate_strictly(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
state.tool='segment';trendManualChoose(state,at(1,100),sessions);trendManualChoose(state,at(5,200),sessions);const daily=structuredClone(state.lines[0]);
const base=trendManualRecord({...state,lines:[]},{session:'2026-10-02',price:100,t:-.2},{session:'2026-10-02',price:110,t:.3},true,'segment');
const check=record=>{try{trendManualValidateV2([record],'soxx');return true;}catch(e){return e.message;}};
const geometry=trendManualGeometry(base,detail,analysis,'linear',m);
const moved=trendManualMove(base,.5,0,sessions,'linear');
process.stdout.write(JSON.stringify({daily:daily.a,base,ok:check(base),big:check({...base,a:{...base.a,t:.7}}),extra:check({...base,a:{...base.a,x:1}}),reversed:check({...base,a:base.b,b:base.a}),same:(()=>{try{trendManualRecord({...state,lines:[]},{session:'2026-10-02',price:1},{session:'2026-10-02',price:2},true,'segment');return null;}catch(e){return e.message;}})(),anchors:[geometry.first_anchor.index,geometry.second_anchor.index],points:geometry.points.map(p=>p.index),moved:[moved.a,moved.b]}));
''', FIXTURE)
    assert out['daily'] == {'session': '2026-10-02', 'price': 100}
    assert out['ok'] is True
    assert out['big'] is not True and out['extra'] is not True and out['reversed'] is not True
    assert '서로 다른' in out['same']
    assert out['anchors'] == [pytest.approx(.8), pytest.approx(1.3)]
    assert out['points'] == [pytest.approx(.8), 1, pytest.approx(1.3)]
    assert out['moved'][0] == {'session': '2026-10-02', 'price': 100, 't': .3}
    assert out['moved'][1] == {'session': '2026-10-03', 'price': 110, 't': -.2}


def test_pointer_on_an_intraday_chart_lands_on_the_bar_not_the_day(tmp_path):
    out = run(tmp_path, r'''
const bars2=Array.from({length:3},(_,i)=>({session:'2026-10-0'+(i+1),session_index:i,open:100,high:110,low:90,close:100}));
const detail2={asset_id:'soxx',bars:bars2,gaps:[]},analysis2={lines:[],projection_sessions:[]};
const rows=trendWsIntradayRows([1,2,3,4].map(k=>({session:'2026-10-02',time:'09:3'+k,open:100+k,high:101+k,low:99+k,close:100+k,volume:1})),trendManualSessions(detail2,analysis2)).rows;
const model={analysis:analysis2,wsAll:rows,wsIntraday:true,first:.5,end:1.5,W:1000,H:500,L:0,R:0,T:0,B:0,ticks:[0,1000],x:i=>(i-.5)*1000,y:p=>500-p*.5};
const pointer=(k,price,snap)=>trendManualPoint(model,detail2,model.x(rows[k].session_index)+3,model.y(price),'linear',snap);
process.stdout.write(JSON.stringify({free:pointer(0,500,'off'),last:pointer(3,500,'off'),snapped:pointer(1,102.1,'strong'),expected:rows.map(row=>row.session_index-1)}));
''', FIXTURE)
    assert out['free']['session'] == '2026-10-02' and out['free']['t'] == pytest.approx(out['expected'][0], abs=1e-5)
    assert out['last']['t'] == pytest.approx(out['expected'][3], abs=1e-5)
    assert out['snapped']['price'] in (101, 102, 103)


# ---- drawing shapes
@pytest.mark.parametrize('tool,shape,single', [('cross', 'cross', True), ('ellipse', 'ellipse', False), ('pricerange', 'pricerange', False), ('daterange', 'daterange', False), ('box', 'box', False), ('fibtime', 'fibtime', False), ('fibfan', 'fibfan', False), ('regression', 'regression', False)])
def test_more_tools_stay_two_anchor_records(tmp_path, tool, shape, single):
    out = run(tmp_path, SESSIONS + 'state.tool=' + repr(tool) + ';const single=' + ('true' if single else 'false') + r''';
if(!single)trendManualChoose(state,at(1,100),sessions);trendManualChoose(state,at(5,200),sessions);
const drawn=state.lines[0],line=trendManualGeometry(drawn,detail,analysis,'linear',m),html=trendManualShapeSvg(m,line,true);
const box=Object.keys(TREND_TOOL_ACTIONS).find(key=>TREND_TOOL_ACTIONS[key]===state.tool||TREND_TOOL_ACTIONS[key]===__NAME__);
process.stdout.write(JSON.stringify({shape:drawn.shape,valid:trendManualValidateV2(state.lines,'soxx').length,box,nan:html.includes('NaN')||html.includes('undefined'),length:html.length,handles:(html.match(/data-trend-manual-handle/g)||[]).length,hit:(()=>{const xa=m.x(line.first_anchor.index),xb=m.x(line.second_anchor.index),ya=m.y(line.first_anchor.price),yb=m.y(line.second_anchor.price),name=__NAME__,target=name==='ellipse'?[(xa+xb)/2,(ya+yb)/2]:name==='regression'?[xa,m.y(trendManualRegression(m,line).start(0))]:[xa,ya];return trendManualShapeHit(m,line,target[0],target[1],6);})()}));
'''.replace('__NAME__', repr(tool)), FIXTURE)
    assert out['shape'] == shape and out['valid'] == 1 and out['box'] and not out['nan'] and out['length'] > 60
    assert out['handles'] == (1 if single else 2)
    assert out['hit'] is True


def test_regression_channel_fits_closes_exactly_on_a_straight_series(tmp_path):
    out = run(tmp_path, r'''
const rows=Array.from({length:20},(_,i)=>({session_index:i,close:100+2*i}));
const fit=trendManualRegression({wsAll:rows},{axis:'linear',first_anchor:{index:5},second_anchor:{index:15}});
const none=trendManualRegression({wsAll:rows},{axis:'linear',first_anchor:{index:5.1},second_anchor:{index:5.2}});
process.stdout.write(JSON.stringify({start:fit.start(0),end:fit.end(0),deviation:fit.deviation,band:fit.end(2)-fit.end(0),none}));
''', FIXTURE)
    assert out['start'] == pytest.approx(110) and out['end'] == pytest.approx(130)
    assert out['deviation'] == pytest.approx(0, abs=1e-9) and out['band'] == pytest.approx(0, abs=1e-9)
    assert out['none'] is None


def test_fib_fan_passes_through_its_levels_at_the_second_anchor(tmp_path):
    out = run(tmp_path, r'''
const model={W:1000,R:0,x:i=>i*100,y:p=>1000-p};
const rows=trendManualFibFan(model,{axis:'linear',first_anchor:{index:1,price:100},second_anchor:{index:3,price:200}});
process.stdout.write(JSON.stringify(rows.map(row=>[row.level,row.price,row.near.x,row.x])));
''', FIXTURE)
    assert [row[0] for row in out] == [0, .25, .382, .5, .618, .75, 1]
    assert out[3][1] == pytest.approx(150) and out[6][1] == pytest.approx(200)
    assert all(row[2] == 300 and row[3] == 1000 for row in out)


def test_frame_offers_every_interval_type_tool_and_range(tmp_path):
    out = run(tmp_path, r'''
const ws={context:{family:null},family:null,hideAuto:false,panelOpen:true,helpOpen:false,assetMenu:false,confirmClose:false,assetId:'soxx',pendingAsset:null,menu:'type'};
const type=trendWorkspaceFrame({asset_id:'soxx'},{label:'SOXX'},'linear',ws);ws.menu='intraday';const minute=trendWorkspaceFrame({asset_id:'soxx'},{label:'SOXX'},'linear',ws);
ws.replay={cut:3,speed:2,timer:null};
process.stdout.write(JSON.stringify({types:TREND_WS_TYPES.filter(([key])=>!type.includes('data-trend-ws-set="type:'+key+'"')),minutes:TREND_WS_INTRADAY.filter(([key])=>!minute.includes('data-trend-ws-set="interval:'+key+'"')),tabs:['lines','watch','alerts','data'].filter(key=>!type.includes('data-trend-ws-tab-button="'+key+'"')),actions:['menu:compare','alerts','replay','invert','indexed','menu:layout','menu:tools'].filter(key=>!type.includes('data-trend-ws-action="'+key+'"')),ranges:TREND_RANGE_PRESETS.map(row=>row[0]),bar:trendWorkspaceReplayBar(ws).includes('aria-pressed="true"')}));
''', FIXTURE)
    assert out['types'] == [] and out['minutes'] == [] and out['tabs'] == [] and out['actions'] == []
    assert out['ranges'] == ['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', '전체']
    assert out['bar'] is True


# ---- local service and parsing
def intraday_chart(symbol='TSLA', rows=None, **meta):
    start = int(datetime(2026, 11, 4, 14, 30, tzinfo=timezone.utc).timestamp())
    rows = rows if rows is not None else [(start + i * 300, 100 + i) for i in range(5)]
    return {'chart': {'result': [{'meta': {'symbol': symbol, 'exchangeTimezoneName': 'America/New_York', **meta},
                                  'timestamp': [row[0] for row in rows],
                                  'indicators': {'quote': [{'open': [row[1] for row in rows], 'high': [row[1] + 1 for row in rows],
                                                            'low': [row[1] - 1 for row in rows], 'close': [row[1] for row in rows],
                                                            'volume': [10 for _ in rows]}]}}]}}


NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_intraday_rows_carry_exchange_time_and_drop_the_forming_bar():
    start = int(datetime(2026, 11, 4, 14, 30, tzinfo=timezone.utc).timestamp())
    body = Y.parse_intraday(intraday_chart(), 'TSLA', '5m', now=datetime.fromtimestamp(start + 1250, timezone.utc))
    assert body['contract_id'] == 'chart_symbol_intraday_v1' and body['interval'] == '5m'
    # Four bars have closed; 09:50 ends after the clock and is left out.
    assert [row['time'] for row in body['bars']] == ['09:30', '09:35', '09:40', '09:45'] and body['forming_rows'] == 1
    assert body['bars'][0]['session'] == '2026-11-04' and body['timezone'] == 'America/New_York'


def test_intraday_drops_the_closing_tick_on_every_day():
    def at(day, hour, minute):
        return int(datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc).timestamp())
    rows = [(at(3, 20, 55), 100), (at(3, 21, 0), 101), (at(4, 14, 30), 102), (at(4, 21, 0), 103)]
    period = {'regular': {'start': at(5, 14, 30), 'end': at(5, 21, 0)}}
    body = Y.parse_intraday(intraday_chart(rows=rows, currentTradingPeriod=period), 'TSLA', '5m', now=NOW)
    assert [(row['session'], row['time']) for row in body['bars']] == [('2026-11-03', '15:55'), ('2026-11-04', '09:30')]
    assert body['closing_rows'] == 2


def test_round_the_clock_markets_keep_their_last_minutes():
    def at(day, hour, minute):
        return int(datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc).timestamp())
    rows = [(at(4, 23, 55), 100), (at(5, 0, 0), 101)]
    period = {'regular': {'start': at(5, 0, 0), 'end': at(5, 23, 59)}}
    body = Y.parse_intraday(intraday_chart(rows=rows, currentTradingPeriod=period, exchangeTimezoneName='UTC'), 'TSLA', '5m', now=NOW)
    assert len(body['bars']) == 2 and body['closing_rows'] == 0


def test_four_hour_bars_merge_within_a_session_only():
    def at(day, hour):
        return int(datetime(2026, 11, day, hour, 30, tzinfo=timezone.utc).timestamp())
    rows = [(at(3, h), 100 + h) for h in range(14, 21)] + [(at(4, h), 200 + h) for h in range(14, 16)]
    body = Y.parse_intraday(intraday_chart(rows=rows), 'TSLA', '4h', now=NOW)
    assert [(row['session'], row['time']) for row in body['bars']] == [('2026-11-03', '09:30'), ('2026-11-03', '13:30'), ('2026-11-04', '09:30')]
    first = body['bars'][0]
    assert (first['open'], first['close'], first['high'], first['low'], first['volume']) == (114, 117, 118, 113, 40)


def test_broken_intraday_rows_are_counted_not_repaired():
    chart = intraday_chart()
    chart['chart']['result'][0]['indicators']['quote'][0]['close'][1] = None
    body = Y.parse_intraday(chart, 'TSLA', '5m', now=NOW)
    assert len(body['bars']) == 4 and body['dropped_rows'] == 1


@pytest.mark.parametrize('request_text', ['TSLA', 'TSLA@', 'TSLA@2m', 'TSLA@1d', '../x@5m', '@5m', 'TS LA@5m'])
def test_intraday_request_needs_a_valid_symbol_and_a_listed_interval(request_text):
    def forbidden(url):
        raise AssertionError('no request should leave: ' + url)
    with pytest.raises(Y.SymbolLookupError):
        Y.SymbolLookup(fetch=forbidden).intraday(request_text)


def test_intraday_and_quote_urls_are_fixed_and_cached():
    seen = []

    def fetch(url):
        seen.append(url)
        if 'range=1d' in url:
            return {'chart': {'result': [{'meta': {'symbol': 'TSLA', 'regularMarketPrice': 5.5, 'regularMarketTime': 1_800_000_000, 'chartPreviousClose': 5, 'currency': 'USD'}}]}}
        return intraday_chart()
    lookup = Y.SymbolLookup(fetch=fetch)
    assert lookup.intraday('tsla@4h')['interval'] == '4h'
    lookup.intraday('TSLA@4h')
    quote = lookup.quote('TSLA')
    lookup.quote('tsla')
    assert quote['price'] == 5.5 and quote['previous_close'] == 5 and quote['as_of'].endswith('Z')
    assert len(seen) == 2 and all(url.startswith(Y.YAHOO_CHART + 'TSLA?') for url in seen)
    assert 'interval=60m' in seen[0] and 'range=730d' in seen[0]


def test_quote_without_a_price_is_refused():
    with pytest.raises(Y.SymbolLookupError):
        Y.parse_quote({'chart': {'result': [{'meta': {'symbol': 'TSLA', 'regularMarketPrice': None}}]}}, 'TSLA')
    with pytest.raises(Y.SymbolLookupError):
        Y.parse_quote({'chart': {'result': [{'meta': {'symbol': 'OTHER', 'regularMarketPrice': 1, 'regularMarketTime': 1}}]}}, 'TSLA')


@pytest.fixture
def quote_server():
    def fetch(url):
        if 'range=1d' in url:
            return {'chart': {'result': [{'meta': {'symbol': 'TSLA', 'regularMarketPrice': 5.5, 'regularMarketTime': 1_800_000_000}}]}}
        return intraday_chart()
    http = L.make_http_server(StubService(), port=0, symbols=Y.SymbolLookup(fetch=fetch))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield http
    http.shutdown()
    thread.join(5)
    http.server_close()


def test_service_answers_intraday_and_quote_only_to_trusted_origins(quote_server):
    with get(quote_server, '/api/private-trendlines/symbol-intraday/' + segment('TSLA@5m'), Origin=L.TRUSTED_ORIGIN) as response:
        assert json.loads(response.read())['interval'] == '5m'
        assert response.headers['Access-Control-Allow-Origin'] == L.TRUSTED_ORIGIN
    with get(quote_server, '/api/private-trendlines/symbol-quote/' + segment('^TSLA'.replace('^', ''))) as response:
        assert json.loads(response.read())['price'] == 5.5
    for path in ('symbol-intraday/' + segment('TSLA@9h'), 'symbol-quote/' + segment('../x')):
        with pytest.raises(HTTPError):
            get(quote_server, '/api/private-trendlines/' + path)
    with pytest.raises(HTTPError) as refused:
        get(quote_server, '/api/private-trendlines/symbol-quote/' + segment('TSLA'), Origin='https://evil.example')
    assert refused.value.code == 403


def test_lookup_module_writes_nothing_durable():
    source = Path(Y.__file__).read_text(encoding='utf-8')
    assert 'sqlite' not in source and 'write_text' not in source and 'open(' not in source.replace('urlopen(', '')
