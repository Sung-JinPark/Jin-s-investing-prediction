"""데이터 피드 — Yahoo chart API + FRED CSV (키 불필요, 표준 라이브러리만)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


@dataclass(frozen=True)
class YahooPriceSeriesResult:
    dates: list[date]
    closes: list[float]
    adjusted: list[float]
    receipt: dict[str, Any]
    data_quality: dict[str, Any]


def _get(url: str, timeout: int = 60, retries: int = 3) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — 타임아웃·일시 오류 재시도
            last = exc
            time.sleep(2 * (attempt + 1))
    if last is None:
        raise RuntimeError("HTTP fetch was not attempted; retries must be at least 1")
    raise last


def yahoo_price_series_detail(symbol: str, start: date, end: date,
                              interval: str = "1mo") -> YahooPriceSeriesResult:
    """Yahoo 일자·종가·수정종가와 요청 영수증·품질 진단.

    공급자가 수정종가 배열을 생략하거나 빈 배열로 보내면 종가로 명시적
    fallback 한다. 반면 타임스탬프·종가·비어 있지 않은 수정종가의 길이가
    다르면 zip 절단 대신 실패한다. 0 이하 종가는 로그수익률에 흘려보내지
    않고 해당 행을 결측 처리한다.
    """
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?interval={interval}&period1={p1}&period2={p2}&events=div%2Csplits")
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw = _get(url)
    data = json.loads(raw)
    results = data.get("chart", {}).get("result") or []
    if not results:
        raise ValueError(f"Yahoo returned no chart result for {symbol}")
    result = results[0]
    ts = list(result.get("timestamp") or [])
    quotes = result.get("indicators", {}).get("quote") or []
    if not quotes:
        raise ValueError(f"Yahoo returned no quote indicator for {symbol}")
    closes = list(quotes[0].get("close") or [])
    if len(ts) != len(closes):
        raise ValueError(
            f"Yahoo timestamp/close length mismatch for {symbol}: {len(ts)} != {len(closes)}"
        )
    adj_nodes = result.get("indicators", {}).get("adjclose") or []
    adj_values = list((adj_nodes[0].get("adjclose") if adj_nodes else None) or [])
    adjusted_fallback = not adj_values
    if adjusted_fallback:
        adj_values = list(closes)
    elif len(adj_values) != len(ts):
        raise ValueError(
            f"Yahoo timestamp/adjclose length mismatch for {symbol}: "
            f"{len(ts)} != {len(adj_values)}"
        )

    dates: list[date] = []
    values: list[float] = []
    adjusted: list[float] = []
    dropped_rows = 0
    adjusted_fallback_rows = 0
    for stamp, close, adj in zip(ts, closes, adj_values, strict=True):
        if stamp is None or close is None or not isinstance(close, (int, float)) or close <= 0:
            dropped_rows += 1
            continue
        if adj is None or not isinstance(adj, (int, float)) or adj <= 0:
            adj = close
            adjusted_fallback_rows += 1
        dates.append(datetime.fromtimestamp(stamp, tz=timezone.utc).date())
        values.append(float(close))
        adjusted.append(float(adj))
    if not dates:
        raise ValueError(f"Yahoo returned no positive closes for {symbol}")
    quality = {
        "symbol": symbol,
        "status": "fallback_close" if adjusted_fallback else (
            "degraded" if dropped_rows or adjusted_fallback_rows else "ok"),
        "input_rows": len(ts),
        "output_rows": len(dates),
        "dropped_rows": dropped_rows,
        "adjusted_fallback": adjusted_fallback,
        "adjusted_fallback_rows": adjusted_fallback_rows,
    }
    receipt = {
        "source": "yahoo-chart",
        "symbol": symbol,
        "interval": interval,
        "request_url": url,
        "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "fetched_at": fetched_at,
    }
    return YahooPriceSeriesResult(dates, values, adjusted, receipt, quality)


def yahoo_price_series(symbol: str, start: date, end: date, interval: str = "1mo"
                       ) -> tuple[list[date], list[float], list[float]]:
    """Yahoo chart API의 일자·종가·수정종가 시계열.

    ``adjclose``는 분할과 현금배당을 반영하므로 Realty Income 같은 고배당
    자산의 가격수익과 총수익 proxy를 분리할 때만 명시적으로 사용한다.
    공급자가 수정종가를 주지 않으면 종가로 fail-soft 한다.
    """
    result = yahoo_price_series_detail(symbol, start, end, interval)
    return result.dates, result.closes, result.adjusted


def yahoo_series(symbol: str, start: date, end: date, interval: str = "1mo"
                 ) -> tuple[list[date], list[float]]:
    """Yahoo chart API에서 (일자, 종가) 시계열. 1mo는 월초 스탬프 = 해당 월."""
    dates, closes, _ = yahoo_price_series(symbol, start, end, interval)
    return dates, closes


def monthly_closes(symbol: str, start: date, end: date) -> tuple[list[str], list[float]]:
    """월별 종가 (YYYY-MM 라벨). 진행 중인 미완성 월은 제외."""
    dates, vals = yahoo_series(symbol, start, end, "1mo")
    today = date.today()
    out_labels, out_vals = [], []
    for d, v in zip(dates, vals):
        if d.year == today.year and d.month == today.month:
            continue  # 미완성 월
        out_labels.append(f"{d.year:04d}-{d.month:02d}")
        out_vals.append(v)
    return out_labels, out_vals


def fred_m2() -> dict[str, float]:
    """FRED M2SL 월별 ($B). {YYYY-MM: value}"""
    text = _get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    out = {}
    for row in reader:
        if len(row) < 2 or not row[1] or row[1] == ".":
            continue
        out[row[0][:7]] = float(row[1])
    return out
