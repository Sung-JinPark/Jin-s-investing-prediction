from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_fc.timeseries_v6.atlas import AtlasStore, AtlasTask, AtlasWorker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "run", "resume", "status", "report"])
    parser.add_argument("--db", default="outputs/timeseries_v6/atlas/control.sqlite")
    parser.add_argument("--plan")
    parser.add_argument("--max-iterations", type=int, default=100)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    store = AtlasStore(root / args.db)
    if args.command == "init":
        if not args.plan:
            parser.error("--plan is required for init")
        payload = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        tasks = [AtlasTask(**{**row, "dependencies": tuple(row.get("dependencies", ())), "command": tuple(row["command"])}) for row in payload["tasks"]]
        print(store.register_plan(tasks))
        return 0
    if args.command in {"run", "resume"}:
        worker = AtlasWorker(store, worker_id="local-v6-worker", capabilities={"materializer", "trainer_cpu", "evaluator", "codex_worker", "reviewer"}, root=root)
        print(json.dumps(worker.run_until_terminal(max_iterations=args.max_iterations), indent=2))
        return 0
    print(json.dumps(store.status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
