"""Render backend line equations exactly; independently test route and tamper gates."""
from __future__ import annotations

import copy
import hashlib
import json
import runpy
import shutil
import subprocess
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
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding='utf-8')
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
 discloses:markup.includes('원천 검증 미완료')&&markup.includes('과거 이탈·복귀 신호를 판정하지 않습니다'),
 quoteSeparated:markup.includes('별도 장중 관측 · 일봉 종가 아님'),
 stale:markup.includes('최근 마감 일봉 누락'),
 unsafeLink:trendSourceUrl('javascript:alert(1)')
}));''')
    assert out == {'valid': True, 'same': True, 'gaps': 1, 'candles': 63,
                   'missingIsNotCandle': True, 'quote': 1, 'quoteWithinAxis': True,
                   'discloses': True, 'quoteSeparated': True, 'stale': True, 'unsafeLink': None}


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


@pytest.mark.parametrize('asset_id', ['constructor', '__proto__', 'toString', 'mag7'])
def test_private_import_accepts_only_own_exact_registered_research_assets(tmp_path, asset_id):
    envelope = {'schema_version': 1, 'contract_id': 'trendlines_private_import_v1', 'publication_scope': 'private_only',
                'asset_id': asset_id, 'payload_json': '{}', 'payload_sha256': hashlib.sha256(b'{}').hexdigest()}
    out = run(tmp_path, 'globalThis.crypto=require("node:crypto").webcrypto;const raw=' + json.dumps(json.dumps(envelope)) + ';const asset=' + json.dumps(asset_id) + r''';
(async()=>{let rejected=false;try{await parseTrendPrivateImport(raw,asset);}catch(error){rejected=true;}process.stdout.write(JSON.stringify({rejected}));})();''')
    assert out['rejected']


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
