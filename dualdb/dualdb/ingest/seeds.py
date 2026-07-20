"""큐레이션 시드 적재 (Tier-3) + era·alignment(calendar_m) 초기화."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from .. import config


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _month_add(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def ingest(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    s = config.SEEDS_DIR

    # era
    for era_id, a in config.ANCHORS.items():
        conn.execute(
            "INSERT OR REPLACE INTO era (era_id, anchor_month, peak_date, bottom_date, note)"
            " VALUES (?,?,?,?,?)",
            (era_id, a["anchor_month"], a.get("peak_date"), a.get("bottom_date"),
             "AI 정점·바닥 미확정 — NULL 유지" if era_id == "ai" else None))

    # alignment: calendar_m M+0 ~ M+60
    for n in range(0, 61):
        conn.execute(
            "INSERT OR REPLACE INTO alignment (method, cycle_index, event_name,"
            " dotcom_date, ai_date) VALUES ('calendar_m', ?, '', ?, ?)",
            (float(n),
             _month_add(config.ANCHORS["dotcom"]["anchor_month"], n),
             _month_add(config.ANCHORS["ai"]["anchor_month"], n)))
    # alignment: event (닷컴측 확정, AI측은 데이터에서 확정되는 항목은 derive가 갱신)
    for name, dc, ai in [("midterm", "1998-11-03", "2026-11-03"),
                         ("crisis_bottom", "1998-10-08", None),
                         ("peak", "2000-03-10", None)]:
        conn.execute(
            "INSERT OR REPLACE INTO alignment (method, cycle_index, event_name,"
            " dotcom_date, ai_date) VALUES ('event', 0, ?, ?, ?)", (name, dc, ai))
    counts["alignment"] = 64

    for r in _load_csv(s / "roles.csv"):
        conn.execute(
            "INSERT OR REPLACE INTO role (role_code, name_kr, layer, description)"
            " VALUES (?,?,?,?)",
            (r["role_code"], r["name_kr"], int(r["layer"]), r["description"]))
    counts["roles"] = conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"]

    for i, r in enumerate(_load_csv(s / "entities.csv"), start=1):
        conn.execute(
            """INSERT OR REPLACE INTO entity (entity_id, era_id, ticker, name, role_code,
               status, data_ticker, is_twin, survivorship_note, source_note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (i, r["era_id"], r["ticker"], r["name"], r["role_code"], r["status"],
             r["data_ticker"] or None, int(r["is_twin"]),
             r["survivorship_note"], r["source_note"]))
    counts["entities"] = conn.execute("SELECT COUNT(*) c FROM entity").fetchone()["c"]

    for r in _load_csv(s / "dotcom_casualty.csv"):
        conn.execute(
            """INSERT OR REPLACE INTO dotcom_casualty
               (name, role_code, peak_mcap_bil, peak_date, outcome,
                months_after_index_peak, source) VALUES (?,?,?,?,?,?,?)""",
            (r["name"], r["role_code"],
             float(r["peak_mcap_bil"]) if r["peak_mcap_bil"] else None,
             r["peak_date"] or None, r["outcome"],
             float(r["months_after_index_peak"]) if r["months_after_index_peak"] else None,
             r["source"]))
    counts["casualties"] = conn.execute("SELECT COUNT(*) c FROM dotcom_casualty").fetchone()["c"]

    conn.execute("DELETE FROM event")  # 시드가 원천 — 전량 재적재 (멱등)
    for i, r in enumerate(_load_csv(s / "events.csv"), start=1):
        conn.execute(
            """INSERT OR REPLACE INTO event (event_id, era_id, date, type, title,
               magnitude, cycle_month, source_url, note) VALUES (?,?,?,?,?,?,?,?,?)""",
            (i, r["era_id"], r["date"], r["type"], r["title"],
             float(r["magnitude"]) if r["magnitude"] else None,
             float(r["cycle_month"]) if r["cycle_month"] else None,
             r["source_url"], r["note"]))
    counts["events"] = conn.execute("SELECT COUNT(*) c FROM event").fetchone()["c"]

    for r in _load_csv(s / "capex_buildout.csv"):
        conn.execute(
            """INSERT OR REPLACE INTO capex_buildout_annual
               (era_id, year, capex_bil, gdp_pct, tier, source, note)
               VALUES (?,?,?,?,?,?,?)""",
            (r["era_id"], int(r["year"]), float(r["capex_bil"]),
             float(r["gdp_pct"]) if r["gdp_pct"] else None,
             int(r["tier"]), r["source"], r["note"]))
    counts["capex"] = conn.execute(
        "SELECT COUNT(*) c FROM capex_buildout_annual").fetchone()["c"]

    conn.commit()
    return counts
