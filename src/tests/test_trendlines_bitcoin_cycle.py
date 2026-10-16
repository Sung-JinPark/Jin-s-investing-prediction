"""The 2023 BTC overlay uses confirmed full-history lows, independently replayed."""
from copy import deepcopy
from datetime import date, timedelta
import json
import math
from pathlib import Path

import pytest
import yaml

from ai_fc.trendlines import contracts as C, engine as E, representative as V, long_boundaries as B
from test_trendlines_ui import run


@pytest.fixture(scope='module')
def cycle_input():
    start = date(2022, 7, 1)
    bars = []
    for i in range(1567):
        day = (start + timedelta(days=i)).isoformat()
        price = 20000*math.exp(.0007*i) + 1800*math.sin(i/38) + 350*math.sin(i/7)
        row = dict(session_index=i, session=day, session_date=day,
                   open=price+100, high=price+1800, low=price-1800, close=price,
                   available_at=day+'T23:59:59+00:00', fetched_at=day+'T23:59:59+00:00')
        row['bar_id'] = 'research-bar-'+C.canonical_hash(row)
        bars.append(row)
    asset = C.load_asset_registry(Path(__file__).parents[2])['bitcoin']
    future = V._future(bars, asset)
    full = dict(asset_id='bitcoin', snapshot_id='full-a', source_snapshot_id='source-a',
                critical_manifest_sha256='a'*64, bars=bars, gaps=[])
    representative = dict(calculation_settings_json=json.dumps(C.default_config()),
                          calculation_tick_size=asset.get('tick_size', 0), projection_sessions=future)
    return dict(full=full, representative=representative, asset=asset)


def setup(f):
    return 'const f='+json.dumps(f, ensure_ascii=False)+';'


def independent(f, axis):
    """Python scalar/pivot implementation is independent of the JS view."""
    bars, asset = f['full']['bars'], f['asset']
    pivots, atr = V._pivots(bars, 10, 10), E._atr(bars, 14, segmented=True)
    last, candidates = bars[-1], []
    for a in pivots:
        if a['side'] != 'support' or not a['session'].startswith('2023-'):
            continue
        for b in pivots:
            if (b['side'] != 'support' or b['session'] < '2024-01-01'
                    or b['index']-a['index'] < 180 or last['session_index']-b['index'] > 365):
                continue
            line = {'kind':'pivot_structure', 'axis':axis, 'first_anchor':a, 'second_anchor':b}
            price = V._scalar_value(line, last['session_index'])
            if (price is None or B._over(price, last['close'])
                    or B._over(abs(price-last['close']), 8*atr[-1])
                    or B._over(abs(price-last['close']), .5*last['close'])
                    or any(V._scalar_value(line, p['index']) is None for p in f['representative']['projection_sessions'])):
                continue
            candidate = B._candidate(a,b,pivots,bars,atr,asset,C.default_config(),axis,
                                     f['representative']['projection_sessions'],'cycle_2023')
            candidate['line_id'] = 'bitcoin-cycle-v1-'+axis+'-'+a['bar_id'][-32:]+'-'+b['bar_id'][-32:]
            candidates.append(candidate)
    return sorted(candidates, key=B._rank)[0]


@pytest.mark.parametrize('axis', ['linear','log'])
@pytest.mark.parametrize('width', [390,1280])
def test_cycle_matches_independent_candidates_and_hover(tmp_path, cycle_input, axis, width):
    expected = independent(cycle_input, axis)
    result = run(tmp_path, setup(cycle_input)+'const axis='+json.dumps(axis)+',width='+str(width)+r''';
const before=JSON.stringify(f),lines=trendBitcoinCycle(f.full,f.representative,axis),line=lines[0],analysis={representative:true,family:'long_boundaries',lines:trendMergeSelectedLines(lines),projection_sessions:f.representative.projection_sessions,critical_reference:{atr14:1500}};
const bars=trendRepresentativeViewport(f.full,analysis,'anchors'),m=trendPlotModel(f.full,analysis,bars,axis,width),index=f.full.bars.at(-1).session_index+7,price=trendLinePrice(line,index,axis),hit=trendHoverAt(m,m.x(index),m.y(price),{scale:axis}),svg=trendSvg(f.full,m,{currency:'USD'});
process.stdout.write(JSON.stringify({line,first:bars[0].session_index,cache:lines===trendBitcoinCycle(f.full,f.representative,axis),unchanged:before===JSON.stringify(f),hit:{kind:hit.kind,future:hit.future,price:hit.row.price},svg:(svg.match(/data-trend-slot="cycle_2023"/g)||[]).length}));''')
    actual = result['line']
    for field in ('line_id','contact_count','structural_state','classification','formation_complete'):
        assert actual[field] == expected[field]
    for field in ('slope','intercept','current_price','formation_penetration','distance_atr'):
        assert actual[field] == pytest.approx(expected[field], abs=1e-6, rel=1e-10)
    assert [actual[k]['bar_id'] for k in ('first_anchor','second_anchor')] == [expected[k]['bar_id'] for k in ('first_anchor','second_anchor')]
    assert actual['first_anchor']['session'].startswith('2023-')
    assert actual['second_anchor']['confirmation_end_index'] <= cycle_input['full']['bars'][-1]['session_index']
    assert actual['source_full_snapshot_id'] == 'full-a'
    assert len(actual['projections']) == 30
    assert result['first'] == max(0, actual['first_anchor']['index']-10)
    assert result['cache'] and result['unchanged'] and result['svg'] == 1
    assert result['hit']['kind'] == 'line' and result['hit']['future']
    projection = actual['projections'][6]['price']
    assert result['hit']['price'] == pytest.approx(projection, abs=1e-6, rel=1e-10)


def test_cycle_is_optional_and_never_invents_2023_or_other_asset_lines(tmp_path, cycle_input):
    f = deepcopy(cycle_input)
    f['full']['bars'] = f['full']['bars'][800:]
    result = run(tmp_path, setup(f)+r'''
const missing=trendBitcoinCycle(f.full,f.representative,'linear');const other=trendBitcoinCycle({...f.full,asset_id:'soxx'},f.representative,'linear');
process.stdout.write(JSON.stringify({missing,other}));''')
    assert result['missing'][0]['status'] == 'hold'
    assert result['other'] == []


def test_new_cohort_recalculates_without_mutating_previous_line(tmp_path, cycle_input):
    result = run(tmp_path, setup(cycle_input)+r'''
const old=trendBitcoinCycle(f.full,f.representative,'linear'),before=JSON.stringify(old),next={...f.full,snapshot_id:'full-b',source_snapshot_id:'source-b',bars:f.full.bars.map(b=>({...b,bar_id:b.bar_id.slice(0,-1)+(b.bar_id.endsWith('a')?'b':'a')}))},fresh=trendBitcoinCycle(next,f.representative,'linear');
process.stdout.write(JSON.stringify({unchanged:before===JSON.stringify(old),old:old[0].source_full_snapshot_id,fresh:fresh[0].source_full_snapshot_id,idsDiffer:old[0].line_id!==fresh[0].line_id}));''')
    assert result == dict(unchanged=True,old='full-a',fresh='full-b',idsDiffer=True)


def test_invalid_source_binding_cannot_enable_cycle(tmp_path, cycle_input):
    result = run(tmp_path, setup(cycle_input)+r'''
const current={asset_id:'bitcoin',snapshot_id:'wrong-source',content_hash:'x'},body={...f.representative,as_of:'now',analyses:{linear:{representatives:[]}}};
Object.defineProperty(body,TREND_REPRESENTATIVE_PROOF,{value:{source:'source-a',full:'full-a'}});TREND_REPRESENTATIVE_DETAILS.set('bitcoin',body);
const analysis=trendRepresentativeAnalysis(current,f.full,'linear');process.stdout.write(JSON.stringify({lines:analysis.lines,cycle:analysis.cycle_2023}));''')
    assert result == dict(lines=[],cycle=[])


def test_additive_selection_filters_and_supplement_failure_preserve_original_three(tmp_path, cycle_input):
    result = run(tmp_path, setup(cycle_input)+r'''
const current={asset_id:'bitcoin',snapshot_id:'source-a',content_hash:'hash-a',as_of:'now'},base=['regression_200','current_structure','major_structure'].map(slot=>({slot,line_id:slot,status:'ready',kind:'regression',axis:'linear',slope:1,intercept:10})),body={as_of:'now',snapshot_id:'rep-a',analyses:{linear:{representatives:base}},projection_sessions:f.representative.projection_sessions};
Object.defineProperty(body,TREND_REPRESENTATIVE_PROOF,{value:{source:'source-a',sourceHash:'hash-a',full:'full-a',manifest:f.full.critical_manifest_sha256,payload:'payload-a'}});TREND_REPRESENTATIVE_DETAILS.set('bitcoin',body);
const supplement={...f.representative,analyses:{linear:{boundaries:[]}}};Object.defineProperty(supplement,TREND_LONG_PROOF,{value:{source:'source-a',full:'full-a',representative:'rep-a',representativePayload:'payload-a'}});TREND_LONG_DETAILS.set('bitcoin',supplement);
const before=JSON.stringify(base),all=trendRepresentativeAnalysis(current,f.full,'linear'),pair=trendRepresentativeAnalysis(current,f.full,'linear','long_boundaries'),focus=trendRepresentativeAnalysis(current,f.full,'linear','regression_200');TREND_LONG_DETAILS.delete('bitcoin');const failed=trendRepresentativeAnalysis(current,f.full,'linear');
process.stdout.write(JSON.stringify({all:all.lines.map(x=>x.slot),pair:pair.lines.map(x=>x.slot),focus:focus.lines.map(x=>x.slot),failed:failed.lines.map(x=>x.line_id),unchanged:before===JSON.stringify(base)}));''')
    assert result['all'] == ['regression_200','current_structure','major_structure','cycle_2023']
    assert result['pair'] == ['cycle_2023'] and result['focus'] == ['regression_200']
    assert result['failed'] == ['regression_200','current_structure','major_structure']
    assert result['unchanged']


def test_versioned_policy_matches_ui(tmp_path):
    policy = yaml.safe_load((Path(__file__).parents[2]/'data/contracts/trendlines_bitcoin_cycle_v1.yaml').read_text())
    ui = run(tmp_path, 'process.stdout.write(JSON.stringify(TREND_BITCOIN_CYCLE_POLICY));')
    assert all(policy[k] == v for k,v in ui.items())
    assert not policy['official_forecast_write'] and not policy['verified_boundary']
