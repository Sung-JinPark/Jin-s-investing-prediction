"""Personal drawings use declared sessions and never alter automatic geometry."""
import pytest

from test_trendlines_ui import run as _run

def run(tmp_path, program, extra=""):
    return _run(tmp_path, "(async()=>{\n" + extra + "\n" + program + "\n})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});", STORE)



STORE = r"""
// A transactional asynchronous IndexedDB fixture; writes publish only on commit.
const docs=new Map();let failStorage=false;
globalThis.indexedDB={open(){const request={};setImmediate(()=>{if(failStorage){request.error=new Error('quota unavailable');request.onerror?.();return;}request.result={close(){},transaction(_name,mode){let pending=0,aborted=false,done=false;const staged=new Map(docs),tx={error:null,abort(){aborted=true;this.error=new Error('aborted');setImmediate(()=>this.onabort?.());},objectStore(){const make=(work)=>{pending++;const req={};setImmediate(()=>{if(aborted)return;try{req.result=work();req.onsuccess?.();}catch(error){tx.error=error;tx.abort();}pending--;finish();});return req;};return {get:key=>make(()=>staged.get(key)),getAll:()=>make(()=>[...staged.values()]),put:value=>make(()=>staged.set(value.key,structuredClone(value)))};}};const finish=()=>{if(!pending&&!aborted&&!done){done=true;if(mode==='readwrite'){docs.clear();for(const [k,v] of staged)docs.set(k,v);}setImmediate(()=>tx.oncomplete?.());}};setImmediate(finish);return tx;}};request.onsuccess?.();});return request;}};
"""

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
m.lines=[{...personal,line_id:'automatic',intercept:101,points:personal.points.map(p=>({...p,price:p.price+1}))}];delete m.lines[0].manual;
const selected=trendHoverAt(m,m.x(4),m.y(176)).line.line_id;
m.manualState.selected=null;
const closest=trendHoverAt(m,m.x(4),m.y(176)).line.line_id;
process.stdout.write(JSON.stringify({selected,closest}));
''', FIXTURE)
    assert result == {'selected': 'manual-test', 'closest': 'automatic'}


def test_selected_personal_hover_remains_accessible_near_intraday_marker(tmp_path):
    result = run(tmp_path, r'''
const personal=trendManualGeometry(record,detail,analysis,'linear',m);
m.manualLines=[personal];m.manualState={selected:record.id};m.quote={session_index:4,price:176};
const selected=trendHoverAt(m,m.x(4),m.y(175)).kind;
m.manualState.selected=null;
const ordinary=trendHoverAt(m,m.x(4),m.y(175)).kind;
process.stdout.write(JSON.stringify({selected,ordinary}));
''', FIXTURE)
    assert result == {'selected': 'line', 'ordinary': 'quote'}


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
const state=trendManualState('soxx');await state.loading;const point={session:'2026-10-02',price:100};
state.mode=true;trendManualChoose(state,point);point.price=999;
const firstPrice=state.first.price;
trendManualChoose(state,{session:'2026-10-06',price:200});
const saved=structuredClone(state.lines),other=trendManualState('sk-hynix').lines;
trendManualApply(state,[]);trendManualUndo(state);await trendManualSave(state);
TREND_MANUAL_STATES.delete('soxx');const next=trendManualState('soxx');await next.loading;const reloaded=next.lines;
process.stdout.write(JSON.stringify({firstPrice,saved,other,reloaded,unrelated:memory.get('unrelated'),keys:[...memory.keys()]}));
''', FIXTURE)
    assert result['firstPrice'] == 100
    assert result['saved'] == result['reloaded']
    assert result['other'] == []
    assert result['unrelated'] == 'keep'
    assert set(result['keys']) == {'unrelated'}


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
failStorage=true;const state=trendManualState('soxx');await state.loading;trendManualApply(state,[record],record.id);await trendManualSave(state);
process.stdout.write(JSON.stringify({lines:state.lines,message:state.message}));
''', FIXTURE)
    assert len(result['lines']) == 1
    assert '저장 실패' in result['message']


def test_offscreen_first_anchor_keeps_second_handle_identity(tmp_path):
    result = run(tmp_path, r'''
m.first=3;m.manualDetail=detail;m.manualLines=[trendManualGeometry(record,detail,analysis,'linear',m)];
const svg=trendManualSvg(m,{selected:record.id,mode:false});
process.stdout.write(JSON.stringify({second:svg.includes('data-trend-manual-handle="1"'),first:svg.includes('data-trend-manual-handle="0"')}));
''', FIXTURE)
    assert result == {'second': True, 'first': False}


POINTER_HOST = r'''
const events={},buttons=['draw','snap','delete','undo','clear'].map(action=>({dataset:{trendManualAction:action},setAttribute(){}}));
const formEvents={},editorEvents={},layer={innerHTML:''},select={innerHTML:'',value:''},status={},editor={addEventListener:(k,v)=>editorEvents[k]=v},form={addEventListener:(k,v)=>formEvents[k]=v,contains:()=>false,elements:Object.fromEntries(['name','note','a_session','a_price','b_session','b_price','extension','color','opacity','width','dash','arrow','labels','stats'].map(k=>[k,{}]))};
globalThis.document={activeElement:null};
const svg={ownerDocument:{createElementNS(){}},classList:{toggle(){}},focus(){},addEventListener:(k,v)=>events[k]=v,getBoundingClientRect:()=>({left:0,top:0,width:1000,height:500})};
const host={isConnected:true,querySelector:s=>s==='svg'?svg:({'[data-trend-manual-layer]':layer,'[data-trend-manual-select]':select,'[data-trend-manual-status]':status,'[data-trend-manual-editor]':editor,'[data-trend-manual-form]':form})[s],querySelectorAll:()=>buttons};
m.manualDetail=detail;m.manualState=trendManualState('soxx');await m.manualState.loading;m.manualLines=[];
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


def test_unsubmitted_editor_input_survives_refresh_without_mutating_saved_line(tmp_path):
    result = run(tmp_path, r'''
trendManualApply(m.manualState,[record],record.id);
editor.open=true;editorEvents.toggle();
form.elements.a_price.value='123.456';form.elements.b_session.value='2026-10-04';formEvents.input();
bindTrendManual(host,detail,m,{currency:'USD',price_unit:'USD_per_share'},'linear');
const restored={open:editor.open,price:form.elements.a_price.value,date:form.elements.b_session.value};
const dirty=m.manualState.saveStatus==='dirty'&&status.textContent.includes('입력 변경');
const saved=structuredClone(m.manualState.lines[0]);
trendManualApply(m.manualState,[record],record.id);
process.stdout.write(JSON.stringify({restored,saved,draft:m.manualState.editDraft,dirty}));
''', FIXTURE + POINTER_HOST)
    assert result['restored'] == {'open': True, 'price': '123.456', 'date': '2026-10-04'}
    assert result['saved']['a']['price'] == 100
    assert result['saved']['b']['session'] == '2026-10-06'
    assert result['draft'] is None and result['dirty']

@pytest.mark.parametrize('creation_axis', ['linear', 'log'])
@pytest.mark.parametrize('display_axis', ['linear', 'log'])
@pytest.mark.parametrize('extension', ['none', 'left', 'right', 'both'])
def test_fixed_equation_survives_axis_switch_and_all_extensions(tmp_path, creation_axis, display_axis, extension):
    out = run(tmp_path, r'''
const row={...trendManualUpgrade(record),axis:CREATE,extension:EXTEND,extend:['right','both'].includes(EXTEND)};
const line=trendManualGeometry(row,detail,analysis,DISPLAY,m);
process.stdout.write(JSON.stringify({price:trendLinePrice(line,4,DISPLAY),axis:line.axis,indices:line.points.map(p=>p.index),source:record}));
'''.replace('CREATE', repr(creation_axis)).replace('DISPLAY', repr(display_axis)).replace('EXTEND', repr(extension)), FIXTURE)
    assert out['axis'] == creation_axis
    assert out['price'] == pytest.approx(175 if creation_axis == 'linear' else 100 * 2 ** .75, rel=1e-12)
    assert min(out['indices']) == (0 if extension in ('left', 'both') else 1)
    assert max(out['indices']) == (9 if extension in ('right', 'both') else 5)


def test_explicit_save_separates_draft_and_keeps_legacy_bytes(tmp_path):
    out = run(tmp_path, r'''
const raw=JSON.stringify({schema_version:1,asset_id:'soxx',lines:[record]});memory.set(TREND_MANUAL_STORAGE_PREFIX+'soxx',raw);
const state=trendManualState('soxx');await state.loading;state.view.scale='log';trendManualApply(state,[{...state.lines[0],name:'changed'}],record.id);
await new Promise(resolve=>setTimeout(resolve,550));
const before={confirmed:docs.has('asset:soxx'),draft:docs.get('draft:soxx:'+TREND_MANUAL_TAB),status:state.saveStatus};
await trendManualSave(state);const saved=docs.get('asset:soxx');const history=state.undo.length;
TREND_MANUAL_STATES.delete('soxx');const reloaded=trendManualState('soxx');await reloaded.loading;
process.stdout.write(JSON.stringify({before,saved,history,reloaded:reloaded.lines,legacyUnchanged:memory.get(TREND_MANUAL_STORAGE_PREFIX+'soxx')===raw}));
''', FIXTURE)
    assert not out['before']['confirmed'] and out['before']['status'] == 'dirty'
    assert out['before']['draft']['lines'][0]['axis'] == 'legacy'
    assert out['saved']['lines'][0]['axis'] == 'log'
    assert out['saved']['lines'] == out['reloaded'] and out['legacyUnchanged'] and out['history'] == 1


def test_failed_or_incomplete_save_never_replaces_confirmed(tmp_path):
    out = run(tmp_path, r'''
const state=trendManualState('soxx');await state.loading;trendManualApply(state,[record],record.id);await trendManualSave(state);
const original=JSON.stringify(docs.get('asset:soxx'));state.mode=true;const incomplete=await trendManualSave(state);state.mode=false;
const invalid=await trendManualSave(state,()=>false);TREND_WORKSPACE_OPEN=null;failStorage=true;trendManualApply(state,[{...state.lines[0],note:'new'}],record.id);const failed=await trendManualSave(state);
process.stdout.write(JSON.stringify({incomplete,invalid,failed,unchanged:original===JSON.stringify(docs.get('asset:soxx')),status:state.saveStatus,note:state.lines[0].note}));
''', FIXTURE)
    assert not out['incomplete'] and not out['invalid'] and not out['failed']
    assert out['unchanged'] and out['status'] == 'failed' and out['note'] == 'new'


def test_two_tabs_revision_conflict_is_atomic_with_templates(tmp_path):
    out = run(tmp_path, r'''
const state=trendManualState('soxx');await state.loading;trendManualApply(state,[record],record.id);await trendManualSave(state);
const first=docs.get('asset:soxx');
await trendWorkspaceCommit('soxx',{...first,lines:[{...first.lines[0],name:'other tab'}]},1);
state.lines[0].name='my edit';const ok=await trendManualSave(state);
const template={revision:0,items:[],default_id:null};await trendWorkspaceWrite('templates',template,0);
let conflict=false;try{await trendWorkspaceCommit('soxx',{...first,lines:[]},2,template);}catch(error){conflict=error.conflict;}
process.stdout.write(JSON.stringify({ok,conflict,stateConflict:state.conflict,myEdit:state.lines[0].name,savedName:docs.get('asset:soxx').lines[0].name,revision:docs.get('asset:soxx').revision}));
''', FIXTURE)
    assert not out['ok'] and out['conflict'] and out['stateConflict']
    assert out['myEdit'] == 'my edit' and out['savedName'] == 'other tab' and out['revision'] == 2


def test_draft_restore_and_saved_restore_both_undoable(tmp_path):
    out = run(tmp_path, r'''
let state=trendManualState('soxx');await state.loading;trendManualApply(state,[record],record.id);await trendManualSave(state);
trendManualApply(state,[{...state.lines[0],name:'unsaved'}],record.id);await new Promise(resolve=>setTimeout(resolve,550));
TREND_MANUAL_STATES.delete('soxx');state=trendManualState('soxx');await state.loading;
const initial=state.lines[0].name,pending=state.recovery.lines[0].name;trendManualRestore(state,state.recovery);const recovered=state.lines[0].name;
trendManualRestore(state,state.confirmed);const reverted=state.lines[0].name;trendManualUndo(state);const undone=state.lines[0].name;trendManualUndo(state,true);
process.stdout.write(JSON.stringify({initial,pending,recovered,reverted,undone,redone:state.lines[0].name}));
''', FIXTURE)
    assert out == {'initial': '내 빗각선 1', 'pending': 'unsaved', 'recovered': 'unsaved', 'reverted': '내 빗각선 1', 'undone': 'unsaved', 'redone': '내 빗각선 1'}


def test_hundred_step_history_and_delete_fallback_never_deletes_old_saved(tmp_path):
    out = run(tmp_path, r'''
const state=trendManualState('soxx');await state.loading;trendManualApply(state,[record],record.id);await trendManualSave(state);
for(let i=0;i<105;i++)trendManualApply(state,[{...state.lines[0],note:String(i)}],record.id);
const depth=state.undo.length;for(let i=0;i<100;i++)trendManualUndo(state);const earliest=state.lines[0].note;
for(let i=0;i<100;i++)trendManualUndo(state,true);state.selected=null;state.selection=[];trendManualDelete(state);const oldRemains=state.lines.length===1;
const fresh=trendManualRecord(state,{session:'2026-10-03',price:140},{session:'2026-10-07',price:160});trendManualApply(state,[...state.lines,fresh]);state.created.push(fresh.id);trendManualDelete(state);
process.stdout.write(JSON.stringify({depth,earliest,oldRemains,ids:state.lines.map(l=>l.id),note:state.lines[0].note}));
''', FIXTURE)
    assert out == {'depth': 100, 'earliest': '4', 'oldRemains': True, 'ids': ['manual-test'], 'note': '104'}


def test_locked_batch_is_rejected_without_partial_mutation(tmp_path):
    out = run(tmp_path, r'''
const state=trendManualState('soxx');await state.loading;const a=trendManualUpgrade(record),b={...a,id:'manual-other',number:2,locked:true};trendManualApply(state,[a,b],null,true);state.selection=[a.id,b.id];
const before=JSON.stringify(state.lines),errors=[];for(const fn of [()=>trendManualDelete(state),()=>trendManualClone(state,state.lines),()=>trendManualMove(b,1,1,trendManualSessions(detail,analysis),'linear')]){try{fn();}catch(e){errors.push(e.message);}}
process.stdout.write(JSON.stringify({unchanged:before===JSON.stringify(state.lines),errors}));
''', FIXTURE)
    assert out['unchanged'] and len(out['errors']) == 3


@pytest.mark.parametrize('axis', ['linear', 'log'])
def test_parallel_move_preserves_equation_slope_and_rejects_missing_session(tmp_path, axis):
    out = run(tmp_path, r'''
const row={...trendManualUpgrade(record),axis:AXIS},sessions=trendManualSessions(detail,analysis),moved=trendManualMove(row,1,AXIS==='log'?Math.log(1.1):10,sessions,'linear');
const old=trendManualGeometry(row,detail,analysis,'log',m),next=trendManualGeometry(moved,detail,analysis,'linear',m);
let rejected=false;try{trendManualMove(row,1,1,sessions.filter(s=>s.index!==6),'linear');}catch(_){rejected=true;}
process.stdout.write(JSON.stringify({slopeOld:old.slope,slopeNext:next.slope,moved,rejected}));
'''.replace('AXIS', repr(axis)), FIXTURE)
    assert out['slopeNext'] == pytest.approx(out['slopeOld'], rel=1e-12)
    assert out['moved']['a']['price'] == pytest.approx(110)
    assert out['moved']['b']['price'] == pytest.approx(220 if axis == 'log' else 210)
    assert out['rejected']


@pytest.mark.parametrize('fault', ['unit', 'asset', 'version', 'extra', 'count', 'style', 'date', 'duplicate', 'templates'])
def test_backup_is_strict_and_does_not_clip_or_migrate_silently(tmp_path, fault):
    out = run(tmp_path, r'''
const state=trendManualState('soxx');await state.loading;trendManualApply(state,[record],record.id);
const backup={schema_version:2,contract_id:'trendlines_personal_backup_v2',exported_at:new Date().toISOString(),assets:TREND_VISIBLE_ASSETS.map(([id])=>({...trendManualPayload(state),asset_id:id,unit:TREND_PRIVATE_IDENTITIES[id][4]})),templates:TREND_TEMPLATE_STATE};
const valid=trendManualBackupCheck(backup),fault=FAULT;
if(fault==='unit')backup.assets[0].unit='USD_per_share';if(fault==='asset')backup.assets[0].asset_id='mag7';if(fault==='version')backup.schema_version=1;
if(fault==='extra')backup.assets[0].lines[0].approved=true;if(fault==='count')backup.assets[0].lines=Array.from({length:21},(_,i)=>({...backup.assets[0].lines[0],id:'manual-'+i,number:i+1}));
if(fault==='style')backup.assets[0].lines[0].style.color='url(javascript:test)';if(fault==='date')backup.assets[0].lines[0].a.session='2026-02-30';if(fault==='duplicate')backup.assets[0]=backup.assets[1];if(fault==='templates')backup.templates.items=[{id:'template-a',name:'x',style:{...TREND_MANUAL_STYLE},a:record.a}];
let rejected=false;try{trendManualBackupCheck(backup);}catch(_){rejected=true;}process.stdout.write(JSON.stringify({valid:valid.assets.length,rejected,unchanged:state.lines.length===1}));
'''.replace('FAULT', repr(fault)), FIXTURE)
    assert out == {'valid': 10, 'rejected': True, 'unchanged': True}


def test_author_stroke_and_strong_magnet_are_not_hover_dependent(tmp_path):
    out = run(tmp_path, r'''
m.manualDetail=detail;const row={...trendManualUpgrade(record),style:{...TREND_MANUAL_STYLE,width:3.2,dash:'dot',opacity:.5,color:'#123456',arrow:'both'}};m.manualLines=[trendManualGeometry(row,detail,analysis,'linear',m)];
const svg=trendManualSvg(m,{selection:[row.id],selected:row.id,mode:false}),strong=trendManualPoint(m,detail,m.x(3),m.y(200),'linear','strong'),off=trendManualPoint(m,detail,m.x(3),m.y(200),'linear','off');
process.stdout.write(JSON.stringify({svg,strong,off}));
''', FIXTURE)
    assert 'stroke-width="3.2"' in out['svg'] and 'stroke-dasharray="1 4"' in out['svg'] and 'marker-start=' in out['svg']
    assert out['strong']['price'] == 130 and out['off']['price'] == pytest.approx(200)


def test_keyboard_delete_input_priority_and_multi_clone_redo(tmp_path):
    out = run(tmp_path, r'''
buttons[0].onclick();click(1,100);click(5,200);
const key=(key,extra={})=>trendManualKeyboard({key,target:{closest:()=>null},preventDefault(){},stopImmediatePropagation(){},...extra});
key('Delete',{target:{closest:()=>({tagName:'INPUT'})}});const inputPreserved=m.manualState.lines.length===1;
key('c',{ctrlKey:true});key('v',{ctrlKey:true});const cloned=m.manualState.lines.length===2;
key('Delete');const deleted=m.manualState.lines.length===1;key('z',{ctrlKey:true});const restored=m.manualState.lines.length===2;key('z',{ctrlKey:true,shiftKey:true});
process.stdout.write(JSON.stringify({inputPreserved,cloned,deleted,restored,redone:m.manualState.lines.length===1}));
''', FIXTURE + POINTER_HOST)
    assert all(out.values())


def test_ctrl_click_adds_and_toggles_without_double_selection(tmp_path):
    out = run(tmp_path, r'''
const first={...trendManualUpgrade(record),b:{...record.b,price:140}},second={...first,id:'manual-other',number:2,a:{...record.a,price:150},b:{...record.b,price:180}};
trendManualApply(m.manualState,[first,second],first.id);
click(3,165,{ctrlKey:true});const both=[...m.manualState.selection].sort();click(3,165,{ctrlKey:true});
process.stdout.write(JSON.stringify({both,remaining:m.manualState.selection}));
''', FIXTURE + POINTER_HOST)
    assert out['both'] == ['manual-other', 'manual-test']
    assert out['remaining'] == ['manual-test']


def test_whole_line_drag_and_ctrl_drag_clone_commit_once(tmp_path):
    out = run(tmp_path, r'''
const flat={...trendManualUpgrade(record),b:{...record.b,price:100}};trendManualApply(m.manualState,[flat],flat.id);const before=m.manualState.undo.length;
events.pointerdown(event(3,100));events.pointermove(event(4,110));events.pointerup(event(4,110));const moved=structuredClone(m.manualState.lines[0]),depth=m.manualState.undo.length-before;
events.pointerdown(event(4,110,{ctrlKey:true}));events.pointermove(event(5,120,{ctrlKey:true}));events.pointerup(event(5,120,{ctrlKey:true}));
process.stdout.write(JSON.stringify({moved,depth,lines:m.manualState.lines}));
''', FIXTURE + POINTER_HOST)
    assert out['moved']['a'] == {'session': '2026-10-03', 'price': 110}
    assert out['moved']['b'] == {'session': '2026-10-07', 'price': 110}
    assert out['depth'] == 1 and len(out['lines']) == 2
    assert out['lines'][0] == out['moved']
    assert out['lines'][1]['a']['price'] == 120


def test_resize_redraw_preserves_modal_return_focus_on_expand_button(tmp_path):
    out = run(tmp_path, r'''
const state=trendManualState('soxx');await state.loading;let focused=0;
const trigger={dataset:{trendTool:'expand'},focus(){focused++;},closest:()=>null};globalThis.document={activeElement:trigger};
const host={contains:()=>true,clientWidth:1000,querySelector:s=>s==='[data-trend-tool="expand"]'?trigger:null,querySelectorAll:()=>[],innerHTML:''};
trendPlotModel=()=>({...m});bindTrendChart=()=>{};bindTrendManual=()=>{};
drawTrendInteractiveChart(host,detail,analysis,bars,{currency:'USD',label:'SOXX'},'linear','representative',{factor:1,offset:0});
process.stdout.write(JSON.stringify({focused,containsSvg:host.innerHTML.includes('<svg')}));
''', FIXTURE)
    assert out == {'focused': 1, 'containsSvg': True}


def test_creation_uses_the_active_chart_axis_with_a_different_saved_view(tmp_path):
    out = run(tmp_path, r'''
m.manualState.view.scale='log';buttons[0].onclick();click(1,100);click(5,200);
process.stdout.write(JSON.stringify({axis:m.manualState.lines[0].axis}));
''', FIXTURE + POINTER_HOST)
    assert out['axis'] == 'linear'


def test_passive_history_growth_keeps_both_saved_dates_and_waits_for_full_series(tmp_path):
    out = run(tmp_path, r'''
const state=trendManualState('soxx');await state.loading;
const history=Array.from({length:100},(_,i)=>({...bars[0],session:new Date(Date.UTC(2025,0,1+i)).toISOString().slice(0,10),session_index:i}));
const wanted={start:history[20].session,end:history[44].session,factor:4,tail:false};state.view.window=structuredClone(wanted);
const host={contains:()=>false,clientWidth:1000,querySelector:()=>null,querySelectorAll:()=>[],innerHTML:''};globalThis.document={activeElement:null};trendPlotModel=(_detail,_analysis,visible)=>({...m,bars:visible});bindTrendChart=()=>{};bindTrendManual=()=>{};
const view={factor:4,offset:null};drawTrendInteractiveChart(host,detail,analysis,history.slice(50),{currency:'USD',label:'SOXX'},'linear','representative',view);const pending=structuredClone(state.view.window);
drawTrendInteractiveChart(host,detail,analysis,history,{currency:'USD',label:'SOXX'},'linear','representative',view);const loaded=structuredClone(state.view.window),count=trendZoomViewport(history,view).length;
const longer=[...history,...Array.from({length:10},(_,i)=>({...history.at(-1),session:new Date(Date.UTC(2025,0,101+i)).toISOString().slice(0,10),session_index:100+i}))];
drawTrendInteractiveChart(host,detail,analysis,longer,{currency:'USD',label:'SOXX'},'linear','representative',view);
process.stdout.write(JSON.stringify({wanted,pending,loaded,current:state.view.window,count,nextCount:trendZoomViewport(longer,view).length}));
''', FIXTURE)
    assert out['pending'] == out['loaded'] == out['current'] == out['wanted']
    assert out['count'] == out['nextCount'] == 25
