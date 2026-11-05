"""Searched symbols: fixed hosts, finished sessions only, memory cache, no durable writes."""
import base64
import json
import threading
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ai_fc.trendlines import local_service as L
from ai_fc.trendlines import symbol_lookup as Y
from test_trendlines_manual_ui import FIXTURE, run


def chart(symbol='TSLA', **meta):
    day = 86_400
    start = 1_780_000_000 - 1_780_000_000 % day + 14 * 3600
    stamps = [start + day * i for i in range(5)]
    return {'chart': {'result': [{'meta': {'symbol': symbol, 'currency': 'USD', 'instrumentType': 'EQUITY',
                                           'exchangeTimezoneName': 'America/New_York', 'longName': 'Fixture Inc.',
                                           'regularMarketPrice': 111.5, **meta},
                                  'timestamp': stamps,
                                  'indicators': {'quote': [{'open': [100, 101, None, 103, 104], 'high': [102, 103, 104, 105, 106],
                                                            'low': [99, 100, 101, 102, 103], 'close': [101, 102, 103, 104, 105],
                                                            'volume': [10, 20, 30, None, 50]}]}}]}}


NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_chart_rows_count_broken_candles_instead_of_repairing_them():
    body = Y.parse_chart(chart(), 'TSLA', now=NOW)
    assert body['contract_id'] == 'chart_symbol_bars_v1' and body['unit'] == 'USD_per_share'
    assert [row['session_index'] for row in body['bars']] == [0, 1, 2, 3]
    assert body['dropped_rows'] == 1 and body['intraday_quote'] is None
    assert body['bars'][2]['volume'] is None
    sessions = [row['session'] for row in body['bars']]
    assert sessions == sorted(sessions) and len(set(sessions)) == 4


def test_unfinished_session_becomes_a_labelled_quote_not_a_bar():
    raw = chart()
    last = raw['chart']['result'][0]['timestamp'][-1]
    raw['chart']['result'][0]['meta']['currentTradingPeriod'] = {'regular': {'end': last + 3600}}
    body = Y.parse_chart(raw, 'TSLA', now=datetime.fromtimestamp(last + 60, timezone.utc))
    assert len(body['bars']) == 3
    assert body['intraday_quote']['session_index'] == 3 and body['intraday_quote']['price'] == 111.5


@pytest.mark.parametrize('raw', [{}, {'chart': {'result': []}}, chart('OTHER')])
def test_unusable_chart_answers_are_rejected(raw):
    with pytest.raises(Y.SymbolLookupError):
        Y.parse_chart(raw, 'TSLA', now=NOW)


@pytest.mark.parametrize('symbol', ['../etc', 'A B', 'http://x', 'a/b', '', 'TOOLONGTOOLONGTOOLONGTOOLONG'])
def test_symbol_pattern_stops_anything_that_could_steer_the_url(symbol):
    seen = []
    with pytest.raises(Y.SymbolLookupError):
        Y.SymbolLookup(fetch=lambda url: seen.append(url)).bars(symbol)
    assert not seen


def test_search_routes_hangul_to_naver_and_caches_in_memory():
    urls = []

    def fetch(url):
        urls.append(url)
        if 'naver' in url:
            return {'items': [{'code': '005930', 'name': '삼성전자', 'typeCode': 'KOSPI', 'typeName': '코스피', 'nationCode': 'KOR', 'category': 'stock'},
                              {'code': 'TSLA', 'name': '테슬라', 'typeCode': 'NASDAQ', 'nationCode': 'USA', 'category': 'stock'},
                              {'code': 'X', 'name': '기타', 'typeCode': 'TSE', 'nationCode': 'JPN', 'category': 'stock'}]}
        return {'quotes': [{'symbol': 'TSLA', 'quoteType': 'EQUITY', 'longname': 'Tesla', 'exchDisp': 'NASDAQ'},
                           {'symbol': 'TSLA', 'quoteType': 'EQUITY', 'longname': 'Duplicate'},
                           {'symbol': 'NEWS', 'quoteType': 'OPTION'}]}
    lookup = Y.SymbolLookup(fetch=fetch)
    korean = lookup.search('삼성전자')
    assert [row['symbol'] for row in korean['results']] == ['005930.KS', 'TSLA']
    assert urls[0].startswith(Y.NAVER_SEARCH)
    english = lookup.search('Tesla')
    assert [row['symbol'] for row in english['results']] == ['TSLA']
    assert urls[1].startswith(Y.YAHOO_SEARCH)
    lookup.search('  tesla ')
    assert len(urls) == 2, 'a repeated query is answered from memory'
    assert lookup.search('   ')['results'] == [] and len(urls) == 2


def test_bars_use_explicit_daily_bounds():
    urls = []
    Y.SymbolLookup(fetch=lambda url: urls.append(url) or chart()).bars('tsla')
    assert urls[0].startswith(Y.YAHOO_CHART + 'TSLA?period1=0&period2=') and 'interval=1d' in urls[0] and 'range=' not in urls[0]


class StubService:
    def status(self):
        return {'ok': True}


@pytest.fixture
def server():
    lookup = Y.SymbolLookup(fetch=lambda url: chart() if url.startswith(Y.YAHOO_CHART) else {'quotes': [{'symbol': 'TSLA', 'quoteType': 'EQUITY', 'longname': 'Tesla'}]})
    http = L.make_http_server(StubService(), port=0, symbols=lookup)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield http
    http.shutdown()
    thread.join(5)
    http.server_close()


def get(http, path, **headers):
    return urlopen(Request('http://' + http.expected_host + path, headers=headers), timeout=5)


def segment(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')


def test_service_answers_symbol_routes_only_to_trusted_origins(server):
    with get(server, '/api/private-trendlines/symbol-search/' + segment('tesla'), Origin=L.TRUSTED_ORIGIN) as response:
        assert json.loads(response.read())['results'][0]['symbol'] == 'TSLA'
        assert response.headers['Access-Control-Allow-Origin'] == L.TRUSTED_ORIGIN
    with get(server, '/api/private-trendlines/symbol-bars/' + segment('TSLA')) as response:
        assert len(json.loads(response.read())['bars']) == 4
    with pytest.raises(HTTPError) as refused:
        get(server, '/api/private-trendlines/symbol-search/' + segment('tesla'), Origin='https://evil.example')
    assert refused.value.code == 403


@pytest.mark.parametrize('path', ['symbol-bars/' + segment('../etc'), 'symbol-bars/a%2Fb', 'symbol-search/a?b=1', 'symbol-other/QQ'])
def test_service_rejects_bad_symbol_requests(server, path):
    with pytest.raises(HTTPError) as refused:
        get(server, '/api/private-trendlines/' + path)
    assert refused.value.code in (404, 503)


# ---- browser-side pure pieces -------------------------------------------------------------------
SHAPES = r'''
const state=trendManualState('soxx');await state.loading;state.drawingScale='linear';
const sessions=trendManualSessions(detail,analysis),at=(i,price)=>({session:sessions[i].session,price});
'''


@pytest.mark.parametrize('tool,shape,clicks', [('rect', 'rect', 2), ('fib', 'fib', 2), ('vertical', 'vertical', 1), ('text', 'text', 1), ('arrow', None, 2)])
def test_new_tools_stay_two_anchor_records_and_pass_the_strict_validator(tmp_path, tool, shape, clicks):
    out = run(tmp_path, SHAPES + 'state.tool=' + repr(tool) + ''';
trendManualChoose(state,at(1,100),sessions);''' + ('trendManualChoose(state,at(5,200),sessions);' if clicks == 2 else '') + r'''
const line=state.lines[0];process.stdout.write(JSON.stringify({line,valid:trendManualValidateV2(state.lines,'soxx').length,saved:trendManualDocumentCheck(trendManualPayload(state),'soxx').lines.length}));
''', FIXTURE)
    assert out['valid'] == out['saved'] == 1
    assert out['line'].get('shape') == shape
    if tool == 'arrow':
        assert out['line']['style']['arrow'] == 'end'


def test_validator_keeps_old_records_valid_and_refuses_unknown_shapes(tmp_path):
    out = run(tmp_path, SHAPES + r'''
const old={...trendManualUpgrade(record),axis:'linear'};let refused='';
try{trendManualValidateV2([{...old,shape:'circle'}],'soxx');}catch(error){refused=error.message;}
process.stdout.write(JSON.stringify({old:trendManualValidateV2([old],'soxx').length,refused,symbol:trendManualKnownAsset('sym:BRK-B'),index:trendManualKnownAsset('sym:^GSPC'),bad:trendManualKnownAsset('sym:a/b')}));
''', FIXTURE)
    assert out['old'] == 1 and out['refused']
    assert out['symbol'] and out['index'] and not out['bad']


def test_fibonacci_runs_from_second_anchor_back_to_first_on_the_creation_axis(tmp_path):
    out = run(tmp_path, r'''
const a={first_anchor:{price:100},second_anchor:{price:200},axis:'linear'},b={...a,axis:'log'};
process.stdout.write(JSON.stringify({linear:trendManualFibRows(a),log:trendManualFibRows(b)}));
''', FIXTURE)
    assert out['linear'][0]['price'] == pytest.approx(200) and out['linear'][-1]['price'] == pytest.approx(100)
    assert out['linear'][3]['price'] == pytest.approx(150)
    assert out['log'][3]['price'] == pytest.approx(100 * 2 ** .5)


def test_drawing_calendar_extends_past_the_data_and_a_holiday_lands_on_the_next_session(tmp_path):
    out = run(tmp_path, r'''
const drawing={...analysis,drawing_sessions:trendDrawingCalendar(detail,analysis)},rows=trendManualSessions(detail,drawing);
const weekend=rows.filter(row=>[0,6].includes(new Date(row.session+'T00:00:00Z').getUTCDay())&&row.index>9).length;
const far={...record,a:{session:'2026-10-02',price:100},b:{session:rows.at(-1).session,price:200}};
const skipped={...record,a:{session:'2026-10-02',price:100},b:{session:'2026-10-17',price:200}};
process.stdout.write(JSON.stringify({count:rows.length,weekend,contiguous:rows.every((row,i)=>!i||row.index===rows[i-1].index+1),far:!!trendManualGeometry(far,detail,drawing,'linear',m),skipped:trendManualGeometry(skipped,detail,drawing,'linear',m)?.second_anchor,strict:trendManualGeometry(skipped,detail,analysis,'linear',m)}));
''', FIXTURE)
    assert out['count'] > 1500 and out['weekend'] == 0 and out['contiguous'] and out['far']
    assert out['skipped']['session'] == '2026-10-19'
    assert out['strict'] is None, 'without the calendar an unknown date still stays unresolved'


def test_series_and_indicators_match_hand_arithmetic(tmp_path):
    out = run(tmp_path, r'''
const days=Array.from({length:60},(_,i)=>{const date=new Date(Date.UTC(2026,0,5+i)).toISOString().slice(0,10);return {session:date,session_index:i,open:100+i,high:102+i,low:99+i,close:101+i,volume:10};}).filter(row=>![0,6].includes(new Date(row.session+'T00:00:00Z').getUTCDay())).map((row,i)=>({...row,session_index:i}));
const weekly=trendWsAggregate(days,'W'),monthly=trendWsAggregate(days,'M'),heikin=trendWsSeries(days,'D','heikin'),sma=trendWsIndicator(days,'ma20').line,ema=trendWsIndicator(days,'ema20').line,rsi=trendWsIndicator(days,'rsi').line,bb=trendWsIndicator(days,'bb'),macd=trendWsIndicator(days,'macd');
const flat=days.map(row=>({...row,close:100}));
process.stdout.write(JSON.stringify({days:days.length,week:weekly[0],months:monthly.length,heikin:heikin[1],source:days[1],sma19:sma[19],smaNull:sma[18],smaLast:sma.at(-1),closes:days.slice(0,20).map(r=>r.close),ema19:ema[19],rsiLast:rsi.at(-1),bbFlat:trendWsIndicator(flat,'bb').upper[19],macdNull:macd.signal[32],macdValue:macd.signal[33],rowAt:[trendWsRowAt(weekly,0),trendWsRowAt(weekly,4),trendWsRowAt(weekly,5),trendWsRowAt(weekly,999)]}));
''', FIXTURE)
    assert out['week']['open'] == 100 and out['week']['close'] == 105 and out['week']['high'] == 106 and out['week']['low'] == 99
    assert out['week']['session_index'] == 2 and out['week']['volume'] == 50
    assert out["months"] == 3
    assert out['heikin']['close'] == pytest.approx((out['source']['open'] + out['source']['high'] + out['source']['low'] + out['source']['close']) / 4)
    assert out['source']['open'] == 101, 'derived rows never edit the source bars'
    assert out['smaNull'] is None and out['sma19'] == pytest.approx(sum(out['closes']) / 20) and out['ema19'] == pytest.approx(out['sma19'])
    assert out['rsiLast'] == 100, 'an unbroken rise has no losses'
    assert out['bbFlat'] == 100
    assert out['macdNull'] is None and out['macdValue'] is not None
    assert out['rowAt'] == [0, 0, 1, -1]
