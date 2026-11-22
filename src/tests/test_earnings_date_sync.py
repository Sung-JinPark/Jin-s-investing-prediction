"""추정 실적일 → Nasdaq 확정일 동기화 (오프라인 fixture)."""
from __future__ import annotations

import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ai_fc import config
from ai_fc.earnings_date_sync import sync_estimated_earnings
from ai_fc.event_calendar import load_events

NOW = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)


def _root(tmp_path: Path) -> Path:
    (tmp_path / "data/calendar").mkdir(parents=True)
    (tmp_path / "data/contracts").mkdir(parents=True)
    shutil.copy(config.ROOT / "data/contracts/calendar_sources.yaml", tmp_path / "data/contracts/calendar_sources.yaml")
    with (config.ROOT / "data/calendar/events.csv").open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if r["event_id"] == "nvda_fy27_q3_est"]
    assert rows, "fixture needs the estimated NVDA event"
    with (tmp_path / "data/calendar/events.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return tmp_path


def _fetch(confirmed_day: str, *, estimate_style: bool = False):
    def fetch(url: str):
        day = url.rsplit("=", 1)[1]
        if day != confirmed_day:
            return {"data": {"rows": []}}
        row = {"symbol": "NVDA", "time": "time-after-hours", "fiscalQuarterEnding": "Oct/2026"}
        if estimate_style:
            row["lastYearRptDt"] = "11/20/2025"
        return {"data": {"rows": [row]}}
    return fetch


def test_estimated_date_is_superseded_by_confirmed_nasdaq_date(tmp_path):
    root = _root(tmp_path)
    result = sync_estimated_earnings(root, now=NOW, fetch=_fetch("2026-11-17"))
    assert result["promoted"] and not result["failures"]
    active = {r["event_id"]: r for r in load_events(root)}
    assert "nvda_fy27_q3_est" not in active
    row = active["nvda_fy27_q3"]
    assert (row["date"], row["status"], row["time_et"], row["supersedes"]) == (
        "2026-11-17", "confirmed", "16:30", "nvda_fy27_q3_est")
    # 원본 행은 지워지지 않는다(append-only).
    assert "nvda_fy27_q3_est" in (root / "data/calendar/events.csv").read_text(encoding="utf-8")
    # 멱등: 다시 돌려도 새 행이 없다.
    assert sync_estimated_earnings(root, now=NOW, fetch=_fetch("2026-11-17"))["promoted"] == []


def test_vendor_estimate_rows_are_not_treated_as_confirmed(tmp_path):
    root = _root(tmp_path)
    result = sync_estimated_earnings(root, now=NOW, fetch=_fetch("2026-11-17", estimate_style=True))
    assert result["promoted"] == []
    assert {r["event_id"] for r in load_events(root)} == {"nvda_fy27_q3_est"}


def test_other_fiscal_quarter_is_not_matched(tmp_path):
    root = _root(tmp_path)

    def fetch(url: str):
        day = url.rsplit("=", 1)[1]
        rows = [{"symbol": "NVDA", "time": "time-after-hours", "fiscalQuarterEnding": "Jul/2026"}] if day == "2026-11-17" else []
        return {"data": {"rows": rows}}

    assert sync_estimated_earnings(root, now=NOW, fetch=fetch)["promoted"] == []


def test_confirmed_row_names_the_calendar_it_came_from(tmp_path):
    root = _root(tmp_path)
    sync_estimated_earnings(root, now=NOW, fetch=_fetch("2026-11-17"))
    row = {r["event_id"]: r for r in load_events(root)}["nvda_fy27_q3"]
    assert row["source_url"] == "https://www.nasdaq.com/market-activity/earnings"
    assert "Nasdaq 캘린더 확정" in row["title"] and "추정" not in row["title"]
