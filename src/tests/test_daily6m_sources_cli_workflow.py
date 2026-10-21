"""Research source dispatches are explicit and cannot write other ledgers."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from typer.testing import CliRunner

from ai_fc.cli import app

ROOT = Path(__file__).resolve().parents[2]


def _inject(monkeypatch, result, calls):
    module = ModuleType("ai_fc.daily6m_sources")
    def call(root, **kwargs):
        calls.append((root, kwargs))
        return result
    module.capture_daily6m_sources = call
    module.apply_daily6m_sources = call
    monkeypatch.setitem(sys.modules, "ai_fc.daily6m_sources", module)


@pytest.mark.parametrize("action,status", [("capture", "captured"), ("apply", "applied")])
def test_cli_uses_explicit_checkout_and_writes_an_atomic_bounded_report(tmp_path, monkeypatch, action, status):
    calls = []
    result = {"changed": True, "status": status, "source_failures": []}
    _inject(monkeypatch, result, calls)
    report, root, bundle = tmp_path / "report.json", tmp_path / "checkout", tmp_path / "bundle"
    flag = "--out" if action == "capture" else "--bundle"
    response = CliRunner().invoke(app, [f"timeseries-daily6m-sources-{action}", "--root", str(root), flag, str(bundle), "--report", str(report)])
    assert response.exit_code == 0, response.output
    assert calls == [(root, {"output_dir" if action == "capture" else "bundle_dir": bundle})]
    assert json.loads(report.read_text(encoding="utf-8")) == result
    assert not report.with_suffix(".json.tmp").exists()


def test_partial_capture_reports_failure_without_losing_its_audit(tmp_path, monkeypatch):
    result = {"changed": False, "status": "partial", "source_failures": [{"source_id": "fixture", "reason": "HTTP503"}]}
    _inject(monkeypatch, result, [])
    report = tmp_path / "report.json"
    response = CliRunner().invoke(app, ["timeseries-daily6m-sources-capture", "--report", str(report)])
    assert response.exit_code == 1
    assert json.loads(report.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("result", [{"changed": "false", "status": "applied"}, {"changed": True, "status": "applied", "detail": "x" * 16384}])
def test_invalid_dispatch_decision_cannot_create_a_report(tmp_path, monkeypatch, result):
    _inject(monkeypatch, result, [])
    report = tmp_path / "report.json"
    response = CliRunner().invoke(app, ["timeseries-daily6m-sources-apply", "--bundle", str(tmp_path), "--report", str(report)])
    assert response.exit_code != 0
    assert not report.exists()


def _workflow(name="daily6m-sources-refresh.yml"):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def _step(name):
    return next(step for step in _workflow()["jobs"]["publish"]["steps"] if step.get("name") == name)


def test_keyless_source_capture_is_independent_of_model_runtime_and_long_locks():
    doc = _workflow()
    triggers = doc.get("on") or doc.get(True)
    assert triggers["schedule"] == [{"cron": "4-59/5 * * * *"}]
    assert doc["permissions"] == {"contents": "read"}
    assert doc["jobs"]["publish"]["permissions"] == {"contents": "write", "actions": "write"}
    assert doc["jobs"]["publish"]["concurrency"]["group"] == "daily6m-sources-publisher"
    commands = "\n".join(step.get("run", "") for job in doc["jobs"].values() for step in job["steps"])
    for forbidden in ("secrets.", "python -m ai_fc timeseries-v8", "python -m ai_fc timeseries-v2", "timeseries-refresh", "pytest", "investing-data-writer"):
        assert forbidden not in commands
    for name in ("pages.yml", "verify.yml", "timeseries-v8-daily.yml", "timeseries-daily6m.yml"):
        listeners = (_workflow(name).get("on") or _workflow(name).get(True))["workflow_run"]["workflows"]
        assert "daily6m-sources-refresh" not in listeners


def test_immutable_artifact_paths_preserve_capture_directory_layout():
    jobs = _workflow()["jobs"]
    upload = next(step for step in jobs["capture"]["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    download = next(step for step in jobs["publish"]["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert upload["with"]["include-hidden-files"] is True
    assert upload["with"]["path"].splitlines() == [".tmp/daily6m-sources-capture/", ".tmp/daily6m-sources-capture-report.json"]
    assert download["with"]["path"] == ".tmp"
    assert "!cancelled()" in jobs["publish"]["if"]


def test_every_retry_reparses_sources_against_a_fresh_tip_and_stages_only_research_inputs():
    script = _step("Replay official source receipts against a fresh main")["run"]
    positions = [script.index(token) for token in ("git fetch --no-tags origin main", "git worktree add --detach", "timeseries-daily6m-sources-apply --root", "git commit", "push origin HEAD:main")]
    assert positions == sorted(positions)
    assert "for attempt in 1 2 3" in script
    assert script.index('test "$changed" = false') < script.index("git commit")
    assert "--diff-filter=D" in script
    for forbidden in ("--force", "git reset", "git pull --rebase", "--ours", "--theirs"):
        assert forbidden not in script
    allowed = re.search(r"grep -Ev '([^']+)'", script).group(1)
    for path in ("data/timeseries_daily6m/raw/nasdaq_comp_official/fixture.gz", "data/timeseries_daily6m/source_receipts.jsonl", "data/timeseries_daily6m/source_observations.jsonl"):
        assert re.fullmatch(allowed, path)
    for path in ("data/timeseries_daily6m/ledgers/forecasts.jsonl", "data/timeseries_daily6m/latest.json", "data/timeseries_v2/ledgers/market_observations.jsonl", "forecasts/fixture.md", "calibration/ledger.csv"):
        assert not re.fullmatch(allowed, path)


def test_only_a_verified_source_change_dispatches_the_separate_forecast():
    dispatch = _step("Recheck and regenerate the separate weekly research forecast")
    assert dispatch["if"] == "${{ steps.decision.outputs.changed == 'true' }}"
    assert "timeseries-daily6m.yml" in dispatch["run"]
    assert "pages.yml" not in str(_workflow())
    assert "daily6m-sources-refresh" in (_workflow("ops-failure-alert.yml").get("on") or _workflow("ops-failure-alert.yml").get(True))["workflow_run"]["workflows"]
