#!/usr/bin/env python3
"""Resumable V5 research orchestrator with secret and path isolation.

Atlas is deliberately conservative: collection is a separate capability, the
compute worker never receives provider credentials, and release is possible
only after an explicit PASS artifact has been independently verified.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "outputs/timeseries_v5/atlas"
SECRET_PREFIXES = ("FRED_", "TSV5_", "AWS_", "GITHUB_TOKEN", "GH_TOKEN")
PROTECTED = ("data/timeseries_v1/", "data/timeseries_v2/", "data/timeseries_v3/", "data/timeseries_v4/", "data/scenarios/", "data/forecasts/", "data/ledgers/")
ALLOWED = ("data/timeseries_v5/", "data/contracts/multivariate_timeseries_v5.yaml", "src/ai_fc/timeseries_v5/", "src/tests/test_multivariate_timeseries_v5.py", "tools/atlas_timeseries.py", ".github/workflows/timeseries-v5-refresh.yml", "docs/timeseries_v5/", "outputs/timeseries_v5/", "migrations/timeseries_v5/", "pyproject.toml", ".gitignore", "src/ai_fc/cli.py", "src/ai_fc/dashboard.py", "src/ai_fc/read_model_contract.py", "docs/generated/")


def now() -> str: return datetime.now(timezone.utc).isoformat()


def _paths(run_id: str) -> tuple[Path, Path]: return STATE_ROOT / f"{run_id}.json", STATE_ROOT / f"{run_id}.events.jsonl"


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_suffix(path.suffix + ".tmp"); temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"); os.replace(temp, path)


def _event(run_id: str, event: str, detail: dict[str, Any]) -> None:
    _, ledger = _paths(run_id); ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as handle: handle.write(json.dumps({"at": now(), "event": event, "detail": detail}, ensure_ascii=False, sort_keys=True) + "\n")


def init(run_id: str) -> dict[str, Any]:
    path, _ = _paths(run_id)
    if path.is_file(): return json.loads(path.read_text(encoding="utf-8"))
    value = {"run_id": run_id, "status": "planned", "created_at": now(), "phase": 0, "steps": ["collect", "reconcile", "materialize", "mature-labels", "train", "backtest", "gate", "forecast", "resolve", "verify", "workbook"], "completed": [], "release_eligible": False}
    _atomic(path, value); _event(run_id, "initialized", {"steps": value["steps"]}); return value


def _git_paths() -> list[str]:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [line[3:].replace("\\", "/") for line in result.stdout.splitlines() if len(line) > 3]


def _allowlist() -> None:
    bad = [path for path in _git_paths() if path.startswith(PROTECTED) or not any(path == prefix or path.startswith(prefix) for prefix in ALLOWED)]
    if bad: raise RuntimeError(f"Atlas path/protection violation: {bad}")


def _compute_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not any(key == prefix or key.startswith(prefix) for prefix in SECRET_PREFIXES)}
    env["PYTHONPATH"] = str(ROOT / "src"); return env


def _command(step: str) -> list[str]:
    mapping = {
        "collect": ["timeseries-v5-collect"], "reconcile": ["timeseries-v5-reconcile"], "materialize": ["timeseries-v5-materialize"],
        "mature-labels": ["timeseries-v5-mature-labels"], "train": ["timeseries-v5-train"],
        "backtest": ["timeseries-v5-backtest"], "gate": ["timeseries-v5-gate"],
        "forecast": ["timeseries-v5-forecast"], "resolve": ["timeseries-v5-resolve"],
        "verify": ["timeseries-v5-verify"], "workbook": ["timeseries-v5-workbook"],
    }
    return [sys.executable, "-m", "ai_fc", *mapping[step]]


def worker(run_id: str, step: str) -> dict[str, Any]:
    state = init(run_id); _allowlist()
    if state["status"] in {"aborted", "paused", "released"}: raise RuntimeError(f"Atlas run is {state['status']}")
    env = os.environ.copy() if step == "collect" else _compute_env()
    result = subprocess.run(_command(step), cwd=ROOT, env=env, capture_output=True, text=True)
    detail = {"step": step, "returncode": result.returncode, "stdout_tail": result.stdout[-4000:], "stderr_tail": result.stderr[-4000:], "secret_capability": "collector_only" if step == "collect" else "none"}
    _event(run_id, "step_finished", detail)
    if result.returncode: state.update({"status": "hold", "blocking_step": step, "updated_at": now()}); _atomic(_paths(run_id)[0], state); return state
    if step not in state["completed"]: state["completed"].append(step)
    state["phase"] = len(state["completed"]); state["status"] = "running"; state["updated_at"] = now(); _allowlist(); _atomic(_paths(run_id)[0], state); return state


def run(run_id: str) -> dict[str, Any]:
    state = init(run_id); state["status"] = "running"; _atomic(_paths(run_id)[0], state)
    for step in state["steps"]:
        if step in state["completed"]: continue
        state = worker(run_id, step)
        if state["status"] == "hold": return state
    latest = ROOT / "data/timeseries_v5/multivariate_v5_latest.json"
    payload = json.loads(latest.read_text(encoding="utf-8")) if latest.is_file() else {}
    state["release_eligible"] = bool(payload.get("numbers_visible") and payload.get("research_gate", {}).get("pass") and payload.get("operational_gate", {}).get("pass"))
    state["status"] = "verified" if state["release_eligible"] else "hold"; state["updated_at"] = now(); _atomic(_paths(run_id)[0], state); _event(run_id, "run_finished", {"release_eligible": state["release_eligible"]}); return state


def release(run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    if not state.get("release_eligible"): raise RuntimeError("Atlas release requires both V5 Gates and verification")
    _allowlist(); paths = _git_paths()
    if not paths: return state
    subprocess.run(["git", "add", "--", *paths], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"feat(timeseries): publish V5 research Gate {run_id}"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=ROOT, check=True)
    subprocess.run(["gh", "pr", "create", "--fill"], cwd=ROOT, check=True)
    subprocess.run(["gh", "pr", "merge", "--auto", "--squash"], cwd=ROOT, check=True)
    state["status"] = "release_queued"; state["updated_at"] = now(); _atomic(_paths(run_id)[0], state); _event(run_id, "release_queued", {})
    return state


def command() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "plan", "run", "resume", "status", "pause", "abort", "reconcile", "report"):
        child = sub.add_parser(name); child.add_argument("--run-id", required=True)
        if name in {"run", "resume"}: child.add_argument("--auto-merge", action="store_true")
    work = sub.add_parser("worker"); work.add_argument("--run-id", required=True); work.add_argument("--step", required=True)
    args = parser.parse_args(); state = init(args.run_id)
    if args.command in {"run", "resume"}:
        state = run(args.run_id)
        if getattr(args, "auto_merge", False): state = release(args.run_id, state)
    elif args.command == "worker": state = worker(args.run_id, args.step)
    elif args.command in {"pause", "abort"}: state["status"] = "paused" if args.command == "pause" else "aborted"; state["updated_at"] = now(); _atomic(_paths(args.run_id)[0], state); _event(args.run_id, state["status"], {})
    elif args.command == "reconcile": _allowlist(); _event(args.run_id, "reconciled", {"paths": _git_paths()})
    elif args.command == "report":
        events = _paths(args.run_id)[1]; print(events.read_text(encoding="utf-8") if events.is_file() else "")
    print(json.dumps(state, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(command())
