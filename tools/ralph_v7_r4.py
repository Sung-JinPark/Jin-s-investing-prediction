#!/usr/bin/env python3
"""NASDAQ V7 R4 PostgreSQL research supervisor CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_fc.timeseries_v7_r4.control_plane import PostgresControlPlane  # noqa: E402
from ai_fc.timeseries_v7_r4.integrity import canonical_json, sha256_file  # noqa: E402
from ai_fc.timeseries_v7_r4.specs import (read_json, read_yaml, verify_delivery_spec,
                                          verify_pack)  # noqa: E402
from ai_fc.timeseries_v7_r4.supervisor import Supervisor, SupervisorContext  # noqa: E402

SPEC_ROOT = ROOT / "data/timeseries_v7_r4/ralph/spec"
MIGRATION_ROOT = ROOT / "migrations/timeseries_v7_r4"
OUTPUT = ROOT / "outputs/timeseries_v7_r4"


def resolve(value: str, *, extra: list[Path] | None = None) -> Path:
    path = Path(value)
    candidates = [path, ROOT / path, SPEC_ROOT / path.name]
    candidates.extend((folder / path.name) for folder in (extra or []))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(value)


def database_url() -> str:
    value = os.getenv("RALPH_V7_R4_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("PostgreSQL required: set RALPH_V7_R4_DATABASE_URL or DATABASE_URL")
    return value


def run_id_now() -> str:
    return "v7r4-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_run_metadata(run_id: str) -> dict:
    path = OUTPUT / "runs" / run_id / "bootstrap.json"
    return json.loads(path.read_text(encoding="utf-8"))


def command_bootstrap(args: argparse.Namespace) -> int:
    config_path = resolve(args.config)
    backlog_path = resolve(args.backlog)
    review_pack = resolve(args.review_pack, extra=[ROOT / "outputs/review-packs"])
    config = read_yaml(config_path)
    backlog = read_json(backlog_path)
    delivery = verify_delivery_spec(SPEC_ROOT)
    if not delivery["file_hashes_pass"] or not delivery["backlog_internal_pass"]:
        raise ValueError("R4 delivery specification integrity failed")
    expected = config["inputs"]["latest_review_pack"]["sha256"]
    review = verify_pack(review_pack, expected)
    if int(backlog.get("task_count", -1)) != len(backlog.get("tasks", [])):
        raise ValueError("backlog task_count mismatch")
    control = PostgresControlPlane(database_url())
    for migration in sorted(MIGRATION_ROOT.glob("*.sql")):
        control.migrate(migration)
    run_id = args.run_id or run_id_now()
    control.create_run(run_id=run_id, config_hash=sha256_file(config_path),
                       backlog_hash=sha256_file(backlog_path), review_pack_hash=review["sha256"])
    inserted = control.import_tasks(run_id, backlog["tasks"])
    metadata = {
        "schema_version": 1, "run_id": run_id,
        "config_path": str(config_path), "config_sha256": sha256_file(config_path),
        "backlog_path": str(backlog_path), "backlog_sha256": sha256_file(backlog_path),
        "review_pack": review, "tasks_declared": len(backlog["tasks"]),
        "tasks_inserted": inserted, "database": "postgresql:timeseries_v7_r4",
        "delivery_spec": delivery,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    folder = OUTPUT / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bootstrap.json").write_bytes(canonical_json(metadata) + b"\n")
    control.event(run_id, "RUN_BOOTSTRAPPED", metadata)
    print(run_id)
    return 0


def make_supervisor(run_id: str, args: argparse.Namespace) -> Supervisor:
    metadata = load_run_metadata(run_id)
    config = read_yaml(Path(metadata["config_path"]))
    r3_pack = Path(os.getenv("R4_R3_DESIGN_PACK", r"C:\Users\91ssj\Downloads\NASDAQ_V7_FRED_ALFRED_OPEN_DATA_RALPH_R3_PACK_20260825.zip"))
    predecessor = Path(os.getenv("R4_PREDECESSOR_REPO", str(ROOT / "worktrees/active/timeseries-v5-gate")))
    context = SupervisorContext(
        repo=ROOT, output_root=OUTPUT,
        review_pack=Path(metadata["review_pack"]["path"]),
        r3_design_pack=r3_pack if r3_pack.exists() else None,
        predecessor_repo=predecessor if predecessor.exists() else None,
        config=config, auto_codex=bool(getattr(args, "auto_codex", False)),
    )
    return Supervisor(PostgresControlPlane(database_url()), context)


def command_run(args: argparse.Namespace) -> int:
    supervisor = make_supervisor(args.run_id, args)
    for migration in sorted(MIGRATION_ROOT.glob("*.sql")):
        supervisor.control.migrate(migration)
    supervisor.control.reconcile_dependencies(args.run_id)
    supervisor.control.correct_execution_permission_waits(args.run_id)
    if os.getenv("R4_ALLOW_CODEX_CHILD") == "1":
        supervisor.control.wake_execution_permission(args.run_id)
    until = {item.strip() for item in args.until.split(",") if item.strip()}
    return supervisor.run(args.run_id, until=until, max_tasks=args.max_tasks)


def command_status(args: argparse.Namespace) -> int:
    control = PostgresControlPlane(database_url())
    print(json.dumps(control.status(args.run_id), ensure_ascii=False, indent=2, default=str))
    return 0


def command_report(args: argparse.Namespace) -> int:
    control = PostgresControlPlane(database_url())
    payload = {"status": control.status(args.run_id), "events": control.list_events(args.run_id)}
    path = OUTPUT / "runs" / args.run_id / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(payload) + b"\n")
    print(path)
    return 0


def command_state(args: argparse.Namespace, state: str) -> int:
    control = PostgresControlPlane(database_url())
    control.set_run_state(args.run_id, state, {"operator_command": state.lower()})
    print(state)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap")
    boot.add_argument("--review-pack", required=True)
    boot.add_argument("--config", required=True)
    boot.add_argument("--backlog", required=True)
    boot.add_argument("--run-id")
    boot.set_defaults(func=command_bootstrap)
    run = sub.add_parser("run")
    run.add_argument("--run-id", required=True)
    run.add_argument("--auto-codex", action="store_true")
    run.add_argument("--continuous", action="store_true")
    run.add_argument("--until", default="REVIEW_PROPOSAL,WAIT_DATA,HARD_BLOCK")
    run.add_argument("--max-tasks", type=int)
    run.set_defaults(func=command_run)
    resume = sub.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--auto-codex", action="store_true")
    resume.add_argument("--continuous", action="store_true")
    resume.add_argument("--until", default="REVIEW_PROPOSAL,WAIT_DATA,HARD_BLOCK")
    resume.add_argument("--max-tasks", type=int)
    resume.set_defaults(func=command_run)
    for name in ("status", "report"):
        item = sub.add_parser(name); item.add_argument("--run-id", required=True)
        item.set_defaults(func=command_status if name == "status" else command_report)
    for name, state in (("pause", "PAUSED"), ("abort", "ABORTED")):
        item = sub.add_parser(name); item.add_argument("--run-id", required=True)
        item.set_defaults(func=lambda args, value=state: command_state(args, value))
    return result


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
