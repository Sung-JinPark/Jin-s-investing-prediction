"""'월 패턴 추정' 실적일을 회사가 확정한 실제 발표일로 따라간다 (표시 전용).

배경 (2026-11-18): NVIDIA Q3 실적이 캘린더에는 '11-18 추정'으로만 있었고 실제 발표는
11-17 장마감 후였다. 확정 일정만 감시·표시하므로 발표 뒤 10시간이 지나도 칸이 비었다.

Nasdaq 실적 캘린더는 회사가 확정한 일정과 추정 일정을 구분한다 — 추정 행에는
``lastYearRptDt``(작년 같은 분기 발표일)가 붙고, 확정 행에는 붙지 않는다. 확정 행만
믿고, 추정 이벤트를 supersedes 로 이어 붙인 새 확정 행으로 대체한다(기존 행 무수정).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .event_consensus import ConsensusError, _get_json
from .event_calendar import append_event, load_events

CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings?date={day}"
CALENDAR_PAGE = "https://www.nasdaq.com/market-activity/earnings"
LOOKBACK_DAYS = 7
LOOKAHEAD_DAYS = 14
# Nasdaq 은 정확한 시각을 주지 않고 구간만 준다. 칸의 시각은 구간의 대표값이다.
_TIME_ET = {"time-pre-market": "08:00", "time-after-hours": "16:30"}
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _quarter_end(text: Any) -> Optional[date]:
    match = re.fullmatch(r"([A-Za-z]{3})[A-Za-z]*[/ ](\d{4})", str(text or "").strip())
    if not match or match[1].lower() not in _MONTHS:
        return None
    month, year = _MONTHS[match[1].lower()], int(match[2])
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _confirmed_id(event_id: str, taken: set[str]) -> str:
    base = event_id[:-4] if event_id.endswith("_est") else f"{event_id}_c"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def sync_estimated_earnings(root: Path, *, now: Optional[datetime] = None,
                            fetch: Callable[[str], dict[str, Any]] = _get_json) -> dict[str, Any]:
    """추정 실적 이벤트를 Nasdaq 이 확정한 날짜·구간으로 대체하는 새 행을 덧붙인다."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    events = load_events(root)
    taken = {row["event_id"] for row in events}
    pending = [row for row in events if row["kind"] == "earnings" and row["status"] == "estimated"
               and row["ticker"] and today - timedelta(days=LOOKBACK_DAYS * 2)
               <= date.fromisoformat(row["date"]) <= today + timedelta(days=LOOKAHEAD_DAYS)]
    result: dict[str, Any] = {"checked": len(pending), "promoted": [], "failures": []}
    if not pending:
        return result
    wanted = {row["ticker"].upper() for row in pending}
    found: dict[str, list[tuple[date, dict[str, Any]]]] = {}
    for offset in range(-LOOKBACK_DAYS, LOOKAHEAD_DAYS + 1):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            rows = ((fetch(CALENDAR_URL.format(day=day.isoformat())).get("data") or {}).get("rows")) or []
        except ConsensusError as exc:
            result["failures"].append(str(exc))
            continue
        for raw in rows:
            symbol = str(raw.get("symbol", "")).upper()
            # 추정 행(작년 발표일 동반)은 확정이 아니다 — 건너뛴다.
            if symbol in wanted and "lastYearRptDt" not in raw:
                found.setdefault(symbol, []).append((day, raw))
    for row in pending:
        old_day = date.fromisoformat(row["date"])
        candidates = []
        for day, raw in found.get(row["ticker"].upper(), []):
            end = _quarter_end(raw.get("fiscalQuarterEnding"))
            # 같은 분기의 발표 — 분기말 뒤 75일 안, 추정일과 3주 이내.
            if end and timedelta(0) < day - end <= timedelta(days=75) and abs((day - old_day).days) <= 21:
                candidates.append((abs((day - old_day).days), day, raw))
        if not candidates:
            continue
        _, day, raw = min(candidates, key=lambda item: item[:2])
        time_et = _TIME_ET.get(str(raw.get("time", "")), "")
        if day.isoformat() == row["date"] and time_et == row["time_et"]:
            continue
        new_id = _confirmed_id(row["event_id"], taken)
        title = re.sub(r"\s*\(월 패턴 추정\)", "", row["title"]) + " (Nasdaq 캘린더 확정)"
        stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        append_event(root, {
            "event_id": new_id, "kind": "earnings", "date": day.isoformat(), "time_et": time_et,
            "status": "confirmed", "ticker": row["ticker"], "title": title,
            "source_id": row["source_id"], "source_url": CALENDAR_PAGE,
            "available_at": stamp, "registered_at": stamp, "supersedes": row["event_id"],
        })
        taken.add(new_id)
        result["promoted"].append(f"{row['event_id']} {row['date']} → {new_id} {day.isoformat()} {time_et}".strip())
    return result
