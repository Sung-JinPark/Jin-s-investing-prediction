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
