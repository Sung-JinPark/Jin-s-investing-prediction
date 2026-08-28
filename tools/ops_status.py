"""One-shot operations status for the FRED refresh pipelines.

Run manually at the start of a work session (never scheduled — heavy or
unattended automation stays opt-in):

    python tools/ops_status.py

Reports, per refresh workflow: the last three run conclusions, the newest
failure's URL, the latest bot data-commit dates on origin/main, and the
current V2 hold reasons with market freshness — applying the documented
216-hour allowance for the weekly-published DTWEXBGS group (KNOWN_LIMITS).
GitHub cron delays of several hours are normal and are not failures.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO = "Sung-JinPark/Jin-s-investing-prediction"
WORKFLOWS = ("timeseries-refresh.yml", "timeseries-v2-refresh.yml")
DTWEXBGS_ALLOWANCE_HOURS = 216.0


def _gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh {' '.join(args)} failed")
    return result.stdout


def workflow_status() -> None:
    for workflow in WORKFLOWS:
        rows = json.loads(_gh(
            "run", "list", "--repo", REPO, "--workflow", workflow, "--limit", "3",
            "--json", "createdAt,event,conclusion,htmlUrl",
        ))
        print(f"\n== {workflow}")
        if not rows:
            print("  (no runs)")
            continue
        for row in rows:
            print(f"  {row['createdAt']} [{row['event']}] {row['conclusion'] or 'running'}")
        newest_failure = next((row for row in rows if row["conclusion"] == "failure"), None)
        if newest_failure:
            print(f"  latest failure: {newest_failure['htmlUrl']}")


def bot_commits() -> None:
    log = subprocess.run(
        ["git", "log", "origin/main", "--author=github-actions", "-5",
         "--format=%ad %s", "--date=format:%Y-%m-%d %H:%M"],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT,
    ).stdout.strip()
    print("\n== latest bot data commits (origin/main)")
    print("\n".join(f"  {line}" for line in log.splitlines()) or "  (none)")


def v2_hold() -> None:
    path = REPO_ROOT / "data/timeseries_v2/multivariate_v2_latest.json"
    if not path.is_file():
        print("\n== V2 latest pointer: missing locally (fetch/checkout main)")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(f"\n== V2 status: {payload.get('status')} (gate pass: {payload.get('gate', {}).get('pass')})")
    for reason in payload.get("gate", {}).get("reasons", []):
        print(f"  - {reason}")
    freshness = (payload.get("data_summary") or {}).get("required_market_freshness") or {}
    now = datetime.now(timezone.utc)
    for group in freshness.get("groups", []):
        limit = DTWEXBGS_ALLOWANCE_HOURS if "DTWEXBGS" in group["group"] else float(
            freshness.get("maximum_age_hours", 48.0)
        )
        available = group.get("available_at")
        age = (now - datetime.fromisoformat(available)).total_seconds() / 3600.0 if available else None
        status = "?" if age is None else ("fresh" if age <= limit else "stale")
        shown = "n/a" if age is None else f"{age:.0f}h"
        print(f"  {group['group']}: obs {group.get('observation_time')} age {shown} (limit {limit:.0f}h) -> {status}")


def main() -> int:
    print(f"ops status @ {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    try:
        workflow_status()
    except (RuntimeError, OSError) as exc:
        print(f"  gh unavailable: {exc}")
    bot_commits()
    v2_hold()
    return 0


if __name__ == "__main__":
    sys.exit(main())
