"""Five-minute earnings polling must not bypass audit or fan out on no changes."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow(name="earnings-refresh.yml"):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def _step(name, job="publish"):
    return next(s for s in _workflow()["jobs"][job]["steps"] if s.get("name") == name)


def test_polling_has_no_model_runtime_or_long_market_close_lock():
    doc = _workflow()
    triggers = doc.get(True) or doc.get("on")
    assert triggers["schedule"] == [{"cron": "2-59/5 * * * *"}]
    assert "workflow_dispatch" in triggers
    assert doc["jobs"]["publish"]["concurrency"]["group"] == "earnings-publisher"
    commands = "\n".join(s.get("run", "") for j in doc["jobs"].values() for s in j["steps"])
    for forbidden in ("forecast-run", "timeseries-fit", "timeseries-refresh", "pytest", "resolution", "secrets."):
        assert forbidden not in commands
    assert "investing-data-writer" not in str(doc)
    assert doc["jobs"]["publish"]["permissions"] == {"contents": "write", "actions": "write"}
    capture = doc["jobs"]["capture"]
    assert capture["timeout-minutes"] == 360
    assert any("earnings-watch --out" in step.get("run", "") for step in capture["steps"])
    for name in ("pages.yml", "verify.yml", "timeseries-v8-daily.yml", "timeseries-daily6m.yml"):
        listeners = (_workflow(name).get(True) or _workflow(name).get("on"))["workflow_run"]["workflows"]
        assert "earnings-refresh" not in listeners


def test_partial_capture_replays_but_unchanged_capture_never_starts_publisher():
    doc = _workflow()
    job = doc["jobs"]["publish"]
    assert "always()" in job["if"]
    assert "bundle_ready == 'true'" in job["if"]
    assert "changed_hint == 'true'" in job["if"]
    capture = doc["jobs"]["capture"]["steps"]
    assert next(s for s in capture if s.get("id") == "capture")["continue-on-error"] is True
    upload = next(s for s in capture if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["include-hidden-files"] is True
    assert "earnings-capture/" in upload["with"]["path"]
    assert "data/" not in upload["with"]["path"]


def test_every_retry_replays_immutable_sources_and_only_stages_display_ledger():
    script = _step("Replay and publish against a fresh main for each attempt")["run"]
    positions = [script.index(token) for token in ("git fetch --no-tags origin main", "git worktree add --detach", "earnings-apply --root", "git commit", 'push origin HEAD:main')]
    assert positions == sorted(positions)
    assert "for attempt in 1 2 3" in script
    assert script.index('[ "$changed" = "false" ]') < script.index("git commit")
    for forbidden in ("git reset", "--force", "git pull --rebase", "--ours", "--theirs"):
        assert forbidden not in script
    allowed = re.search(r"grep -Ev '([^']+)'", script).group(1)
    for path in ("data/calendar/event_consensus.jsonl", "data/calendar/earnings_raw/fixture.html.gz"):
        assert re.fullmatch(allowed, path)
    for path in ("forecasts/example.md", "calibration/ledger.csv", "data/calendar/events.csv", "data/timeseries/ledgers/forecasts.jsonl"):
        assert re.fullmatch(allowed, path) is None
    assert "--diff-filter=D" in script


@pytest.mark.parametrize("report,expected", [
    ({"changed": True, "status": "ready"}, "changed=true\nstatus=ready\nwatch_pending=false\n"),
    ({"changed": True, "status": "partial"}, "changed=true\nstatus=partial\nwatch_pending=false\n"),
    ({"changed": False, "status": "ready"}, "changed=false\nstatus=ready\nwatch_pending=false\n"),
    ({"changed": "false", "status": "ready"}, None),
    ({"changed": True, "status": "invalid"}, None),
])
def test_dispatch_decision_requires_explicit_values(tmp_path, report, expected):
    script = _step("Read the verified change and capture status")["run"]
    code = re.search(r"python - <<'PY'\n(.*?)\nPY", script, re.S).group(1)
    (tmp_path / ".tmp").mkdir()
    (tmp_path / ".tmp/earnings-report.json").write_text(json.dumps(report), encoding="utf-8")
    (tmp_path / ".tmp/earnings-capture-report.json").write_text(json.dumps({"watch_pending": False, "watch_until": None}), encoding="utf-8")
    output = tmp_path / "github_output"
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            env={**os.environ, "GITHUB_OUTPUT": str(output)}, capture_output=True, text=True)
    if expected is None:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert output.read_text(encoding="utf-8") == expected


def test_changed_results_deploy_before_partial_failure_is_reported():
    steps = _workflow()["jobs"]["publish"]["steps"]
    pages = _step("Deploy verified earnings changes")
    failure = _step("Report unavailable sources after publishing valid results")
    assert pages["if"] == "${{ steps.decision.outputs.changed == 'true' }}"
    assert 'gh workflow run pages.yml --repo "$GITHUB_REPOSITORY" --ref main' in pages["run"]
    assert pages["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert steps.index(pages) < steps.index(failure)
    assert "status == 'partial'" in failure["if"]
    alert = _workflow("ops-failure-alert.yml")
    assert "earnings-refresh" in (alert.get(True) or alert.get("on"))["workflow_run"]["workflows"]
    mood = _workflow("market-mood-refresh.yml")
    last = next(s for s in mood["jobs"]["refresh"]["steps"] if s.get("name") == "Report refresh failure")
    assert "steps.consensus.outcome == 'failure'" in last["if"]


def test_completed_publication_and_budget_limit_rearm_the_remaining_window():
    capture = _step("Continue an unchanged watch that reached its runner budget", job="capture")
    publish = _step("Resume watching other confirmed earnings after publication")
    assert "steps.capture.outcome == 'success'" in capture["if"]
    assert "changed_hint == 'false'" in capture["if"]
    assert "watch_pending == 'true'" in capture["if"]
    assert "watch_pending == 'true'" in publish["if"]
    assert "status == 'ready' || steps.decision.outputs.changed == 'true'" in publish["if"]
    for step in (capture, publish):
        assert 'gh workflow run earnings-refresh.yml --repo "$GITHUB_REPOSITORY" --ref main' == step["run"]
    assert _workflow()["concurrency"]["cancel-in-progress"] is False


def test_workflow_bash_blocks_parse_without_expanding_actions_expressions(tmp_path):
    bash = Path("C:/Program Files/Git/bin/bash.exe")
    if not bash.is_file():
        bash = Path(shutil.which("bash") or "")
    if not bash.is_file():
        pytest.skip("bash unavailable")
    for job in _workflow()["jobs"].values():
        for index, step in enumerate(job["steps"]):
            if "run" not in step or "${{" in step["run"]:
                continue
            script = tmp_path / f"script-{index}.sh"
            script.write_text(step["run"], encoding="utf-8", newline="\n")
            result = subprocess.run([str(bash), "--noprofile", "--norc", "-n", str(script)], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
