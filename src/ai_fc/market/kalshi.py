"""Kalshi 예측시장 — 공개 market data API (read 무인증 시도, 실패 시 None).

이벤트 질문(FOMC 등)의 시장내재확률 1차 소스. 가격 단위: 센트(0~100).
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field

from ..quant.feed import _get

API = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass
class MarketQuote:
    prob: float
    source: str
    detail: dict = field(default_factory=dict)


def _mid_prob(m: dict) -> float | None:
    bid, ask = m.get("yes_bid") or 0, m.get("yes_ask") or 0
    if bid and ask:
        return (bid + ask) / 2 / 100.0
    last = m.get("last_price") or 0
    return last / 100.0 if last else None


def fetch_series_markets(series_ticker: str) -> list[dict]:
    url = f"{API}/markets?" + urllib.parse.urlencode(
        {"series_ticker": series_ticker, "status": "open", "limit": 100})
    return json.loads(_get(url, timeout=30, retries=2)).get("markets", [])


def fetch_market_prob(series_ticker: str, contains: list[str],
                      title_contains: list[str] | None = None) -> MarketQuote | None:
    """시리즈에서 조건(티커 부분일치 AND, 제목 부분일치 AND)에 맞는 첫 시장의 mid 확률.

    401/403/파싱 실패 등 모든 오류는 None (fail-soft — 폴백 provider로 넘어감).
    """
    try:
        markets = fetch_series_markets(series_ticker)
        for m in markets:
            ticker = (m.get("ticker") or "").upper()
            title = f"{m.get('title', '')} {m.get('subtitle', '')} {m.get('yes_sub_title', '')}".lower()
            if not all(c.upper() in ticker for c in contains):
                continue
            if title_contains and not all(t.lower() in title for t in title_contains):
                continue
            p = _mid_prob(m)
            if p is None:
                continue
            return MarketQuote(prob=p, source="kalshi", detail={
                "ticker": m.get("ticker"), "yes_bid": m.get("yes_bid"),
                "yes_ask": m.get("yes_ask"), "volume": m.get("volume")})
        return None
    except Exception:  # noqa: BLE001 — 인증 요구·네트워크·스키마 변경 전부 폴백
        return None
