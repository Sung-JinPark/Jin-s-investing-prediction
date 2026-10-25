"""TradingView-style workspace: tools stay two-anchor records, previews never draw."""
import math
from pathlib import Path

import pytest

from test_trendlines_manual_ui import FIXTURE, POINTER_HOST, run


SESSIONS = r'''
const state=trendManualState('soxx');await state.loading;state.drawingScale='linear';
const sessions=trendManualSessions(detail,analysis),at=(i,price)=>({session:sessions[i].session,price});
'''


def test_horizontal_tools_store_one_price_on_neighbouring_sessions(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
state.tool='horizontal';trendManualChoose(state,at(2,120),sessions);const horizontal=structuredClone(state.lines[0]);
state.tool='hray';trendManualChoose(state,at(sessions.length-1,130),sessions);const ray=structuredClone(state.lines[1]);
process.stdout.write(JSON.stringify({horizontal,ray,valid:trendManualValidateV2(state.lines,'soxx').length}));
''', FIXTURE)
    assert out['horizontal']['a'] == {'session': '2026-10-03', 'price': 120}
    assert out['horizontal']['b'] == {'session': '2026-10-04', 'price': 120}
    assert out['horizontal']['extension'] == 'both' and out['horizontal']['name'] == '수평선 1'
    # The last declared session has no successor: its predecessor anchors the ray.
    assert out['ray']['a'] == {'session': '2026-10-09', 'price': 130}
    assert out['ray']['b'] == {'session': '2026-10-12', 'price': 130}
    assert out['ray']['extension'] == 'right' and out['ray']['extend'] is True
    assert out['valid'] == 2


@pytest.mark.parametrize('tool,extension,name', [('ray', 'right', '내 빗각선 1'), ('segment', 'none', '추세선 1'), ('extended', 'both', '연장선 1')])
def test_two_point_tools_differ_only_by_extension_and_name(tmp_path, tool, extension, name):
    out = run(tmp_path, SESSIONS + 'state.tool=' + repr(tool) + r''';
trendManualChoose(state,at(1,100),sessions);const waiting=state.lines.length;trendManualChoose(state,at(5,200),sessions);
process.stdout.write(JSON.stringify({waiting,line:state.lines[0],selection:state.selection}));
''', FIXTURE)
    assert out['waiting'] == 0
    assert out['line']['a'] == {'session': '2026-10-02', 'price': 100}
    assert out['line']['b'] == {'session': '2026-10-06', 'price': 200}
    assert out['line']['extension'] == extension and out['line']['name'] == name
    assert out['selection'] == [out['line']['id']]


@pytest.mark.parametrize('axis', ['linear', 'log'])
def test_channel_parallel_passes_through_third_point_on_creation_axis(tmp_path, axis):
    out = run(tmp_path, SESSIONS + 'state.drawingScale=' + repr(axis) + r''';state.tool='channel';
trendManualChoose(state,at(1,100),sessions);trendManualChoose(state,at(5,200),sessions);const pending=state.lines.length;
trendManualChoose(state,at(3,180),sessions);
const [base,parallel]=state.lines,line=trendManualGeometry(parallel,detail,analysis,AXIS,m);
process.stdout.write(JSON.stringify({pending,base,parallel,through:trendLinePrice(line,3,AXIS),selection:state.selection}));
'''.replace('AXIS', repr(axis)), FIXTURE)
    assert out['pending'] == 0
    assert out['base']['name'] == '채널 1 · 기준선' and out['parallel']['name'] == '채널 1 · 평행선'
    assert out['base']['number'] == 1 and out['parallel']['number'] == 2
    assert out['base']['axis'] == out['parallel']['axis'] == axis
    assert out['parallel']['a']['session'] == out['base']['a']['session'] and out['parallel']['b']['session'] == out['base']['b']['session']
    assert out['through'] == pytest.approx(180)
    if axis == 'linear':
        assert out['parallel']['a']['price'] == pytest.approx(130) and out['parallel']['b']['price'] == pytest.approx(230)
    else:
        ratio = 180 / (100 * 2 ** .5)
        assert out['parallel']['a']['price'] == pytest.approx(100 * ratio) and out['parallel']['b']['price'] == pytest.approx(200 * ratio)
    assert out['selection'] == [out['base']['id'], out['parallel']['id']]


def test_channel_needs_two_free_slots_and_leaves_lines_unchanged(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const filler=Array.from({length:19},(_,i)=>({...trendManualUpgrade({...record,id:'manual-fill-'+i,number:i+1}),axis:'linear'}));trendManualApply(state,filler);
state.tool='channel';trendManualChoose(state,at(1,100),sessions);trendManualChoose(state,at(5,200),sessions);trendManualChoose(state,at(3,180),sessions);
process.stdout.write(JSON.stringify({count:state.lines.length,message:state.message}));
''', FIXTURE)
    assert out['count'] == 19 and '20개' in out['message']


def test_measurement_is_transient_and_never_enters_the_saved_document(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
state.tool='measure';state.mode=true;trendManualChoose(state,at(1,100),sessions);trendManualChoose(state,at(4,150),sessions);
const svg=trendManualSvg({...m,manualLines:[],manualDetail:detail},state);
process.stdout.write(JSON.stringify({measure:state.measure,lines:state.lines.length,status:state.saveStatus,mode:state.mode,payload:trendManualPayload(state),drawn:svg.includes('data-trend-measure'),label:svg.includes('+50 (+50.00%)')&&svg.includes('3봉 · 3일')}));
''', FIXTURE)
    assert out['measure'] == {'a': {'session': '2026-10-02', 'price': 100}, 'b': {'session': '2026-10-05', 'price': 150}}
    assert out['lines'] == 0 and out['status'] != 'dirty' and out['mode'] is False
    assert 'measure' not in out['payload'] and out['payload']['lines'] == []
    assert out['drawn'] and out['label']


def test_shift_levels_the_second_point_and_shift_drag_measures(tmp_path):
    out = run(tmp_path, r'''
buttons[0].onclick();click(1,100);click(5,200,{shiftKey:true});const levelled=structuredClone(m.manualState.lines[0]);
events.pointerdown(event(2,130,{shiftKey:true}));events.pointermove(event(4,170));events.pointerup(event(4,170));
process.stdout.write(JSON.stringify({levelled,count:m.manualState.lines.length,measure:m.manualState.measure,mode:m.manualState.mode}));
''', FIXTURE + POINTER_HOST)
    assert out['levelled']['a']['price'] == 100 and out['levelled']['b']['price'] == 100
    assert out['count'] == 1
    assert out['measure']['a']['session'] == '2026-10-03' and out['measure']['b']['session'] == '2026-10-05'
    assert out['mode'] is False


def test_press_then_drag_draws_and_cancel_drops_the_pressed_anchor(tmp_path):
    out = run(tmp_path, r'''
buttons[0].onclick();events.pointerdown(event(1,100));events.pointermove(event(5,200));events.pointerup(event(5,200));
const dragged=structuredClone(m.manualState.lines[0]);
buttons[0].onclick();events.pointerdown(event(2,120));events.pointercancel({});
process.stdout.write(JSON.stringify({dragged,first:m.manualState.first,count:m.manualState.lines.length}));
''', FIXTURE + POINTER_HOST)
    assert out['dragged']['a'] == {'session': '2026-10-02', 'price': 100}
    assert out['dragged']['b']['session'] == '2026-10-06'
    assert out['first'] is None and out['count'] == 1


def test_older_companion_status_is_accepted_and_missing_asset_asks_for_update(tmp_path):
    out = run(tmp_path, r'''
const row=asset_id=>({asset_id,status:'ready',stale:false,last_success:null,last_attempt:null,source_asof:null,next_refresh_kst:null,observation_through:'2026-10-21',reason:null,error:null});
const older={schema_version:1,contract_id:'trendlines_local_status_v1',publication_scope:'private_only',running:true,refresh_in_progress:false,next_refresh_kst:null,assets:['sk-hynix','soxx','nasdaq','sp500','bitcoin','dow','mag7'].map(row)};
const current={...older,assets:TREND_ASSETS.map(([id])=>row(id))};let missing=null;
try{validateTrendLocalStatus(older,'kospi');}catch(error){missing=error.message;}
process.stdout.write(JSON.stringify({older:validateTrendLocalStatus(older,'sk-hynix').asset_id,current:validateTrendLocalStatus(current,'kospi').asset_id,missing}));
''', FIXTURE)
    assert out['older'] == 'sk-hynix' and out['current'] == 'kospi'
    assert '최신 버전' in out['missing']


def test_legacy_six_asset_backup_still_imports(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const doc=id=>({schema_version:2,asset_id:id,unit:TREND_PRIVATE_IDENTITIES[id][4],lines:[],view:{family:'all',scope:'all',scale:'linear',window:null,priceStep:1,snap:'weak',continuous:false}});
const backup=ids=>({schema_version:2,contract_id:'trendlines_personal_backup_v2',exported_at:new Date().toISOString(),assets:ids.map(doc),templates:{revision:0,items:[],default_id:null}});
const legacy=trendManualBackupCheck(backup(['sk-hynix','soxx','nasdaq','sp500','bitcoin','dow'])).assets.length,full=trendManualBackupCheck(backup(TREND_VISIBLE_ASSETS.map(([id])=>id))).assets.length;
let hidden=false;try{trendManualBackupCheck(backup(['mag7']));}catch(_){hidden=true;}
process.stdout.write(JSON.stringify({legacy,full,hidden}));
''', FIXTURE)
    assert out == {'legacy': 6, 'full': 10, 'hidden': True}


def test_right_axis_frame_and_round_ticks(tmp_path):
    out = run(tmp_path, r'''
const wide=trendPlotFrame(1200,{axis:'right',height:700},460,1546258),index=trendPlotFrame(1200,{axis:'right',height:700},460,2601.36),page=trendPlotFrame(1200,null,460,1546258);
const model=(scale,low,high)=>({scale,H:700,T:10,B:26,ticks:[low,high]});
process.stdout.write(JSON.stringify({wide,index,page,linear:trendNiceTicks(model('linear',1375691,1546258)),narrowLog:trendNiceTicks(model('log',1375691,1546258)),wideLog:trendNiceTicks(model('log',90,12000)),kospi:trendPrice(2601.356,{currency:'KRW',price_unit:'index_points'}),share:trendPrice(1294000,{currency:'KRW',price_unit:'KRW_per_share'}),tag:trendAxisPrice(2601.356,{price_unit:'index_points'})}));
''', FIXTURE)
    assert out['wide']['axisRight'] and out['wide']['H'] == 700 and out['wide']['R'] >= 70 and out['wide']['L'] < 10
    assert 54 <= out['index']['R'] < out['wide']['R'] + 10
    assert out['page'] == {'W': 1200, 'H': 460, 'L': 88, 'R': 20, 'T': 24, 'B': 46, 'axisRight': False}
    assert out['linear'] and all(value % 20000 == 0 for value in out['linear'])
    assert out['narrowLog'] and all(value % 20000 == 0 for value in out['narrowLog'])
    assert 1000 in out['wideLog'] and all(90 <= value <= 12000 for value in out['wideLog'])
    assert out['kospi'] == '2,601.36 pt' and out['share'] == '1,294,000원' and out['tag'] == '2,601.36'


def test_workspace_markup_carries_every_editor_hook_and_preview_keeps_one_entry(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const ws={context:{family:'all'},family:'all',hideAuto:false,panelOpen:true,helpOpen:true,assetMenu:true,confirmClose:false,assetId:'soxx',pendingAsset:null};
const frame=trendWorkspaceFrame({asset_id:'soxx'},{label:'SOXX'},'linear',ws),preview=trendPreviewBar({asset_id:'soxx'});
const hooks=['data-trend-manual-select','data-trend-manual-status','data-trend-manual-editor','data-trend-manual-form','data-trend-manual-list','data-trend-save-state','data-trend-recovery','data-trend-more','data-trend-import','data-trend-ws-span','data-trend-ws-goto'];
process.stdout.write(JSON.stringify({missing:hooks.filter(hook=>!frame.includes(hook)),tools:Object.keys(TREND_TOOL_ACTIONS).filter(action=>!frame.includes('data-trend-manual-action="'+action+'"')),ranges:TREND_RANGE_PRESETS.every(([label])=>frame.includes('data-trend-range="'+label+'"')),menu:TREND_VISIBLE_ASSETS.every(([id])=>frame.includes('data-trend-ws-asset="'+id+'"')),help:frame.includes('Alt+H'),preview,legacyToolbar:preview.includes('data-trend-manual-action')}));
''', FIXTURE)
    assert out['missing'] == []
    assert out['tools'] == [] and out['ranges'] and out['menu'] and out['help']
    assert 'data-trend-tool="expand"' in out['preview'] and not out['legacyToolbar']


@pytest.fixture(scope='module')
def workspace_browser():
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(channel='chrome', headless=True)
        except playwright.Error as error:
            pytest.skip(f'installed Chrome not available: {error}')
        yield browser
        browser.close()


@pytest.mark.parametrize('ending', ['up', 'cancel', 'lostcapture', 'blur', 'dispose'])
def test_workspace_mouse_pan_suppresses_selection_and_always_releases(workspace_browser, ending):
    """Run the real pan handlers and CSS; isolate chart data, rendering and storage."""
    parts = Path(__file__).parents[1] / 'ai_fc/dashboard_parts'
    source = (parts / 'trendlines.js').read_text(encoding='utf-8')
    drawing = source[source.index('function drawTrendWorkspace('):source.index('function trendWorkspaceSnapshot(')]
    css = (parts / 'trendlines.css').read_text(encoding='utf-8')
    program = r'''
const manual={ready:true,mode:false,lines:[],selection:[],saveStatus:'saved'},state={factor:2,offset:100,heldCount:100,yRange:null};
const baseBars=Array.from({length:200},(_,i)=>({session:'2026-'+String(i).padStart(3,'0'),close:100+i})),bars=baseBars.slice(100);
const detail={asset_id:'soxx',bars:baseBars},analysis={lines:[]},asset={label:'SOXX'},ws={context:{family:null},family:null,panelOpen:false};
const before=JSON.stringify({baseBars,analysis,manual}),TREND_ZOOM={ws},TREND_RANGE_PRESETS=[];
const trendManualState=()=>manual,trendManualGeometry=()=>null;
const trendPlotModel=()=>({W:1000,H:500,L:50,R:60,T:20,B:40,range:[50,150]});
const trendWorkspaceFrame=()=>'<header class="trend-ws-top"><p>SOXX chart toolbar</p><input id="editable" value="line name"></header><div class="trend-ws-main"><nav class="trend-ws-tools"></nav><div class="trend-ws-stage" data-trend-ws-stage></div></div><footer class="trend-ws-bottom">Chart dates and price labels</footer>';
const trendWorkspaceLegend=()=>'',trendWorkspaceSelectionBar=()=>'';
const trendSvg=()=>'<svg data-trend-plot viewBox="0 0 1000 500" tabindex="0"><text x="100" y="100">SOXX selectable price labels and chart history</text><text x="100" y="130">2026-10-22  100  200  300</text></svg>';
const bindTrendWorkspaceChart=()=>{},bindTrendManual=()=>{},drawTrendInteractiveChart=()=>{};
''' + drawing + r'''
const host=document.querySelector('[data-trend-zoom-chart]');
drawTrendWorkspace(host,detail,analysis,baseBars,bars,asset,'linear','workspace',state,ws,10);
host.addEventListener('pointerdown',event=>{window.lastPointer=event.pointerId;});
window.inspect=()=>({offset:state.offset,cursor:getComputedStyle(host.querySelector('svg')).cursor,selection:getSelection().toString(),
  active:host.hasAttribute('data-trend-gesture'),captured:host.hasPointerCapture(window.lastPointer||1),
  unchanged:before===JSON.stringify({baseBars,analysis,manual})});
'''
    page = workspace_browser.new_page(viewport={'width': 1280, 'height': 900})
    try:
        page.set_content('<style>' + css + '</style><div class="trend-ws" style="width:1100px;height:700px"><div class="trend-ws-host" data-trend-zoom-chart></div></div><p>Outside chart text</p><script>' + program + '</script>')
        svg = page.locator('svg[data-trend-plot]')
        box = svg.bounding_box()
        assert box and box['width'] > 500 and box['height'] > 200
        x, y = box['x'] + box['width'] * .2, box['y'] + box['height'] * .2
        page.mouse.move(x, y)
        assert page.evaluate('inspect().cursor') == 'grab'
        page.mouse.down()
        page.mouse.move(x + 90, y, steps=6)
        dragging = page.evaluate('inspect()')
        assert dragging['offset'] < 100 and dragging['cursor'] == 'grabbing'
        assert dragging['active'] and dragging['captured'] and dragging['selection'] == ''
        if ending == 'up':
            page.mouse.up()
        elif ending == 'cancel':
            page.evaluate("document.querySelector('[data-trend-zoom-chart]').dispatchEvent(new PointerEvent('pointercancel',{bubbles:true,pointerId:lastPointer}))")
        elif ending == 'lostcapture':
            page.evaluate("document.querySelector('[data-trend-zoom-chart]').releasePointerCapture(lastPointer)")
            # Chrome processes the pending capture change with the next pointer event.
            page.mouse.move(x + 90, y)
        elif ending == 'blur':
            page.evaluate("window.dispatchEvent(new Event('blur'))")
        else:
            page.evaluate("document.querySelector('[data-trend-zoom-chart]')._trendWsDisposeNavigation()")
        page.wait_for_function('!inspect().active')
        released = page.evaluate('inspect()')
        assert released['cursor'] == 'grab' and not released['captured']
        page.mouse.move(x + 130, y, steps=2)
        assert page.evaluate('inspect().offset') == released['offset'], 'released gestures must not keep panning'
        page.mouse.up()
        assert page.evaluate('inspect().unchanged'), 'panning must not edit source bars, automatic lines or drawings'
        page.locator('#editable').fill('editable line name')
        page.locator('#editable').press('Control+a')
        assert page.locator('#editable').evaluate('node=>node.selectionStart===0&&node.selectionEnd===node.value.length')
        svg.evaluate("node=>node.classList.add('trend-manual-drawing')")
        assert svg.evaluate('node=>getComputedStyle(node).cursor') == 'crosshair'
    finally:
        page.close()


@pytest.fixture
def workspace_chart(workspace_browser, request):
    """Use production viewport/model/redraw code, isolating editor UI and storage."""
    parts = Path(__file__).parents[1] / 'ai_fc/dashboard_parts'
    source = (parts / 'trendlines.js').read_text(encoding='utf-8')
    helpers = source[source.index('const TREND_ASSETS='):source.index('globalThis.TrendlineUI=')]
    css = (parts / 'trendlines.css').read_text(encoding='utf-8')
    program = 'const esc=value=>String(value??\'\');\n' + helpers + r'''
const manual={ready:true,mode:false,lines:[],selection:[],saveStatus:'saved',view:{window:null}};
const baseBars=Array.from({length:500},(_,i)=>({session:new Date(Date.UTC(2024,0,i+1)).toISOString().slice(0,10),session_index:i,open:90+i*.4,close:92+i*.4,low:85+i*.4,high:100+i*.4}));
const analysis={lines:[],projection_sessions:[]},detail={asset_id:'soxx',bars:baseBars},asset={label:'SOXX'};
let state={},ws={context:{family:null},family:null,panelOpen:false},host=document.querySelector('[data-trend-zoom-chart]');
const original=JSON.stringify({baseBars,analysis,manual});let axis='linear',frames=new Map(),nextFrame=0;
window.requestAnimationFrame=callback=>{const id=++nextFrame;frames.set(id,callback);return id;};
window.cancelAnimationFrame=id=>frames.delete(id);
window.flushFrames=()=>{while(frames.size){const pending=[...frames.values()];frames.clear();pending.forEach(callback=>callback(0));}};
const el=markup=>{const template=document.createElement('template');template.innerHTML=markup;return template.content.firstElementChild;};
trendManualState=()=>manual;
trendWorkspaceFrame=()=>'<header class="trend-ws-top"><input id="editable" value="line name"></header><div class="trend-ws-main"><nav class="trend-ws-tools"><button data-trend-tool="in">+</button><button data-trend-tool="out">−</button><button data-trend-tool="left">←</button><button data-trend-tool="right">→</button></nav><div class="trend-ws-stage" data-trend-ws-stage></div></div><footer class="trend-ws-bottom">Chart dates and price labels</footer>';
trendWorkspaceLegend=()=>'';trendWorkspaceSelectionBar=()=>'';
bindTrendWorkspaceChart=()=>{};bindTrendManual=()=>{};
TREND_ZOOM={ws};
window.resetChart=(scale='linear',initial={})=>{
  axis=scale;frames.clear();host._trendWsFrameRequest=0;
  for(const key of Object.keys(state))delete state[key];
  Object.assign(state,{factor:4,offset:150,heldCount:125,yRange:null,maxFactor:8},initial);
  drawTrendInteractiveChart(host,detail,analysis,baseBars,asset,axis,'workspace',state,()=>{},ws);
};
window.openFullWorkspace=(scale='linear')=>{
  TREND_ZOOM=null;axis=scale;
  ws=openTrendWorkspace({assetId:'soxx',asset,scale,family:null,initialBars:baseBars.slice(150,275),build:()=>({source:detail,analysis})});
  host=TREND_ZOOM.host;state=ws.state;
  host._trendManual={state:manual,busy:()=>manual.mode};
};
window.inspectChart=()=>{
  const {m,bars}=host._trendNavigation;
  return {factor:state.factor,x:state.xRange?.slice()||[m.first,m.end],y:(state.yRange||m.range).slice(),first:m.first,end:m.end,
    bars:bars.map(bar=>bar.session_index),plotHeight:(m.H-m.T-m.B)/m.H*host.querySelector('svg').getBoundingClientRect().height,
    finite:[m.first,m.end,...m.range,...(state.xRange||[]),...(state.yRange||[])].every(Number.isFinite),
    unchanged:original===JSON.stringify({baseBars,analysis,manual}),cursor:getComputedStyle(host.querySelector('svg')).cursor,
    selection:getSelection().toString(),active:host.hasAttribute('data-trend-gesture'),pending:frames.size,
    disabled:Object.fromEntries([...host.querySelectorAll('[data-trend-tool]')].map(button=>[button.dataset.trendTool,button.disabled]))};
};
window.chartPoint=(rx,ry,priceAxis=false)=>{
  const {m}=host._trendNavigation,box=host.querySelector('svg').getBoundingClientRect();
  const x=priceAxis?m.W-m.R/2:m.L+rx*(m.W-m.L-m.R),y=m.T+ry*(m.H-m.T-m.B);
  return {x:box.left+x/m.W*box.width,y:box.top+y/m.H*box.height};
};
window.anchorAt=(rx,ry)=>{
  const {m}=host._trendNavigation,t=m.range[1]-ry*(m.range[1]-m.range[0]);
  return {...chartPoint(rx,ry),index:m.first+rx*(m.end-m.first),price:axis==='log'?Math.exp(t):t};
};
window.anchorError=anchor=>{
  const {m}=host._trendNavigation,box=host.querySelector('svg').getBoundingClientRect();
  return {x:Math.abs(box.left+m.x(anchor.index)/m.W*box.width-anchor.x),y:Math.abs(box.top+m.y(anchor.price)/m.H*box.height-anchor.y)};
};
window.wheelAt=({rx=.5,ry=.5,dy=-80,dx=0,mode=0,shift=false,priceAxis=false,target='svg'}={})=>{
  const point=chartPoint(rx,ry,priceAxis),event=new WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:point.x,clientY:point.y,deltaY:dy,deltaX:dx,deltaMode:mode,shiftKey:shift});
  host.querySelector(target).dispatchEvent(event);return event.defaultPrevented;
};
host.addEventListener('pointerdown',event=>{window.lastPointer=event.pointerId;});
resetChart();
'''
    options = getattr(request, 'param', {'viewport': {'width': 1280, 'height': 900}})
    page = workspace_browser.new_page(**options)
    try:
        page.set_content('<meta name="viewport" content="width=device-width, initial-scale=1"><style>' + css + '</style><div class="trend-ws" style="width:min(1100px,100%);height:700px;overflow:hidden"><div class="trend-ws-host" data-trend-zoom-chart></div></div><script>' + program + '</script>')
        yield page
    finally:
        page.close()


@pytest.mark.parametrize('scale', ['linear', 'log'])
@pytest.mark.parametrize('rx,ry', [(.2, .25), (.5, .5), (.8, .75)])
@pytest.mark.parametrize('dy', [-80, 80])
def test_workspace_wheel_keeps_cursor_session_and_price_fixed(workspace_chart, scale, rx, ry, dy):
    result = workspace_chart.evaluate('''({scale,rx,ry,dy})=>{
      resetChart(scale);const anchor=anchorAt(rx,ry),before=inspectChart();
      const prevented=wheelAt({rx,ry,dy});flushFrames();
      return {before,after:inspectChart(),error:anchorError(anchor),prevented};
    }''', {'scale': scale, 'rx': rx, 'ry': ry, 'dy': dy})
    assert result['prevented']
    assert (result['after']['factor'] > result['before']['factor']) == (dy < 0)
    assert result['error']['x'] < 1 and result['error']['y'] < 1
    assert result['after']['finite'] and result['after']['unchanged']
    assert len(result['after']['bars']) >= 20
    # The rendered candle context consists solely of original verified rows.
    assert result['after']['bars'] == list(range(result['after']['bars'][0], result['after']['bars'][-1] + 1))


@pytest.mark.parametrize('scale', ['linear', 'log'])
def test_workspace_wheel_bursts_match_separate_frames_and_delta_units(workspace_chart, scale):
    result = workspace_chart.evaluate('''scale=>{
      const run=(events,separate)=>{resetChart(scale);for(const event of events){wheelAt(event);if(separate)flushFrames();}const queued=inspectChart().pending;flushFrames();return {state:inspectChart(),queued};};
      const events=Array.from({length:4},()=>({rx:.35,ry:.6,dy:-35}));
      const burst=run(events,false),separate=run(events,true);
      const pixel=run([{dy:-80}],false),line=run([{dy:-5,mode:1}],false);
      resetChart(scale);const height=inspectChart().plotHeight;
      const page=run([{dy:-80/height,mode:2}],false);
      resetChart(scale);const before=inspectChart();wheelAt({dy:0});flushFrames();const zero=inspectChart();
      resetChart(scale);wheelAt({dy:-1e6});flushFrames();const capped=inspectChart();
      return {burst,separate,pixel,line,page,before,zero,capped};
    }''', scale)
    assert result['burst']['queued'] == 1, 'rapid wheel input should share one redraw'
    for key in ('factor', 'x', 'y'):
        assert result['burst']['state'][key] == pytest.approx(result['separate']['state'][key])
        assert result['pixel']['state'][key] == pytest.approx(result['line']['state'][key])
        assert result['pixel']['state'][key] == pytest.approx(result['page']['state'][key])
        assert result['zero'][key] == result['before'][key]
    assert result['capped']['factor'] == pytest.approx(4 * math.exp(.32))
    assert all(result[key]['state']['unchanged'] for key in ('burst', 'separate', 'pixel', 'line', 'page'))


@pytest.mark.parametrize('scale', ['linear', 'log'])
def test_workspace_wheel_limits_axes_and_pan_keep_valid_original_data(workspace_chart, scale):
    result = workspace_chart.evaluate('''scale=>{
      const bounds=[];for(const dy of [-1e6,1e6]){resetChart(scale);for(let i=0;i<30;i++){wheelAt({dy});flushFrames();}bounds.push(inspectChart());}
      resetChart(scale);wheelAt({dy:-80});flushFrames();const before=inspectChart(),anchor=anchorAt(.5,.3);
      const axisPrevented=wheelAt({dy:-60,ry:.3,priceAxis:true});flushFrames();const priceAxis={state:inspectChart(),error:anchorError(anchor)};
      resetChart(scale);wheelAt({dy:-80});flushFrames();const panBefore=inspectChart();
      wheelAt({dy:60,shift:true});flushFrames();const shifted=inspectChart();
      wheelAt({dy:0,dx:-60});flushFrames();const horizontal=inspectChart();
      const outsidePrevented=wheelAt({target:'#editable'});
      return {bounds,before,axisPrevented,priceAxis,panBefore,shifted,horizontal,outsidePrevented};
    }''', scale)
    assert [row['factor'] for row in result['bounds']] == [8, 1]
    assert result['bounds'][0]['disabled']['in']
    assert result['bounds'][1]['disabled']['out']
    for row in result['bounds']:
        assert row['finite'] and row['x'][1] > row['x'][0] and row['y'][1] > row['y'][0]
        assert 0 <= row['x'][0] < row['x'][1] <= 500
        assert len(row['bars']) >= 20 and row['unchanged']
    assert result['axisPrevented'] and not result['outsidePrevented']
    assert result['priceAxis']['state']['x'] == result['before']['x']
    assert result['priceAxis']['state']['factor'] == result['before']['factor']
    assert result['priceAxis']['state']['y'] != result['before']['y']
    assert result['priceAxis']['error']['y'] < 1
    for row in (result['shifted'], result['horizontal']):
        assert row['factor'] == result['panBefore']['factor']
        assert row['y'] == result['panBefore']['y'] and row['unchanged']
    assert result['shifted']['x'][0] > result['panBefore']['x'][0]
    assert result['horizontal']['x'][0] < result['shifted']['x'][0]


def test_workspace_wheel_anchor_survives_price_axis_width_change(workspace_chart):
    result = workspace_chart.evaluate('''()=>{
      resetChart('linear',{yRange:[50,1005]});
      const before=host._trendNavigation.m.R,anchor=anchorAt(.8,.25);
      wheelAt({rx:.8,ry:.25});flushFrames();
      return {before,after:host._trendNavigation.m.R,error:anchorError(anchor),state:inspectChart()};
    }''')
    assert result['before'] != result['after'], 'fixture must exercise changing axis label width'
    assert result['error']['x'] < 1 and result['error']['y'] < 1
    assert result['state']['unchanged']


def test_workspace_mouse_drag_after_wheel_preserves_continuous_zoom_window(workspace_chart):
    page = workspace_chart
    page.evaluate('wheelAt({dy:-80});flushFrames()')
    before = page.evaluate('inspectChart()')
    point = page.evaluate('chartPoint(.5,.5)')
    page.mouse.move(point['x'], point['y'])
    page.mouse.down()
    page.mouse.move(point['x'] + 75, point['y'], steps=4)
    dragging = page.evaluate('inspectChart()')
    assert dragging['active'] and dragging['cursor'] == 'grabbing' and dragging['selection'] == ''
    page.mouse.up()
    page.evaluate('flushFrames()')
    after = page.evaluate('inspectChart()')
    assert after['x'][0] < before['x'][0]
    assert after['x'][1] - after['x'][0] == pytest.approx(before['x'][1] - before['x'][0])
    assert after['y'] == before['y'] and after['factor'] == before['factor']
    assert not after['active'] and after['cursor'] == 'grab' and after['unchanged']


@pytest.mark.parametrize('window', [(470.25, 498.75), (505.25, 515.75)])
def test_workspace_fractional_windows_keep_svg_dimensions_and_date_ticks_valid(workspace_chart, window):
    result = workspace_chart.evaluate('''range=>{
      resetChart('linear',{xRange:range});const {m}=host._trendNavigation;
      m.lines=[{line_id:'fixture-future',role:'support',points:[{index:499,price:290,future:false},{index:520,price:300,future:true}]}];
      const holder=document.createElement('div');holder.innerHTML=trendSvg(detail,m,asset);
      const svg=holder.querySelector('svg'),ticks=[...svg.querySelectorAll(':scope > text[text-anchor]')];
      return {valid:[...svg.querySelectorAll('rect')].every(rect=>['width','height'].every(name=>Number.isFinite(Number(rect.getAttribute(name)))&&Number(rect.getAttribute(name))>=0)),
        ticks:ticks.map(tick=>Number(tick.getAttribute('x'))),left:m.L,right:m.W-m.R,
        visible:m.bars.filter(bar=>bar.session_index>=m.first&&bar.session_index<=m.end).length,
        unchanged:inspectChart().unchanged};
    }''', window)
    assert result['valid'] and result['unchanged']
    assert all(result['left'] <= x <= result['right'] for x in result['ticks'])
    assert bool(result['ticks']) == bool(result['visible'])


@pytest.mark.parametrize('scale', ['linear', 'log'])
@pytest.mark.parametrize('region', ['plot', 'price_axis', 'time_axis'])
def test_workspace_double_click_restores_opening_window_and_keeps_dialog_and_drawings(workspace_chart, scale, region):
    page = workspace_chart
    initial = page.evaluate('''scale=>{
      manual.lines=[{id:'manual-fixture',number:1,axis:scale,extension:'both',extend:true,name:'Saved line',note:'',hidden:false,locked:false,
        a:{session:baseBars[160].session,price:160},b:{session:baseBars[200].session,price:180},style:{...TREND_MANUAL_STYLE}}];
      openFullWorkspace(scale);window.sourceBeforeReset=JSON.stringify({baseBars,analysis,lines:manual.lines});
      return inspectChart();
    }''', scale)
    assert initial['bars'] == list(range(150, 275)), 'home must differ from the full source series'
    changed = page.evaluate('''()=>{
      wheelAt({dy:-80});flushFrames();wheelAt({dy:80,shift:true});flushFrames();
      wheelAt({dy:-60,priceAxis:true});flushFrames();return inspectChart();
    }''')
    assert changed['x'] != initial['x'] and changed['y'] != initial['y']
    point = page.evaluate('''region=>region==='price_axis'?chartPoint(.5,.5,true):chartPoint(.5,region==='time_axis'?1.025:.5)''', region)
    page.mouse.dblclick(point['x'], point['y'])
    page.evaluate('flushFrames()')
    restored = page.evaluate('inspectChart()')
    for key in ('factor', 'x', 'y', 'bars'):
        assert restored[key] == pytest.approx(initial[key])
    assert page.locator('[data-trend-zoom] [role="dialog"][aria-modal="true"]').count() == 1
    assert page.evaluate('TREND_ZOOM.ws===ws && state.xRange===null && state.yRange===null')
    assert page.evaluate('sourceBeforeReset===JSON.stringify({baseBars,analysis,lines:manual.lines})')


def test_workspace_double_click_on_controls_preserves_view_and_pending_render_cannot_undo_reset(workspace_chart):
    page = workspace_chart
    result = page.evaluate('''()=>{
      openFullWorkspace();wheelAt({dy:-80});flushFrames();const changed=inspectChart();
      const controlPoint=chartPoint(.5,.5);
      for(const selector of ['#editable','[data-trend-tool="in"]'])host.querySelector(selector).dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true,clientX:controlPoint.x,clientY:controlPoint.y}));
      const controls=inspectChart();wheelAt({dy:-40});const queued=inspectChart().pending;
      const point=chartPoint(.5,.5);host.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true,clientX:point.x,clientY:point.y}));
      const pending=inspectChart().pending;flushFrames();return {changed,controls,queued,pending,restored:inspectChart()};
    }''')
    for key in ('factor', 'x', 'y', 'bars'):
        assert result['controls'][key] == result['changed'][key]
    assert result['queued'] == 1 and result['pending'] == 0
    assert result['restored']['bars'] == list(range(150, 275))
    assert result['restored']['factor'] == 4


@pytest.mark.parametrize('priority', ['drawing', 'busy', 'selected', 'measure', 'draft'])
def test_workspace_double_click_respects_manual_editing_priority(workspace_chart, priority):
    result = workspace_chart.evaluate('''priority=>{
      openFullWorkspace();wheelAt({dy:-80});flushFrames();const before=inspectChart();
      if(priority==='drawing')manual.mode=true;
      if(priority==='busy')host._trendManual.busy=()=>true;
      if(priority==='selected')manual.selected='manual-fixture';
      if(priority==='measure')manual.measure={a:{session:baseBars[160].session,price:160},b:{session:baseBars[200].session,price:180}};
      if(priority==='draft')manual.editDraft={name:'Unsaved edit'};
      const point=chartPoint(.5,.5),event=new MouseEvent('dblclick',{bubbles:true,cancelable:true,clientX:point.x,clientY:point.y});
      host.querySelector('svg').dispatchEvent(event);flushFrames();
      return {before,after:inspectChart()};
    }''', priority)
    for key in ('factor', 'x', 'y', 'bars'):
        assert result['after'][key] == result['before'][key]


MOBILE_WORKSPACE = pytest.mark.parametrize('workspace_chart', [{
    'viewport': {'width': 390, 'height': 844}, 'is_mobile': True, 'has_touch': True,
}], indirect=True, ids=['mobile-390'])


def prepare_mobile_gesture(page, scale='linear'):
    return page.evaluate('''scale=>{
      manual.lines=[{id:'manual-touch',number:1,axis:scale,extension:'both',extend:true,name:'Saved touch line',note:'',hidden:false,locked:false,
        a:{session:baseBars[160].session,price:160},b:{session:baseBars[200].session,price:180},style:{...TREND_MANUAL_STYLE}}];
      openFullWorkspace(scale);window.touchResetCount=0;window.touchSource=JSON.stringify({baseBars,analysis,lines:manual.lines});
      const reset=ws.resetView;ws.resetView=()=>{touchResetCount++;return reset();};
      const home=inspectChart();wheelAt({dy:-80});flushFrames();wheelAt({dy:60,shift:true});flushFrames();
      wheelAt({dy:-40,priceAxis:true});flushFrames();
      return {home,changed:inspectChart(),width:innerWidth,touch:navigator.maxTouchPoints};
    }''', scale)


def dispatch_native_touch(session, kind, points=()):
    session.send('Input.dispatchTouchEvent', {
        'type': kind,
        'touchPoints': [{'id': i + 1, 'x': point['x'], 'y': point['y']} for i, point in enumerate(points)],
    })


@MOBILE_WORKSPACE
@pytest.mark.parametrize('scale', ['linear', 'log'])
@pytest.mark.parametrize('region', ['plot', 'price_axis', 'time_axis'])
def test_workspace_native_double_tap_restores_home_once(workspace_chart, scale, region):
    page = workspace_chart
    initial = prepare_mobile_gesture(page, scale)
    assert initial['width'] == 390 and initial['touch'] > 0
    assert initial['home']['bars'] == list(range(150, 275))
    assert initial['changed']['x'] != initial['home']['x'] and initial['changed']['y'] != initial['home']['y']
    point = page.evaluate("region=>region==='price_axis'?chartPoint(.5,.5,true):chartPoint(.5,region==='time_axis'?1.025:.5)", region)
    page.touchscreen.tap(point['x'], point['y'])
    assert page.evaluate('touchResetCount') == 0
    page.touchscreen.tap(point['x'], point['y'])
    page.evaluate('flushFrames()')
    restored = page.evaluate('inspectChart()')
    for key in ('factor', 'x', 'y', 'bars'):
        assert restored[key] == pytest.approx(initial['home'][key])
    assert page.evaluate('touchResetCount') == 1, 'compatibility mouse events must not cause a second reset'
    assert page.locator('[data-trend-zoom] [role="dialog"][aria-modal="true"]').count() == 1
    assert page.evaluate('touchSource===JSON.stringify({baseBars,analysis,lines:manual.lines})')


@MOBILE_WORKSPACE
@pytest.mark.parametrize('interruption', ['drag', 'move_return', 'pinch', 'long_press', 'cancel', 'slow', 'far', 'control', 'wheel', 'blur'])
def test_workspace_touch_gestures_and_interruptions_do_not_become_double_taps(workspace_chart, interruption):
    page = workspace_chart
    prepare_mobile_gesture(page)
    point = page.evaluate('chartPoint(.4,.5)')
    moved = {'x': point['x'] + 35, 'y': point['y']}
    page.touchscreen.tap(point['x'], point['y'])
    session = page.context.new_cdp_session(page)
    if interruption in ('drag', 'move_return', 'long_press', 'cancel'):
        dispatch_native_touch(session, 'touchStart', [point])
        if interruption in ('drag', 'move_return'):
            dispatch_native_touch(session, 'touchMove', [moved])
            if interruption == 'move_return':
                dispatch_native_touch(session, 'touchMove', [point])
        elif interruption == 'long_press':
            page.wait_for_timeout(350)
        dispatch_native_touch(session, 'touchCancel' if interruption == 'cancel' else 'touchEnd')
        if interruption != 'drag':
            page.touchscreen.tap(point['x'], point['y'])
    elif interruption == 'pinch':
        dispatch_native_touch(session, 'touchStart', [point])
        dispatch_native_touch(session, 'touchStart', [point, moved])
        dispatch_native_touch(session, 'touchMove', [{'x': point['x'] - 15, 'y': point['y']}, {'x': moved['x'] + 15, 'y': moved['y']}])
        dispatch_native_touch(session, 'touchEnd')
        page.touchscreen.tap(point['x'], point['y'])
    elif interruption == 'slow':
        page.wait_for_timeout(450)
        page.touchscreen.tap(point['x'], point['y'])
    elif interruption == 'far':
        page.touchscreen.tap(point['x'] + 70, point['y'])
    elif interruption == 'control':
        box = page.locator('[data-trend-zoom] #editable').bounding_box()
        assert box
        page.touchscreen.tap(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.touchscreen.tap(point['x'], point['y'])
    elif interruption == 'wheel':
        page.evaluate('wheelAt({dy:-20})')
        page.touchscreen.tap(point['x'], point['y'])
    else:
        page.evaluate("window.dispatchEvent(new Event('blur'))")
        page.touchscreen.tap(point['x'], point['y'])
    page.evaluate('flushFrames()')
    assert page.evaluate('touchResetCount') == 0
    assert page.evaluate('touchSource===JSON.stringify({baseBars,analysis,lines:manual.lines})')


@MOBILE_WORKSPACE
@pytest.mark.parametrize('priority', ['drawing', 'selected'])
def test_workspace_native_double_tap_preserves_manual_editing_priority(workspace_chart, priority):
    page = workspace_chart
    initial = prepare_mobile_gesture(page)
    page.evaluate("priority=>{if(priority==='drawing')manual.mode=true;else manual.selected='manual-touch';}", priority)
    point = page.evaluate('chartPoint(.4,.5)')
    page.touchscreen.tap(point['x'], point['y'])
    page.touchscreen.tap(point['x'], point['y'])
    page.evaluate('flushFrames()')
    after = page.evaluate('inspectChart()')
    assert page.evaluate('touchResetCount') == 0
    for key in ('factor', 'x', 'y', 'bars'):
        assert after[key] == initial['changed'][key]


@MOBILE_WORKSPACE
def test_workspace_genuine_mouse_double_click_still_resets_after_touch(workspace_chart):
    page = workspace_chart
    initial = prepare_mobile_gesture(page)
    point = page.evaluate('chartPoint(.4,.5)')
    page.touchscreen.tap(point['x'], point['y'])
    page.mouse.dblclick(point['x'], point['y'])
    page.evaluate('flushFrames()')
    assert page.evaluate('touchResetCount') == 1
    assert page.evaluate('inspectChart().bars') == initial['home']['bars']
