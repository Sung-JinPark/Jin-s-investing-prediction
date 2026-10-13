"""Exact HTML-source identity and lossless price column parsing."""
import json

import pytest

from ai_fc.trendlines.contracts import TrendlinesError
from ai_fc.trendlines.research_html import parse_yahoo_history

ASSET = {"symbol": "BTC-USD", "provider_symbol": "BTC-USD", "currency": "USD", "timezone": "UTC"}


def document(*, alter=None, url=None, copies=1):
    item = {"meta": {"symbol": "BTC-USD", "currency": "USD", "exchangeTimezoneName": "UTC",
                     "dataGranularity": "1d", "regularMarketTime": 1704153600,
                     "regularMarketPrice": 102},
            "timestamp": [1704067200, 1704153600],
            "indicators": {"quote": [{"open": [100, None], "high": [104, None],
                                       "low": [98, None], "close": [102, None], "volume": [3, None]}],
                           "adjclose": [{"adjclose": [2, 3]}]}}
    if alter:
        alter(item)
    envelope = {"status": 200, "body": json.dumps({"chart": {"result": [item], "error": None}})}
    script = ('<script type="application/json" data-sveltekit-fetched data-url="'
              + (url or 'https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1d')
              + '">' + json.dumps(envelope) + '</script>')
    return ('<!doctype html>' + script * copies).encode()


def test_parser_preserves_nulls_close_column_and_quote_watermark():
    rows, meta = parse_yahoo_history(document(), ASSET)
    assert rows == [{"date": "2024-01-01", "open": 100, "high": 104, "low": 98, "close": 102, "volume": 3},
                    {"date": "2024-01-02", "open": None, "high": None, "low": None, "close": None, "volume": None}]
    assert meta["price_column"] == "close_not_adj_close"
    assert meta["parser_id"] == "yahoo_history_html_v1"
    assert meta["adjustment_verified"] is False
    assert meta["quote"]["observed_at"] == "2024-01-02T00:00:00+00:00"


@pytest.mark.parametrize('key,value', [('symbol', 'ETH-USD'), ('currency', 'KRW'),
                                      ('exchangeTimezoneName', 'Asia/Seoul'), ('dataGranularity', '1h')])
def test_meta_mismatch_rejects_exact_outer_url(key, value):
    with pytest.raises(TrendlinesError, match='mismatch'):
        parse_yahoo_history(document(alter=lambda item: item['meta'].update({key: value})), ASSET)


@pytest.mark.parametrize('url', [
    'http://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1d',
    'https://query1.finance.yahoo.com/v8/finance/chart/ETH-USD?interval=1d',
    'https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1h',
    'https://query1.finance.yahoo.com/v8/finance/chart/extra/BTC-USD?interval=1d',
    'https://user@query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1d',
])
def test_nonexact_embedded_source_rejected(url):
    with pytest.raises(TrendlinesError, match='one exact'):
        parse_yahoo_history(document(url=url), ASSET)


def test_ambiguous_daily_responses_rejected():
    with pytest.raises(TrendlinesError, match='one exact'):
        parse_yahoo_history(document(copies=2), ASSET)


def test_price_array_and_bool_timestamp_rejected():
    with pytest.raises(TrendlinesError, match='aligned'):
        parse_yahoo_history(document(alter=lambda item: item['indicators']['quote'][0].update({'low': [98]})), ASSET)
    with pytest.raises(TrendlinesError, match='integer'):
        parse_yahoo_history(document(alter=lambda item: item.update({'timestamp': [True, 1704153600]})), ASSET)


def test_missing_quote_watermark_is_never_inferred_from_fetch_time():
    _, meta = parse_yahoo_history(document(alter=lambda item: item['meta'].pop('regularMarketTime')), ASSET)
    assert meta['quote']['observed_at'] is None
