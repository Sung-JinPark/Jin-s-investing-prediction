"""Read-only symbol search and daily bars for the private chart workspace.

Answers live only in this process's bounded cache. Nothing is written to the
research store, the ledgers or any public read model, and automatic trendlines
never read it: a searched symbol is something to look at and draw on, not a
verified snapshot. Hosts are fixed and every symbol passes a strict pattern
before it can reach a URL, so a browser request cannot choose where we connect.
"""

from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

YAHOO_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search?quotesCount=12&newsCount=0&q="
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
NAVER_SEARCH = "https://ac.stock.naver.com/ac?target=stock,index,etf&q="
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
RESPONSE_LIMIT = 8 * 1024 * 1024
MAX_BARS = 12_000
SEARCH_TTL = 600.0
BARS_TTL = 900.0
CACHE_ENTRIES = 256
SYMBOL = re.compile(r"\^?[A-Z0-9][A-Z0-9.=_-]{0,23}")
SEARCH_TYPES = {"EQUITY": "주식", "ETF": "ETF", "INDEX": "지수", "CRYPTOCURRENCY": "가상자산",
                "MUTUALFUND": "펀드", "CURRENCY": "환율", "FUTURE": "선물"}
KIND = {"EQUITY": "equity", "ETF": "etf", "INDEX": "index", "CRYPTOCURRENCY": "crypto",
        "MUTUALFUND": "fund", "CURRENCY": "currency", "FUTURE": "future"}
NAVER_SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}


class SymbolLookupError(ValueError):
    pass


def _fetch_json(url: str) -> Any:
    with urlopen(Request(url, headers=HEADERS), timeout=15) as response:
        raw = response.read(RESPONSE_LIMIT + 1)
    if len(raw) > RESPONSE_LIMIT:
        raise SymbolLookupError("symbol_response_too_large")
    return json.loads(raw)


def valid_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not SYMBOL.fullmatch(symbol):
        raise SymbolLookupError("invalid_symbol")
    return symbol


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _yahoo_results(body: Any) -> list[dict[str, str]]:
    rows = []
    for quote_row in (body or {}).get("quotes") or []:
        kind = quote_row.get("quoteType")
        symbol = str(quote_row.get("symbol") or "").upper()
        if kind not in SEARCH_TYPES or not SYMBOL.fullmatch(symbol):
            continue
        rows.append({"symbol": symbol, "name": str(quote_row.get("longname") or quote_row.get("shortname") or symbol)[:80],
                     "exchange": str(quote_row.get("exchDisp") or quote_row.get("exchange") or "")[:40],
                     "type": SEARCH_TYPES[kind]})
    return rows


def _naver_results(body: Any) -> list[dict[str, str]]:
    rows = []
    for item in (body or {}).get("items") or []:
        code, nation, market = str(item.get("code") or ""), item.get("nationCode"), item.get("typeCode")
        symbol = code + NAVER_SUFFIX[market] if nation == "KOR" and market in NAVER_SUFFIX else code if nation == "USA" else ""
        if not SYMBOL.fullmatch(symbol):
            continue
        rows.append({"symbol": symbol, "name": str(item.get("name") or symbol)[:80],
                     "exchange": str(item.get("typeName") or market or "")[:40],
                     "type": "ETF" if item.get("category") == "etf" else "주식"})
    return rows


def parse_chart(body: Any, symbol: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Keep finished sessions as bars; an unfinished one becomes a labelled quote."""
    result = ((body or {}).get("chart") or {}).get("result") or []
    if len(result) != 1:
        raise SymbolLookupError("symbol_chart_missing")
    meta, stamps = result[0].get("meta") or {}, result[0].get("timestamp") or []
    candles = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
    if str(meta.get("symbol") or "").upper() != symbol:
        raise SymbolLookupError("symbol_chart_mismatch")
    zone = ZoneInfo(str(meta.get("exchangeTimezoneName") or "UTC"))
    now = now or datetime.now(timezone.utc)
    period_end = ((meta.get("currentTradingPeriod") or {}).get("regular") or {}).get("end")
    today_open = _positive(period_end) and now.timestamp() < period_end
    open_session = datetime.fromtimestamp(period_end, zone).date().isoformat() if today_open else None
    rows: dict[str, dict[str, Any]] = {}
    dropped = 0
    columns = [candles.get(name) or [] for name in ("open", "high", "low", "close", "volume")]
    for position, stamp in enumerate(stamps):
        values = [column[position] if position < len(column) else None for column in columns]
        o, h, l, c, volume = values
        # A halted or half-filled row is not a candle. Count it rather than repair it.
        if not all(_positive(v) for v in (o, h, l, c)) or h < max(o, c, l) or l > min(o, c, h):
            dropped += 1
            continue
        session = datetime.fromtimestamp(stamp, zone).date().isoformat()
        rows[session] = {"session": session, "open": o, "high": h, "low": l, "close": c,
                         "volume": volume if _positive(volume) else None}
    ordered = [rows[key] for key in sorted(rows)]
    quote_row = ordered.pop() if ordered and ordered[-1]["session"] == open_session else None
    ordered = ordered[-MAX_BARS:]
    if len(ordered) < 2:
        raise SymbolLookupError("symbol_history_too_short")
    for index, row in enumerate(ordered):
        row["session_index"] = index
    kind = KIND.get(str(meta.get("instrumentType") or "").upper(), "equity")
    currency = str(meta.get("currency") or "")[:8]
    unit = "index_points" if kind == "index" else currency if kind in ("crypto", "currency", "future") and currency else currency + "_per_share" if currency else "price"
    payload = {"schema_version": 1, "contract_id": "chart_symbol_bars_v1", "symbol": symbol,
               "name": str(meta.get("longName") or meta.get("shortName") or symbol)[:80],
               "exchange": str(meta.get("fullExchangeName") or meta.get("exchangeName") or "")[:40],
               "currency": currency, "unit": unit, "kind": kind, "dropped_rows": dropped, "bars": ordered,
               "observation_through": ordered[-1]["session"], "intraday_quote": None}
    live = meta.get("regularMarketPrice")
    if quote_row is not None:
        payload["intraday_quote"] = {"session_index": len(ordered), "date": quote_row["session"],
                                     "price": live if _positive(live) else quote_row["close"], "time": ""}
    return payload


class SymbolLookup:
    def __init__(self, fetch: Callable[[str], Any] = _fetch_json):
        self._fetch = fetch
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: str, ttl: float, build: Callable[[], Any]) -> Any:
        with self._lock:
            hit = self._cache.get(key)
            if hit and monotonic() - hit[0] < ttl:
                return hit[1]
        value = build()
        with self._lock:
            if len(self._cache) >= CACHE_ENTRIES:
                self._cache.pop(min(self._cache, key=lambda name: self._cache[name][0]))
            self._cache[key] = (monotonic(), value)
        return value

    def search(self, query: str) -> dict[str, Any]:
        text = " ".join(str(query or "").split())[:60]
        if not text:
            return {"schema_version": 1, "query": "", "results": []}
        return self._cached("search:" + text.casefold(), SEARCH_TTL, lambda: self._search(text))

    def _search(self, text: str) -> dict[str, Any]:
        # Yahoo rejects Hangul outright, so Korean names go through Naver's index.
        hangul = any("가" <= char <= "힣" for char in text)
        rows = _naver_results(self._fetch(NAVER_SEARCH + quote(text, safe=""))) if hangul else \
            _yahoo_results(self._fetch(YAHOO_SEARCH + quote(text, safe="")))
        unique = {row["symbol"]: row for row in reversed(rows)}
        ordered = [unique[row["symbol"]] for row in rows if unique.get(row["symbol"]) is row][:12]
        return {"schema_version": 1, "query": text, "results": ordered}

    def bars(self, symbol: str) -> dict[str, Any]:
        checked = valid_symbol(symbol)
        # range=max silently degrades to monthly rows; explicit bounds keep daily ones.
        def build():
            stop = int(datetime.now(timezone.utc).timestamp()) + 86_400
            url = (YAHOO_CHART + quote(checked, safe="") + "?period1=0&period2=" + str(stop)
                   + "&interval=1d&includePrePost=false")
            return parse_chart(self._fetch(url), checked)
        return self._cached("bars:" + checked, BARS_TTL, build)
