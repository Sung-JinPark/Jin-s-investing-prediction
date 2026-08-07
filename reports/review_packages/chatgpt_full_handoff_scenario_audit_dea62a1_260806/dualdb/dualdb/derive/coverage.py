"""데이터 커버리지 리포트 — Phase 완료 보고용 (§0 규칙 6: 완료는 DoD 통과만)."""

from __future__ import annotations

import sqlite3


def report(conn: sqlite3.Connection) -> str:
    lines = ["# dualdb 커버리지 리포트", ""]
    rows = conn.execute(
        """SELECT series, COUNT(*) n, MIN(date) d0, MAX(date) d1, source
           FROM price_daily GROUP BY series ORDER BY series""").fetchall()
    lines.append("## price_daily")
    lines.append("| series | 행수 | 시작 | 끝 | source |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r['series']} | {r['n']:,} | {r['d0']} | {r['d1']} | {r['source']} |")

    lines.append("\n## macro_daily / monthly")
    for table in ("macro_daily", "macro_monthly"):
        for r in conn.execute(
                f"SELECT series_id, COUNT(*) n, MIN(date) d0, MAX(date) d1"
                f" FROM {table} GROUP BY series_id ORDER BY series_id"):
            lines.append(f"- {table}.{r['series_id']}: {r['n']:,}행 ({r['d0']} ~ {r['d1']})")

    for table, label in [("ipo_annual", "IPO 연간"), ("valuation_monthly", "밸류 월간"),
                         ("dotcom_casualty", "사상자"), ("event", "이벤트"),
                         ("entity", "엔티티"), ("capex_buildout_annual", "capex")]:
        n = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        lines.append(f"- {label}: {n}행")

    # ^IXIC 영업일 결측률 (1995-01-01~) — 센티널 게이트 참고치
    r = conn.execute(
        """SELECT COUNT(*) n, MIN(date) d0, MAX(date) d1 FROM price_daily
           WHERE series='^IXIC' AND date >= '1995-01-01'""").fetchone()
    if r["n"]:
        from datetime import date
        d0 = date.fromisoformat(r["d0"])
        d1 = date.fromisoformat(r["d1"])
        biz = sum(1 for i in range((d1 - d0).days + 1)
                  if (d0.fromordinal(d0.toordinal() + i)).weekday() < 5)
        missing = max(0.0, 1 - r["n"] / biz)
        lines.append(f"\n^IXIC 1995+ 커버리지: {r['n']:,}/{biz:,} 영업일 "
                     f"(결측 추정 {missing:.2%} — 미 공휴일 포함이라 실제는 더 낮음)")
    return "\n".join(lines)
