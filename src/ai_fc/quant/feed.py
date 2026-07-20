"""데이터 피드 — Yahoo chart API + FRED CSV (키 불필요, 표준 라이브러리만)."""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


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
    raise last  # type: ignore[misc]


def yahoo_series(symbol: str, start: date, end: date, interval: str = "1mo"
                 ) -> tuple[list[date], list[float]]:
    """Yahoo chart API에서 (일자, 종가) 시계열. 1mo는 월초 스탬프 = 해당 월."""
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?interval={interval}&period1={p1}&period2={p2}")
    data = json.loads(_get(url))
    result = data["chart"]["result"][0]
    ts = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    dates, vals = [], []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        dates.append(datetime.fromtimestamp(t, tz=timezone.utc).date())
        vals.append(float(c))
    return dates, vals


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
