"""Cheap stdlib-only decision: does the daily6m v2 shadow have a paired forecast or new paired outcomes to process?

forecast=true  when the latest active v1 forecast has no v2 pair yet and now is before 16:00 America/New_York
               on that v1 run's first target session (early closes are re-judged by the real command, which holds).
resolve=true   when a paired v1 forecast has an active v1 resolution not yet scored by v2.
work = forecast or resolve.  Missing ledgers mean empty sets (first run).  No model or source writes.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

V1 = Path("data/timeseries_daily6m/ledgers")
V2 = Path("data/timeseries_daily6m_v2/ledgers")
NEW_YORK = ZoneInfo("America/New_York")
REGULAR_CLOSE = time(16, 0)


def rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def active(items: list[dict], identity: str) -> list[dict]:
    superseded = {row["supersedes"] for row in items if row.get("supersedes")}
    return [row for row in items if row[identity] not in superseded]


def first_target_close(root: Path, v1_row: dict) -> datetime:
    run = json.loads((root / v1_row["run_path"]).read_text(encoding="utf-8"))
    day = datetime.fromisoformat(run["dates"][0]).date()
    return datetime.combine(day, REGULAR_CLOSE, tzinfo=NEW_YORK).astimezone(timezone.utc)


def decide(root: Path, now: datetime) -> dict:
    v1_forecasts = active(rows(root / V1 / "forecasts.jsonl"), "forecast_id")
    v2_forecasts = rows(root / V2 / "forecasts.jsonl")
    paired = {row["paired_v1_forecast_id"] for row in v2_forecasts}
    forecast = False
    reason = "no active v1 forecast"
    if v1_forecasts:
        latest = v1_forecasts[-1]
        if latest["forecast_id"] in paired:
            reason = "latest v1 forecast already paired"
        else:
            close = first_target_close(root, latest)
            forecast = now < close
            reason = "unpaired latest v1 forecast" if forecast else "pair window closed at " + close.isoformat()
    scored = {row["v1_resolution_id"] for row in rows(root / V2 / "resolutions.jsonl")}
    pending = [row["resolution_id"] for row in active(rows(root / V1 / "resolutions.jsonl"), "resolution_id")
               if row["forecast_id"] in paired and row["resolution_id"] not in scored]
    resolve = bool(pending)
    return {"schema_version": 1, "as_of": now.isoformat(), "forecast": forecast, "forecast_reason": reason,
            "resolve": resolve, "pending_v1_resolutions": len(pending), "work": forecast or resolve,
            "model_writes": False, "source_writes": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--as-of")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    options = parser.parse_args()
    now = datetime.now(timezone.utc) if options.as_of is None else datetime.fromisoformat(options.as_of)
    if now.tzinfo is None:
        raise SystemExit("--as-of needs an explicit timezone")
    report = decide(options.root, now.astimezone(timezone.utc))
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if options.github_output:
        with options.github_output.open("a", encoding="utf-8") as handle:
            for key in ("forecast", "resolve", "work"):
                handle.write(f"{key}={str(report[key]).lower()}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
