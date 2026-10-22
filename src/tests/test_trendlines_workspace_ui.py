"""TradingView-style workspace: tools stay two-anchor records, previews never draw."""
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
