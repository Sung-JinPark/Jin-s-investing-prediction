"""Jay Ritter IPO 통계 — 자동 xls 탐지 시도 → 실패 시 큐레이션 시드 폴백 (CHANGELOG #5).

버블 온도계 2대장: 연간 첫날수익률·적자기업 비율. 어느 경로든 source에 계보 명기.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from datetime import datetime

from .. import config, net


def _try_auto(conn: sqlite3.Connection, now: str) -> int:
    """리터 페이지에서 xls 링크 자동 탐지 → pandas 파싱. 성공 행 수 반환 (0 = 실패)."""
    try:
        page = net.get(config.RITTER_PAGE).decode("utf-8", errors="replace")
        links = re.findall(r'href="([^"]+\.xlsx?)"', page, re.I)
        cand = [l for l in links if re.search(r"ipo", l, re.I)]
        if not cand:
            return 0
        import pandas as pd
        for link in cand[:3]:
            url = link if link.startswith("http") else \
                "https://site.warrington.ufl.edu" + link
            try:
                body = net.get(url)
                net.save_raw("ritter", "auto", body, url.rsplit(".", 1)[-1])
                import io
                sheets = pd.read_excel(io.BytesIO(body), sheet_name=None, header=None)
            except Exception:  # noqa: BLE001
                continue
            n = 0
            for df in sheets.values():
                # 휴리스틱: 1열이 1975~2030 연도이고 수치 열이 2+개인 표 탐색
                for _, row in df.iterrows():
                    try:
                        year = int(row.iloc[0])
                    except (ValueError, TypeError):
                        continue
                    if not (1975 <= year <= 2030):
                        continue
                    nums = [x for x in row.iloc[1:6] if isinstance(x, (int, float))]
                    if len(nums) < 2:
                        continue
                    conn.execute(
                        "INSERT OR REPLACE INTO ipo_annual (year, ipo_count,"
                        " mean_first_day_ret, source, ingested_at) VALUES (?,?,?,?,?)",
                        (year, int(nums[0]), float(nums[1]),
                         f"ritter-auto({url})", now))
                    n += 1
            if n >= 20:
                return n
        return 0
    except Exception:  # noqa: BLE001
        return 0


def _seed_fallback(conn: sqlite3.Connection, now: str) -> int:
    path = config.SEEDS_DIR / "ritter_curated.csv"
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            conn.execute(
                """INSERT OR REPLACE INTO ipo_annual
                   (year, ipo_count, tech_count, mean_first_day_ret,
                    pct_negative_eps, proceeds_bil, source, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (int(r["year"]),
                 int(r["ipo_count"]) if r["ipo_count"] else None,
                 int(r["tech_count"]) if r["tech_count"] else None,
                 float(r["mean_first_day_ret"]) if r["mean_first_day_ret"] else None,
                 float(r["pct_negative_eps"]) if r["pct_negative_eps"] else None,
                 float(r["proceeds_bil"]) if r["proceeds_bil"] else None,
                 f"ritter-curated(tier3): {r['source']}", now))
            n += 1
    return n


def ingest(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    n_auto = _try_auto(conn, now)
    n_seed = 0
    if n_auto == 0:
        n_seed = _seed_fallback(conn, now)
    else:
        # 자동 파싱은 적자비율 컬럼 식별이 불확실 — 큐레이션의 pct_negative_eps로 보강
        n_seed = _seed_fallback_negative_eps_only(conn, now)
    conn.commit()
    return {"ritter_auto": n_auto, "ritter_curated": n_seed}


def _seed_fallback_negative_eps_only(conn: sqlite3.Connection, now: str) -> int:
    path = config.SEEDS_DIR / "ritter_curated.csv"
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["pct_negative_eps"]:
                continue
            conn.execute(
                "UPDATE ipo_annual SET pct_negative_eps = ?,"
                " source = source || ' + neg_eps:ritter-curated(tier3)' WHERE year = ?"
                " AND pct_negative_eps IS NULL",
                (float(r["pct_negative_eps"]), int(r["year"])))
            n += 1
    return n
