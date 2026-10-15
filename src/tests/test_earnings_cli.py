"""Operational earnings decisions use injected sources and disposable output paths."""
from __future__ import annotations

import json
import sys
from types import ModuleType

import pytest
from typer.testing import CliRunner

from ai_fc.cli import app


def _inject(monkeypatch, *, capture=None, apply=None):
    module = ModuleType("ai_fc.earnings_refresh")
    module.capture_earnings = capture
    module.apply_earnings = apply
    monkeypatch.setitem(sys.modules, "ai_fc.earnings_refresh", module)


@pytest.mark.parametrize("status,exit_code", [("captured", 0), ("partial", 1)])
def test_capture_preserves_partial_checkpoint_for_verified_replay(tmp_path, monkeypatch, status, exit_code):
    calls = []
    expected = {"status": status, "changed_hint": True, "bundle_id": "fixture"}
    def capture(root, **kwargs):
        calls.append((root, kwargs))
        return expected
    _inject(monkeypatch, capture=capture)
    checkout, bundle, report = tmp_path / "checkout", tmp_path / "bundle", tmp_path / "report.json"
    result = CliRunner().invoke(app, ["earnings-capture", "--root", str(checkout), "--out", str(bundle), "--report", str(report)])
    assert result.exit_code == exit_code, result.output
    assert calls == [(checkout, {"output_dir": bundle})]
    assert json.loads(report.read_text(encoding="utf-8")) == expected


def test_apply_persists_a_partial_source_decision_before_workflow_failure(tmp_path, monkeypatch):
    calls = []
    expected = {"status": "partial", "changed": True, "appended": 1, "source_failures": ["fixture HTTP failure"]}
    def apply(root, **kwargs):
        calls.append((root, kwargs))
        return expected
    _inject(monkeypatch, apply=apply)
    checkout, bundle, report = tmp_path / "fresh-main", tmp_path / "bundle", tmp_path / "report.json"
    result = CliRunner().invoke(app, ["earnings-apply", "--root", str(checkout), "--bundle", str(bundle), "--report", str(report)])
    assert result.exit_code == 0, result.output
    assert calls == [(checkout, {"bundle_dir": bundle})]
    assert json.loads(report.read_text(encoding="utf-8")) == expected
    assert not report.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("value", [None, "false", 0])
def test_ambiguous_dispatch_decision_is_rejected_before_report(tmp_path, monkeypatch, value):
    _inject(monkeypatch, apply=lambda *_args, **_kwargs: {"status": "ready", "changed": value})
    report = tmp_path / "invalid.json"
    result = CliRunner().invoke(app, ["earnings-apply", "--bundle", str(tmp_path), "--report", str(report)])
    assert result.exit_code != 0
    assert not report.exists()


@pytest.mark.parametrize("extra", [{"detail": "x" * 16384}, {"bad_number": float("nan")}])
def test_unbounded_or_non_json_report_cannot_leave_success_output(tmp_path, monkeypatch, extra):
    _inject(monkeypatch, apply=lambda *_args, **_kwargs: {"status": "ready", "changed": False, **extra})
    report = tmp_path / "invalid.json"
    result = CliRunner().invoke(app, ["earnings-apply", "--bundle", str(tmp_path), "--report", str(report)])
    assert result.exit_code != 0
    assert not report.exists()


@pytest.mark.parametrize("status,exit_code", [("captured", 0), ("partial", 1)])
def test_warm_watch_keeps_its_selected_immutable_bundle_report(tmp_path, monkeypatch, status, exit_code):
    module = ModuleType("ai_fc.earnings_watch")
    expected = {"status": status, "changed_hint": True, "watch_attempts": 2, "bundle_path": "fixture"}
    calls = []
    def watch(root, **kwargs):
        calls.append((root, kwargs))
        return expected
    module.watch_earnings = watch
    monkeypatch.setitem(sys.modules, "ai_fc.earnings_watch", module)
    bundle, report = tmp_path / "bundle", tmp_path / "report.json"
    result = CliRunner().invoke(app, ["earnings-watch", "--root", str(tmp_path), "--out", str(bundle), "--report", str(report)])
    assert result.exit_code == exit_code, result.output
    assert calls == [(tmp_path, {"output_dir": bundle})]
    assert json.loads(report.read_text(encoding="utf-8")) == expected
