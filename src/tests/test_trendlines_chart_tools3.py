"""Third chart batch: derived chart types and drawing tools of more than two clicks."""
import pytest

from test_trendlines_chart_features import SESSIONS, WALK
from test_trendlines_manual_ui import FIXTURE, run


def closes(*values):
    return 'const rows=[' + ','.join(
        f"{{session:'2026-01-{i + 1:02d}',session_index:{i},open:{value},high:{value},low:{value},close:{value},volume:1}}"
        for i, value in enumerate(values)) + '];'


# ---- derived chart types, against hand arithmetic
def test_renko_needs_two_boxes_to_reverse_and_splits_a_session_between_its_bricks(tmp_path):
    out = run(tmp_path, closes(100, 104, 112, 111, 109, 99, 118) + r'''
const bricks=trendWsRenko(rows,trendWsAbsoluteGrid(5));
process.stdout.write(JSON.stringify(bricks.map(row=>[row.open,row.close,row.first,row.last])));
''', FIXTURE)
    # 100 -> 112: two bricks in one session. 111 and 109 hold; 99 is two boxes under the 110 top; 118 is back up.
    assert [row[:2] for row in out] == [[100, 105], [105, 110], [105, 100], [105, 110], [110, 115]]
    assert out[0][2:] == [-0.5, 2.0] and out[1][2:] == [2.0, 2.5]
    assert out[2][2:] == [2.5, 5.5]
    assert all(left[3] == right[2] for left, right in zip(out, out[1:]))


def test_three_line_break_reverses_only_past_the_last_three_lines(tmp_path):
    out = run(tmp_path, closes(100, 101, 102, 103, 101, 100.5, 104, 99) + r'''
process.stdout.write(JSON.stringify(trendWsLineBreak(rows).map(row=>[row.open,row.close])));
''', FIXTURE)
    # 101 and 100.5 stay above the low of the last three lines (100); 104 continues; 99 breaks 101.
    assert out == [[100, 101], [101, 102], [102, 103], [103, 104], [103, 99]]


def test_kagi_turns_on_the_reversal_amount_and_changes_weight_past_a_shoulder(tmp_path):
    out = run(tmp_path, closes(100, 110, 104, 109.5, 96, 112) + r'''
process.stdout.write(JSON.stringify(trendWsKagi(rows,trendWsAbsoluteGrid(5)).map(row=>({from:row.open,to:row.close,yang:row.yang,parts:row.parts}))));
''', FIXTURE)
    assert [[row['from'], row['to']] for row in out] == [[100, 110], [110, 104], [104, 109.5], [109.5, 96], [96, 112]]
    # 96 falls through the 104 waist: thick above it, thin below. 112 clears the 109.5 shoulder.
    assert out[3]['parts'] == [{'from': 109.5, 'to': 104, 'yang': True}, {'from': 104, 'to': 96, 'yang': False}]
    assert out[4]['parts'] == [{'from': 96, 'to': 109.5, 'yang': False}, {'from': 109.5, 'to': 112, 'yang': True}]


def test_point_and_figure_opens_a_column_only_after_three_boxes(tmp_path):
    out = run(tmp_path, closes(100, 120, 112, 104, 96, 130) + r'''
process.stdout.write(JSON.stringify(trendWsPnf(rows,trendWsAbsoluteGrid(5)).map(row=>[row.direction,row.low,row.high])));
''', FIXTURE)
    # 112 holds; 104 is three boxes under 120, so the column turns a box lower. 96 fills down to 100, not past it.
    assert out == [[1, 100, 120], [-1, 100, 115], [1, 105, 130]]


def test_range_bars_never_exceed_their_range_and_walk_the_whole_bar(tmp_path):
    out = run(tmp_path, r'''
const rows=[{session:'2026-01-01',session_index:0,open:100,high:112,low:98,close:110},{session:'2026-01-02',session_index:1,open:110,high:111,low:90,close:92}];
const built=trendWsRange(rows,trendWsAbsoluteGrid(5));
process.stdout.write(JSON.stringify({bars:built.map(row=>[row.open,row.high,row.low,row.close]),contiguous:built.slice(1).every((row,i)=>row.first===built[i].last)}));
''', FIXTURE)
    assert out['contiguous']
    assert all(high - low <= 5 + 1e-9 for _, high, low, _ in out['bars'])
    assert out['bars'][0][3] == 98 + 5
    assert max(row[1] for row in out['bars']) >= 110
    assert min(row[2] for row in out['bars']) <= 92


def test_percent_box_steps_geometrically_and_automatic_box_is_a_round_number(tmp_path):
    out = run(tmp_path, WALK + r'''
const grid=trendWsPercentGrid(1),size=trendWsAtrSize(rows),leading=Number(String(size.toExponential()).split('e')[0]);
process.stdout.write(JSON.stringify({ratio:grid.price(11)/grid.price(10),back:grid.level(grid.price(7)),leading,label:trendWsDerived(rows,'renko','1').boxLabel,auto:trendWsDerived(rows,'renko','auto').boxLabel}));
''', FIXTURE)
    assert out['ratio'] == pytest.approx(1.01)
    assert out['back'] == pytest.approx(7)
    assert out['leading'] in (1, 2, 2.5, 5, 10)
    assert out['label'] == '칸 1%' and out['auto'].startswith('칸 ')


def test_a_box_too_small_to_draw_is_widened_and_says_so(tmp_path):
    out = run(tmp_path, r'''
let last=100;const rows=Array.from({length:3000},(_,i)=>{last=last*(i%2?1.2:1/1.19);return {session:'2026-01-01',session_index:i,open:last,high:last*1.2,low:last/1.2,close:last};});
const built=trendWsDerived(rows,'range','0.5');process.stdout.write(JSON.stringify({rows:built.length,label:built.boxLabel}));
''', FIXTURE)
    assert out['rows'] <= 21000 and out['label'] != '칸 0.5%'


@pytest.mark.parametrize('type_', ['renko', 'kagi', 'linebreak', 'pnf', 'range'])
@pytest.mark.parametrize('box', ['auto', '2'])
def test_every_derived_type_draws_clean_markup_and_stays_on_the_time_axis(tmp_path, type_, box):
    out = run(tmp_path, WALK + f"const type='{type_}',box='{box}';" + r'''
const series=trendWsTyped(rows,type,box),view={...m,W:1200,H:600,L:10,R:60,T:10,B:30,first:rows[0].session_index,end:rows.at(-1).session_index};
const low=Math.min(...rows.map(r=>r.low)),high=Math.max(...rows.map(r=>r.high));view.x=i=>view.L+(i-view.first)/(view.end-view.first)*(view.W-view.L-view.R);view.y=p=>view.T+(high-p)/(high-low)*(view.H-view.T-view.B);
view.wsSeries=series;view.wsType=type;view.wsClip='t';const html=trendWsSeriesMarkup(view);
process.stdout.write(JSON.stringify({rows:series.length,bad:html.includes('NaN')||html.includes('undefined'),length:html.length,ordered:series.every((row,i)=>!i||row.session_index>=series[i-1].session_index),bounded:series.every(row=>row.high>=row.low&&row.low>0&&row.session_index>=rows[0].session_index-1&&row.session_index<=rows.at(-1).session_index+2),cached:trendWsTyped(rows,type,box)===series}));
''', FIXTURE)
    assert out['rows'] > 0 and out['length'] > 60
    assert not out['bad'] and out['ordered'] and out['bounded'] and out['cached']


def test_the_type_menu_offers_a_box_size_only_where_it_means_something(tmp_path):
    out = run(tmp_path, r'''
const saved=box=>{memory.set(TREND_WS_PREFS_KEY,JSON.stringify({type:'renko',box}));return trendWsPrefs();};
process.stdout.write(JSON.stringify({kept:saved('2').box,rejected:saved('7').box,types:TREND_WS_TYPES.length}));
''', FIXTURE)
    assert out == {'kept': '2', 'rejected': 'auto', 'types': 18}


# ---- drawing tools of more than two clicks
CLICKS = {'pitchfork': 3, 'schiff': 3, 'fibext': 3, 'triangle': 3, 'long': 3, 'short': 3, 'abcd': 4, 'elliott3': 4,
          'xabcd': 5, 'elliott5': 6, 'hs': 7}


@pytest.mark.parametrize('tool,count', sorted(CLICKS.items()))
def test_a_many_click_tool_finishes_on_its_last_click_and_round_trips(tmp_path, tool, count):
    out = run(tmp_path, SESSIONS + f"state.tool='{tool}';state.mode=true;const count={count};" + r'''
const prices=[100,180,120,170,110,190,130];let pending=0;
for(let i=0;i<count;i++){const done=trendManualChoose(state,at(i%8,prices[i]),sessions);if(!done)pending++;}
const drawn=state.lines[0],line=trendManualGeometry(drawn,detail,analysis,'linear',m),html=trendManualShapeSvg(m,line,true);
const moved=trendManualMove(drawn,1,10,sessions,'linear');
const stray={...drawn,points:drawn.points.slice(0,-1)},swapped={...drawn,a:{...drawn.a,price:drawn.a.price+1}};const rejects=record=>{try{trendManualValidateV2([record],'soxx');return false;}catch(_){return true;}};
const parts=trendManualMultiParts(m,line),first=parts.polys[0],hit=trendManualShapeHit(m,line,(first[0].x+first[1].x)/2,(first[0].y+first[1].y)/2,6);
process.stdout.write(JSON.stringify({pending,count:state.lines.length,mode:state.mode,clicks:state.clicks.length,points:drawn.points.length,shape:drawn.shape,valid:trendManualValidateV2(state.lines,'soxx').length,bad:html.includes('NaN')||html.includes('undefined'),handles:(html.match(/data-trend-manual-handle/g)||[]).length,hit,movedValid:trendManualValidateV2([moved],'soxx').length,movedFirst:moved.points[0].price-drawn.points[0].price,rejectStray:rejects(stray),rejectSwapped:rejects(swapped),rejectLoose:rejects({...drawn,shape:'rect'})}));
''', FIXTURE)
    assert out['pending'] == count - 1 and out['count'] == 1 and out['mode'] is False and out['clicks'] == 0
    assert out['points'] == count and out['shape'] == tool and out['valid'] == 1 and not out['bad']
    assert out['handles'] == count and out['hit'] is True
    assert out['movedValid'] == 1 and out['movedFirst'] == 10
    assert out['rejectStray'] and out['rejectSwapped'] and out['rejectLoose']


def test_position_tool_reports_reward_over_risk_and_refuses_a_nonsense_order(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const build=(tool,prices)=>{const list=prices.map((price,i)=>at(i+1,price)),record=trendManualMultiRecord(state,list,tool);return trendManualMultiParts(m,trendManualGeometry(record,detail,analysis,'linear',m)).labels.map(row=>row.text);};
process.stdout.write(JSON.stringify({long:build('long',[100,130,90]),short:build('short',[100,70,110]),wrong:build('long',[100,90,130])}));
''', FIXTURE)
    assert out['long'][2] == '손익비 3.00' and out['long'][0].startswith('목표 130') and '+30.00%' in out['long'][0]
    assert '-10.00%' in out['long'][1]
    assert out['short'][2] == '손익비 3.00'
    assert out['wrong'][2] == '손익비 —'


def test_pitchfork_median_runs_through_the_midpoint_and_prongs_are_parallel(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const fork=trendManualMultiRecord(state,[at(0,100),at(2,150),at(4,110)],'pitchfork'),line=trendManualGeometry(fork,detail,analysis,'linear',m),parts=trendManualMultiParts(m,line),[handle,median,upper,lower]=parts.polys,slope=poly=>(poly.at(-1).y-poly[0].y)/(poly.at(-1).x-poly[0].x);
const midX=m.x(3),midY=m.y(130),atMid=median.reduce((best,p)=>Math.abs(p.x-midX)<Math.abs(best.x-midX)?p:best,median[0]),expected=median[0].y+slope(median)*(midX-median[0].x);
const schiff=trendManualMultiParts(m,trendManualGeometry(trendManualMultiRecord(state,[at(0,100),at(2,150),at(4,110)],'schiff'),detail,analysis,'linear',m)).polys[1];
process.stdout.write(JSON.stringify({expected,midY,upper:slope(upper),lower:slope(lower),median:slope(median),starts:[upper[0].x,lower[0].x,m.x(2),m.x(4)],schiffStart:schiff[0].y,schiffExpected:m.y(125),handle:handle.length}));
''', FIXTURE)
    assert out['expected'] == pytest.approx(out['midY'])
    assert out['upper'] == pytest.approx(out['median']) and out['lower'] == pytest.approx(out['median'])
    assert out['starts'][0] == out['starts'][2] and out['starts'][1] == out['starts'][3]
    assert out['schiffStart'] == pytest.approx(out['schiffExpected'])
    assert out['handle'] == 2


def test_fib_extension_projects_the_first_move_from_the_third_point(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const parts=trendManualMultiParts(m,trendManualGeometry(trendManualMultiRecord(state,[at(0,100),at(2,150),at(4,120)],'fibext'),detail,analysis,'linear',m));
process.stdout.write(JSON.stringify(parts.labels.map(row=>row.text)));
''', FIXTURE)
    assert out[0] == '0 · 120' and '1 · 170' in out and '1.618 · 200.9' in out


def test_harmonic_ratios_use_the_prices_clicked(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const parts=trendManualMultiParts(m,trendManualGeometry(trendManualMultiRecord(state,[at(0,100),at(1,200),at(2,150),at(3,180),at(4,120)],'xabcd'),detail,analysis,'linear',m));
process.stdout.write(JSON.stringify({labels:parts.labels.map(row=>row.text),fills:parts.fills.length,guides:parts.guides.length}));
''', FIXTURE)
    assert 'AB/XA 0.500' in out['labels'] and 'BC/AB 0.600' in out['labels'] and 'CD/BC 2.000' in out['labels'] and 'AD/XA 0.800' in out['labels']
    assert out['fills'] == 2 and out['guides'] == 4


def test_path_ends_on_a_repeated_click_and_needs_two_dates(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
state.tool='path';state.mode=true;
const once=trendManualChoose(state,at(1,100),sessions),same=trendManualChoose(state,at(1,120),sessions),message=state.message,second=trendManualChoose(state,at(3,150),sessions),third=trendManualChoose(state,at(5,130),sessions),hint=trendManualMultiHint('path',state),finish=trendManualChoose(state,at(5,131),sessions);
process.stdout.write(JSON.stringify({once,same,message,second,third,hint,finish,points:state.lines[0].points.length,mode:state.mode}));
''', FIXTURE)
    assert out['finish'] is True and out['points'] == 3 and out['mode'] is False
    assert not any((out['once'], out['same'], out['second'], out['third']))
    assert out['message'] == '서로 다른 두 날짜를 선택해 주세요'
    assert 'Enter' in out['hint']


def test_handle_drag_keeps_end_points_in_time_order(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const shape=trendManualMultiRecord(state,[at(2,100),at(4,150),at(6,120)],'triangle'),dragged=trendManualWithPoints(shape,shape.points.map((p,i)=>i===2?at(0,90):p));
process.stdout.write(JSON.stringify({a:dragged.a.session===at(0,90).session,b:dragged.b.session===at(4,150).session,valid:trendManualValidateV2([dragged],'soxx').length,order:dragged.points[2].price}));
''', FIXTURE)
    assert out == {'a': True, 'b': True, 'valid': 1, 'order': 90}


def test_two_click_gann_tools_stay_plain_two_anchor_records(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const make=tool=>trendManualRecord(state,at(1,100),at(3,140),true,tool),fan=make('ganfan'),box=make('ganbox'),line=trendManualGeometry(fan,detail,analysis,'linear',m),rows=trendManualGannFan(m,line),html=[fan,box].map(r=>trendManualShapeSvg(m,trendManualGeometry(r,detail,analysis,'linear',m),true)).join('');
const one=rows.find(row=>row.label==='1/1');
process.stdout.write(JSON.stringify({count:rows.length,oneNear:one.near.y,anchor:m.y(140),points:'points' in fan,valid:trendManualValidateV2([fan,{...box,id:'manual-other',number:9}],'soxx').length,bad:html.includes('NaN')||html.includes('undefined'),gridLines:(html.match(/data-trend-gann-box/g)||[]).length,hit:trendManualShapeHit(m,line,m.x(2),m.y(120),6)}));
''', FIXTURE)
    assert out['count'] == 9 and out['oneNear'] == pytest.approx(out['anchor'])
    assert out['points'] is False and out['valid'] == 2 and not out['bad'] and out['gridLines'] == 7 and out['hit'] is True


def test_older_records_and_backups_still_validate(tmp_path):
    out = run(tmp_path, SESSIONS + r'''
const old=trendManualRecord(state,at(1,100),at(3,140),true,'fib'),many=trendManualMultiRecord({...state,lines:[old]},[at(1,100),at(3,140),at(5,120)],'triangle');
const lines=trendManualValidateV2([old,many],'soxx'),copied=trendManualClone({...state,lines},[many]);
process.stdout.write(JSON.stringify({old:'points' in lines[0],many:lines[1].points.length,cloned:copied[0].points.length,same:copied[0].id!==many.id,clonedValid:trendManualValidateV2(copied,'soxx').length}));
''', FIXTURE)
    assert out == {'old': False, 'many': 3, 'cloned': 3, 'same': True, 'clonedValid': 1}
