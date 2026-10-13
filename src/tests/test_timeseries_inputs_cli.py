"""Batch CLI boundaries use disposable paths and injected capture functions."""

from __future__ import annotations

import json
import sys
from types import ModuleType

import pytest
from typer.testing import CliRunner

from ai_fc.cli import app


def _inject(monkeypatch, capture=None, apply=None):
    module = ModuleType("ai_fc.timeseries_inputs")
    module.capture_timeseries_inputs = capture
    module.apply_timeseries_inputs = apply
    monkeypatch.setitem(sys.modules, "ai_fc.timeseries_inputs", module)


def test_capture_uses_requested_checkout_and_only_reports_public_metadata(tmp_path, monkeypatch):
    calls = []

    def capture(root, **kwargs):
        calls.append((root, kwargs))
        return {"status": "captured", "bundle_id": "fixture-public-id"}

    _inject(monkeypatch, capture=capture)
    monkeypatch.setenv("FRED_API_KEY", "fixture-runtime-key")
    checkout, bundle = tmp_path / "checkout", tmp_path / "raw-bundle"
    result = CliRunner().invoke(app, ["timeseries-inputs-capture", "--root", str(checkout), "--out", str(bundle)])
    assert result.exit_code == 0, result.output
    assert calls == [(checkout, {"output_dir": bundle, "api_key": "fixture-runtime-key"})]
    assert json.loads(result.output)["bundle_id"] == "fixture-public-id"
    assert "fixture-runtime-key" not in result.output


@pytest.mark.parametrize("status", ["partial", "failed"])
def test_failed_capture_keeps_its_auditable_result_and_fails_the_command(status, monkeypatch):
    _inject(monkeypatch, capture=lambda *args, **kwargs: {"status": status, "source_failures": ["fixture HTTP 503"]})
    result = CliRunner().invoke(app, ["timeseries-inputs-capture"])
    assert result.exit_code == 1
    assert json.loads(result.output)["source_failures"] == ["fixture HTTP 503"]


def test_apply_targets_latest_checkout_and_writes_dispatch_decision_atomically(tmp_path, monkeypatch):
    calls = []
    expected = {"status": "hold", "changed": True, "publication_allowed": False, "source_failures": ["fixture"]}

    def apply(root, **kwargs):
        calls.append((root, kwargs))
        return expected

    _inject(monkeypatch, apply=apply)
    checkout, bundle, report = tmp_path / "latest-main", tmp_path / "capture", tmp_path / "dispatch.json"
    result = CliRunner().invoke(app, ["timeseries-inputs-apply", "--root", str(checkout), "--bundle", str(bundle), "--report", str(report)])
    assert result.exit_code == 0, result.output
    assert calls == [(checkout, {"bundle_dir": bundle})]
    assert json.loads(report.read_text(encoding="utf-8")) == expected
    assert not report.with_suffix(".json.tmp").exists()


def test_oversized_dispatch_report_is_rejected_without_partial_file(tmp_path, monkeypatch):
    _inject(monkeypatch, apply=lambda *args, **kwargs: {"status": "hold", "detail": "x" * 16384})
    report = tmp_path / "oversized.json"
    result = CliRunner().invoke(app, ["timeseries-inputs-apply", "--bundle", str(tmp_path), "--report", str(report)])
    assert result.exit_code != 0
    assert "16KiB" in str(result.exception)
    assert not report.exists()
