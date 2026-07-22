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

    # alignment (long format): calendar_m M+0 ~ M+60 — 전 시대 era별 1행
    n_align = 0
    for n in range(0, 61):
        for era_id, a in config.ANCHORS.items():
            conn.execute(
                "INSERT OR REPLACE INTO alignment (method, cycle_index, event_name,"
                " era_id, date) VALUES ('calendar_m', ?, '', ?, ?)",
                (float(n), era_id, _month_add(a["anchor_month"], n)))
            n_align += 1
    # alignment: event — peak/bottom은 config anchors에서 전 시대 일반화 (미확정 = NULL).
    # midterm(미 중간선거)·crisis_bottom(사이클 중반 위기 저점 — AI측은 derive가 실측
    # 갱신)은 dotcom↔ai 특화 이벤트로 두 시대만 기록.
    for era_id, a in config.ANCHORS.items():
        for name, d in (("peak", a.get("peak_date")), ("bottom", a.get("bottom_date"))):
            conn.execute(
                "INSERT OR REPLACE INTO alignment (method, cycle_index, event_name,"
                " era_id, date) VALUES ('event', 0, ?, ?, ?)", (name, era_id, d))
            n_align += 1
    for name, era_id, d in [("midterm", "dotcom", "1998-11-03"),
                            ("midterm", "ai", "2026-11-03"),
                            ("crisis_bottom", "dotcom", "1998-10-08"),
                            ("crisis_bottom", "ai", None)]:
        conn.execute(
            "INSERT OR REPLACE INTO alignment (method, cycle_index, event_name,"
            " era_id, date) VALUES ('event', 0, ?, ?, ?)", (name, era_id, d))
        n_align += 1
    counts["alignment"] = n_align

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
