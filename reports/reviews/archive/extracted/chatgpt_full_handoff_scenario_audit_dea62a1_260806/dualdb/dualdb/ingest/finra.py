"""FINRA 마진부채 월간 (Tier-2 — 페이지 테이블 파싱) → margin_debt_monthly.

1997+ FINRA 계보. 페이지가 노출하는 범위만 수집 — 없으면 없다고 기록 (원칙 3).
Q13(마진부채 YoY 동시점)의 AI측 원천. 닷컴측(1997~2003)은 페이지 노출 범위에
따라 부분일 수 있음 — 커버리지 리포트로 확인.
"""

from __future__ import annotations

import io
import re
import sqlite3
from datetime import datetime

from .. import net

URL = "https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _parse_month(text: str) -> str | None:
    """'Jan-26' / 'January 2026' / '2026-01' → '2026-01'."""
    t = str(text).strip().lower()
    m = re.match(r"^(\d{4})-(\d{2})$", t)
    if m:
        return t
    m = re.match(r"^([a-z]{3,9})[\s\-]+'?(\d{2,4})$", t)
    if not m:
        return None
    mon = MONTHS.get(m.group(1)[:3])
    if not mon:
        return None
    year = int(m.group(2))
    year = year + 2000 if year < 50 else (year + 1900 if year < 100 else year)
    return f"{year:04d}-{mon:02d}"


def _to_bil(v) -> float | None:
    """백만$ 표기(FINRA 관례) → 십억$. 숫자·콤마 문자열 허용."""
    try:
        s = re.sub(r"[^\d.]", "", str(v))
        if not s:
            return None
        return round(float(s) / 1000.0, 3)
    except ValueError:
        return None


def ingest(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    import pandas as pd

    now = datetime.now().isoformat(timespec="seconds")
    body = net.get(URL, timeout=60)
    net.save_raw("finra", "margin_stats", body, "html")
    tables = pd.read_html(io.BytesIO(body))

    n = 0
    for df in tables:
        cols = [str(c).lower() for c in df.columns]
        # 'debit'을 포함한 열이 있는 표만 (마진부채 테이블 식별)
        debit_idx = next((i for i, c in enumerate(cols) if "debit" in c), None)
        if debit_idx is None or len(cols) < 2:
            continue
        credit_idx = next((i for i, c in enumerate(cols) if "credit" in c), None)
        for _, row in df.iterrows():
            month = _parse_month(row.iloc[0])
            if month is None or (since and month < since[:7]):
                continue
            debit = _to_bil(row.iloc[debit_idx])
            if debit is None:
                continue  # 결측은 결측으로
            credit = _to_bil(row.iloc[credit_idx]) if credit_idx is not None else None
            conn.execute(
                "INSERT OR REPLACE INTO margin_debt_monthly"
                " (date, debit_bil, credit_bil, source, ingested_at) VALUES (?,?,?,?,?)",
                (month + "-01", debit, credit, "finra(tier2)", now))
            n += 1
    conn.commit()
    return {"finra_margin_months": n}
