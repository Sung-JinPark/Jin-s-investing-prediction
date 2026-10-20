"""Personal drawings use declared sessions and never alter automatic geometry."""
import pytest

from test_trendlines_ui import run


FIXTURE = r'''
const bars=Array.from({length:8},(_,i)=>({session:'2026-10-'+String(i+1).padStart(2,'0'),session_index:i,open:110+i*5,high:115+i*5,low:105+i*5,close:112+i*5}));
const detail={asset_id:'soxx',bars,gaps:[]},analysis={axis:'linear',projection_sessions:[{index:8,session:'2026-10-09'},{index:9,session:'2026-10-12'}],lines:[]};
const m={analysis,bars,gaps:[],lines:[],first:0,last:7,sourceLast:7,end:9,W:1000,H:500,L:80,R:20,T:20,B:40,ticks:[50,100,150,200,250],x:i=>80+i*100,y:p=>460-(p-50)*2.2,critical:true};
const record={id:'manual-test',number:1,a:{session:'2026-10-02',price:100},b:{session:'2026-10-06',price:200},extend:true};
const memory=new Map([['unrelated','keep']]);globalThis.localStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)};
'''


@pytest.mark.parametrize('axis', ['linear', 'log'])
def test_equation_and_hover_are_independent_of_automatic_lines(tmp_path, axis):
    result = run(tmp_path, r'''
const axis=AXIS;analysis.axis=axis;
const original=JSON.stringify({detail,analysis,lines:m.lines,ticks:m.ticks});
const line=trendManualGeometry(record,detail,analysis,axis,m);
m.manualLines=[line];
const price=trendLinePrice(line,4,axis),hit=trendHoverAt(m,m.x(4),m.y(price),{scale:axis});
const future=trendHoverAt(m,m.x(8),m.y(trendLinePrice(line,8,axis)),{scale:axis});
process.stdout.write(JSON.stringify({a:trendLinePrice(line,1,axis),b:trendLinePrice(line,5,axis),price,hit,future,unchanged:original===JSON.stringify({detail,analysis,lines:m.lines,ticks:m.ticks})}));
'''.replace('AXIS', repr(axis)), FIXTURE)
    assert result['a'] == pytest.approx(100)
    assert result['b'] == pytest.approx(200)
    assert result['price'] == pytest.approx(175 if axis == 'linear' else 100 * 2 ** .75)
    assert result['hit']['kind'] == 'line'
    assert result['hit']['row']['close'] == 132
    # The line may leave the visible Y range: do not inflate the chart to fit it.
    assert result['future'] is None
    assert result['unchanged']


def test_future_hover_is_an_extension_without_future_ohlc(tmp_path):
    result = run(tmp_path, r'''
const flat={...record,b:{...record.b,price:100}};
m.manualLines=[trendManualGeometry(flat,detail,analysis,'linear',m)];
process.stdout.write(JSON.stringify(trendHoverAt(m,m.x(8),m.y(100),{scale:'linear'})));
''', FIXTURE)
    assert result['kind'] == 'line'
    assert result['future'] is True
    assert result['row']['close'] is None
    assert result['row']['session'] == '2026-10-09'


def test_selected_personal_line_wins_nearby_overlap_within_hit_tolerance(tmp_path):
    result = run(tmp_path, r'''
const personal=trendManualGeometry(record,detail,analysis,'linear',m);
m.manualLines=[personal];m.manualState={selected:record.id};
m.lines=[{...personal,manual:false,line_id:'automatic',intercept:101,points:personal.points.map(p=>({...p,price:p.price+1}))}];
const selected=trendHoverAt(m,m.x(4),m.y(176)).line.line_id;
m.manualState.selected=null;
const closest=trendHoverAt(m,m.x(4),m.y(176)).line.line_id;
process.stdout.write(JSON.stringify({selected,closest}));
''', FIXTURE)
    assert result == {'selected': 'manual-test', 'closest': 'automatic'}


def test_date_anchors_rebase_but_never_snap_to_missing_sessions(tmp_path):
    result = run(tmp_path, r'''
const original=trendManualGeometry(record,detail,analysis,'linear',m);
const rebased=structuredClone(detail);rebased.bars.forEach(b=>b.session_index+=100);
const next={...analysis,projection_sessions:analysis.projection_sessions.map(p=>({...p,index:p.index+100}))};
const moved=trendManualGeometry(record,rebased,next,'linear',{...m,first:100,end:109,last:107,sourceLast:107});
rebased.bars=rebased.bars.filter(b=>b.session!==record.a.session);
const missing=trendManualGeometry(record,rebased,next,'linear',{...m,first:100,end:109});
process.stdout.write(JSON.stringify({old:trendLinePrice(original,7,'linear'),current:trendLinePrice(moved,107,'linear'),missing}));
''', FIXTURE)
    assert result['old'] == result['current'] == 250
    assert result['missing'] is None


def test_only_supplied_sessions_and_valid_prices_can_be_drawn(tmp_path):
    result = run(tmp_path, r'''
detail.gaps=[{session:'2026-10-09',session_index:8,reason:'source_null_ohlc_no_fill'}];
const sessions=trendManualSessions(detail,analysis),valid=trendManualPoint(m,detail,m.x(9),m.y(160),'linear',false);
const gap=trendManualPoint(m,detail,m.x(8),m.y(160),'linear',false),outside=trendManualPoint(m,detail,0,m.y(160),'linear');
const weekend={...record,a:{session:'2026-10-10',price:150},b:{session:'2026-10-12',price:160}};
const absent=trendManualGeometry(weekend,detail,analysis,'linear',m);
const bad=[0,-1,Infinity,NaN,1e16].map(price=>{try{trendManualValidate({schema_version:1,asset_id:'soxx',lines:[{...record,a:{...record.a,price}}]},'soxx');return false;}catch(_){return true;}});
process.stdout.write(JSON.stringify({sessions,valid,gap,outside,absent,bad}));
''', FIXTURE)
    assert len(result['sessions']) == 9
    assert result['valid']['session'] == '2026-10-12'
    assert result['valid']['price'] == pytest.approx(160)
    assert result['gap'] is result['outside'] is result['absent'] is None
    assert all(result['bad'])


@pytest.mark.parametrize('axis', ['linear', 'log'])
def test_inverse_price_and_magnet_use_screen_pixel_distance(tmp_path, axis):
    result = run(tmp_path, r'''
const axis=AXIS;if(axis==='log')m.y=p=>460-(Math.log(p)-Math.log(50))/(Math.log(250)-Math.log(50))*440;
const price=133.123,y=m.y(price),inverse=trendManualPriceAt(m,y,axis);
const near=trendManualPoint(m,detail,m.x(3),m.y(bars[3].low)+10,axis,true,1,.5);
const far=trendManualPoint(m,detail,m.x(3),m.y(bars[3].low)+100,axis,true,1,.5);
process.stdout.write(JSON.stringify({inverse,near,far}));
'''.replace('AXIS', repr(axis)), FIXTURE)
    assert result['inverse'] == pytest.approx(133.123, rel=1e-12)
    assert result['near']['price'] == 120
    assert result['far']['price'] != 120


def test_personal_storage_undo_reload_and_asset_isolation(tmp_path):
    result = run(tmp_path, r'''
const state=trendManualState('soxx'),point={session:'2026-10-02',price:100};
state.mode=true;trendManualChoose(state,point);point.price=999;
const firstPrice=state.first.price;
trendManualChoose(state,{session:'2026-10-06',price:200});
const saved=structuredClone(state.lines),other=trendManualState('sk-hynix').lines;
trendManualApply(state,[]);trendManualUndo(state);
TREND_MANUAL_STATES.delete('soxx');const reloaded=trendManualState('soxx').lines;
process.stdout.write(JSON.stringify({firstPrice,saved,other,reloaded,unrelated:memory.get('unrelated'),keys:[...memory.keys()]}));
''', FIXTURE)
    assert result['firstPrice'] == 100
    assert result['saved'] == result['reloaded']
    assert result['other'] == []
    assert result['unrelated'] == 'keep'
    assert set(result['keys']) == {'unrelated', 'jins-trendlines-drawings-v1:soxx'}


@pytest.mark.parametrize('corruption', ['extra_key', 'wrong_asset', 'duplicate_id', 'invalid_date', 'too_many'])
def test_invalid_storage_is_reported_and_not_overwritten(tmp_path, corruption):
    result = run(tmp_path, r'''
const value={schema_version:1,asset_id:'soxx',lines:[record]},kind=KIND;
if(kind==='extra_key')value.lines[0].source_approved=true;
if(kind==='wrong_asset')value.asset_id='bitcoin';
if(kind==='duplicate_id')value.lines.push({...record,number:2});
if(kind==='invalid_date')value.lines[0].a.session='2026-02-30';
if(kind==='too_many')value.lines=Array.from({length:21},(_,i)=>({...record,id:'manual-'+i,number:i+1}));
const raw=JSON.stringify(value);memory.set(TREND_MANUAL_STORAGE_PREFIX+'soxx',raw);
const state=trendManualState('soxx');process.stdout.write(JSON.stringify({count:state.lines.length,message:state.message,preserved:raw===memory.get(TREND_MANUAL_STORAGE_PREFIX+'soxx')}));
'''.replace('KIND', repr(corruption)), FIXTURE)
    assert result['count'] == 0
    assert result['message']
    assert result['preserved']


def test_blocked_storage_keeps_edit_in_memory_with_message(tmp_path):
    result = run(tmp_path, r'''
globalThis.localStorage={getItem:()=>null,setItem:()=>{throw new Error('blocked');}};
const state=trendManualState('soxx');trendManualApply(state,[record],record.id);
process.stdout.write(JSON.stringify({lines:state.lines,message:state.message}));
''', FIXTURE)
    assert len(result['lines']) == 1
    assert '이 화면에서만' in result['message']


def test_offscreen_first_anchor_keeps_second_handle_identity(tmp_path):
    result = run(tmp_path, r'''
m.first=3;m.manualDetail=detail;m.manualLines=[trendManualGeometry(record,detail,analysis,'linear',m)];
const svg=trendManualSvg(m,{selected:record.id,mode:false});
process.stdout.write(JSON.stringify({second:svg.includes('data-trend-manual-handle="1"'),first:svg.includes('data-trend-manual-handle="0"')}));
''', FIXTURE)
    assert result == {'second': True, 'first': False}


POINTER_HOST = r'''
const events={},buttons=['draw','snap','delete','undo','clear'].map(action=>({dataset:{trendManualAction:action},setAttribute(){}}));
const layer={innerHTML:''},select={innerHTML:'',value:''},status={},editor={},form={contains:()=>false,elements:Object.fromEntries(['a_session','a_price','b_session','b_price','extend'].map(k=>[k,{}]))};
globalThis.document={activeElement:null};
const svg={ownerDocument:{createElementNS(){}},classList:{toggle(){}},focus(){},addEventListener:(k,v)=>events[k]=v,getBoundingClientRect:()=>({left:0,top:0,width:1000,height:500})};
const host={isConnected:true,querySelector:s=>s==='svg'?svg:({'[data-trend-manual-layer]':layer,'[data-trend-manual-select]':select,'[data-trend-manual-status]':status,'[data-trend-manual-editor]':editor,'[data-trend-manual-form]':form})[s],querySelectorAll:()=>buttons};
m.manualDetail=detail;m.manualState=trendManualState('soxx');m.manualLines=[];
bindTrendManual(host,detail,m,{currency:'USD',price_unit:'USD_per_share'},'linear');
const event=(index,price,extra={})=>({button:0,pointerType:'mouse',pointerId:1,clientX:m.x(index),clientY:m.y(price),preventDefault(){},stopPropagation(){},...extra});
const click=(index,price,extra={})=>{events.pointerdown(event(index,price,extra));events.pointerup(event(index,price,extra));};
'''


def test_mouse_touch_cancel_and_drag_commit_use_final_pointer_position(tmp_path):
    result = run(tmp_path, r'''
buttons[0].onclick();click(1,100);click(5,200);
const created=structuredClone(m.manualState.lines[0]);
click(5,200.1);
const stationaryPreserved=JSON.stringify(created)===JSON.stringify(m.manualState.lines[0]);
events.pointerdown(event(5,200));events.pointermove(event(6,210));events.pointerup(event(0,210,{clientX:0}));
const cancelled=JSON.stringify(created)===JSON.stringify(m.manualState.lines[0]);
events.pointerdown(event(5,200));events.pointerup(event(6,220));
const edited=structuredClone(m.manualState.lines[0]);
buttons[0].onclick();events.pointerdown(event(2,150,{pointerType:'touch'}));events.pointercancel({});
const noTouchCommit=m.manualState.lines.length===1;
click(2,150,{pointerType:'touch'});click(4,170,{pointerType:'touch'});
process.stdout.write(JSON.stringify({created,stationaryPreserved,cancelled,edited,noTouchCommit,count:m.manualState.lines.length}));
''', FIXTURE + POINTER_HOST)
    assert result['created']['a'] == {'session': '2026-10-02', 'price': 100}
    assert result['stationaryPreserved']
    assert result['cancelled']
    assert result['edited']['b']['session'] == '2026-10-07'
    assert result['edited']['b']['price'] == pytest.approx(220)
    assert result['noTouchCommit']
    assert result['count'] == 2


def test_keyboard_drawing_preserves_first_anchor_and_escape_cancels(tmp_path):
    result = run(tmp_path, r'''
buttons[0].onclick();const key=key=>events.keydown({key,preventDefault(){},stopPropagation(){}});
key('Home');key('Enter');key('ArrowUp');key('ArrowRight');key('Enter');
const line=structuredClone(m.manualState.lines[0]);
buttons[0].onclick();key('Enter');key('Escape');
process.stdout.write(JSON.stringify({line,count:m.manualState.lines.length,mode:m.manualState.mode,first:m.manualState.first}));
''', FIXTURE + POINTER_HOST)
    assert result['line']['a'] == {'session': '2026-10-01', 'price': 112}
    assert result['line']['b']['session'] == '2026-10-02'
    assert result['count'] == 1
    assert result['mode'] is False
    assert result['first'] is None
