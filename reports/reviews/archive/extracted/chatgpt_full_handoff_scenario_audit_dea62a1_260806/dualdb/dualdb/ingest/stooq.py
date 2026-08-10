"""Stooq 일간 CSV — 지수 백본(^IXIC·^SPX·^NDX·^SOX, 닷컴기 포함 OHLCV) + 상폐종목 시도.

상폐·개명 심볼(yhoo.us 등)이 무자료면 entity.source_note에 data_gap 기록 —
없으면 없다고 기록한다 (원칙 3).
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime

from .. import config, net

URL = "https://stooq.com/q/d/l/?s={sym}&i=d"


def ingest(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    for canonical, sym in config.STOOQ.items():
        body = net.get(URL.format(sym=sym))
        text = body.decode("utf-8", errors="replace")
        if len(text) < 100 or text.lower().startswith("no data"):
            counts[canonical] = 0
            conn.execute(
                "UPDATE entity SET source_note = COALESCE(source_note,'') || ? "
                "WHERE data_ticker = ?",
                (f" | data_gap: stooq {sym} 무자료 ({now[:10]})", sym))
            continue
        net.save_raw("stooq", sym.replace("^", "idx_").replace(".", "_"), body, "csv")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for r in reader:
            d = r.get("Date", "")
            if not d or (since and d < since):
                continue
            try:
                rows.append((canonical, d,
                             float(r["Open"]), float(r["High"]), float(r["Low"]),
                             float(r["Close"]), None,
                             float(r["Volume"]) if r.get("Volume") not in (None, "", "0") else None,
                             "stooq", now))
            except (ValueError, KeyError):
                continue  # 결측 행은 저장하지 않음
        conn.executemany(
            "INSERT OR REPLACE INTO price_daily "
            "(series,date,open,high,low,close,adj_close,volume,source,ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        counts[canonical] = len(rows)
    conn.commit()
    return counts
