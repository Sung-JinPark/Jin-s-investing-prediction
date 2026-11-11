"""Publish the daily6m v2 shadow store only; replay from current main after a race.

Allowed: the v2 forecast/resolution/verdict ledgers (append-only prefix check),
new immutable run files, and the derived scorecard (overwritten).  approvals.jsonl
and prereg/ are outside the allow-list (human commits only).  v1 files are never
touched.  A rejected attempt stays in its checkout; the next attempt replays the
pending check and the v2 commands in a fresh checkout.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

STORE = "data/timeseries_daily6m_v2/"
LEDGERS = {STORE + "ledgers/forecasts.jsonl", STORE + "ledgers/resolutions.jsonl", STORE + "ledgers/verdicts.jsonl"}
MUTABLE = {STORE + "derived/scorecard.json"}


class PublicationError(RuntimeError):
    pass


def git(root, *args, check=True):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if check and result.returncode:
        # Do not echo remote URLs, which may carry credentials.
        raise PublicationError("git operation failed: " + args[0])
    return result


def allowed(path):
    return path in LEDGERS or path in MUTABLE or (
        path.startswith(STORE + "runs/") and path.endswith(".json")
        and len(Path(path).parts) == 4
    )


def commit_changes(root):
    """Reject out-of-scope edits, history rewrites and immutable run changes."""
    staged = git(root, "diff", "--cached", "--name-only", "-z").stdout
    tracked = git(root, "diff", "--name-only", "-z", "HEAD").stdout
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z", STORE).stdout
    paths = sorted({p.decode() for p in (staged + tracked + untracked).split(b"\0") if p})
    if any(not allowed(p) for p in paths):
        raise PublicationError("unexpected v2 shadow publication path")
    for path in paths:
        target = root / path
        if not target.is_file() or target.is_symlink():
            raise PublicationError("v2 shadow publication cannot delete or redirect history")
        old = git(root, "show", "HEAD:" + path, check=False)
        if old.returncode == 0:
            if path in LEDGERS and not target.read_bytes().startswith(old.stdout):
                raise PublicationError("v2 shadow ledger is not an append")
            if path.startswith(STORE + "runs/") and target.read_bytes() != old.stdout:
                raise PublicationError("immutable v2 shadow run changed")
    if not paths:
        return False
    git(root, "add", "--", *paths)
    if git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    git(root, "-c", "user.name=github-actions[bot]", "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", "data: append daily6m v2 shadow forecasts and paired outcomes")
    return True


def replay(root, report_dir):
    """Re-run the pending check and the v2 commands on this exact fresh main (no source fetch)."""
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}
    pending = report_dir / "pending.json"
    subprocess.run([sys.executable, "tools/check_daily6m_v2_pending.py", "--root", str(root), "--report", str(pending)],
                   cwd=root, env=env, check=True)
    state = json.loads(pending.read_text(encoding="utf-8"))
    if state.get("work") is not True:
        return False
    commands = []
    if state.get("forecast") is True:
        commands.append("daily6m-v2-forecast")
    commands += ["daily6m-v2-resolve", "daily6m-v2-scorecard", "daily6m-v2-verify"]
    for command in commands:
        subprocess.run([sys.executable, "-m", "ai_fc", *command.split()], cwd=root, env=env, check=True)
    return True


def publish(root, *, report, parent, replay_fn=replay, before_push=None, sleep=time.sleep):
    root, report, parent = root.resolve(), report.resolve(), parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "committed": False, "attempts": [], "status": "failed"}
    current = root
    try:
        for attempt in range(1, 4):
            base = git(current, "rev-parse", "HEAD").stdout.decode().strip()
            if git(current, "merge-base", "--is-ancestor", base, "origin/main", check=False).returncode:
                raise PublicationError("publication checkout must start from main history")
            entry = {"attempt": attempt, "base": base}
            result["attempts"].append(entry)
            if attempt > 1:
                attempt_dir = report.parent / f"attempt-{attempt}"
                attempt_dir.mkdir(exist_ok=True)
                if not replay_fn(current, attempt_dir):
                    entry["status"] = "nothing_pending"
                    result["status"] = "nothing_pending"
                    break
            changed = commit_changes(current)
            if not changed:
                entry["status"] = "unchanged"
                result["status"] = "unchanged"
                break
            entry["commit"] = git(current, "rev-parse", "HEAD").stdout.decode().strip()
            if before_push:
                before_push(attempt, current)
            pushed = git(current, "push", "origin", "HEAD:main", check=False)
            if pushed.returncode == 0:
                entry["status"] = "published"
                result.update(committed=True, status="published", commit=entry["commit"])
                break
            git(current, "fetch", "--no-tags", "origin", "main")
            tip = git(current, "rev-parse", "origin/main").stdout.decode().strip()
            if git(current, "merge-base", "--is-ancestor", entry["commit"], tip, check=False).returncode == 0:
                entry["status"] = "published_confirmed_by_fetch"
                result.update(committed=True, status="published", commit=entry["commit"])
                break
            # A non-race (permissions/network/protection) must not trigger model retries.
            if tip == base:
                raise PublicationError("push failed without a newer main")
            if git(current, "merge-base", "--is-ancestor", base, "origin/main", check=False).returncode:
                raise PublicationError("main history no longer descends from attempt base")
            entry.update(status="race", remote_tip=tip)
            if attempt == 3:
                raise PublicationError("v2 shadow push failed after three fresh-main attempts")
            sleep(15)
            current = parent / ("daily6m-v2-publish-" + uuid.uuid4().hex)
            # Owned disposable CI checkout. Failed attempts are retained for diagnosis.
            git(root, "worktree", "add", "--detach", str(current), tip)
        return result
    except (PublicationError, subprocess.CalledProcessError) as exc:
        result["error"] = str(exc) if isinstance(exc, PublicationError) else "fresh-main replay command failed"
        raise
    finally:
        temporary = report.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        temporary.replace(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    configured = os.environ.get("RUNNER_TEMP")
    if not configured:
        configured = git(args.root, "config", "--get", "codex.worktreeRoot").stdout.decode().strip()
    if not Path(configured).is_absolute():
        raise PublicationError("retry worktree parent must be an absolute configured path")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write("committed=false\n")
    result = publish(args.root, report=args.report, parent=Path(configured))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write("committed=" + str(result["committed"]).lower() + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
