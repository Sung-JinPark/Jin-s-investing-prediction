"""Polymarket Gamma API — 무인증 공개 read. Kalshi 실패 시 폴백."""

from __future__ import annotations

import json
import urllib.parse

from ..quant.feed import _get
from .kalshi import MarketQuote

API = "https://gamma-api.polymarket.com"


def _yes_price(m: dict) -> float | None:
    outcomes = json.loads(m.get("outcomes") or "[]")
    prices = json.loads(m.get("outcomePrices") or "[]")
    for name, price in zip(outcomes, prices):
        if str(name).lower() == "yes":
            return float(price)
    return None


def fetch_market_prob(slug: str) -> MarketQuote | None:
    """슬러그로 시장 조회 → YES 아웃컴 가격. 실패 시 None (fail-soft)."""
    try:
        url = f"{API}/markets?" + urllib.parse.urlencode({"slug": slug})
        markets = json.loads(_get(url, timeout=30, retries=2))
        if not markets:
            return None
        p = _yes_price(markets[0])
        if p is None:
            return None
        return MarketQuote(prob=p, source="polymarket", detail={
            "slug": slug, "volume": markets[0].get("volume")})
    except Exception:  # noqa: BLE001
        return None


def fetch_event_sum(query: str, event_slug_contains: str,
                    market_slug_contains: list[str],
                    must_contain: str = "") -> MarketQuote | None:
    """이벤트 검색 → 조건에 맞는 하위 시장들의 YES 가격 **합**.

    다중 아웃컴 이벤트(예: FOMC 인상 25bp/50bp 분리 상장)를 하나의 질문
    ("25bp 이상 인상")으로 접는 용도. 상호배타 아웃컴 가정 — detail에 합산 시장 기록.
    """
    try:
        url = f"{API.replace('gamma-api', 'gamma-api')}/public-search?" \
            + urllib.parse.urlencode({"q": query})
        data = json.loads(_get(url, timeout=30, retries=2))
        for e in data.get("events", []):
            if event_slug_contains not in (e.get("slug") or ""):
                continue
            total, used = 0.0, []
            for m in e.get("markets", []):
                slug = m.get("slug") or ""
                if must_contain and must_contain not in slug:
                    continue
                if not any(c in slug for c in market_slug_contains):
                    continue
                p = _yes_price(m)
                if p is not None:
                    total += p
                    used.append(f"{slug}={p:.4f}")
            if used:
                return MarketQuote(prob=min(total, 1.0), source="polymarket", detail={
                    "event": e.get("slug"), "summed_markets": used,
                    "note": "상호배타 아웃컴 YES 가격 합산"})
        return None
    except Exception:  # noqa: BLE001
        return None
