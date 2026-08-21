#!/usr/bin/env python3
"""Local, isolated repair loop for the frozen NASDAQ time-series V2 contract.

The loop never tunes frozen model coordinates and never exposes collection or
GitHub credentials to the Codex subprocess.  It can auto-merge only after the
repository's full tests, V2 sealed/publication gate, protected manifest, and CI
all pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = REPOSITORY_ROOT / "outputs/timeseries_v2/ralph"
WORKTREE_ROOT = Path(tempfile.gettempdir()) / "ai-investing-ralph-worktrees"
ABORT_FILE = "ABORT"
STATE_FILE = "state.json"
REPORT_FILE = "REPORT.md"
SECRET_NAMES = {"FRED_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"}
ALLOWED_PREFIXES = (
    "data/contracts/multivariate_timeseries_v2.yaml",
    "src/ai_fc/timeseries_v2/",
    "src/tests/test_multivariate_timeseries_v2.py",
    "src/tests/test_ralph_timeseries.py",
    "tools/ralph_timeseries.py",
    ".github/workflows/timeseries-v2-refresh.yml",
    "src/ai_fc/cli.py",
    "src/ai_fc/dashboard.py",
    "src/ai_fc/read_model_contract.py",
    "src/ai_fc/dashboard_parts/dashboard.js",
    "src/ai_fc/dashboard_parts/dashboard.css",
    "data/timeseries_v2/",
    "outputs/timeseries_v2/",
    "README.md",
    "docs/generated/inventory.generated.md",
)


class RalphError(RuntimeError):
    """Ralph loop stopped at a safety or quality boundary."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], Path, dict[str, str]], CommandResult]


def _run(command: Sequence[str], cwd: Path, env: dict[str, str]) -> CommandResult:
    completed = subprocess.run(
        list(command), cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_state(run_id: str) -> tuple[Path, dict[str, Any]]:
    directory = STATE_ROOT / run_id
    path = directory / STATE_FILE
    if not path.is_file():
        raise RalphError(f"unknown Ralph run: {run_id}")
    return directory, json.loads(path.read_text(encoding="utf-8"))


def _contract_module(worktree: Path):
    sys.path.insert(0, str(worktree / "src"))
    try:
        from ai_fc.timeseries_v2.contracts import frozen_hash, load_contract_v2
        return load_contract_v2, frozen_hash
    finally:
        sys.path.pop(0)


def _frozen_hash(worktree: Path) -> str:
    load_contract_v2, frozen_hash = _contract_module(worktree)
    return frozen_hash(load_contract_v2(worktree))


def sanitized_agent_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if source is None else source)
    for name in list(env):
        upper = name.upper()
        if upper in SECRET_NAMES or upper.startswith("FRED_") or upper in {"GITHUB_TOKEN", "GH_TOKEN"}:
            env.pop(name, None)
    env["RALPH_SECRET_ISOLATION"] = "FRED_API_KEY,GH_TOKEN,GITHUB_TOKEN,.secrets"
    env["PYTHONUTF8"] = "1"
    return env


def path_allowed(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if normalized == ".secrets" or normalized.startswith(".secrets/"):
        return False
    return any(normalized == prefix or normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def changed_paths(worktree: Path, runner: Runner = _run) -> list[str]:
    result = runner(["git", "status", "--porcelain=v1"], worktree, dict(os.environ))
    if result.returncode:
        raise RalphError(result.stderr or result.stdout)
    output: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        output.append(path.replace("\\", "/"))
    return sorted(set(output))


def blocker_signature(text: str) -> str:
    normalized = re.sub(r"[0-9a-f]{7,64}", "<HASH>", text.lower())
    normalized = re.sub(r"\d+(?:\.\d+)?", "<N>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _protected_hash(worktree: Path) -> str:
    code = (
        "import json; from pathlib import Path; "
        "from ai_fc.scenario_v5.contracts import protected_hashes; "
        "print(protected_hashes(Path('.'))['manifest_sha256'])"
    )
    result = _run(
        [sys.executable, "-c", code], worktree,
        {**sanitized_agent_environment(), "PYTHONPATH": "src"},
    )
    if result.returncode:
        raise RalphError(f"protected manifest failed: {result.stderr}")
    return result.stdout.strip().splitlines()[-1]


def _diagnose(worktree: Path, *, runner: Runner = _run) -> CommandResult:
    env = {**sanitized_agent_environment(), "PYTHONPATH": "src", "PYTHONUTF8": "1"}
    return runner(
        [sys.executable, "-m", "pytest", "src/tests/test_multivariate_timeseries_v2.py",
         "src/tests/test_ralph_timeseries.py", "-q", "-p", "no:cacheprovider"],
        worktree, env,
    )


def _quick_gate(worktree: Path, *, runner: Runner = _run) -> CommandResult:
    env = {**sanitized_agent_environment(), "PYTHONPATH": "src", "PYTHONUTF8": "1"}
    return runner(
        [sys.executable, "-m", "ai_fc", "timeseries-v2-preflight"], worktree, env,
    )


def _codex_prompt(state: dict[str, Any], diagnosis: CommandResult) -> str:
    tail = (diagnosis.stdout + "\n" + diagnosis.stderr)[-12000:]
    return f"""You are repairing the preregistered NASDAQ time-series V2 system in an isolated worktree.

Frozen coordinate hash: {state['frozen_hash']}
Iteration: {state['iteration'] + 1}/{state['max_iterations']}

Rules:
- Do not change candidate inventory C1-C5, evaluation windows, gates, probability units, or model id.
- Edit only the allowlisted V2 paths described in data/contracts/multivariate_timeseries_v2.yaml.
- Never read or modify .secrets and never request credentials.
- Do not touch official ledgers, Scenario V5.2, or protected snapshots.
- Fix only data collection, PIT alignment, calculation, tests, or runtime defects.
- Do not run the sealed evaluation merely to tune against it.
- Use apply_patch for edits. Run targeted tests before finishing.

Current diagnostic output:
{tail}
"""


def _invoke_codex(
    worktree: Path, state: dict[str, Any], diagnosis: CommandResult,
    *, runner: Runner = _run,
) -> CommandResult:
    run_dir = STATE_ROOT / state["run_id"]
    output = run_dir / f"codex_iteration_{state['iteration'] + 1:03d}.txt"
    command = [
        "codex", "exec", "--sandbox", "workspace-write", "--json",
        "--output-last-message", str(output), "-C", str(worktree),
        _codex_prompt(state, diagnosis),
    ]
    return runner(command, worktree, sanitized_agent_environment())


def _commit_iteration(worktree: Path, iteration: int, paths: list[str], runner: Runner = _run) -> str:
    env = dict(os.environ)
    for path in paths:
        result = runner(["git", "add", "--", path], worktree, env)
        if result.returncode:
            raise RalphError(f"git add failed for {path}: {result.stderr}")
    commit = runner(
        ["git", "commit", "-m", f"fix(timeseries-v2): Ralph iteration {iteration}"],
        worktree, env,
    )
    if commit.returncode:
        raise RalphError(commit.stderr or commit.stdout)
    head = runner(["git", "rev-parse", "HEAD"], worktree, env)
    if head.returncode:
        raise RalphError(head.stderr)
    return head.stdout.strip()


def _full_release_gate(worktree: Path, state: dict[str, Any], runner: Runner = _run) -> tuple[bool, str]:
    env = {**sanitized_agent_environment(), "PYTHONPATH": "src", "PYTHONUTF8": "1"}
    tests = runner([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], worktree, env)
    if tests.returncode:
        return False, f"full tests failed\n{tests.stdout}\n{tests.stderr}"
    verify = runner(
        [sys.executable, "-m", "ai_fc", "timeseries-v2-verify"], worktree, env,
    )
    if verify.returncode:
        return False, f"V2 verify failed\n{verify.stdout}\n{verify.stderr}"
    try:
        payload = json.loads(verify.stdout[verify.stdout.find("{"):])
    except json.JSONDecodeError:
        return False, f"V2 verify output was not JSON\n{verify.stdout}"
    if payload.get("publication_gate_pass") is not True:
        return False, "sealed publication gate is not PASS"
    if _protected_hash(worktree) != state["protected_hash"]:
        return False, "protected manifest changed"
    return True, "all local release gates passed"


def _sealed_evaluation_failed(worktree: Path, frozen_contract_hash: str) -> bool:
    path = worktree / "data/timeseries_v2/ledgers/sealed_evaluations.jsonl"
    if not path.is_file():
        return False
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    matches = [row for row in rows if row.get("contract_hash") == frozen_contract_hash]
    return bool(matches and matches[-1].get("summary", {}).get("gate_pass") is False)


def _external_publication_hold(worktree: Path, frozen_contract_hash: str) -> list[str]:
    sealed_path = worktree / "data/timeseries_v2/ledgers/sealed_evaluations.jsonl"
    latest_path = worktree / "data/timeseries_v2/multivariate_v2_latest.json"
    if not sealed_path.is_file() or not latest_path.is_file():
        return []
    sealed_rows = [
        json.loads(line) for line in sealed_path.read_text(encoding="utf-8").splitlines() if line
    ]
    passed = any(
        row.get("contract_hash") == frozen_contract_hash
        and row.get("summary", {}).get("gate_pass") is True
        for row in sealed_rows
    )
    if not passed:
        return []
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    if latest.get("publication", {}).get("customer_numbers_visible") is True:
        return []
    return [str(reason) for reason in latest.get("gate", {}).get("reasons", [])]


def _runtime_publication_hold(worktree: Path) -> list[str]:
    """Treat missing preregistered DFM runtime receipts as an environment HOLD.

    Ralph may repair code and alignment defects, but it must not rewrite the
    contract or model implementation merely because the isolated worktree is
    running with the wrong numerical package build.
    """
    path = worktree / "data/timeseries_v2/ledgers/dfm_cache_manifest.jsonl"
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not rows:
        return []
    superseded = {
        str(row["supersedes"]) for row in rows if row.get("supersedes") is not None
    }
    entries = [
        row for row in rows
        if str(row.get("manifest_id") or row["cache_id"]) not in superseded
    ]
    missing = 0
    mismatched = 0
    for entry in entries:
        runtime = entry.get("runtime")
        if not isinstance(runtime, dict):
            missing += 1
            continue
        if runtime.get("statsmodels") != "0.14.6":
            mismatched += 1
    if missing or mismatched:
        return [
            "preregistered DFM runtime receipts are incomplete or incompatible "
            f"(missing={missing}, mismatched={mismatched}, required statsmodels=0.14.6)"
        ]
    return []


def _publish(worktree: Path, state: dict[str, Any], runner: Runner = _run) -> dict[str, Any]:
    env = dict(os.environ)
    branch = state["branch"]
    push = runner(["git", "push", "-u", "origin", branch], worktree, env)
    if push.returncode:
        raise RalphError(push.stderr or push.stdout)
    title = f"feat: NASDAQ multivariate time-series V2 ({state['run_id']})"
    body_path = STATE_ROOT / state["run_id"] / "PR_BODY.md"
    body_path.write_text(
        "NASDAQ multivariate time-series V2 and isolated Ralph repair evidence.\n\n"
        f"- Ralph run: `{state['run_id']}`\n"
        f"- Frozen hash: `{state['frozen_hash']}`\n"
        "- Official/Scenario probability spaces unchanged.\n"
        "- Auto-merge requested only after all local and repository CI gates pass.\n",
        encoding="utf-8",
    )
    create = runner(
        ["gh", "pr", "create", "--title", title, "--body-file", str(body_path), "--base", "main", "--head", branch],
        worktree, env,
    )
    if create.returncode:
        raise RalphError(create.stderr or create.stdout)
    url = create.stdout.strip().splitlines()[-1]
    number = url.rstrip("/").split("/")[-1]
    checks = runner(["gh", "pr", "checks", number, "--watch", "--fail-fast"], worktree, env)
    if checks.returncode:
        raise RalphError(checks.stderr or checks.stdout)
    merge = runner(["gh", "pr", "merge", number, "--squash", "--delete-branch"], worktree, env)
    if merge.returncode:
        raise RalphError(merge.stderr or merge.stdout)
    view = runner(["gh", "pr", "view", number, "--json", "mergeCommit"], worktree, env)
    if view.returncode:
        raise RalphError(view.stderr or view.stdout)
    merge_sha = json.loads(view.stdout)["mergeCommit"]["oid"]
    runs: list[dict[str, Any]] = []
    for _ in range(20):
        pages = runner(
            ["gh", "run", "list", "--workflow", "pages.yml", "--branch", "main", "--limit", "5",
             "--json", "databaseId,status,conclusion,headSha"],
            worktree, env,
        )
        if pages.returncode:
            raise RalphError(f"Pages run lookup failed after merge: {pages.stderr or pages.stdout}")
        runs = [row for row in json.loads(pages.stdout or "[]") if row.get("headSha") == merge_sha]
        if runs:
            break
        time.sleep(15)
    if not runs:
        raise RalphError(f"Pages deployment did not start for merge {merge_sha}")
    pages_id = str(runs[0]["databaseId"])
    watch = runner(["gh", "run", "watch", pages_id, "--exit-status"], worktree, env)
    if watch.returncode:
        raise RalphError(watch.stderr or watch.stdout)
    live_url = "https://sung-jinpark.github.io/Jin-s-investing-prediction/data.json"
    live_ok = False
    live_error = ""
    for _ in range(20):
        try:
            request = urllib.request.Request(live_url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
            if b"shadow.mf_dfm_ridge_varx_v2" in body:
                live_ok = True
                break
            live_error = "V2 model id absent from live data.json"
        except OSError as exc:
            live_error = str(exc)
        time.sleep(15)
    if not live_ok:
        raise RalphError(f"live DOM payload verification failed: {live_error}")
    return {
        "pr_url": url, "pr_number": int(number), "merged": True,
        "pages_run_id": int(pages_id), "live_url": live_url, "live_verified": True,
    }


def _report(directory: Path, state: dict[str, Any]) -> Path:
    rows = [
        "# NASDAQ time-series V2 Ralph run",
        "",
        f"- Run: `{state['run_id']}`",
        f"- Status: **{state['status']}**",
        f"- Iterations: {state['iteration']} / {state['max_iterations']}",
        f"- Started: {state['started_at']}",
        f"- Updated: {state['updated_at']}",
        f"- Frozen contract hash: `{state['frozen_hash']}`",
        f"- Protected manifest: `{state['protected_hash']}`",
        f"- Stop reason: {state.get('stop_reason') or '—'}",
        "",
        "## Iterations",
        "",
        "| # | result | commit | blocker |",
        "|---:|---|---|---|",
    ]
    for row in state.get("iterations", []):
        rows.append(
            f"| {row['iteration']} | {row['result']} | `{row.get('commit') or '—'}` | "
            f"`{row.get('blocker_signature') or '—'}` |"
        )
    path = directory / REPORT_FILE
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + os.urandom(3).hex()


def create_run(
    *, max_iterations: int, max_hours: float, auto_merge: bool,
    base_ref: str = "HEAD", runner: Runner = _run,
) -> dict[str, Any]:
    if not 1 <= max_iterations <= 50:
        raise RalphError("max-iterations must be between 1 and 50")
    if not 0 < max_hours <= 24:
        raise RalphError("max-hours must be between 0 and 24")
    run_id = _new_run_id()
    directory = STATE_ROOT / run_id
    worktree = WORKTREE_ROOT / run_id
    branch = f"codex/timeseries-ralph-{run_id.lower()}"
    directory.mkdir(parents=True, exist_ok=False)
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    result = runner(
        ["git", "worktree", "add", "-b", branch, str(worktree), base_ref],
        REPOSITORY_ROOT, dict(os.environ),
    )
    if result.returncode:
        raise RalphError(result.stderr or result.stdout)
    state = {
        "schema_version": 1, "run_id": run_id, "branch": branch,
        "base_ref": base_ref,
        "worktree": str(worktree), "status": "running", "iteration": 0,
        "max_iterations": max_iterations, "max_hours": max_hours, "auto_merge": auto_merge,
        "started_at": _now(), "updated_at": _now(), "deadline_epoch": time.time() + max_hours * 3600,
        "frozen_hash": _frozen_hash(worktree), "protected_hash": _protected_hash(worktree),
        "iterations": [], "blocker_counts": {}, "stop_reason": None,
    }
    _atomic_json(directory / STATE_FILE, state)
    return state


def execute_run(
    state: dict[str, Any], *, runner: Runner = _run,
    codex_executor: Callable[[Path, dict[str, Any], CommandResult], CommandResult] | None = None,
) -> dict[str, Any]:
    directory = STATE_ROOT / state["run_id"]
    worktree = Path(state["worktree"])
    codex_executor = codex_executor or (lambda path, active, diag: _invoke_codex(path, active, diag, runner=runner))
    while state["status"] == "running":
        if (directory / ABORT_FILE).exists():
            state["status"] = "aborted"
            state["stop_reason"] = "abort requested"
            break
        if state["iteration"] >= state["max_iterations"] or time.time() >= state["deadline_epoch"]:
            state["status"] = "hold"
            state["stop_reason"] = "iteration or wall-clock budget reached"
            break
        if _frozen_hash(worktree) != state["frozen_hash"]:
            state["status"] = "blocked"
            state["stop_reason"] = "frozen candidate/evaluation/gate coordinates changed"
            break
        diagnosis = _diagnose(worktree, runner=runner)
        if diagnosis.returncode == 0:
            release_ok, release_reason = _full_release_gate(worktree, state, runner=runner)
            if release_ok:
                state["status"] = "passed"
                state["stop_reason"] = release_reason
                if state["auto_merge"]:
                    state["publication"] = _publish(worktree, state, runner=runner)
                    state["status"] = "merged"
                break
            if _sealed_evaluation_failed(worktree, state["frozen_hash"]):
                state["status"] = "hold"
                state["stop_reason"] = "sealed evaluation failed; a new preregistered model version is required"
                break
            runtime_hold = _runtime_publication_hold(worktree)
            if runtime_hold:
                state["status"] = "hold"
                state["stop_reason"] = (
                    "external numerical runtime HOLD; code was not modified: "
                    + "; ".join(runtime_hold)
                )
                break
            external_hold = _external_publication_hold(worktree, state["frozen_hash"])
            if external_hold:
                state["status"] = "hold"
                state["stop_reason"] = (
                    "external data or operational publication gate HOLD; code was not modified: "
                    + "; ".join(external_hold)
                )
                break
        state["iteration"] += 1
        invocation = codex_executor(worktree, state, diagnosis)
        paths = changed_paths(worktree, runner=runner)
        forbidden = [path for path in paths if not path_allowed(path)]
        result_row: dict[str, Any] = {"iteration": state["iteration"], "paths": paths, "commit": None}
        if forbidden:
            runner(["git", "reset", "--hard", "HEAD"], worktree, dict(os.environ))
            runner(["git", "clean", "-fd", "--", *forbidden], worktree, dict(os.environ))
            state["status"] = "blocked"
            state["stop_reason"] = f"forbidden path mutation: {forbidden}"
            result_row["result"] = "discarded_protected_scope"
            state["iterations"].append(result_row)
            break
        if _frozen_hash(worktree) != state["frozen_hash"] or _protected_hash(worktree) != state["protected_hash"]:
            runner(["git", "reset", "--hard", "HEAD"], worktree, dict(os.environ))
            state["status"] = "blocked"
            state["stop_reason"] = "frozen/protected hash mutation attempt"
            result_row["result"] = "discarded_hash_violation"
            state["iterations"].append(result_row)
            break
        tests = _diagnose(worktree, runner=runner)
        quick = _quick_gate(worktree, runner=runner) if tests.returncode == 0 else tests
        failure_text = "\n".join((invocation.stdout, invocation.stderr, tests.stdout, tests.stderr, quick.stdout, quick.stderr))
        signature = blocker_signature(failure_text)
        result_row["blocker_signature"] = signature
        if invocation.returncode == 0 and tests.returncode == 0 and paths:
            result_row["commit"] = _commit_iteration(worktree, state["iteration"], paths, runner=runner)
            result_row["result"] = "committed"
        else:
            result_row["result"] = "no_progress" if not paths else "tests_failed"
        state["blocker_counts"][signature] = int(state["blocker_counts"].get(signature, 0)) + 1
        state["iterations"].append(result_row)
        if state["blocker_counts"][signature] >= 3:
            state["status"] = "hold"
            state["stop_reason"] = f"same blocker repeated 3 times: {signature}"
        state["updated_at"] = _now()
        _atomic_json(directory / STATE_FILE, state)
    state["updated_at"] = _now()
    _atomic_json(directory / STATE_FILE, state)
    _report(directory, state)
    return state


def command_run(args: argparse.Namespace) -> int:
    state = create_run(
        max_iterations=args.max_iterations, max_hours=args.max_hours,
        auto_merge=args.auto_merge, base_ref=args.base_ref,
    )
    completed = execute_run(state)
    print(json.dumps(completed, ensure_ascii=False, indent=2))
    return 0 if completed["status"] in {"passed", "merged"} else 2


def command_resume(args: argparse.Namespace) -> int:
    _, state = _load_state(args.run_id)
    if state["status"] not in {"running", "hold"}:
        raise RalphError(f"run cannot resume from {state['status']}")
    state["status"] = "running"
    state["deadline_epoch"] = time.time() + min(float(args.max_hours), 24.0) * 3600
    completed = execute_run(state)
    print(json.dumps(completed, ensure_ascii=False, indent=2))
    return 0 if completed["status"] in {"passed", "merged"} else 2


def command_status(args: argparse.Namespace) -> int:
    _, state = _load_state(args.run_id)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def command_abort(args: argparse.Namespace) -> int:
    directory, state = _load_state(args.run_id)
    (directory / ABORT_FILE).write_text(f"requested_at={_now()}\n", encoding="utf-8")
    print(f"abort requested for {state['run_id']}")
    return 0


def command_report(args: argparse.Namespace) -> int:
    directory, state = _load_state(args.run_id)
    print(_report(directory, state))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--max-iterations", type=int, default=50)
    run.add_argument("--max-hours", type=float, default=24)
    run.add_argument("--auto-merge", action="store_true")
    run.add_argument("--base-ref", default="HEAD")
    run.set_defaults(func=command_run)
    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    resume.add_argument("--max-hours", type=float, default=24)
    resume.set_defaults(func=command_resume)
    for name, function in (("status", command_status), ("abort", command_abort), ("report", command_report)):
        item = commands.add_parser(name)
        item.add_argument("run_id")
        item.set_defaults(func=function)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RalphError as exc:
        print(f"ralph-timeseries: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
