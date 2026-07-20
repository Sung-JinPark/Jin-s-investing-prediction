"""Yahoo v8 chart API — 트윈·AI측 종목 일간 (상장~현재, adj close 포함).

yfinance 대신 표준 라이브러리 (CHANGELOG #3). 원본 JSON은 data/raw/yahoo 보존.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from datetime import datetime, timezone

from .. import config, net

# range=max는 interval=1d를 무시하고 월간/주간으로 강등된다 (2026-07-15 실측) —
# period1/period2 명시가 전기간 일간을 보장 (ai_fc quant/feed.py에서 검증된 패턴)
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
       "?interval=1d&period1=0&period2={p2}")


def _series(sym: str) -> list[tuple]:
    """전기간 + 최근 30일 top-up 병합 — 초장기 요청은 마지막 1~2봉을 누락하는
    경우가 있어(2026-07-15 실측) 최근 구간을 별도 요청해 덮어쓴다."""
    import time as _t

    now = int(_t.time())
    rows = dict()
    for p1 in (0, now - 30 * 86400):
        for r in _fetch(sym, p1, now):
            rows[r[0]] = r  # date 키 — 최근 요청이 우선
    return [rows[d] for d in sorted(rows)]


def _fetch(sym: str, p1: int, p2: int) -> list[tuple]:
    body = net.get(URL.format(sym=urllib.parse.quote(sym), p2=p2).replace(
        "period1=0", f"period1={p1}"))
    net.save_raw("yahoo", sym.replace("^", "idx_"), body, "json")
    data = json.loads(body)
    result = data["chart"]["result"][0]
    ts = result.get("timestamp") or []
    q = result["indicators"]["quote"][0]
    adj = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose") or [None] * len(ts)
    rows = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
        rows.append((d, q["open"][i], q["high"][i], q["low"][i], c, adj[i], q["volume"][i]))
    return rows


def ingest_indices(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    """지수 백본 — Stooq JS 벽으로 Yahoo가 정본 (CHANGELOG #6). canonical→yahoo 심볼 매핑."""
    now = datetime.now().isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    for canonical, sym in config.YAHOO_INDICES.items():
        try:
            rows = [(canonical, d, o, h, lo, c, a, v, "yahoo", now)
                    for d, o, h, lo, c, a, v in _series(sym)
                    if since is None or d >= since]
        except Exception as exc:  # noqa: BLE001
            counts[canonical] = -1
            continue
        conn.executemany(
            "INSERT OR REPLACE INTO price_daily "
            "(series,date,open,high,low,close,adj_close,volume,source,ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        counts[canonical] = len(rows)
    conn.commit()
    return counts


def ingest(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    for sym in config.YAHOO_DAILY:
        try:
            rows = [(sym, d, o, h, lo, c, a, v, "yahoo", now)
                    for d, o, h, lo, c, a, v in _series(sym)
                    if since is None or d >= since]
        except Exception as exc:  # noqa: BLE001 — 종목 1개 실패가 전체를 막지 않게
            counts[sym] = -1
            conn.execute(
                "UPDATE entity SET source_note = COALESCE(source_note,'') || ? "
                "WHERE data_ticker = ?",
                (f" | data_gap: yahoo 실패 {type(exc).__name__} ({now[:10]})", sym))
            continue
        conn.executemany(
            "INSERT OR REPLACE INTO price_daily "
            "(series,date,open,high,low,close,adj_close,volume,source,ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        counts[sym] = len(rows)
    conn.commit()
    return counts
