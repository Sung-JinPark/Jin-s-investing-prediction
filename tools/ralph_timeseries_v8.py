"""V8 development-loop harness: state, budgets, guards, and stop discipline.

Unlike the V2 Ralph controller this harness does not drive a code-repair
agent.  The executor (a Claude session or a human) implements and launches
each preregistered experiment through ``python -m ai_fc
timeseries-v8-dev-backtest``; the harness owns run state, the experiment
queue, frozen/protected hash guards, blocker counting, and the stop rules.
The hard limits themselves (grid membership, evaluation budget, append-only
ledgers, 2019-blindness) are enforced inside ``ai_fc.timeseries_v8`` and do
not depend on this file.

The sealed 2019+ disclosure is out of scope by design: this harness has no
verb for it, and the V8 contract prohibits ``automatic_sealed_disclosure``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_fc.scenario_v5.contracts import protected_hashes  # noqa: E402
from ai_fc.timeseries_v8.artifact import read_experiments  # noqa: E402
from ai_fc.timeseries_v8.contracts import canonical_hash, frozen_hash, load_contract_v8  # noqa: E402
from ai_fc.timeseries_v8.pipeline import verify_timeseries_v8  # noqa: E402


STATE_ROOT = REPO_ROOT / "outputs/timeseries_v8/ralph"

# Preregistered opening queue (contract: development_protocol.preregistered_
# first_experiments).  E0 anchors the paired comparisons; the Cramér audit
# (E3) is collected by every run, so it needs no evaluation of its own.
OPENING_QUEUE = [
    {"label": "E0_neutral_v2_identity", "config": {}},
    {"label": "E1_B1_phi_0.97", "config": {"phi": 0.97}},
    {"label": "E1_B1_phi_fitted_ar1", "config": {"phi": "fitted_ar1"}},
    {
        "label": "E2_B1_plus_B2",
        "config": {
            "phi": 0.97,
            "omega_by_horizon": {21: 0.5, 63: 0.75},
            "sigma_cap": 0.25,
        },
    },
]


class RalphV8Error(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _state_path(run_id: str) -> Path:
    return STATE_ROOT / run_id / "state.json"


def _load_state(run_id: str) -> dict:
    path = _state_path(run_id)
    if not path.is_file():
        raise RalphV8Error(f"unknown run: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    path = _state_path(state["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _guards(state: dict) -> list[str]:
    problems: list[str] = []
    contract = load_contract_v8(REPO_ROOT)
    if frozen_hash(contract) != state["frozen_hash"]:
        problems.append("frozen contract hash drifted mid-run")
    observed_protected = canonical_hash(protected_hashes(REPO_ROOT))
    if observed_protected != state["protected_hash"]:
        problems.append("protected manifest changed mid-run")
    if (STATE_ROOT / state["run_id"] / "ABORT").exists():
        problems.append("abort file present")
    if time.time() > float(state["deadline_epoch"]):
        problems.append("wall-clock budget exhausted")
    return problems


def cmd_init(args: argparse.Namespace) -> None:
    contract = load_contract_v8(REPO_ROOT)
    verify = verify_timeseries_v8(REPO_ROOT)
    if not verify["ok"]:
        raise RalphV8Error(f"verify failed before init: {verify['errors']}")
    run_id = f"tsv8-ralph-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": _now(),
        "status": "running",
        "frozen_hash": frozen_hash(contract),
        "protected_hash": canonical_hash(protected_hashes(REPO_ROOT)),
        "deadline_epoch": time.time() + float(args.max_hours) * 3600.0,
        "max_iterations": int(args.max_iterations),
        "iteration": 0,
        "queue": OPENING_QUEUE,
        "history": [],
        "blockers": {},
        "stop_reason": None,
    }
    _save_state(state)
    print(json.dumps({"run_id": run_id, "queued": [item["label"] for item in OPENING_QUEUE]}, ensure_ascii=False))


def cmd_next(args: argparse.Namespace) -> None:
    state = _load_state(args.run_id)
    if state["status"] != "running":
        raise RalphV8Error(f"run is {state['status']}: {state.get('stop_reason')}")
    problems = _guards(state)
    if problems:
        state["status"] = "blocked"
        state["stop_reason"] = "; ".join(problems)
        _save_state(state)
        raise RalphV8Error(state["stop_reason"])
    if state["iteration"] >= state["max_iterations"]:
        state["status"] = "hold"
        state["stop_reason"] = "iteration budget exhausted"
        _save_state(state)
        raise RalphV8Error(state["stop_reason"])
    if not state["queue"]:
        print(json.dumps({"next": None, "note": "queue empty; extend with add-experiment"}, ensure_ascii=False))
        return
    item = state["queue"][0]
    print(json.dumps({
        "next": item,
        "command": (
            "python -m ai_fc timeseries-v8-dev-backtest "
            f"--label {item['label']} --config '{json.dumps(item['config'])}'"
        ),
    }, ensure_ascii=False, indent=2))


def cmd_add_experiment(args: argparse.Namespace) -> None:
    state = _load_state(args.run_id)
    if state["status"] != "running":
        raise RalphV8Error(f"run is {state['status']}")
    item = {"label": args.label, "config": json.loads(args.config)}
    state["queue"].append(item)
    _save_state(state)
    print(json.dumps({"queued": item}, ensure_ascii=False))


def cmd_record(args: argparse.Namespace) -> None:
    state = _load_state(args.run_id)
    if state["status"] != "running":
        raise RalphV8Error(f"run is {state['status']}")
    problems = _guards(state)
    if problems:
        state["status"] = "blocked"
        state["stop_reason"] = "; ".join(problems)
        _save_state(state)
        raise RalphV8Error(state["stop_reason"])
    verify = verify_timeseries_v8(REPO_ROOT)
    if not verify["ok"]:
        signature = canonical_hash(verify["errors"])[:16]
        state["blockers"][signature] = int(state["blockers"].get(signature, 0)) + 1
        if state["blockers"][signature] >= 3:
            state["status"] = "hold"
            state["stop_reason"] = f"same blocker three times: {verify['errors']}"
        _save_state(state)
        raise RalphV8Error(f"verify failed: {verify['errors']}")
    experiments = {row["experiment_id"]: row for row in read_experiments(REPO_ROOT)}
    if args.experiment_id not in experiments:
        raise RalphV8Error("experiment id is not in the append-only ledger")
    row = experiments[args.experiment_id]
    state["iteration"] += 1
    state["queue"] = [item for item in state["queue"] if item["label"] != row["experiment_label"]]
    state["history"].append({
        "iteration": state["iteration"],
        "recorded_at": _now(),
        "experiment_id": args.experiment_id,
        "label": row["experiment_label"],
        "paired_mean": row["paired_long_horizon"]["mean"],
        "paired_ci90_upper": row["paired_long_horizon"]["ci90"]["upper"],
        "proxy_pass": row["proxy"]["pass"],
    })
    if row["proxy"]["pass"]:
        state["status"] = "proxy_green"
        state["stop_reason"] = (
            "design proxy green; holdout scoring and contract freeze require "
            "explicit user decisions"
        )
    _save_state(state)
    print(json.dumps(state["history"][-1], ensure_ascii=False, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    state = _load_state(args.run_id)
    print(json.dumps({
        key: state[key]
        for key in ("run_id", "status", "iteration", "max_iterations", "stop_reason", "history")
    }, ensure_ascii=False, indent=2))
    print(json.dumps({"queued": [item["label"] for item in state["queue"]]}, ensure_ascii=False))


def cmd_abort(args: argparse.Namespace) -> None:
    state = _load_state(args.run_id)
    (STATE_ROOT / state["run_id"] / "ABORT").write_text(_now() + "\n", encoding="utf-8")
    state["status"] = "aborted"
    state["stop_reason"] = "user abort"
    _save_state(state)
    print(json.dumps({"run_id": state["run_id"], "status": "aborted"}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="V8 development loop harness")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--max-iterations", type=int, default=24)
    init.add_argument("--max-hours", type=float, default=24.0)
    init.set_defaults(func=cmd_init)
    for name, func, extra in (
        ("next", cmd_next, ()),
        ("status", cmd_status, ()),
        ("abort", cmd_abort, ()),
    ):
        sub = commands.add_parser(name)
        sub.add_argument("run_id")
        sub.set_defaults(func=func)
    record = commands.add_parser("record")
    record.add_argument("run_id")
    record.add_argument("--experiment-id", required=True, dest="experiment_id")
    record.set_defaults(func=cmd_record)
    add = commands.add_parser("add-experiment")
    add.add_argument("run_id")
    add.add_argument("--label", required=True)
    add.add_argument("--config", required=True)
    add.set_defaults(func=cmd_add_experiment)
    args = parser.parse_args()
    try:
        args.func(args)
    except RalphV8Error as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
