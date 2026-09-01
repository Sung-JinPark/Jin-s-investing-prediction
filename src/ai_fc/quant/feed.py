"""데이터 피드 — Yahoo chart API + FRED CSV (키 불필요, 표준 라이브러리만)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_python_path_blocked = False


@dataclass(frozen=True)
class YahooPriceSeriesResult:
    dates: list[date]
    closes: list[float]
    adjusted: list[float]
    receipt: dict[str, Any]
    data_quality: dict[str, Any]


@dataclass(frozen=True)
class YahooDividendResult:
    dates: list[date]
    amounts: list[float]
    receipt: dict[str, Any]


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


def _resolve_via_public_dns(host: str, resolver: str = "1.1.1.1") -> str | None:
    """Resolve an A record when the local resolver intermittently blocks a source."""
    try:
        result = subprocess.run(
            ["nslookup", host, resolver], capture_output=True, text=True, timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    addresses = [
        value for value in re.findall(
            r"Address:\s+(\d+\.\d+\.\d+\.\d+)", result.stdout or ""
        ) if value != resolver
    ]
    return addresses[0] if addresses else None


def get_with_curl_fallback(url: str, *, timeout: int = 30) -> str:
    """Fetch text via Python, curl, then curl with a public-DNS resolution.

    The fallback changes only the transport, not the official source or URL,
    and preserves the exact response bytes used for receipt hashing.
    """
    global _python_path_blocked
    if not _python_path_blocked:
        try:
            return _get(url, timeout=timeout, retries=2)
        except Exception:  # noqa: BLE001 - use the verified transport fallback
            _python_path_blocked = True

    command = ["curl", "-sS", "--fail", "--max-time", str(timeout), url]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout + 5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"curl transport unavailable for {url}") from exc
    if result.returncode == 0 and result.stdout:
        return result.stdout.decode("utf-8")

    host = urllib.parse.urlparse(url).hostname
    address = _resolve_via_public_dns(host) if host else None
    if not host or not address:
        raise RuntimeError(
            f"curl failed ({result.returncode}) and public DNS did not resolve {host}"
        )
    resolved = subprocess.run(
        ["curl", "-sS", "--fail", "--max-time", str(timeout),
         "--resolve", f"{host}:443:{address}", url],
        capture_output=True, timeout=timeout + 5, check=False,
    )
    if resolved.returncode != 0 or not resolved.stdout:
        raise RuntimeError(f"curl --resolve failed ({resolved.returncode}) for {url}")
    return resolved.stdout.decode("utf-8")


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



def fred_price_series_detail(series_id: str, start: date, end: date,
                             interval: str = "1d") -> YahooPriceSeriesResult:
    """FRED 관측치를 가격 시계열 결과 모양으로 돌려준다 (DECISIONS 12-9).

    NASDAQ 종가는 9-5가 FRED(NASDAQCOM)를 정본으로 승격했고, Yahoo 약관은
    자동 수집을 명시 금지한다(12-5·12-8).  지수·BTC처럼 배당 조정 개념이 없는
    시리즈는 adjusted == closes이므로 의미 손실 없이 옮길 수 있다 — 배당조정이
    필요한 개별주(O·DHI)는 이 함수의 대상이 아니다.

    "1mo"는 달력 월초일로 라벨하고 값은 그 달 마지막 관측 종가다 — Yahoo 월봉과
    같은 의미이며, 소스가 갈린 월간 시계열의 교집합이 바 라벨 일자 차이로 비지
    않게 한다.  결측(".")은 관측이 아니므로 건너뛴다 (0으로 만들지 않는다).
    """
    from .. import fred_api

    raw = fred_api.observations_csv(series_id, observation_start=start.isoformat())
    dates: list[date] = []
    values: list[float] = []
    reader = csv.reader(io.StringIO(raw))
    next(reader, None)
    for row in reader:
        if len(row) < 2 or not row[1] or row[1] == ".":
            continue
        day = date.fromisoformat(row[0])
        if not (start <= day < end):
            continue
        dates.append(day)
        values.append(float(row[1]))
    if interval == "1mo":
        monthly: dict[date, float] = {}
        for day, value in zip(dates, values):
            monthly[date(day.year, day.month, 1)] = value  # 마지막 관측이 월말 종가로 남는다
        dates = sorted(monthly)
        values = [monthly[day] for day in dates]
    receipt = {
        "source": "fred-observations",
        "series_id": series_id,
        "interval": interval,
        # 키 없는 공개 URL만 기록한다 — 요청 URL을 그대로 적으면 시크릿이 남는다.
        "request_url": fred_api.observations_public_url(
            series_id, observation_start=start.isoformat()),
        "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    quality = {"status": "ok", "source": "fred-api", "dropped_rows": 0,
               "rows": len(dates)}
    return YahooPriceSeriesResult(dates, values, list(values), receipt, quality)

def yahoo_dividends(symbol: str, start: date, end: date) -> YahooDividendResult:
    """Return explicit cash-dividend events with a reproducibility receipt."""
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?interval=1d&period1={p1}&period2={p2}&events=div")
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw = _get(url)
    data = json.loads(raw)
    results = data.get("chart", {}).get("result") or []
    if not results:
        raise ValueError(f"Yahoo returned no dividend result for {symbol}")
    events = (results[0].get("events") or {}).get("dividends") or {}
    rows: list[tuple[date, float]] = []
    for event in events.values():
        stamp, amount = event.get("date"), event.get("amount")
        if not isinstance(stamp, (int, float)) or not isinstance(amount, (int, float)):
            continue
        if amount <= 0:
            continue
        rows.append((datetime.fromtimestamp(stamp, tz=timezone.utc).date(), float(amount)))
    rows.sort()
    return YahooDividendResult(
        dates=[row[0] for row in rows], amounts=[row[1] for row in rows],
        receipt={
            "source": "yahoo-chart", "symbol": symbol, "interval": "dividend_events",
            "request_url": url,
            "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "fetched_at": fetched_at,
        },
    )


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
    # FRED 약관은 API 경로만 자동 수집을 허용한다 (DECISIONS 12-6).
    from ..fred_api import observations_csv
    text = observations_csv("M2SL")
    reader = csv.reader(io.StringIO(text))
    next(reader)
    out = {}
    for row in reader:
        if len(row) < 2 or not row[1] or row[1] == ".":
            continue
        out[row[0][:7]] = float(row[1])
    return out
