"""FRED fredgraph.csv 수집 (무키) — 일간→macro_daily, 월간→macro_monthly.

NASDAQCOM(나스닥 일간)은 Stooq 정본의 교차검증용으로 macro_daily에 둔다
(CHANGELOG #4 — price_daily PK 충돌 해소).
결측('.')은 저장하지 않는다 — 결측은 결측으로 (§10.1).
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime

from .. import config, net

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def _rows(sid: str) -> list[tuple[str, float]]:
    # WS-T5: 파이썬 시그니처 봇 필터 대응 — 실패 시 curl 폴백 (net.py 주석 참조)
    body = net.get_with_curl_fallback(URL.format(sid=sid), timeout=30)
    net.save_raw("fred", sid, body, "csv")
    reader = csv.reader(io.StringIO(body.decode("utf-8")))
    header = next(reader)
    assert len(header) == 2, f"FRED 형식 변화: {header}"
    out = []
    for row in reader:
        if len(row) != 2 or row[1] in (".", ""):
            continue  # 결측은 결측으로
        out.append((row[0], float(row[1])))
    return out


def ingest(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    for sid in config.FRED_DAILY:
        rows = [(sid, d, v, "fred", now) for d, v in _rows(sid)
                if since is None or d >= since]
        conn.executemany(
            "INSERT OR REPLACE INTO macro_daily (series_id,date,value,source,ingested_at)"
            " VALUES (?,?,?,?,?)", rows)
        counts[sid] = len(rows)
    for sid in config.FRED_MONTHLY:
        rows = [(sid, d, v, "fred", now) for d, v in _rows(sid)
                if since is None or d >= since]
        conn.executemany(
            "INSERT OR REPLACE INTO macro_monthly (series_id,date,value,source,ingested_at)"
            " VALUES (?,?,?,?,?)", rows)
        counts[sid] = len(rows)
    conn.commit()
    return counts
