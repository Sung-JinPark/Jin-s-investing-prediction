#!/usr/bin/env python3
"""V7 Ralph research controller. It never promotes, publishes, or trades."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ai_fc.timeseries_v7.scheduler import (  # noqa: E402
    task_blueprint,
)
from ai_fc.timeseries_v7.security import sanitized_environment  # noqa: E402


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    sub = value.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--cycle-id", required=True)
    plan.add_argument("--generation-id", required=True)
    sub.add_parser("status")
    for name in ("init", "run", "worker", "resume", "pause", "abort", "reconcile", "report"):
        sub.add_parser(name)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.command == "plan":
        tasks = task_blueprint(args.run_id, args.cycle_id, args.generation_id)
        print(json.dumps({"tasks": tasks, "automatic_publication": False, "automatic_trading": False}, indent=2))
        return 0
    dsn_present = bool(os.environ.get("RALPH_V7_DATABASE_URL"))
    report = {
        "command": args.command,
        "database_configured": dsn_present,
        "state": "WAIT_DATA" if args.command in {"init", "status", "resume", "report"} else "BLOCKED_DATABASE",
        "automatic_publication": False,
        "automatic_trading": False,
        "provider_secrets_visible_to_controller": bool(
            set(os.environ) - set(sanitized_environment("evaluator", os.environ))
        ),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(report, indent=2))
    return 0 if dsn_present or args.command in {"status", "report"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
