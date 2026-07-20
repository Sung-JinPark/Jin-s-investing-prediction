"""Shiller ie_data.xls — CAPE·S&P·GS10 월간 (1871~). valuation_monthly + macro_monthly."""

from __future__ import annotations

import io
import sqlite3
from datetime import datetime

from .. import config, net


def _parse_date(v: float) -> str | None:
    """1996.01 → '1996-01', 1996.1 → '1996-10' (Shiller 표기 특칙)."""
    try:
        f = float(v)
        if f != f:  # nan 가드
            return None
        s = f"{f:.2f}"
    except (ValueError, TypeError):
        return None
    year, month = s.split(".")
    if len(year) != 4:
        return None
    m = int(month)
    if not 1 <= m <= 12:
        return None
    return f"{year}-{m:02d}"


def ingest(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    import pandas as pd

    now = datetime.now().isoformat(timespec="seconds")
    body = net.get(config.SHILLER_URL, timeout=120)
    net.save_raw("shiller", "ie_data", body, "xls")
    df = pd.read_excel(io.BytesIO(body), sheet_name="Data", header=None)

    # 헤더 행 탐색: 첫 열이 'Date'인 행
    header_row = None
    for i in range(min(15, len(df))):
        if str(df.iloc[i, 0]).strip().lower() == "date":
            header_row = i
            break
    if header_row is None:
        raise RuntimeError("Shiller 시트에서 Date 헤더를 찾지 못함 — 형식 변화")

    # 관례적 컬럼 위치: 0=Date, 1=P(S&P), 7=GS10, CAPE는 헤더에 'CAPE' 포함 열 탐색
    cape_col = None
    for c in range(df.shape[1]):
        col_text = " ".join(str(df.iloc[r, c]) for r in range(header_row + 1))
        if "CAPE" in col_text and "TR" not in col_text:
            cape_col = c
            break
    if cape_col is None:
        raise RuntimeError("CAPE 열을 찾지 못함 — 형식 변화")

    n = 0
    for i in range(header_row + 2, len(df)):
        d = _parse_date(df.iloc[i, 0])
        if d is None or (since and d < since[:7]):
            continue
        date_str = d + "-01"
        sp = df.iloc[i, 1]
        cape = df.iloc[i, cape_col]
        if isinstance(sp, (int, float)):
            conn.execute(
                "INSERT OR REPLACE INTO macro_monthly (series_id,date,value,source,ingested_at)"
                " VALUES (?,?,?,?,?)", ("SHILLER_SP", date_str, float(sp), "shiller", now))
        if isinstance(cape, (int, float)):
            conn.execute(
                """INSERT INTO valuation_monthly (scope,date,cape,tier,source,ingested_at)
                   VALUES ('SP500',?,?,1,'shiller',?)
                   ON CONFLICT(scope,date) DO UPDATE SET cape=excluded.cape""",
                (date_str, float(cape), now))
            n += 1
    conn.commit()
    return {"shiller_cape": n}
