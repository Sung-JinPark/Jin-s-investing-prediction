"""Render backend line equations exactly; independently test route and tamper gates."""
from __future__ import annotations

import copy
import hashlib
import json
import runpy
import shutil
import subprocess
import math
from datetime import date, timedelta
from pathlib import Path

import pytest
from ai_fc import dashboard

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / 'src/ai_fc/dashboard_parts/trendlines.js'
MAIN_SOURCE = ROOT / 'src/ai_fc/dashboard_parts/dashboard.js'


def fixture():
    return runpy.run_path(str(ROOT / 'tools/preview_trendlines.py'))['fixture_projection']()


def research_detail_fixture():
    """Synthetic geometry only: prove research qualification and gaps at the UI boundary."""
    detail = fixture()['details']['sk-hynix']
    detail.update(status='unverified_display', contract_id='trendlines_research_display_v1',
                  publication_class='research_source', verified_source=False, numbers_visible=True,
                  official_forecast_write=False, source_context='user_authorized_public_html_research',
                  adjustment_verified=False, historical_signals_available=False,
                  source_url='https://finance.yahoo.com/quote/000660.KS/history/',
                  retrieved_at='2026-10-13T06:49:55+00:00')
    detail['source_identity'] = {'rights_status': 'uncertified_research_source',
                                 'price_basis': 'provider_reported_ohlc_current_vintage'}
    detail['guards'] = {'approved_free_ohlc': False}
    for windows in detail['analyses'].values():
        for analysis in windows.values():
            analysis['events'] = []
            analysis['borders']['broken'] = []
            for line in analysis['lines']:
                line['state'] = 'research_reference'
            for key in ('down', 'up'):
                for row in analysis['borders'][key]:
                    row['state'] = 'research_reference'
    missing = detail['bars'].pop(-2)
    detail['gaps'] = [{'session': missing['session'], 'session_index': missing['session_index'],
                       'reason': 'source_null_ohlc_no_fill'}]
    last = detail['bars'][-1]
    detail['intraday_quote'] = {'date': last['session'], 'time': '15:19:59',
                                'session_index': last['session_index'], 'price': last['high'] + 20,
                                'source_url': detail['source_url'], 'retrieved_at': detail['retrieved_at'],
                                'status': 'intraday_snapshot_not_final_close'}
    detail['quality'] = {'stale': True, 'expected_completed_session': '2026-10-12'}
    return detail


def run(tmp_path, program, extra=''):
    node = shutil.which('node')
    if not node:
        pytest.skip('node not available')
    source = SOURCE.read_text(encoding='utf-8')
    helpers = source[source.index('const TREND_ASSETS='):source.index('globalThis.TrendlineUI=')]
    path = tmp_path / 'trend_probe.cjs'
    path.write_text("const esc=s=>String(s??'');\n" + helpers + '\n' + extra + '\n' + program, encoding='utf-8')
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr[:3000]
    return json.loads(result.stdout)


def test_svg_endpoints_and_tooltip_equations_keep_backend_values(tmp_path):
    detail = fixture()['details']['sk-hynix']
    out = run(tmp_path, 'const d=' + json.dumps(detail) + r''';
const before=JSON.stringify(d),linear=trendChartModel(d,63,'linear',390),log=trendChartModel(d,63,'log',390);
const svg=trendSvg(d,linear,{label:'fixture',currency:'KRW'}),line=linear.lines[0],last=line.points.at(-1);
process.stdout.write(JSON.stringify({
 exactEndpoint:svg.includes(`${linear.x(last.index).toFixed(3)},${linear.y(last.price).toFixed(3)}`),
 barCount:(svg.match(/data-trend-bar=/g)||[]).length,
 sameInput:JSON.stringify(d)===before,eq:trendLinePrice(line,last.index,'linear')===last.price,
 logEq:Math.abs(trendLinePrice(log.lines[0],log.lines[0].points.at(-1).index,'log')-log.lines[0].points.at(-1).price)<1e-7,
 containedTicks:linear.ticks.every(price=>linear.y(price)>=linear.T&&linear.y(price)<=linear.H-linear.B),
 counts:[63,252,756].map(period=>trendChartModel(d,period).bars.length)
}));''')
    assert out['exactEndpoint'] and out['sameInput'] and out['eq'] and out['logEq'] and out['containedTicks']
    assert out['barCount'] == 63 and out['counts'] == [63, 252, 756]


def test_positive_prices_keep_nonnegative_linear_axis_without_changing_values(tmp_path):
    detail = fixture()['details']['sk-hynix']
    out = run(tmp_path, 'const d=' + json.dumps(detail) + r''';
const a=d.analyses.linear['63'],line=a.lines[0];
line.intercept=2000000;line.slope=(20-line.intercept)/(line.points.at(-1).index-line.coordinate_origin_index);
for(const point of line.points)point.price=trendLinePrice(line,point.index,'linear');
line.current_price=trendLinePrice(line,d.bars.at(-1).session_index,'linear');
for(const key of ['down','up','broken'])for(const border of a.borders[key])if(border.line_id===line.line_id)border.price=line.current_price;
const before=JSON.stringify(d),m=trendChartModel(d,63,'linear'),prices=m.bars.flatMap(row=>[row.low,row.high]).concat(m.lines.flatMap(row=>row.points.map(point=>point.price)));
process.stdout.write(JSON.stringify({minimumTick:m.ticks[0],unchanged:before===JSON.stringify(d),allVisible:prices.every(price=>m.y(price)>=m.T&&m.y(price)<=m.H-m.B),smallPricePreserved:line.points.at(-1).price}));''')
    assert out['minimumTick'] == 0 and out['unchanged'] and out['allVisible']
    assert out['smallPricePreserved'] == pytest.approx(20, abs=1e-6)


@pytest.mark.parametrize('problem', ['ohlc', 'unit', 'order', 'point', 'equation', 'current', 'border', 'hold'])
def test_invalid_price_or_line_fails_instead_of_clipping(problem, tmp_path):
    detail = fixture()['details']['sk-hynix']
    if problem == 'ohlc':
        detail['bars'][0]['low'] = detail['bars'][0]['high'] + 1
    elif problem == 'unit':
        detail['bars'][0]['close'] = '100'
    elif problem == 'order':
        detail['bars'][1]['session'] = detail['bars'][0]['session']
    elif problem == 'point':
        detail['analyses']['linear']['63']['lines'][0]['points'][0]['price'] = -1
    elif problem == 'equation':
        detail['analyses']['linear']['63']['lines'][0]['points'][0]['price'] += 100
    elif problem == 'current':
        detail['analyses']['linear']['63']['lines'][0]['current_price'] += 100
    elif problem == 'border':
        borders = detail['analyses']['linear']['63']['borders']
        (borders['down'] or borders['up'])[0]['price'] += 100
    else:
        detail['status'] = 'hold'
    out = run(tmp_path, 'const d=' + json.dumps(detail) + ";let rejected=false;try{trendChartModel(d);}catch(error){rejected=true;}process.stdout.write(JSON.stringify({rejected}));")
    assert out['rejected']


def test_independent_route_keeps_future_data_failure_from_blocking_trendlines(tmp_path):
    source = MAIN_SOURCE.read_text(encoding='utf-8')
    routes = source[source.index('function parseCanonicalRoute'):source.index('function renderFuturePathsLoadState')]
    out = run(tmp_path, "process.stdout.write(JSON.stringify(parseCanonicalRoute('#future/trendlines/bitcoin')));", extra=routes)
    assert out == {'section': 'future', 'view': 'trendlines', 'arg': {'asset': 'bitcoin'}}
    assert "const futurePathsRequested=v==='flow';" in source
    categories = source[source.index('const MID_CATEGORIES='):source.index('function midCategories')]
    assert categories.index("hash:'#future/liquidity'") < categories.index("hash:'#future/trendlines'")


@pytest.mark.parametrize('raw_hash,asset', [
    ('#future/trendlines/%', 'invalid-asset'),
    ('#future/trendlines/%E0%A4%A', 'invalid-asset'),
    ('#future/trendlines/sk-hynix/unexpected', 'invalid-asset'),
    ('#future/trendlines/sk%2Dhynix', 'sk-hynix'),
    ('#future/trendlines', 'sk-hynix'),
])
def test_malformed_asset_hash_does_not_throw_or_leave_another_asset_selected(tmp_path, raw_hash, asset):
    source = MAIN_SOURCE.read_text(encoding='utf-8')
    routes = source[source.index('function parseCanonicalRoute'):source.index('function renderFuturePathsLoadState')]
    out = run(tmp_path, 'process.stdout.write(JSON.stringify(parseCanonicalRoute(' + json.dumps(raw_hash) + ')));', extra=routes)
    assert out == {'section': 'future', 'view': 'trendlines', 'arg': {'asset': asset}}


@pytest.mark.parametrize('problem', [None, 'hash', 'snapshot', 'late_summary'])
def test_lazy_loader_verifies_bytes_metadata_and_summary_identity(tmp_path, problem):
    base, sidecars = dashboard.split_trendlines_data({'trendlines': fixture()})
    payload = copy.deepcopy(sidecars['sk-hynix'])
    if problem == 'snapshot':
        payload['data']['trendlines']['snapshot_id'] = 'different'
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    if problem == 'snapshot':
        base['trendlines']['assets'][0]['deferred_data']['payload_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    if problem == 'hash':
        raw += ' '
    source = SOURCE.read_text(encoding='utf-8')
    loader = source[source.index('const TRENDLINES_PROMISES='):source.index('const TREND_ASSETS=')]
    late = "DATA.trendlines.assets[0]={...DATA.trendlines.assets[0]};" if problem == 'late_summary' else ''
    program = "let DATA=" + json.dumps(base) + ";globalThis.TrendlineUI={validate:trendValidateDetail};globalThis.window={__TRENDLINES_URL__:'trendlines/'};globalThis.crypto=require('node:crypto').webcrypto;globalThis.fetch=async()=>{" + late + "return {ok:true,text:async()=>" + json.dumps(raw) + "};};" + loader + r''';
(async()=>{let rejected=false;try{await ensureTrendlineData('sk-hynix');}catch(error){rejected=true;}process.stdout.write(JSON.stringify({rejected,loaded:!!DATA.trendlines.details?.['sk-hynix']}));})();'''
    out = run(tmp_path, program)
    assert out['rejected'] == (problem is not None)
    assert out['loaded'] == (problem is None)


def test_real_engine_snapshot_equations_are_renderable_without_refitting(tmp_path):
    from ai_fc.trendlines import engine
    inputs = runpy.run_path(str(ROOT / 'src/tests/test_trendlines_engine.py'))['fixture_inputs'](100)
    asset, bars, cutoff, config, policy = inputs
    detail = engine.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    assert engine.verify_asset_snapshot(detail, bars, asset, config=config, source_policy=policy)['ok']
    out = run(tmp_path, 'const d=' + json.dumps(detail) + ";const m=trendChartModel(d);process.stdout.write(JSON.stringify({lines:m.lines.length,bars:m.bars.length,log:trendChartModel(d,63,'log').lines.length,hold:trendChartModel(d,252)===null}));")
    assert out['lines'] > 0 and out['log'] > 0 and out['bars'] == 63 and out['hold']


def test_research_keeps_gap_and_distinct_quote_without_making_a_candle(tmp_path):
    detail = research_detail_fixture()
    out = run(tmp_path, 'const d=' + json.dumps(detail) + r''';
const before=JSON.stringify(d),m=trendChartModel(d,63,'linear',390),svg=trendSvg(d,m,{label:'TEST FIXTURE',currency:'KRW'}),markup=trendResearchMarkup(d,{currency:'KRW'});
process.stdout.write(JSON.stringify({
 valid:trendValidateDetail(d)===d,same:before===JSON.stringify(d),
 gaps:(svg.match(/data-trend-gap=/g)||[]).length,
 candles:(svg.match(/data-trend-bar=/g)||[]).length,
 missingIsNotCandle:!svg.includes(`data-trend-bar="${d.gaps[0].session}"`),
 quote:(svg.match(/data-trend-quote-point=/g)||[]).length,
 quoteWithinAxis:m.y(m.quote.price)>m.T&&m.y(m.quote.price)<m.H-m.B,
 discloses:markup.includes('참고선 · 가격 조정 검증 전'),
 quoteSeparated:markup.includes('장중 관측')&&markup.includes('일봉'),
 folded:markup.startsWith('<details')&&!markup.includes('<details open'),
 noDateList:!markup.includes(d.gaps[0].session),
 unsafeLink:trendSourceUrl('javascript:alert(1)')
}));''')
    assert out == {'valid': True, 'same': True, 'gaps': 1, 'candles': 63,
                   'missingIsNotCandle': True, 'quote': 1, 'quoteWithinAxis': True,
                   'discloses': True, 'quoteSeparated': True, 'folded': True, 'noDateList': True, 'unsafeLink': None}


def test_quote_date_borders_use_axis_formula_and_nearest_price_order(tmp_path):
    detail = research_detail_fixture()
    out = run(tmp_path, 'const d=' + json.dumps(detail) + r''';
const before=JSON.stringify(d),checks=[];
for(const axis of ['linear','log']){
 const analysis=d.analyses[axis]['63'],quote={...d.intraday_quote,session_index:d.bars.at(-1).session_index+5},borders=trendQuoteBorders(analysis,quote,axis);
 const rows=[...borders.down,...borders.up];
 checks.push(rows.every(row=>Math.abs(row.price-trendLinePrice(row,quote.session_index,axis))<1e-7)&&borders.down.every((row,i,all)=>row.price<=quote.price&&(!i||all[i-1].price>=row.price))&&borders.up.every((row,i,all)=>row.price>quote.price&&(!i||all[i-1].price<=row.price))&&borders.down.length<=3&&borders.up.length<=3);
}
process.stdout.write(JSON.stringify({checks,unchanged:before===JSON.stringify(d)}));''')
    assert out == {'checks': [True, True], 'unchanged': True}


@pytest.mark.parametrize('axis', ['linear', 'log'])
@pytest.mark.parametrize('quote_offset', [-1, 0, 5])
def test_clean_insights_use_latest_reference_and_independent_nearest_distances(tmp_path, axis, quote_offset):
    import math
    detail = research_detail_fixture()
    last = detail['bars'][-1]
    detail['intraday_quote']['session_index'] = last['session_index'] + quote_offset
    detail['intraday_quote']['date'] = last['session'] if quote_offset <= 0 else '2026-01-02'
    reference = detail['intraday_quote']['price'] if quote_offset > 0 else last['close']
    if quote_offset > 0:
        rows = []
        for line in detail['analyses'][axis]['63']['lines']:
            value = line['intercept'] + line['slope'] * (detail['intraday_quote']['session_index'] - line['coordinate_origin_index'])
            price = math.exp(value) if axis == 'log' else value
            if math.isfinite(price) and price > 0:
                rows.append((price, line['line_id']))
        down = max((row for row in rows if row[0] <= reference), default=None)
        up = min((row for row in rows if row[0] > reference), default=None)
    else:
        borders = detail['analyses'][axis]['63']['borders']
        down = (borders['down'][0]['price'], borders['down'][0]['line_id']) if borders['down'] else None
        up = (borders['up'][0]['price'], borders['up'][0]['line_id']) if borders['up'] else None
    out = run(tmp_path, 'const d=' + json.dumps(detail) + ';const axis=' + json.dumps(axis) + r''';
const before=JSON.stringify(d),m=trendInsightModel(d,63,axis),markup=trendInsightMarkup(d,63,axis,{currency:'KRW'});
process.stdout.write(JSON.stringify({m,unchanged:before===JSON.stringify(d),bounded:(markup.match(/data-trend-insight=/g)||[]).length,notConfirmed:markup.includes('추세 이탈을 확정하지 않습니다')}));''')
    assert out['unchanged'] and out['bounded'] == 2 and out['notConfirmed']
    assert out['m']['reference']['price'] == reference and out['m']['reference']['quote'] == (quote_offset > 0)
    for side, expected in [('down', down), ('up', up)]:
        row = out['m'][side]
        if expected is None:
            assert row is None
        else:
            assert row['line_id'] == expected[1]
            assert row['price'] == pytest.approx(expected[0], abs=1e-6)
            assert row['distance_percent'] == pytest.approx((expected[0] / reference - 1) * 100, abs=1e-10)


@pytest.mark.parametrize('asset,phase', [('sk-hynix', 'checking'), ('sk-hynix', 'offline'), ('sk-hynix', 'invalid'), ('mag7', 'idle')])
def test_clean_empty_loading_and_validation_states_never_claim_ready_or_show_technical_controls(tmp_path, asset, phase):
    out = run(tmp_path, 'process.stdout.write(JSON.stringify({markup:trendEmptyMarkup(' + json.dumps(asset) + ',' + json.dumps(phase) + ')}));')
    text = out['markup']
    assert '<button' not in text and '<svg' not in text
    assert not any(term in text for term in ('로컬', '개인', '파일', '매수', '매도', '예측', '확정 이탈'))
    assert ('시세를 확인하고 있습니다' in text) == (phase == 'checking')
    if phase == 'invalid':
        assert '자료 검증 보류' in text


@pytest.mark.parametrize('missing_anchors', [False, True])
def test_clean_render_orders_chart_before_explanation_insights_and_folded_source(tmp_path, missing_anchors):
    projection = fixture()
    if missing_anchors:
        line = projection['details']['sk-hynix']['analyses']['linear']['63']['lines'][0]
        line['first_anchor'] = None
        line.pop('second_anchor')
    program = local_browser_stub() + 'globalThis.DATA={trendlines:' + json.dumps(projection) + r'''};
const rendered={};const box=()=>({innerHTML:'',clientWidth:1000,querySelector(){return null}});
const pieces={'.trend-content':box(),'[data-trend-current-chart]':box(),'[data-trend-full-chart]':box(),'[data-trend-full-coverage]':box(),'[data-trend-full-insights]':box(),'[data-trend-full-line-details]':box(),'[data-trend-direction-controls]':box(),'[data-trend-insights]':box(),'[data-trend-line-details]':box(),'[data-trend-local-message]':nodes['[data-trend-local-message]']};
globalThis.el=html=>{rendered.outer=html;return {isConnected:true,querySelector:key=>pieces[key]??null,querySelectorAll:()=>[]}};
globalThis.mount=()=>{};bindTrendChart=()=>{};TREND_LOCAL_ENABLED=false;
renderTrendlinePage({asset:'sk-hynix'});stopTrendLocalSession();
process.stdout.write(JSON.stringify({outer:rendered.outer,body:pieces['.trend-content'].innerHTML,chart:pieces['[data-trend-current-chart]'].innerHTML,full:pieces['[data-trend-full-chart]'].innerHTML,insights:pieces['[data-trend-insights]'].innerHTML,lines:pieces['[data-trend-line-details]'].innerHTML}));'''
    out = run(tmp_path, program)
    combined = out['outer'] + out['body']
    assert not any(token in combined for token in ('data-trend-local-connect', 'data-trend-private', 'trend-research"', 'trend-gap-note', 'input type="file"'))
    body = out['body']
    assert body.index('class="trend-title"') < body.index('class="trend-controls trend-axis-controls"') < body.index('class="trend-chart"')
    assert body.index('class="trend-chart"') < body.index('class="trend-explanation"') < body.index('data-trend-insights') < body.index('class="trend-data-meta"')
    assert '<svg' in out['chart'] and out['insights'].count('data-trend-insight=') == 2
    assert '전체 추세선을 확인하고 있습니다' in out['full']
    assert body.count('class="trend-chart"') == 2
    assert body.index('data-trend-version="full"') < body.index('data-trend-version="current"')
    assert '<details class="trend-data-meta">' in body and '<details open' not in body
    assert 'NaN' not in out['lines'] and 'undefined' not in out['lines']


def test_actual_research_capture_projection_is_renderable_without_source_approval(tmp_path):
    from ai_fc.trendlines import contracts as C, display as D, research as R
    source = runpy.run_path(str(ROOT / 'src/tests/test_trendlines_research.py'))
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    raw = source['public_html'](gap=True)
    cutoff = source['FETCHED']
    R.capture_html(tmp_path, 'bitcoin', raw, source['receipt'](raw), as_of=cutoff)
    projection = R.attach_projection(tmp_path, D.load_projection(tmp_path, now=cutoff), now=cutoff, allow_private_research=True)
    base, sidecars = dashboard.split_trendlines_data({'trendlines': projection})
    detail = sidecars['bitcoin']['data']['trendlines']
    out = run(tmp_path, 'const d=' + json.dumps(detail) + ";const m=trendChartModel(d);process.stdout.write(JSON.stringify({status:d.status,bars:m.bars.length,gaps:m.gaps.length,lines:m.lines.every(row=>row.state==='research_reference'),events:m.analysis.events.length}));")
    assert out == {'status': 'unverified_display', 'bars': 63, 'gaps': 1, 'lines': True, 'events': 0}
    assert next(row for row in base['trendlines']['assets'] if row['asset_id'] == 'bitcoin')['official_snapshot_status'] == 'hold'
    assert not C.load_source_policy(tmp_path)['sources']
    assert all(row['status'] == 'hold' for row in D.load_projection(tmp_path, now=cutoff)['assets'])
    preview = runpy.run_path(str(ROOT / 'tools/preview_trendlines.py'))['build_research_preview']
    original = {str(path.relative_to(tmp_path)): path.read_bytes()
                for path in (tmp_path / R.ROOT).rglob('*') if path.is_file()}
    index = preview(tmp_path, tmp_path / 'private_site')
    assert index.is_file() and 'noindex,nofollow' in index.read_text(encoding='utf-8')
    assert (index.parent / 'trendlines/bitcoin.json').is_file()
    assert json.loads((index.parent / 'private_preview_manifest.json').read_text())['public_export_allowed'] is False
    assert original == {str(path.relative_to(tmp_path)): path.read_bytes()
                        for path in (tmp_path / R.ROOT).rglob('*') if path.is_file()}
    with pytest.raises(ValueError, match='must remain inside'):
        preview(tmp_path, tmp_path.parent / 'outside-research')
    envelope = R.export_private_import(tmp_path, 'bitcoin', now=cutoff)
    out = run(tmp_path, 'globalThis.crypto=require("node:crypto").webcrypto;globalThis.fetch=()=>{throw new Error("file must never be sent over network")};const raw=' + json.dumps(json.dumps(envelope)) + r''';
(async()=>{const d=await parseTrendPrivateImport(raw,'bitcoin');process.stdout.write(JSON.stringify({status:d.status,hash:d.content_hash,receipt:d.receipt_id,bars:d.bars.length}));})();''')
    assert out['status'] == 'unverified_display' and out['hash'] == envelope['payload_sha256']
    assert out['receipt'] == detail['receipt_id'] and out['bars'] == 99
    missing_finality = json.loads(envelope['payload_json'])
    missing_finality['gaps'].append({'session': '2024-04-10', 'session_index': 100,
                                     'reason': 'source_current_session_finality_unverified'})
    envelope['payload_json'] = json.dumps(missing_finality, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    envelope['payload_sha256'] = hashlib.sha256(envelope['payload_json'].encode()).hexdigest()
    out = run(tmp_path, 'globalThis.crypto=require("node:crypto").webcrypto;const raw=' + json.dumps(json.dumps(envelope)) + r''';
(async()=>{const d=await parseTrendPrivateImport(raw,'bitcoin');process.stdout.write(JSON.stringify({reason:d.gaps.at(-1).reason,bars:d.bars.length}));})();''')
    assert out == {'reason': 'source_current_session_finality_unverified', 'bars': 99}


@pytest.fixture(scope='module')
def private_import_envelope(tmp_path_factory):
    from ai_fc.trendlines import contracts as C, research as R
    source = runpy.run_path(str(ROOT / 'src/tests/test_trendlines_research.py'))
    store = tmp_path_factory.mktemp('private-import-receipt')
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        destination = store / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    raw_html = source['public_html']()
    R.capture_html(store, 'bitcoin', raw_html, source['receipt'](raw_html), as_of=source['FETCHED'])
    return R.export_private_import(store, 'bitcoin', now=source['FETCHED'])


@pytest.mark.parametrize('problem', ['corrupt', 'oversize', 'payload_oversize', 'asset', 'scope',
                                    'approved', 'receipt', 'ohlc', 'quote', 'content_hash',
                                    'unit', 'anchor', 'userinfo', 'port', 'fragment', 'secret',
                                    'axis', 'window', 'point_date', 'projection'])
def test_private_import_rejects_bad_files_without_network_or_storage(tmp_path, problem, private_import_envelope):
    """Use the exact Python canonical bytes exported for a disposable research capture."""
    envelope = copy.deepcopy(private_import_envelope)
    detail = json.loads(envelope['payload_json'])
    if problem == 'corrupt':
        envelope['payload_json'] += ' '
    elif problem == 'payload_oversize':
        envelope['payload_json'] += ' ' * 262144
    elif problem == 'asset':
        envelope['asset_id'] = 'sk-hynix'
    elif problem == 'scope':
        envelope['publication_scope'] = 'public'
    elif problem == 'approved':
        detail['verified_source'] = True
    elif problem == 'receipt':
        detail['receipt_id'] = 'receipt-is-missing'
    elif problem == 'ohlc':
        detail['bars'][0]['high'] = 1
    elif problem == 'quote':
        detail['intraday_quote'] = {'date': '2024-04-10', 'price': 115, 'session_index': 100,
                                    'currency': 'USD', 'status': 'intraday_snapshot_not_final_close',
                                    'observed_at': '2024-04-10T02:00:00+00:00',
                                    'retrieved_at': detail['retrieved_at'], 'source_url': detail['source_url']}
    elif problem == 'content_hash':
        detail['content_hash'] = envelope['payload_sha256']
    elif problem == 'unit':
        detail['asset']['unit'] = 'index_points'
    elif problem == 'anchor':
        detail['analyses']['linear']['63']['lines'][0]['first_anchor']['price'] += 1
    elif problem == 'userinfo':
        detail['source_url'] = detail['source_url'].replace('https://', 'https://credentials@')
    elif problem == 'port':
        detail['source_url'] = detail['source_url'].replace('finance.yahoo.com', 'finance.yahoo.com:8443')
    elif problem == 'fragment':
        detail['source_url'] += '#private-token'
    elif problem == 'secret':
        detail['source_url'] += '&API-KEY=untrusted-fixture'
    elif problem == 'axis':
        detail['analyses']['linear']['63']['lines'][0]['axis'] = 'log'
    elif problem == 'window':
        detail['analyses']['linear']['63']['lines'][0]['window'] = 252
    elif problem == 'point_date':
        detail['analyses']['linear']['63']['lines'][0]['points'][-1]['session'] = '2024-12-31'
    elif problem == 'projection':
        detail['analyses']['linear']['63']['lines'][0]['projections'][-1]['index'] += 1
    if problem in {'approved', 'receipt', 'ohlc', 'quote', 'content_hash', 'unit', 'anchor', 'userinfo', 'port', 'fragment', 'secret', 'axis', 'window', 'point_date', 'projection'}:
        envelope['payload_json'] = json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        envelope['payload_sha256'] = hashlib.sha256(envelope['payload_json'].encode()).hexdigest()
    raw = json.dumps(envelope) if problem != 'oversize' else ' ' * 524289
    out = run(tmp_path, 'globalThis.crypto=require("node:crypto").webcrypto;globalThis.fetch=()=>{throw new Error("no network")};globalThis.localStorage={setItem:()=>{throw new Error("no storage")}};const raw=' + json.dumps(raw) + r''';
(async()=>{let rejected=false;try{await parseTrendPrivateImport(raw,'bitcoin');}catch(error){rejected=true;}process.stdout.write(JSON.stringify({rejected}));})();''')
    assert out['rejected']


@pytest.mark.parametrize('problem', [None, 'zero', 'negative', 'missing', 'phantom_border', 'positive_formula'])
def test_unavailable_current_extension_keeps_past_geometry_without_inventing_price(tmp_path, problem):
    program = 'const d=' + json.dumps(fixture()['details']['sk-hynix']) + ';const problem=' + json.dumps(problem) + r''';
const a=d.analyses.linear['63'],line=a.lines[0],last=d.bars.at(-1).session_index;
line.slope=-30000;line.intercept=1400000;line.direction='falling';line.current_price=null;
line.points=line.points.slice(0,2).map(point=>({...point,price:trendLinePrice(line,point.index,'linear')}));
line.first_anchor={...line.first_anchor,price:line.points[0].price};line.second_anchor={...line.second_anchor,price:line.points[1].price};
for(const side of ['down','up','broken'])a.borders[side]=a.borders[side].filter(row=>row.line_id!==line.line_id);
if(problem==='zero')line.current_price=0;
if(problem==='negative')line.current_price=trendLinePrice(line,last,'linear');
if(problem==='missing')delete line.current_price;
if(problem==='phantom_border')a.borders.down.push({line_id:line.line_id,price:1e-8});
if(problem==='positive_formula'){line.slope=0;for(const point of line.points)point.price=line.intercept;}
const before=JSON.stringify(d);let rejected=false,proof=null;
try{const m=trendChartModel(d,63,'linear',390);proof={unchanged:before===JSON.stringify(d),linePreserved:m.lines.includes(line),pastPoints:line.points.length,unavailable:trendLineReadout(line,last,'linear',{currency:'KRW'}),past:trendLineReadout(line,line.points[0].index,'linear',{currency:'KRW'}),svg:trendSvg(d,m,{label:'TEST FIXTURE',currency:'KRW'}).includes(`data-trend-line="${line.line_id}"`)}}catch(_){rejected=true}
process.stdout.write(JSON.stringify({rejected,proof}));'''
    out = run(tmp_path, program)
    assert out['rejected'] == (problem is not None)
    if problem is None:
        assert out['proof'] == {'unchanged': True, 'linePreserved': True, 'pastPoints': 2,
                                'unavailable': '지지 연장값 없음', 'past': '지지 1,400,000원', 'svg': True}


@pytest.mark.parametrize('asset_id', ['constructor', '__proto__', 'toString', 'mag7'])
def test_private_import_accepts_only_own_exact_registered_research_assets(tmp_path, asset_id):
    envelope = {'schema_version': 1, 'contract_id': 'trendlines_private_import_v1', 'publication_scope': 'private_only',
                'asset_id': asset_id, 'payload_json': '{}', 'payload_sha256': hashlib.sha256(b'{}').hexdigest()}
    out = run(tmp_path, 'globalThis.crypto=require("node:crypto").webcrypto;const raw=' + json.dumps(json.dumps(envelope)) + ';const asset=' + json.dumps(asset_id) + r''';
(async()=>{let rejected=false;try{await parseTrendPrivateImport(raw,asset);}catch(error){rejected=true;}process.stdout.write(JSON.stringify({rejected}));})();''')
    assert out['rejected']


def local_status_fixture(envelope):
    detail = json.loads(envelope['payload_json'])
    rows = []
    for asset_id in ('sk-hynix', 'soxx', 'nasdaq', 'sp500', 'bitcoin', 'dow', 'mag7'):
        ready = asset_id == detail['asset_id']
        rows.append({'asset_id': asset_id, 'status': 'ready' if ready else 'hold' if asset_id == 'mag7' else 'missing',
                     'last_success': detail['as_of'] if ready else None, 'last_attempt': detail['as_of'] if ready else None,
                     'source_asof': detail['as_of'] if ready else None,
                     'observation_through': detail['observation_through'] if ready else None,
                     'stale': not ready and asset_id != 'mag7', 'reason': None, 'error': None,
                     'next_refresh_kst': '2027-01-01T07:30:00+09:00'})
    return {'schema_version': 1, 'contract_id': 'trendlines_local_status_v1', 'publication_scope': 'private_only',
            'running': True, 'refresh_in_progress': False, 'next_refresh_kst': '2027-01-01T07:30:00+09:00', 'assets': rows}


def local_browser_stub():
    return r'''
const TREND_PRIVATE_DETAILS=new Map();
const storage={},listeners={},nodes={};
globalThis.localStorage={getItem:key=>storage[key]??null,setItem:(key,value)=>storage[key]=value};
globalThis.document={visibilityState:'visible',addEventListener:(key,fn)=>listeners[key]=fn,removeEventListener:key=>delete listeners[key]};
globalThis.window={addEventListener:(key,fn)=>listeners[key]=fn,removeEventListener:key=>delete listeners[key]};
globalThis.crypto=require('node:crypto').webcrypto;
const node=()=>({textContent:'',innerHTML:'',dataset:{},attrs:{},classList:{toggle(){}},setAttribute(key,value){this.attrs[key]=value},addEventListener(key,fn){this[key]=fn}});
nodes['[data-trend-local-message]']=node();
const root={isConnected:true,querySelector:key=>nodes[key]??null};
const response=(raw,status=200)=>({ok:status===200,status,headers:{get:()=>null},text:async()=>raw});
'''


def full_transport(body):
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    envelope = {'schema_version': 1, 'contract_id': 'trendlines_private_full_transport_v1',
                'publication_scope': 'private_only', 'asset_id': body['asset_id'],
                'snapshot_id': body['snapshot_id'], 'payload_json': payload,
                'payload_sha256': hashlib.sha256(payload.encode()).hexdigest()}
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@pytest.fixture(scope='module')
def full_history_fixture(private_import_envelope):
    """Synthetic older OHLC and supplied equations; no provider fetch or model fitting."""
    current = json.loads(private_import_envelope['payload_json'])
    current['content_hash'] = private_import_envelope['payload_sha256']
    for bar in current['bars']:
        bar['session_index'] += 800
    for windows in current['analyses'].values():
        for analysis in windows.values():
            for row in analysis.get('projection_sessions', []): row['index'] += 800
            for line in analysis['lines']:
                line['coordinate_origin_index'] += 800
                for anchor in (line['first_anchor'], line['second_anchor']): anchor['index'] += 800
                for point in line['points']: point['index'] += 800
                for projection in line['projections']: projection['index'] += 800
    first = date.fromisoformat(current['bars'][0]['session'])
    older = []
    for index in range(800):
        session = (first - timedelta(days=800 - index)).isoformat()
        low = 70 + .02 * index
        older.append({'session': session, 'session_index': index, 'open': low + 1,
                      'high': low + 4, 'low': low, 'close': low + 2,
                      'bar_id': 'research-bar-' + hashlib.sha256(session.encode()).hexdigest()})
    bars = older + copy.deepcopy(current['bars'])
    last = bars[-1]
    snapshot_id = 'research-full-snapshot-' + 'a' * 64
    manifest = {key: copy.deepcopy(value) for key, value in current.items() if key not in ('bars', 'analyses', 'content_hash')}
    manifest.update(schema_version=1, contract_id='trendlines_private_full_manifest_v1',
                    snapshot_id=snapshot_id, source_snapshot_id=current['snapshot_id'],
                    source_engine_snapshot_id=current['engine_snapshot_id'],
                    source_engine_content_hash=current['source_snapshot_hash'],
                    publication_scope='private_only', full_scope='all_captured_finalized_sessions',
                    points_encoding='equations', chunk_size=512, bars_sha256='e' * 64, bar_count=len(bars), observation_start=bars[0]['session'],
                    full_config_sha256='b' * 64,
                    full_parameters={'bars': len(bars), 'minimum_bars': 771, 'left': 10, 'right': 10, 'min_anchor_gap': 60})
    manifest['analyses'] = {}
    for axis in ('linear', 'log'):
        sessions = [{'offset': offset, 'index': last['session_index'] + offset,
                     'session': (date.fromisoformat(last['session']) + timedelta(days=offset)).isoformat()}
                    for offset in (1, 7, 30)]
        lines = []
        for side, a, b in (('support', 60, 180), ('resistance', 80, 210)):
            field = 'low' if side == 'support' else 'high'
            transform = math.log if axis == 'log' else lambda value: value
            p1, p2 = bars[a][field], bars[b][field]
            origin = bars[a]['session_index']
            intercept = transform(p1)
            slope = (transform(p2) - intercept) / (bars[b]['session_index'] - origin)
            price = lambda index: math.exp(intercept + slope * (index - origin)) if axis == 'log' else intercept + slope * (index - origin)
            line = {'line_id': 'trend-line-' + hashlib.sha256(f'{axis}-{side}'.encode()).hexdigest()[:32],
                    'axis': axis, 'window': len(bars), 'side': side, 'direction': 'rising',
                    'state': 'research_reference', 'geometry_status': 'candidate', 'rank': 1, 'touch_count': 2,
                    'coordinate_origin_index': origin, 'intercept': intercept, 'slope': slope,
                    'current_price': price(last['session_index'])}
            for key, row in (('first_anchor', bars[a]), ('second_anchor', bars[b])):
                line[key] = {'session': row['session'], 'index': row['session_index'], 'price': row[field], 'bar_id': row['bar_id']}
            rows = [bars[a], bars[b], last]
            line['points'] = [{'session': row['session'], 'index': row['session_index'], 'price': price(row['session_index']), 'future': False} for row in rows]
            line['points'] += [{**row, 'price': price(row['index']), 'future': True} for row in sessions]
            line['projections'] = [{**row, 'price': price(row['index']), 'status': 'ready'} for row in sessions]
            lines.append(line)
        border = lambda line: {key: line[key] for key in ('line_id', 'side', 'direction', 'state', 'geometry_status', 'touch_count')} | {'price': line['current_price']}
        manifest['analyses'][axis] = {'full': {'status': 'ready', 'axis': axis, 'window': len(bars), 'lines': lines,
                                              'events': [], 'projection_sessions': sessions,
                                              'borders': {'down': sorted((border(line) for line in lines if line['current_price'] <= last['close']), key=lambda row: -row['price']),
                                                          'up': sorted((border(line) for line in lines if line['current_price'] > last['close']), key=lambda row: row['price']), 'broken': []}}}
    chunks = []
    manifest['chunks'] = []
    columns = ['session', 'session_index', 'open', 'high', 'low', 'close', 'bar_id']
    for index, start in enumerate(range(0, len(bars), 512)):
        values = bars[start:start + 512]
        body = {'schema_version': 1, 'contract_id': 'trendlines_private_full_bars_v1', 'publication_scope': 'private_only',
                'asset_id': current['asset_id'], 'snapshot_id': snapshot_id, 'source_snapshot_id': current['snapshot_id'],
                'chunk_index': index, 'count': len(values), 'start_index': values[0]['session_index'], 'end_index': values[-1]['session_index'],
                'bars_packed': {'columns': columns, 'bar_id_prefix': 'research-bar-',
                                'rows': [[row[key] if key != 'bar_id' else row[key].removeprefix('research-bar-') for key in columns] for row in values]}}
        raw = full_transport(body)
        chunks.append(raw)
        manifest['chunks'].append({key: body[key] for key in ('chunk_index', 'count', 'start_index', 'end_index')} |
                                  {'payload_sha256': json.loads(raw)['payload_sha256'], 'envelope_sha256': hashlib.sha256(raw.encode()).hexdigest()})
    return {'current': current, 'manifest': manifest, 'raw_manifest': full_transport(manifest), 'chunks': chunks, 'bars': bars}


def test_full_transport_restores_every_captured_bar_and_distinct_svg_with_exact_equations(tmp_path, full_history_fixture):
    fixture = full_history_fixture
    program = local_browser_stub() + 'const f=' + json.dumps(fixture) + r''';
(async()=>{const decoded=await parseTrendFullTransport(f.raw_manifest,'bitcoin'),manifest=validateTrendFullManifest(decoded.body,f.current),chunks=[];
for(const [index,raw] of f.chunks.entries())chunks.push(await parseTrendFullChunk(raw,manifest,manifest.chunks[index]));
const before=JSON.stringify(manifest),d=buildTrendFullDetail(manifest,chunks.flat(),f.current),models=['linear','log'].map(scale=>trendPlotModel(d,d.analyses[scale].full,d.bars,scale,390));
const current=trendChartModel(f.current,63,'linear',390),svg=trendSvg(d,models[0],{label:'TEST FIXTURE',currency:'USD'},'full'),currentSvg=trendSvg(f.current,current,{label:'TEST FIXTURE',currency:'USD'});
process.stdout.write(JSON.stringify({count:d.bars.length,current:current.bars.length,exact:trendSameValue(d.bars,f.bars),unchanged:before===JSON.stringify(manifest),first:d.bars[0].session,svgCount:(svg.match(/data-trend-bar=/g)||[]).length,unique:svg.includes('trend-clip-bitcoin-full')&&currentSvg.includes('trend-clip-bitcoin-current'),points:models.map(model=>model.lines.every(line=>line.points.every(point=>Math.abs(point.price-trendLinePrice(line,point.index,model===models[0]?'linear':'log'))<1e-10)))}));})();'''
    out = run(tmp_path, program)
    assert out['count'] == 900 and out['current'] == 63 and out['svgCount'] == 900
    assert out['exact'] and out['unchanged'] and out['unique'] and all(out['points'])
    assert out['first'] == fixture['bars'][0]['session']


@pytest.mark.parametrize('problem', ['wire', 'asset', 'snapshot', 'scope', 'source', 'count', 'pin', 'chunk_order',
                                    'chunk_width', 'chunk_hash', 'ohlc', 'overlap', 'anchor', 'window', 'point', 'projection', 'approved',
                                    'border_side', 'gap_metadata', 'unavailable_positive'])
def test_full_data_tampering_fails_without_replacing_current_or_last_good(tmp_path, full_history_fixture, problem):
    f = copy.deepcopy(full_history_fixture)
    manifest = f['manifest']
    raw = f['raw_manifest']
    if problem in ('wire', 'asset', 'snapshot', 'scope'):
        envelope = json.loads(raw)
        if problem == 'wire': envelope['payload_json'] += ' '
        elif problem == 'asset': envelope['asset_id'] = 'soxx'
        elif problem == 'snapshot': envelope['snapshot_id'] = 'research-full-snapshot-' + 'c' * 64
        else: envelope['publication_scope'] = 'public'
        raw = json.dumps(envelope)
    elif problem == 'source': manifest['source_snapshot_id'] = 'research-snapshot-' + 'f' * 64
    elif problem == 'count': manifest['bar_count'] += 1
    elif problem == 'pin': manifest['chunks'][0]['envelope_sha256'] = 'f' * 64
    elif problem == 'anchor': manifest['analyses']['linear']['full']['lines'][0]['first_anchor']['price'] += 1
    elif problem == 'window': manifest['analyses']['linear']['full']['window'] = 756
    elif problem == 'point': manifest['analyses']['linear']['full']['lines'][0]['points'][2]['price'] += .00001
    elif problem == 'projection': manifest['analyses']['linear']['full']['lines'][0]['projections'][-1]['session'] = '2027-01-01'
    elif problem == 'approved': manifest['guards']['approved_free_ohlc'] = True
    elif problem == 'border_side':
        border = manifest['analyses']['linear']['full']['borders']['down'][0]
        border['side'] = 'support' if border['side'] == 'resistance' else 'resistance'
    elif problem == 'gap_metadata': manifest['gaps'] = [{'session': '2023-01-01', 'session_index': 550, 'reason': 'source_session_missing_no_fill'}]
    elif problem == 'unavailable_positive':
        line = manifest['analyses']['linear']['full']['lines'][0]
        line['projections'][-1].update(status='unavailable', price=None)
        line['points'].pop()
    elif problem in ('chunk_order', 'chunk_width', 'chunk_hash', 'ohlc', 'overlap'):
        index = 1 if problem == 'overlap' else 0
        envelope = json.loads(f['chunks'][index]); body = json.loads(envelope['payload_json'])
        if problem == 'chunk_order': body['chunk_index'] = 1
        elif problem == 'chunk_width': body['bars_packed']['rows'][0].append(1)
        elif problem == 'chunk_hash': envelope['payload_json'] += ' '
        elif problem == 'ohlc': body['bars_packed']['rows'][0][3] = 1
        elif problem == 'overlap': body['bars_packed']['rows'][-1][5] += .01
        changed = json.dumps(envelope) if problem == 'chunk_hash' else full_transport(body)
        f['chunks'][index] = changed
        manifest['chunks'][index]['envelope_sha256'] = hashlib.sha256(changed.encode()).hexdigest()
        manifest['chunks'][index]['payload_sha256'] = json.loads(changed)['payload_sha256']
    if problem not in ('wire', 'asset', 'snapshot', 'scope'): raw = full_transport(manifest)
    f['raw_manifest'] = raw
    program = local_browser_stub() + 'const f=' + json.dumps(f) + r''';
(async()=>{const before=JSON.stringify(f.current);TREND_PRIVATE_DETAILS.set('bitcoin',f.current);TREND_FULL_DETAILS.set('bitcoin',{snapshot_id:'last-good'});let rejected=false;
try{const decoded=await parseTrendFullTransport(f.raw_manifest,'bitcoin'),manifest=validateTrendFullManifest(decoded.body,f.current),chunks=[];for(const [index,raw] of f.chunks.entries())chunks.push(await parseTrendFullChunk(raw,manifest,manifest.chunks[index]));buildTrendFullDetail(manifest,chunks.flat(),f.current);}catch(_){rejected=true;}
process.stdout.write(JSON.stringify({rejected,current:before===JSON.stringify(TREND_PRIVATE_DETAILS.get('bitcoin')),lastGood:TREND_FULL_DETAILS.get('bitcoin').snapshot_id==='last-good'}));})();'''
    assert run(tmp_path, program) == {'rejected': True, 'current': True, 'lastGood': True}


def test_full_loading_is_independent_bounded_readonly_and_keeps_current_view(tmp_path, full_history_fixture):
    program = local_browser_stub() + 'const f=' + json.dumps(full_history_fixture) + r''';
const requests=[],publicData={trendlines:{status:'hold'}},before=JSON.stringify(publicData);globalThis.DATA=publicData;
let finish;globalThis.fetch=(url,options)=>{requests.push({url,method:options.method,credentials:options.credentials,mode:options.mode,redirect:options.redirect,space:options.targetAddressSpace});return url.endsWith('/full')?new Promise(resolve=>finish=()=>resolve(response(f.raw_manifest))):Promise.resolve(response(f.chunks[Number(url.split('/').at(-1))]));};
(async()=>{TREND_LOCAL_ENABLED=false;const session=bindTrendLocalConnection(root,{asset:'bitcoin'});await Promise.resolve();TREND_PRIVATE_DETAILS.set('bitcoin',f.current);TREND_LOCAL_ENABLED=true;session.fullMounted=true;let paints=0;session.onFullData=()=>paints++;TREND_VIEW_OPTIONS.set('bitcoin',{period:252,scale:'log',direction:'rising'});
const first=refreshTrendFullSession(session),second=refreshTrendFullSession(session),whilePending={calls:requests.length,currentBars:trendChartModel(f.current,63).bars.length,full:TREND_FULL_DETAILS.size};finish();await Promise.all([first,second]);const full=TREND_FULL_DETAILS.get('bitcoin');const initialCalls=requests.length;await refreshTrendFullSession(session);const repeatedCalls=requests.length;stopTrendLocalSession();
process.stdout.write(JSON.stringify({whilePending,count:full.bar_count,phase:session.fullPhase,requests,initialCalls,repeatedCalls,paints,view:TREND_VIEW_OPTIONS.get('bitcoin'),unchanged:before===JSON.stringify(publicData),storage:Object.keys(storage)}));})();'''
    # A second manifest refresh returns immediately from the existing snapshot cache.
    program = program.replace("url.endsWith('/full')?new Promise(resolve=>finish=()=>resolve(response(f.raw_manifest)))", "url.endsWith('/full')?(finish?Promise.resolve(response(f.raw_manifest)):new Promise(resolve=>finish=()=>resolve(response(f.raw_manifest))))")
    out = run(tmp_path, program)
    assert out['whilePending'] == {'calls': 1, 'currentBars': 63, 'full': 0}
    assert out['count'] == 900 and out['phase'] == 'connected'
    assert out['initialCalls'] == 3 and out['repeatedCalls'] == 4
    assert out['view'] == {'period': 252, 'scale': 'log', 'direction': 'rising'}
    assert out['unchanged'] and out['storage'] == []
    assert all(row['method'] == 'GET' and row['credentials'] == 'omit' and row['mode'] == 'cors'
               and row['redirect'] == 'error' and row['space'] == 'loopback' for row in out['requests'])
    assert out['requests'][1]['url'].endswith('/full/' + full_history_fixture['manifest']['snapshot_id'] + '/bars/0')


@pytest.mark.parametrize('problem', ['corrupt', 'old_source', 'route_abort', 'hidden_abort'])
def test_full_failure_retains_last_good_without_current_data_or_route_mutation(tmp_path, full_history_fixture, problem):
    program = local_browser_stub() + 'const f=' + json.dumps(full_history_fixture) + ';const problem=' + json.dumps(problem) + r''';
(async()=>{const old=buildTrendFullDetail(f.manifest,f.bars,f.current);TREND_FULL_DETAILS.set('bitcoin',old);TREND_PRIVATE_DETAILS.set('bitcoin',f.current);const before=JSON.stringify(f.current);
TREND_LOCAL_ENABLED=false;const session=bindTrendLocalConnection(root,{asset:'bitcoin'});await Promise.resolve();session.fullMounted=true;session.onFullData=()=>{};TREND_LOCAL_ENABLED=true;let finish,calls=0;
const envelope=JSON.parse(f.raw_manifest);if(problem==='corrupt')envelope.payload_json+=' ';if(problem==='old_source')TREND_PRIVATE_DETAILS.set('bitcoin',{...f.current,snapshot_id:'research-snapshot-'+'d'.repeat(64)});
globalThis.fetch=(_url,options)=>{calls++;return new Promise(resolve=>finish=()=>resolve(response(JSON.stringify(envelope))));};
const pending=refreshTrendFullSession(session),signal=session.fullController.signal;if(problem==='route_abort')stopTrendLocalSession();if(problem==='hidden_abort'){document.visibilityState='hidden';listeners.visibilitychange();}finish();await pending;
const result={sameFull:TREND_FULL_DETAILS.get('bitcoin')===old,sameCurrent:before===JSON.stringify(f.current),aborted:signal.aborted,calls,phase:session.fullPhase};stopTrendLocalSession();process.stdout.write(JSON.stringify(result));})();'''
    out = run(tmp_path, program)
    assert out['sameFull'] and out['sameCurrent'] and out['calls'] == 1
    assert out['aborted'] == (problem in ('route_abort', 'hidden_abort'))
    if problem in ('corrupt', 'old_source'):
        assert out['phase'] == 'invalid'


def test_both_graphs_are_simultaneously_visible_with_actual_full_coverage(tmp_path, full_history_fixture):
    program = local_browser_stub() + 'const f=' + json.dumps(full_history_fixture) + r''';
const full=buildTrendFullDetail(f.manifest,f.bars,f.current);TREND_PRIVATE_DETAILS.set('bitcoin',f.current);TREND_FULL_DETAILS.set('bitcoin',full);
globalThis.DATA={trendlines:{assets:[{asset_id:'bitcoin',label:'비트코인',status:'hold',currency:'USD',price_unit:'USD_per_BTC'}]}};
const rendered={},box=()=>({innerHTML:'',textContent:'',clientWidth:390,querySelector(){return null}}),pieces={};
for(const key of ['.trend-content','[data-trend-current-chart]','[data-trend-full-chart]','[data-trend-full-coverage]','[data-trend-full-insights]','[data-trend-full-line-details]','[data-trend-direction-controls]','[data-trend-insights]','[data-trend-line-details]'])pieces[key]=box();pieces['[data-trend-local-message]']=nodes['[data-trend-local-message]'];
globalThis.el=html=>{rendered.outer=html;return {isConnected:true,querySelector:key=>pieces[key]??null,querySelectorAll:()=>[]}};globalThis.mount=()=>{};bindTrendChart=()=>{};TREND_LOCAL_ENABLED=false;
renderTrendlinePage({asset:'bitcoin'});stopTrendLocalSession();process.stdout.write(JSON.stringify({body:pieces['.trend-content'].innerHTML,full:pieces['[data-trend-full-chart]'].innerHTML,current:pieces['[data-trend-current-chart]'].innerHTML,coverage:pieces['[data-trend-full-coverage]'].textContent,fullInsightCount:(pieces['[data-trend-full-insights]'].innerHTML.match(/data-trend-insight=/g)||[]).length,currentInsightCount:(pieces['[data-trend-insights]'].innerHTML.match(/data-trend-insight=/g)||[]).length,view:TREND_VIEW_OPTIONS.get('bitcoin')}));'''
    out = run(tmp_path, program)
    assert out['full'].count('data-trend-bar=') == 900 and out['current'].count('data-trend-bar=') == 63
    assert '<svg' in out['full'] and '<svg' in out['current']
    assert '900개 일봉' in out['coverage'] and full_history_fixture['bars'][0]['session'] in out['coverage']
    assert out['fullInsightCount'] == out['currentInsightCount'] == 2
    assert out['view'] == {'period': 63, 'scale': 'linear', 'direction': 'all'}
    assert '전체 추세선' in out['body'] and '현재 상·하방 추세선' in out['body']


@pytest.mark.parametrize('raw', ['{"a":1,"a":2}', '{"a":1,"\\u0061":2}', '{"a":{"b":1,"b":2}}', '[{"a":1,"a":2}]', '{"a":[1,]}'])
def test_full_json_rejects_duplicate_decoded_keys_and_malformed_data(tmp_path, raw):
    out = run(tmp_path, 'const raw=' + json.dumps(raw) + r''';let rejected=false;try{trendUniqueJson(raw)}catch(_){rejected=true;}const normal='{"escaped\\"key":"\\\\\\"","array":[1,-2.0,null,true,{"nested":[]}]}';process.stdout.write(JSON.stringify({rejected,normal:trendSameValue(trendUniqueJson(normal),JSON.parse(normal))}));''')
    assert out == {'rejected': True, 'normal': True}


def test_full_cold_deadline_is_independent_and_does_not_change_current_8_second_budget(tmp_path, full_history_fixture):
    program = local_browser_stub() + 'const f=' + json.dumps(full_history_fixture) + r''';
const timers=new Map();let next=0;globalThis.setTimeout=(fn,delay)=>{const id=++next;timers.set(id,{fn,delay});return id;};globalThis.clearTimeout=id=>timers.delete(id);
globalThis.fetch=(_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));
(async()=>{TREND_LOCAL_ENABLED=false;const session=bindTrendLocalConnection(root,{asset:'bitcoin'});await Promise.resolve();TREND_PRIVATE_DETAILS.set('bitcoin',f.current);TREND_LOCAL_ENABLED=true;session.fullMounted=true;session.onFullData=()=>{};const pending=refreshTrendFullSession(session),deadline=[...timers.values()].find(row=>row.delay===20000);const current=trendChartModel(f.current,63);deadline.fn();await pending;const out={deadline:deadline.delay,phase:session.fullPhase,currentBars:current.bars.length,currentStillValid:trendValidateDetail(f.current)===f.current};stopTrendLocalSession();process.stdout.write(JSON.stringify(out));})();'''
    assert run(tmp_path, program) == {'deadline': 20000, 'phase': 'offline', 'currentBars': 63, 'currentStillValid': True}
    text = SOURCE.read_text(encoding='utf-8')
    current = text[text.index('async function refreshTrendLocalSession'):text.index('function bindTrendLocalConnection')]
    assert 'setTimeout(()=>controller.abort(),8000)' in current


def test_short_full_capture_keeps_all_candles_without_inventing_a_trendline(tmp_path, full_history_fixture):
    f = copy.deepcopy(full_history_fixture)
    manifest, bars = f['manifest'], f['current']['bars']
    manifest.update(bar_count=len(bars), observation_start=bars[0]['session'],
                    full_parameters={'bars': len(bars), 'minimum_bars': 771, 'left': 10, 'right': 10, 'min_anchor_gap': 60})
    for axis in ('linear', 'log'):
        manifest['analyses'][axis]['full'].update(status='hold', window=len(bars), lines=[],
                                                borders={'down': [], 'up': [], 'broken': []})
    columns = ['session', 'session_index', 'open', 'high', 'low', 'close', 'bar_id']
    body = {'schema_version': 1, 'contract_id': 'trendlines_private_full_bars_v1', 'publication_scope': 'private_only',
            'asset_id': 'bitcoin', 'snapshot_id': manifest['snapshot_id'], 'source_snapshot_id': manifest['source_snapshot_id'],
            'chunk_index': 0, 'count': len(bars), 'start_index': bars[0]['session_index'], 'end_index': bars[-1]['session_index'],
            'bars_packed': {'columns': columns, 'bar_id_prefix': 'research-bar-',
                            'rows': [[bar[key] if key != 'bar_id' else bar[key].removeprefix('research-bar-') for key in columns] for bar in bars]}}
    raw = full_transport(body)
    manifest['chunks'] = [{key: body[key] for key in ('chunk_index', 'count', 'start_index', 'end_index')} |
                          {'payload_sha256': json.loads(raw)['payload_sha256'], 'envelope_sha256': hashlib.sha256(raw.encode()).hexdigest()}]
    program = local_browser_stub() + 'const manifest=' + json.dumps(manifest) + ';const current=' + json.dumps(f['current']) + ';const raw=' + json.dumps(raw) + r''';
(async()=>{const bars=await parseTrendFullChunk(raw,manifest,manifest.chunks[0]),d=buildTrendFullDetail(manifest,bars,current),m=trendPlotModel(d,d.analyses.linear.full,d.bars,'linear',390),svg=trendSvg(d,m,{label:'TEST FIXTURE'});process.stdout.write(JSON.stringify({count:m.bars.length,lines:m.lines.length,svgBars:(svg.match(/data-trend-bar=/g)||[]).length,status:m.analysis.status,insights:trendInsightMarkup(d,null,'linear',{},true)}));})();'''
    out = run(tmp_path, program)
    assert out['count'] == out['svgBars'] == 100 and out['lines'] == 0 and out['status'] == 'hold'
    assert 'data-trend-border=' not in out['insights']


@pytest.mark.parametrize('scale', ['linear', 'log'])
@pytest.mark.parametrize('direction', ['all', 'rising', 'falling'])
def test_direction_filter_uses_same_lines_for_chart_and_independent_nearest_prices(tmp_path, scale, direction):
    detail = research_detail_fixture()
    # Keep supplied directions and equations unchanged; an absent direction leaves candles visible.
    analysis = detail['analyses'][scale]['63']
    selected_ids = [line['line_id'] for line in analysis['lines'] if direction == 'all' or line['direction'] == direction]
    reference = detail['bars'][-1]
    rows = []
    for line in analysis['lines']:
        if line['line_id'] not in selected_ids:
            continue
        value = line['intercept'] + line['slope'] * (reference['session_index'] - line['coordinate_origin_index'])
        rows.append((line['line_id'], math.exp(value) if scale == 'log' else value))
    down = sorted((row for row in rows if row[1] <= reference['close']), key=lambda row: (-row[1], row[0]))
    up = sorted((row for row in rows if row[1] > reference['close']), key=lambda row: (row[1], row[0]))
    out = run(tmp_path, 'const d=' + json.dumps(detail) + ';const scale=' + json.dumps(scale) + ';const direction=' + json.dumps(direction) + r''';
const before=JSON.stringify(d),analysis=trendDirectionalAnalysis(d,d.analyses[scale]['63'],scale,direction),model=trendPlotModel(d,analysis,d.bars.slice(-63),scale,390),insight=trendInsightFromAnalysis(d,analysis,scale);
process.stdout.write(JSON.stringify({ids:model.lines.map(line=>line.line_id),down:insight.down?{id:insight.down.line_id,price:insight.down.price}:null,up:insight.up?{id:insight.up.line_id,price:insight.up.price}:null,bars:model.bars.length,unchanged:before===JSON.stringify(d)}));''')
    assert out['ids'] == selected_ids and out['bars'] == 63 and out['unchanged']
    for side, expected in (('down', down), ('up', up)):
        if not expected:
            assert out[side] is None
        else:
            assert out[side]['id'] == expected[0][0]
            assert out[side]['price'] == pytest.approx(expected[0][1], rel=1e-10, abs=1e-6)


@pytest.mark.parametrize('origin,stored,expected', [
    ('https://sung-jinpark.github.io', None, True), ('http://127.0.0.1:8878', None, True),
    ('http://127.0.0.1:8879', None, False), ('http://localhost:8878', None, False),
    ('http://127.0.0.1:8878', {'schema_version': 1, 'enabled': False}, True),
    ('https://sung-jinpark.github.io', {'schema_version': 1, 'enabled': True}, True),
    ('https://sung-jinpark.github.io', {'schema_version': 1, 'enabled': 'true'}, True),
])
def test_auto_entry_uses_only_exact_trusted_origins_and_never_reads_or_writes_preferences(tmp_path, origin, stored, expected):
    program = local_browser_stub() + 'globalThis.location={origin:' + json.dumps(origin) + '};storage.legacy=' + json.dumps(stored) + r''';
const before=JSON.stringify(storage);globalThis.localStorage={getItem(){throw new Error('no storage read')},setItem(){throw new Error('no storage write')}};
process.stdout.write(JSON.stringify({initial:readTrendLocalPreference(),unchanged:before===JSON.stringify(storage)}));'''
    out = run(tmp_path, program)
    assert out == {'initial': expected, 'unchanged': True}


def test_automatic_entry_is_bounded_fixed_readonly_and_keeps_public_data(tmp_path, private_import_envelope):
    envelope, status = private_import_envelope, local_status_fixture(private_import_envelope)
    program = local_browser_stub() + 'const raw=' + json.dumps(json.dumps(envelope)) + ';const status=' + json.dumps(status) + r''';
const requests=[],publicData={trendlines:{status:'hold'}},before=JSON.stringify(publicData);
globalThis.DATA=publicData;globalThis.fetch=async(url,options)=>{requests.push({url,method:options.method,credentials:options.credentials,mode:options.mode,cache:options.cache,redirect:options.redirect,space:options.targetAddressSpace});return response(url.endsWith('/status')?JSON.stringify(status):raw);};
(async()=>{globalThis.location={origin:'https://sung-jinpark.github.io'};TREND_LOCAL_ENABLED=readTrendLocalPreference();const session=bindTrendLocalConnection(root,{asset:'bitcoin'});let paints=0;session.onData=()=>paints++;TREND_VIEW_OPTIONS.set('bitcoin',{period:252,scale:'log'});await Promise.resolve();await session.inflight;const data=TREND_PRIVATE_DETAILS.get('bitcoin');stopTrendLocalSession();process.stdout.write(JSON.stringify({requests,paints,status:data.status,hash:data.content_hash,storageKeys:Object.keys(storage),view:TREND_VIEW_OPTIONS.get('bitcoin'),unchanged:before===JSON.stringify(publicData)}));})();'''
    out = run(tmp_path, program)
    assert out['paints'] == 1 and out['unchanged']
    assert out['status'] == 'unverified_display' and out['hash'] == envelope['payload_sha256']
    assert out['view'] == {'period': 252, 'scale': 'log'} and out['storageKeys'] == []
    assert out['requests'] == [{'url': f'http://127.0.0.1:8878/api/private-trendlines/{suffix}', 'method': 'GET',
                               'credentials': 'omit', 'mode': 'cors', 'cache': 'no-store', 'redirect': 'error', 'space': 'loopback'}
                              for suffix in ('status', 'bitcoin')]


def test_local_overlap_abort_and_old_reply_do_not_change_another_route(tmp_path, private_import_envelope):
    status = local_status_fixture(private_import_envelope)
    program = local_browser_stub() + 'const status=' + json.dumps(status) + r''';
let calls=0,finish;globalThis.fetch=()=>{calls++;return new Promise(resolve=>finish=resolve);};
(async()=>{TREND_LOCAL_ENABLED=false;const session=bindTrendLocalConnection(root,{asset:'bitcoin'});await Promise.resolve();TREND_LOCAL_ENABLED=true;const one=refreshTrendLocalSession(session);const two=refreshTrendLocalSession(session);const inflight=calls,signal=session.controller.signal;stopTrendLocalSession();TREND_LOCAL_ENABLED=false;const next=bindTrendLocalConnection(root,{asset:'soxx'});await Promise.resolve();finish(response(JSON.stringify(status)));await Promise.all([one,two]);stopTrendLocalSession();process.stdout.write(JSON.stringify({inflight,calls,aborted:signal.aborted,details:TREND_PRIVATE_DETAILS.size,nextAsset:next.assetId}));})();'''
    assert run(tmp_path, program) == {'inflight': 1, 'calls': 1, 'aborted': True, 'details': 0, 'nextAsset': 'soxx'}


def test_invalid_reply_retains_last_good_and_route_cleanup_stops_polling(tmp_path, private_import_envelope):
    envelope, status = private_import_envelope, local_status_fixture(private_import_envelope)
    program = local_browser_stub() + 'const envelope=' + json.dumps(envelope) + ';const status=' + json.dumps(status) + r''';
(async()=>{const original=await parseTrendPrivateImport(JSON.stringify(envelope),'bitcoin');TREND_PRIVATE_DETAILS.set('bitcoin',original);TREND_LOCAL_ENABLED=false;const session=bindTrendLocalConnection(root,{asset:'bitcoin'});session.onData=()=>{throw new Error('bad reply must not repaint')};await Promise.resolve();TREND_LOCAL_ENABLED=true;const broken={...envelope,payload_json:envelope.payload_json+' '};let calls=0;globalThis.fetch=async url=>{calls++;return response(url.endsWith('/status')?JSON.stringify(status):JSON.stringify(broken));};await refreshTrendLocalSession(session);const phase=session.phase,kept=TREND_PRIVATE_DETAILS.get('bitcoin')===original,notice=nodes['[data-trend-local-message]'].textContent;stopTrendLocalSession();await refreshTrendLocalSession(session);process.stdout.write(JSON.stringify({phase,kept,calls,storageKeys:Object.keys(storage),notice:notice.includes('자료 검증 보류')&&notice.includes('확인 자료 유지')}));})();'''
    assert run(tmp_path, program) == {'phase': 'invalid', 'kept': True, 'calls': 2, 'storageKeys': [], 'notice': True}


def test_local_source_refresh_failure_uses_plain_reason_and_keeps_valid_chart(tmp_path, private_import_envelope):
    status = local_status_fixture(private_import_envelope)
    row = next(row for row in status['assets'] if row['asset_id'] == 'bitcoin')
    row.update(status='stale', stale=True, error='refresh_failed')
    program = local_browser_stub() + 'const envelope=' + json.dumps(private_import_envelope) + ';const status=' + json.dumps(status) + r''';
globalThis.fetch=async url=>response(url.endsWith('/status')?JSON.stringify(status):JSON.stringify(envelope));
(async()=>{TREND_LOCAL_ENABLED=false;const session=bindTrendLocalConnection(root,{asset:'bitcoin'});session.onData=()=>{};await Promise.resolve();TREND_LOCAL_ENABLED=true;await refreshTrendLocalSession(session);const notice=nodes['[data-trend-local-message]'].textContent;const out={phase:session.phase,chart:TREND_PRIVATE_DETAILS.has('bitcoin'),plain:notice.includes('마지막 확인 자료를 표시합니다'),noCode:!notice.includes('refresh_failed')};stopTrendLocalSession();process.stdout.write(JSON.stringify(out));})();'''
    assert run(tmp_path, program) == {'phase': 'stale', 'chart': True, 'plain': True, 'noCode': True}


def test_local_hidden_pause_resumes_without_overlap_and_uses_8s_timeout(tmp_path, private_import_envelope):
    program = local_browser_stub() + r''';
const timers=new Map();let next=0;globalThis.setTimeout=(fn,delay)=>{const id=++next;timers.set(id,{fn,delay});return id};globalThis.clearTimeout=id=>timers.delete(id);
let calls=0;globalThis.fetch=async(_url,options)=>{calls++;return new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));};
(async()=>{TREND_LOCAL_ENABLED=false;const session=bindTrendLocalConnection(root,{asset:'bitcoin'});await Promise.resolve();TREND_LOCAL_ENABLED=true;document.visibilityState='hidden';await refreshTrendLocalSession(session);const hiddenCalls=calls;document.visibilityState='visible';const pending=refreshTrendLocalSession(session);const deadline=[...timers.values()].find(row=>row.delay===8000);deadline.fn();await pending;const phase=session.phase,poll=[...timers.values()].some(row=>row.delay===60000);document.visibilityState='hidden';listeners.visibilitychange();const paused=session.phase,pausedTimers=timers.size;stopTrendLocalSession();process.stdout.write(JSON.stringify({hiddenCalls,calls,phase,poll,paused,pausedTimers}));})();'''
    assert run(tmp_path, program) == {'hiddenCalls': 0, 'calls': 1, 'phase': 'offline', 'poll': True, 'paused': 'paused', 'pausedTimers': 0}


@pytest.mark.parametrize('problem', ['scope', 'duplicate', 'state', 'timestamp', 'stale_type'])
def test_invalid_local_status_cannot_enable_a_price_reply(tmp_path, private_import_envelope, problem):
    status = local_status_fixture(private_import_envelope)
    if problem == 'scope':
        status['publication_scope'] = 'public'
    elif problem == 'duplicate':
        status['assets'][0]['asset_id'] = 'bitcoin'
    elif problem == 'state':
        status['assets'][0]['status'] = 'approved'
    elif problem == 'timestamp':
        status['assets'][0]['source_asof'] = '2026-01-01'
    else:
        status['assets'][0]['stale'] = 'false'
    out = run(tmp_path, 'const status=' + json.dumps(status) + r''';let rejected=false;try{validateTrendLocalStatus(status,'bitcoin')}catch(error){rejected=true}process.stdout.write(JSON.stringify({rejected}));''')
    assert out['rejected']


def test_local_revision_never_rolls_back_current_or_status_source_time(tmp_path):
    out = run(tmp_path, r'''
const tests=[['2026-10-14T00:00:00+00:00','2026-10-13T00:00:00+00:00',null],['2026-10-13T00:00:00+00:00','2026-10-14T00:00:00+00:00','2026-10-15T00:00:00+00:00'],['2026-10-13T00:00:00+00:00','2026-10-14T00:00:00+00:00','2026-10-13T00:00:00+00:00'],['2026-10-14T00:00:00.000400+00:00','2026-10-14T00:00:00.000300+00:00',null]];
process.stdout.write(JSON.stringify(tests.map(([old,next,status])=>{try{assertTrendLocalRevision({as_of:old},{as_of:next},{source_asof:status});return true}catch(_){return false}})));''')
    assert out == [False, False, True, False]


def packed_import(envelope, *, prefix=False):
    original = json.loads(envelope['payload_json'])
    columns = ['session', 'session_index', 'open', 'high', 'low', 'close', 'bar_id']
    bars = original.pop('bars')
    original['bars_packed'] = {'columns': columns, 'rows': [[bar[key] for key in columns] for bar in bars]}
    if prefix:
        original['bars_packed']['bar_id_prefix'] = 'research-bar-'
        for row in original['bars_packed']['rows']:
            row[6] = row[6].removeprefix('research-bar-')
    original['original_detail_sha256'] = envelope['payload_sha256']
    payload = json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return {**envelope, 'schema_version': 2, 'contract_id': 'trendlines_private_import_v2',
            'payload_json': payload, 'payload_sha256': hashlib.sha256(payload.encode()).hexdigest(),
            'original_detail_sha256': envelope['payload_sha256']}


@pytest.mark.parametrize('prefix', [False, True])
def test_v2_exact_transport_hash_restores_all_bars_and_separates_original_hash(tmp_path, private_import_envelope, prefix):
    envelope = packed_import(private_import_envelope, prefix=prefix)
    program = local_browser_stub() + 'const v1=' + json.dumps(json.dumps(private_import_envelope)) + ';const v2=' + json.dumps(json.dumps(envelope)) + r''';
(async()=>{const one=await parseTrendPrivateImport(v1,'bitcoin'),two=await parseTrendPrivateImport(v2,'bitcoin');process.stdout.write(JSON.stringify({same:JSON.stringify(one)===JSON.stringify(two),bars:two.bars.length,original:two.content_hash,metadata:two[TREND_IMPORT_TRANSPORT],packedFields:Object.hasOwn(two,'bars_packed')||Object.hasOwn(two,'original_detail_sha256')}));})();'''
    out = run(tmp_path, program)
    # Object insertion order changes while exact decoded values remain equivalent.
    assert out['bars'] == 100 and out['original'] == private_import_envelope['payload_sha256']
    assert out['metadata'] == {'schema_version': 2, 'payload_sha256': envelope['payload_sha256'],
                               'original_detail_sha256': private_import_envelope['payload_sha256']}
    assert not out['packedFields']
    values = run(tmp_path, local_browser_stub() + 'const v1=' + json.dumps(json.dumps(private_import_envelope)) + ';const v2=' + json.dumps(json.dumps(envelope)) + r''';
(async()=>{const one=await parseTrendPrivateImport(v1,'bitcoin'),two=await parseTrendPrivateImport(v2,'bitcoin'),keys=['session','session_index','open','high','low','close','bar_id'];process.stdout.write(JSON.stringify({bars:one.bars.length===two.bars.length&&one.bars.every((row,i)=>keys.every(key=>row[key]===two.bars[i][key])),analyses:JSON.stringify(one.analyses)===JSON.stringify(two.analyses),receipt:one.receipt_id===two.receipt_id}));})();''')
    assert values == {'bars': True, 'analyses': True, 'receipt': True}


@pytest.mark.parametrize('problem', ['checksum', 'original_hash', 'columns', 'width', 'extra_packed', 'duplicate_bars', 'ohlc', 'prefix', 'prefix_suffix', 'prefix_full_id'])
def test_v2_rejects_corruption_or_lossy_packed_shape(tmp_path, private_import_envelope, problem):
    envelope = packed_import(private_import_envelope, prefix=problem.startswith('prefix'))
    body = json.loads(envelope['payload_json'])
    if problem == 'checksum':
        envelope['payload_json'] += ' '
    elif problem == 'original_hash':
        envelope['original_detail_sha256'] = '0' * 64
    elif problem == 'columns':
        body['bars_packed']['columns'][2] = 'adjusted_open'
    elif problem == 'width':
        body['bars_packed']['rows'][0].pop()
    elif problem == 'extra_packed':
        body['bars_packed']['clip'] = True
    elif problem == 'duplicate_bars':
        body['bars'] = []
    elif problem == 'prefix':
        body['bars_packed']['bar_id_prefix'] = 'approved-bar-'
    elif problem == 'prefix_suffix':
        body['bars_packed']['rows'][0][6] = '0' * 63
    elif problem == 'prefix_full_id':
        body['bars_packed']['rows'][0][6] = 'research-bar-' + body['bars_packed']['rows'][0][6]
    else:
        body['bars_packed']['rows'][0][3] = 1
    if problem not in {'checksum', 'original_hash'}:
        envelope['payload_json'] = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        envelope['payload_sha256'] = hashlib.sha256(envelope['payload_json'].encode()).hexdigest()
    program = local_browser_stub() + 'const raw=' + json.dumps(json.dumps(envelope)) + r''';
(async()=>{let rejected=false;try{await parseTrendPrivateImport(raw,'bitcoin')}catch(_){rejected=true}process.stdout.write(JSON.stringify({rejected}));})();'''
    assert run(tmp_path, program)['rejected']


@pytest.mark.parametrize('problem', ['approved', 'contract', 'class', 'rights', 'official',
                                    'adjustment', 'historical', 'state', 'event', 'gap', 'quote'])
def test_research_provenance_or_past_signal_disguise_is_rejected(tmp_path, problem):
    detail = research_detail_fixture()
    if problem == 'approved':
        detail['verified_source'] = True
    elif problem == 'contract':
        detail['contract_id'] = 'trendlines_display_v1'
    elif problem == 'class':
        detail['publication_class'] = 'approved_free'
    elif problem == 'rights':
        detail['source_identity']['rights_status'] = 'approved_free'
    elif problem == 'official':
        detail['official_forecast_write'] = True
    elif problem == 'adjustment':
        detail['adjustment_verified'] = True
    elif problem == 'historical':
        detail['historical_signals_available'] = True
    elif problem == 'state':
        detail['analyses']['linear']['63']['lines'][0]['state'] = 'active'
    elif problem == 'event':
        detail['analyses']['linear']['63']['events'] = [{'new_state': 'broken'}]
    elif problem == 'gap':
        detail['gaps'][0]['session_index'] = detail['bars'][0]['session_index']
    else:
        detail['intraday_quote']['status'] = 'final_close'
    out = run(tmp_path, 'const d=' + json.dumps(detail) + ";let rejected=false;try{trendChartModel(d);}catch(error){rejected=true;}process.stdout.write(JSON.stringify({rejected}));")
    assert out['rejected']
