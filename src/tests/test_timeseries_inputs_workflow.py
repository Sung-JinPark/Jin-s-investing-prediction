"""Fast input capture preserves append-only publication and avoids polling fan-out."""
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
WORKFLOWS = ROOT / ".github/workflows"


def _workflow(name: str = "timeseries-inputs-refresh.yml") -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(name: str) -> dict:
    return next(step for step in _workflow()["jobs"]["commit"]["steps"] if step.get("name") == name)


def test_fast_capture_is_separate_from_the_daily_archive_and_model_runtime() -> None:
    document = _workflow()
    events = document.get(True) or document.get("on")
    assert events["schedule"] == [{"cron": "17,47 * * * *"}]
    assert "workflow_dispatch" in events and "workflow_run" not in events
    capture, commit = document["jobs"]["capture"], document["jobs"]["commit"]
    assert capture["timeout-minutes"] == 15 and "concurrency" not in capture
    assert commit["needs"] == "capture"
    assert "always() && needs.capture.outputs.bundle_ready == 'true'" in commit["if"]
    assert commit["concurrency"] == {"group": "timeseries-inputs-publisher", "cancel-in-progress": False}
    assert "FRED_API_KEY" in capture["env"] and "FRED_API_KEY" not in commit["env"]
    assert commit["permissions"] == {"contents": "write", "actions": "write"}
    commands = "\n".join(step.get("run", "") for job in document["jobs"].values() for step in job["steps"])
    for expensive in ("timeseries-v2-prepare", "timeseries-refresh", "timeseries-fit", "backtest", "pytest"):
        assert expensive not in commands
    full = _workflow("timeseries-v2-refresh.yml")
    assert (full.get(True) or full.get("on"))["schedule"] == [{"cron": "20 8 * * 2-6"}]


def test_artifacts_carry_capture_bytes_instead_of_canonical_ledger_deltas() -> None:
    document = _workflow()
    capture = document["jobs"]["capture"]["steps"]
    upload = next(step for step in capture if step.get("uses", "").startswith("actions/upload-artifact@"))
    fetch = next(step for step in capture if step.get("id") == "capture")
    assert fetch["continue-on-error"] is True, "Partial capture still reaches safe replay and HOLD publication"
    assert upload["if"] == "${{ always() && steps.bundle.outputs.bundle_ready == 'true' }}"
    assert upload["with"]["path"] == ".tmp/inputs-capture/"
    assert upload["with"]["retention-days"] == 3
    assert upload["with"]["include-hidden-files"] is True, ".tmp capture files must not be silently excluded"
    assert upload["with"]["if-no-files-found"] == "error"
    download = next(step for step in document["jobs"]["commit"]["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"]["path"] == ".tmp/inputs-capture"
    assert download["with"]["name"] == upload["with"]["name"]
    assert "data/" not in upload["with"]["path"]
    readiness = next(step for step in capture if step.get("id") == "bundle")
    assert "-f .tmp/inputs-capture/manifest.json" in readiness["run"]
    assert "bundle_ready=true" in readiness["run"] and "bundle_ready=false" in readiness["run"]
    assert capture[-1]["if"] == "${{ always() && steps.bundle.outputs.bundle_ready != 'true' }}"
    assert "exit 1" in capture[-1]["run"]


def test_every_optimistic_publish_attempt_replays_into_a_new_current_main() -> None:
    script = _step("Replay and publish against a fresh main for each attempt")["run"]
    assert "for attempt in 1 2 3; do" in script
    fetch = script.index("git fetch --no-tags origin main")
    worktree = script.index('git worktree add --detach "$attempt_root" origin/main')
    apply = script.index('timeseries-inputs-apply --root "$attempt_root"')
    push = script.index('git -C "$attempt_root" push origin HEAD:main')
    assert fetch < worktree < apply < push
    assert 'attempt_root="$RUNNER_TEMP/inputs-publish-attempt-$attempt"' in script
    assert 'PYTHONPATH="$attempt_root/src" python -m ai_fc inventory' in script
    assert '--bundle "$capture_bundle"' in script and '--report "$report_path"' in script
    assert script.index('[ "$changed" = "false" ]') < script.index("git commit")
    for forbidden in ("git reset", "git pull --rebase", "--force", "git worktree remove", "rm -", "--ours", "--theirs"):
        assert forbidden not in script
    assert "sleep 15" in script and '[ "$attempt" -eq 3 ]' in script


@pytest.mark.parametrize("path", [
    "data/timeseries/ledgers/forecasts.jsonl", "data/timeseries/ledgers/source_backfill_audit.jsonl",
    "data/timeseries_v2/ledgers/sealed_evaluations.jsonl", "data/timeseries_v2/ledgers/dfm_cache_manifest.jsonl",
    "data/timeseries_v2/parquet/features_C1.parquet", "data/timeseries_v8/daily_display_latest.json",
    "data/forecasts/example.json", "src/ai_fc/timeseries_v2/model.py",
])
def test_input_publisher_rejects_model_and_forecast_commit_paths(path: str) -> None:
    script = _step("Replay and publish against a fresh main for each attempt")["run"]
    allowed = re.search(r"grep -Ev '([^']+)'", script).group(1)
    assert re.match(allowed, path) is None
    for source in (
        "data/timeseries/raw/alfred/new.json.gz", "data/timeseries/facts/observations.parquet",
        "data/timeseries/ledgers/observation_chunks.jsonl",
        "data/timeseries_v2/raw/market/cboe_vix_archive/example.gz",
        "data/timeseries_v2/ledgers/market_observations.jsonl",
        "data/timeseries_v2/parquet/market_observations.manifest.json", "data/timeseries_inputs/latest.json",
    ):
        assert re.match(allowed, source), source
    assert "--diff-filter=D" in script


@pytest.mark.parametrize("report,expected", [
    ({"changed": False, "publication_allowed": True}, "changed=false\npublication_allowed=true\n"),
    ({"changed": True, "publication_allowed": True}, "changed=true\npublication_allowed=true\n"),
    ({"changed": True, "publication_allowed": False}, "changed=true\npublication_allowed=false\n"),
    ({"changed": "false", "publication_allowed": True}, None),
    ({"changed": True, "publication_allowed": 1}, None),
    ({"changed": True}, None),
])
def test_workflow_reads_explicit_boolean_decisions_without_truthy_coercion(tmp_path: Path, report: dict, expected: str | None) -> None:
    step = _step("Read the semantic change and publication decision")
    code = re.search(r"python - <<'PY'\n(.*?)\nPY", step["run"], re.S).group(1)
    (tmp_path / ".tmp").mkdir()
    (tmp_path / ".tmp/inputs-report.json").write_text(json.dumps(report), encoding="utf-8")
    output = tmp_path / "github_output"
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            env={**os.environ, "GITHUB_OUTPUT": str(output)}, capture_output=True, text=True)
    if expected is None:
        assert result.returncode != 0
        assert not output.exists(), "Invalid decisions cannot leave partial successful outputs"
    else:
        assert result.returncode == 0, result.stderr
        assert output.read_text(encoding="utf-8") == expected


def test_only_semantic_changes_fan_out_and_failures_publish_hold_without_models() -> None:
    steps = _workflow()["jobs"]["commit"]["steps"]
    decision = next(step for step in steps if step.get("id") == "decision")
    models = next(step for step in steps if "gh workflow run timeseries-v8-daily.yml" in step.get("run", ""))
    pages = next(step for step in steps if "gh workflow run pages.yml" in step.get("run", ""))
    assert "changed == 'true'" in models["if"] and "publication_allowed == 'true'" in models["if"]
    assert pages["if"] == "${{ always() && steps.decision.outputs.changed == 'true' }}"
    assert models["run"].count("gh workflow run") == 2
    assert "timeseries-daily6m.yml" in models["run"] and "timeseries-v8-shadow" not in models["run"]
    assert steps.index(decision) < steps.index(models) < steps.index(pages)
    for step in (models, pages):
        assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
        assert '--repo "$GITHUB_REPOSITORY" --ref main' in step["run"]
    failure = steps[-1]
    assert "publication_allowed == 'false'" in failure["if"] and "always()" in failure["if"]
    assert "exit 1" in failure["run"]
    for name in ("pages.yml", "verify.yml", "timeseries-v8-daily.yml", "timeseries-daily6m.yml"):
        workflow = _workflow(name)
        listeners = (workflow.get(True) or workflow.get("on"))["workflow_run"]["workflows"]
        assert "timeseries-inputs-refresh" not in listeners, "Every no-change poll must avoid downstream jobs"


def test_downstream_completed_events_require_successful_main_and_verify_coalesces() -> None:
    for name, job in (("pages.yml", "build"), ("verify.yml", "verify"), ("timeseries-v8-daily.yml", "forecast")):
        document = _workflow(name)
        guard = document["jobs"][job]["if"]
        assert "github.event_name != 'workflow_run'" in guard
        assert "workflow_run.conclusion == 'success' &&" in guard
        assert "workflow_run.head_branch == 'main'" in guard
    verify = _workflow("verify.yml")
    assert verify["concurrency"]["cancel-in-progress"] is True
    assert "pull_request.number || github.ref" in verify["concurrency"]["group"]
    alert = _workflow("ops-failure-alert.yml")
    assert "timeseries-inputs-refresh" in (alert.get(True) or alert.get("on"))["workflow_run"]["workflows"]


def test_publisher_shell_parses_with_the_available_git_bash(tmp_path: Path) -> None:
    bash = Path("C:/Program Files/Git/bin/bash.exe")
    if not bash.is_file():
        bash = Path(shutil.which("bash") or "")
    if not bash.is_file():
        pytest.skip("bash not available")
    steps = _workflow()["jobs"]["commit"]["steps"]
    for index, step in enumerate(steps):
        if "run" not in step:
            continue
        script = tmp_path / f"inputs_step_{index}.sh"
        script.write_text(step["run"], encoding="utf-8")
        result = subprocess.run([str(bash), "--noprofile", "--norc", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
