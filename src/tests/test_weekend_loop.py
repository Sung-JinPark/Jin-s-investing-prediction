from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is unavailable")


def _loop_repo(tmp_path: Path, *, branch: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / "tools/weekend_loop.sh", repo / "tools/weekend_loop.sh")
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "--allow-empty", "-q", "-m", "seed"],
        check=True,
    )
    return repo


def _run_loop(repo: Path, *, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "DRY_RUN": "1", "MAX_CYCLES": "1", **env_extra}
    return subprocess.run(
        [BASH, "tools/weekend_loop.sh"], cwd=repo, env=env,
        capture_output=True, text=True, timeout=180,
    )


def _log_body(repo: Path) -> str:
    log = repo / f"outputs/timeseries_v8/loop/loop_{datetime.now():%Y%m%d}.log"
    return log.read_text(encoding="utf-8") if log.is_file() else ""


def test_loop_refuses_to_run_on_main(tmp_path: Path) -> None:
    repo = _loop_repo(tmp_path, branch="main")
    result = _run_loop(repo, env_extra={})
    assert result.returncode == 1
    assert "branch is main" in _log_body(repo)


def test_loop_lock_rejects_a_second_instance(tmp_path: Path) -> None:
    repo = _loop_repo(tmp_path, branch="claude/loop-test")
    lock = repo / "outputs/timeseries_v8/loop/lock"
    lock.mkdir(parents=True)
    # The lock check uses MSYS `kill -0`, so the holder pid must be an MSYS
    # pid: let bash record its own $$ before sleeping.
    pid_file = lock / "pid"
    holder = subprocess.Popen(
        [BASH, "-c", f"echo $$ > '{pid_file.as_posix()}'; sleep 30"],
    )
    try:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if pid_file.is_file() and pid_file.read_text(encoding="utf-8").strip():
                break
            time.sleep(0.2)
        holder_pid = pid_file.read_text(encoding="utf-8").strip()
        result = _run_loop(repo, env_extra={})
        assert result.returncode == 0
        assert "already running" in result.stdout
        # The lock must remain held by the first instance.
        assert lock.is_dir() and pid_file.read_text(encoding="utf-8").strip() == holder_pid
    finally:
        holder.kill()


def test_loop_halts_when_the_queue_yields_a_sealed_config(tmp_path: Path) -> None:
    repo = _loop_repo(tmp_path, branch="claude/loop-test")
    (repo / "tools/ralph_timeseries_v8.py").write_text(
        "import sys\n"
        "cmd = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if cmd == 'status':\n"
        "    print('{\"status\": \"running\"}'); sys.exit(0)\n"
        "if cmd == 'next':\n"
        "    print('{\"next\": {\"label\": \"X_probe\", \"config\": "
        "{\"sealed_run\": true}}, \"command\": \"x\"}'); sys.exit(0)\n"
        "sys.exit(2)\n",
        encoding="utf-8",
    )
    loop_dir = repo / "outputs/timeseries_v8/loop"
    loop_dir.mkdir(parents=True)
    (loop_dir / "harness_run_id").write_text("test-run\n", encoding="utf-8")
    result = _run_loop(repo, env_extra={})
    assert result.returncode == 1
    body = _log_body(repo)
    assert "HALT" in body and "sealed" in body
