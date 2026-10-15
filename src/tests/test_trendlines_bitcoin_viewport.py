"""BTC's wider overview keeps focused views and exact hover geometry intact."""
import pytest

from test_trendlines_ui import run


@pytest.mark.parametrize('axis', ['linear', 'log'])
@pytest.mark.parametrize('width', [390, 1280])
def test_bitcoin_overview_exposes_three_years_without_changing_lines(tmp_path, axis, width):
    result = run(tmp_path, r'''
const bars=Array.from({length:1566},(_,i)=>({session_index:i,session:new Date(Date.UTC(2022,6,1+i)).toISOString().slice(0,10),open:100+i,high:110+i,low:90+i,close:102+i}));
const line={line_id:'same-anchor-equation',kind:'pivot_structure',slot:'long_lower',side:'support',role:'support',first_anchor:{index:800},independent_contacts:[],coordinate_origin_index:800,intercept:AXIS==='log'?Math.log(890):890,slope:AXIS==='log'?.0005:1,display_start_index:800};
const detail={asset_id:'bitcoin',bars,gaps:[]},analysis={representative:true,family:'all',lines:[line],projection_sessions:[],critical_reference:{atr14:20}};
const before=JSON.stringify({detail,analysis}),axis=AXIS,width=WIDTH,visible=trendRepresentativeViewport(detail,analysis),m=trendRepresentativePlotModel(detail,analysis,visible,axis,width),svg=trendSvg(detail,m,{currency:'USD'}),bar=visible[50],hover=trendHoverAt(m,m.x(bar.session_index),m.y(bar.close),{scale:axis});
const scopes=Object.fromEntries(['all','anchors'].map(scope=>[scope,trendRepresentativeViewport(detail,analysis,scope).map(b=>b.session_index)]));
const focused=Object.fromEntries(['current_structure','regression_200','major_structure','long_boundaries'].map(family=>[family,trendRepresentativeViewport(detail,{...analysis,family}).map(b=>b.session_index)]));
process.stdout.write(JSON.stringify({visible:visible.map(b=>b.session_index),candles:(svg.match(/data-trend-bar=/g)||[]).length,hoverKind:hover.kind,hoverPrice:hover.row?.close,hoverSession:hover.row?.session,expectedPrice:bar.close,expectedSession:bar.session,scopes,focused,other:trendRepresentativeViewport({...detail,asset_id:'sk-hynix'},analysis).length,unchanged:before===JSON.stringify({detail,analysis}),lineId:m.lines[0].line_id}));
'''.replace('AXIS', repr(axis)).replace('WIDTH', str(width)))
    assert result['visible'] == list(range(471, 1566))
    assert result['candles'] == 1095
    assert result['hoverKind'] == 'bar'
    assert result['hoverPrice'] == result['expectedPrice']
    assert result['hoverSession'] == result['expectedSession']
    assert result['scopes']['all'] == list(range(1566))
    assert result['scopes']['anchors'] == list(range(790, 1566))
    assert len(result['focused']['current_structure']) == 126
    assert len(result['focused']['regression_200']) == 252
    assert result['focused']['major_structure'] == list(range(790, 1566))
    assert result['focused']['long_boundaries'] == list(range(790, 1566))
    assert result['other'] == 252
    assert result['unchanged'] and result['lineId'] == 'same-anchor-equation'


@pytest.mark.parametrize('count', [0, 50, 800])
def test_bitcoin_overview_never_invents_missing_history(tmp_path, count):
    result = run(tmp_path, 'const bars=Array.from({length:' + str(count) + r'''},(_,i)=>({session_index:i})),d={asset_id:'bitcoin',bars},a={family:'all',lines:[]};process.stdout.write(JSON.stringify({count:trendRepresentativeViewport(d,a).length,all:trendRepresentativeViewport(d,a,'all').length,unchanged:d.bars.length}));''')
    assert result == {'count': count, 'all': count, 'unchanged': count}
