"""Parse the public Yahoo history page used for the user's research illustration.

Only the embedded daily chart response is read. Adjusted close is never used to
manufacture OHLC. Null observations remain null evidence for the research gate.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from zoneinfo import ZoneInfo

from .contracts import TrendlinesError


class _HistoryScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current: list[str] | None = None
        self.attributes: dict[str, str | None] = {}
        self.scripts: list[tuple[dict[str, str | None], str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/json":
            self.current, self.attributes = [], dict(attrs)

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.current is not None:
            self.scripts.append((self.attributes, "".join(self.current)))
            self.current = None


def parse_yahoo_history(raw: bytes, asset: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected = asset.get("provider_symbol", asset["symbol"])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrendlinesError("public history page is not UTF-8") from exc
    parser = _HistoryScripts()
    parser.feed(text)
    candidates = []
    for attrs, body in parser.scripts:
        url = attrs.get("data-url") or ""
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if ("data-sveltekit-fetched" not in attrs or parsed.scheme != "https"
                or parsed.username or parsed.password or parsed.fragment
                or parsed.hostname not in {"query1.finance.yahoo.com", "query2.finance.yahoo.com"}
                or unquote(parsed.path) != "/v8/finance/chart/" + expected
                or query.get("interval") != ["1d"]):
            continue
        try:
            envelope = json.loads(body)
            if envelope.get("status") != 200 or type(envelope.get("status")) is not int:
                raise TrendlinesError("embedded daily source response did not succeed")
            chart = json.loads(envelope["body"])["chart"]
            if chart.get("error") is not None or len(chart.get("result") or []) != 1:
                raise TrendlinesError("ambiguous or failed embedded daily source")
            item = chart["result"][0]
            meta = item["meta"]
            if meta.get("symbol") != expected or meta.get("dataGranularity") != "1d":
                raise TrendlinesError("public daily instrument identity mismatch")
            if meta.get("currency") != asset["currency"]:
                raise TrendlinesError("public daily currency mismatch")
            if meta.get("exchangeTimezoneName") != asset["timezone"]:
                raise TrendlinesError("public daily timezone mismatch")
            timestamps = item["timestamp"]
            quotes = item["indicators"]["quote"]
            if not isinstance(timestamps, list) or len(quotes) != 1:
                raise TrendlinesError("invalid public daily quote arrays")
            values = quotes[0]
            if any(not isinstance(values.get(k), list) or len(values[k]) != len(timestamps)
                   for k in ("open", "high", "low", "close")):
                raise TrendlinesError("public OHLC arrays are not aligned")
            volume = values.get("volume")
            if volume is not None and (not isinstance(volume, list) or len(volume) != len(timestamps)):
                raise TrendlinesError("public volume array is not aligned")
            rows = []
            zone = ZoneInfo(meta["exchangeTimezoneName"])
            for index, stamp in enumerate(timestamps):
                if type(stamp) is not int:
                    raise TrendlinesError("public daily timestamp must be an integer")
                row = {"date": datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date().isoformat(),
                       **{key: values[key][index] for key in ("open", "high", "low", "close")},
                       "volume": volume[index] if volume is not None else None}
                rows.append(row)
            days = [row["date"] for row in rows]
            if days != sorted(set(days)):
                raise TrendlinesError("public daily sessions are duplicate or unordered")
            market_time = meta.get("regularMarketTime")
            observed = datetime.fromtimestamp(market_time, timezone.utc).isoformat() if type(market_time) is int else None
            metadata = {**meta, "events": item.get("events") or {},
                        "embedded_source_url": url, "parser_id": "yahoo_history_html_v1",
                        "price_column": "close_not_adj_close", "adjustment_verified": False,
                        "quote": {"price": meta.get("regularMarketPrice"), "observed_at": observed,
                                  "symbol": expected, "currency": meta["currency"],
                                  "status": "separate_provider_quote_not_final_daily_candle"}}
            candidates.append((rows, metadata))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            if isinstance(exc, TrendlinesError):
                raise
            raise TrendlinesError("invalid embedded public daily response") from exc
    if len(candidates) != 1:
        raise TrendlinesError("one exact embedded public daily response required")
    return candidates[0]
