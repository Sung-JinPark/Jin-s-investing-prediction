from __future__ import annotations

import json
from pathlib import Path

from tools import ralph_timeseries as ralph


def test_ralph_allowlist_blocks_secrets_and_protected_paths() -> None:
    assert ralph.path_allowed("src/ai_fc/timeseries_v2/pipeline.py")
    assert ralph.path_allowed("data/contracts/multivariate_timeseries_v2.yaml")
    assert not ralph.path_allowed(".secrets/fred_api_key.dpapi")
    assert not ralph.path_allowed("data/scenarios/nasdaq_latest.json")
    assert not ralph.path_allowed("data/forecasts/ledger.jsonl")


def test_ralph_agent_environment_removes_collection_and_github_secrets() -> None:
    env = ralph.sanitized_agent_environment({
        "PATH": "bin", "FRED_API_KEY": "fred", "GH_TOKEN": "gh",
        "GITHUB_TOKEN": "github", "SAFE": "yes",
    })
    assert env["SAFE"] == "yes"
    assert "FRED_API_KEY" not in env
    assert "GH_TOKEN" not in env
    assert "GITHUB_TOKEN" not in env
    assert ".secrets" in env["RALPH_SECRET_ISOLATION"]


def test_blocker_signature_ignores_hashes_numbers_and_whitespace() -> None:
    left = ralph.blocker_signature("Error 123 hash abcdef1234567890\n  same")
    right = ralph.blocker_signature("Error 999 hash ffffffffffffffff same")
    assert left == right


def test_new_ralph_worktree_uses_the_reviewed_head_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(ralph, "WORKTREE_ROOT", tmp_path / "worktrees")
    monkeypatch.setattr(ralph, "_frozen_hash", lambda _: "frozen")
    monkeypatch.setattr(ralph, "_protected_hash", lambda _: "protected")
    commands: list[list[str]] = []

    def fake_runner(command, _cwd, _env):
        commands.append(list(command))
        return ralph.CommandResult(0, "", "")

    state = ralph.create_run(
        max_iterations=1, max_hours=1, auto_merge=False, runner=fake_runner,
    )
    assert commands[0][-1] == "HEAD"
    assert state["base_ref"] == "HEAD"
    assert Path(state["worktree"]).is_relative_to(tmp_path / "worktrees")


def test_abort_and_report_are_persistent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path)
    directory = tmp_path / "run-1"
    directory.mkdir()
    state = {
        "run_id": "run-1", "status": "running", "iteration": 0, "max_iterations": 50,
        "started_at": "2026-08-20T00:00:00+00:00", "updated_at": "2026-08-20T00:00:00+00:00",
        "frozen_hash": "a", "protected_hash": "b", "iterations": [], "stop_reason": None,
    }
    (directory / ralph.STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    args = type("Args", (), {"run_id": "run-1"})()
    assert ralph.command_abort(args) == 0
    assert (directory / ralph.ABORT_FILE).is_file()
    assert ralph.command_report(args) == 0
    assert (directory / ralph.REPORT_FILE).is_file()


def test_resume_extends_budget_without_changing_frozen_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path)
    directory = tmp_path / "resume-1"
    directory.mkdir()
    state = {
        "run_id": "resume-1", "status": "hold", "iteration": 2, "max_iterations": 50,
        "started_at": "2026-08-20T00:00:00+00:00", "updated_at": "2026-08-20T00:00:00+00:00",
        "frozen_hash": "frozen", "protected_hash": "protected", "iterations": [],
        "stop_reason": "budget", "deadline_epoch": 0,
    }
    (directory / ralph.STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    captured = {}

    def fake_execute(active):
        captured.update(active)
        return {**active, "status": "passed"}

    monkeypatch.setattr(ralph, "execute_run", fake_execute)
    args = type("Args", (), {"run_id": "resume-1", "max_hours": 1.0})()
    assert ralph.command_resume(args) == 0
    assert captured["status"] == "running"
    assert captured["frozen_hash"] == "frozen"
    assert captured["iteration"] == 2


def test_fake_codex_never_auto_merges_without_full_release_gate(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "run"
    worktree = directory / "worktree"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(ralph, "_frozen_hash", lambda _: "frozen")
    monkeypatch.setattr(ralph, "_protected_hash", lambda _: "protected")
    monkeypatch.setattr(ralph, "_diagnose", lambda *_args, **_kwargs: ralph.CommandResult(0, "pass", ""))
    monkeypatch.setattr(ralph, "_full_release_gate", lambda *_args, **_kwargs: (False, "sealed HOLD"))
    monkeypatch.setattr(ralph, "changed_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(ralph, "_quick_gate", lambda *_args, **_kwargs: ralph.CommandResult(1, "", "hold"))
    state = {
        "run_id": "run", "branch": "codex/timeseries-ralph-run", "worktree": str(worktree),
        "status": "running", "iteration": 0, "max_iterations": 3, "max_hours": 1,
        "auto_merge": True, "started_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00", "deadline_epoch": 9e12,
        "frozen_hash": "frozen", "protected_hash": "protected",
        "iterations": [], "blocker_counts": {}, "stop_reason": None,
    }
    called = {"publish": 0}
    monkeypatch.setattr(ralph, "_publish", lambda *_args, **_kwargs: called.__setitem__("publish", 1))
    result = ralph.execute_run(
        state,
        codex_executor=lambda *_: ralph.CommandResult(0, "no change", ""),
    )
    assert result["status"] == "hold"
    assert called["publish"] == 0
    assert result["iteration"] == 3


def test_fake_codex_auto_merge_only_after_release_gate(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "run-pass"
    worktree = directory / "worktree"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(ralph, "_frozen_hash", lambda _: "frozen")
    monkeypatch.setattr(ralph, "_protected_hash", lambda _: "protected")
    monkeypatch.setattr(ralph, "_diagnose", lambda *_args, **_kwargs: ralph.CommandResult(0, "pass", ""))
    monkeypatch.setattr(ralph, "_full_release_gate", lambda *_args, **_kwargs: (True, "all passed"))
    monkeypatch.setattr(ralph, "_publish", lambda *_args, **_kwargs: {"merged": True, "pr_number": 99})
    state = {
        "run_id": "run-pass", "branch": "codex/timeseries-ralph-run-pass", "worktree": str(worktree),
        "status": "running", "iteration": 0, "max_iterations": 50, "max_hours": 24,
        "auto_merge": True, "started_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00", "deadline_epoch": 9e12,
        "frozen_hash": "frozen", "protected_hash": "protected",
        "iterations": [], "blocker_counts": {}, "stop_reason": None,
    }
    result = ralph.execute_run(state)
    assert result["status"] == "merged"
    assert result["publication"] == {"merged": True, "pr_number": 99}


def test_sealed_failure_stops_without_invoking_codex_or_retuning(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "sealed-fail"
    worktree = directory / "worktree"
    ledger = worktree / "data/timeseries_v2/ledgers/sealed_evaluations.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps({"contract_hash": "frozen", "summary": {"gate_pass": False}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(ralph, "_frozen_hash", lambda _: "frozen")
    monkeypatch.setattr(ralph, "_protected_hash", lambda _: "protected")
    monkeypatch.setattr(ralph, "_diagnose", lambda *_args, **_kwargs: ralph.CommandResult(0, "pass", ""))
    monkeypatch.setattr(ralph, "_full_release_gate", lambda *_args, **_kwargs: (False, "sealed HOLD"))
    calls = {"codex": 0}
    state = {
        "run_id": "sealed-fail", "branch": "codex/timeseries-ralph-sealed-fail",
        "worktree": str(worktree), "status": "running", "iteration": 0,
        "max_iterations": 50, "max_hours": 24, "auto_merge": True,
        "started_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00", "deadline_epoch": 9e12,
        "frozen_hash": "frozen", "protected_hash": "protected",
        "iterations": [], "blocker_counts": {}, "stop_reason": None,
    }
    result = ralph.execute_run(
        state,
        codex_executor=lambda *_: calls.__setitem__("codex", calls["codex"] + 1),
    )
    assert result["status"] == "hold"
    assert "new preregistered model version" in result["stop_reason"]
    assert calls["codex"] == 0
    assert result["iteration"] == 0


def test_external_freshness_hold_never_triggers_code_repair(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "freshness-hold"
    worktree = directory / "worktree"
    store = worktree / "data/timeseries_v2"
    ledger = store / "ledgers/sealed_evaluations.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps({"contract_hash": "frozen", "summary": {"gate_pass": True}}) + "\n",
        encoding="utf-8",
    )
    (store / "multivariate_v2_latest.json").write_text(json.dumps({
        "publication": {"customer_numbers_visible": False},
        "gate": {"reasons": ["필수 시장 입력 48시간 SLA 초과"]},
    }), encoding="utf-8")
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(ralph, "_frozen_hash", lambda _: "frozen")
    monkeypatch.setattr(ralph, "_protected_hash", lambda _: "protected")
    monkeypatch.setattr(ralph, "_diagnose", lambda *_args, **_kwargs: ralph.CommandResult(0, "pass", ""))
    monkeypatch.setattr(ralph, "_full_release_gate", lambda *_args, **_kwargs: (False, "publication HOLD"))
    calls = {"codex": 0}
    state = {
        "run_id": "freshness-hold", "branch": "codex/timeseries-ralph-freshness-hold",
        "worktree": str(worktree), "status": "running", "iteration": 0,
        "max_iterations": 50, "max_hours": 24, "auto_merge": True,
        "started_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00", "deadline_epoch": 9e12,
        "frozen_hash": "frozen", "protected_hash": "protected",
        "iterations": [], "blocker_counts": {}, "stop_reason": None,
    }
    result = ralph.execute_run(
        state,
        codex_executor=lambda *_: calls.__setitem__("codex", calls["codex"] + 1),
    )
    assert result["status"] == "hold"
    assert "external data" in result["stop_reason"]
    assert calls["codex"] == 0
    assert result["iteration"] == 0


def test_external_dfm_runtime_hold_never_triggers_code_repair(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "runtime-hold"
    worktree = directory / "worktree"
    manifest = worktree / "data/timeseries_v2/ledgers/dfm_cache_manifest.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"cache_id": "legacy-cache-without-runtime"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(ralph, "_frozen_hash", lambda _: "frozen")
    monkeypatch.setattr(ralph, "_protected_hash", lambda _: "protected")
    monkeypatch.setattr(ralph, "_diagnose", lambda *_args, **_kwargs: ralph.CommandResult(0, "pass", ""))
    monkeypatch.setattr(ralph, "_full_release_gate", lambda *_args, **_kwargs: (False, "runtime HOLD"))
    calls = {"codex": 0}
    state = {
        "run_id": "runtime-hold", "branch": "codex/timeseries-ralph-runtime-hold",
        "worktree": str(worktree), "status": "running", "iteration": 0,
        "max_iterations": 50, "max_hours": 24, "auto_merge": True,
        "started_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00", "deadline_epoch": 9e12,
        "frozen_hash": "frozen", "protected_hash": "protected",
        "iterations": [], "blocker_counts": {}, "stop_reason": None,
    }
    result = ralph.execute_run(
        state,
        codex_executor=lambda *_: calls.__setitem__("codex", calls["codex"] + 1),
    )
    assert result["status"] == "hold"
    assert "external numerical runtime HOLD" in result["stop_reason"]
    assert calls["codex"] == 0
    assert result["iteration"] == 0


def test_superseded_legacy_dfm_runtime_does_not_hold_ralph(tmp_path: Path) -> None:
    manifest = tmp_path / "data/timeseries_v2/ledgers/dfm_cache_manifest.jsonl"
    manifest.parent.mkdir(parents=True)
    rows = [
        {"cache_id": "dfm-v2-a", "path": "legacy.json"},
        {
            "manifest_id": "dfm-v2-a@runtime", "cache_id": "dfm-v2-a",
            "path": "corrected.json", "supersedes": "dfm-v2-a",
            "runtime": {"statsmodels": "0.14.6", "pandas": "2.3.3"},
        },
    ]
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert ralph._runtime_publication_hold(tmp_path) == []


def test_forbidden_mutation_is_discarded_and_stops_the_loop(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(ralph, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(ralph, "_frozen_hash", lambda _: "frozen")
    monkeypatch.setattr(ralph, "_protected_hash", lambda _: "protected")
    monkeypatch.setattr(
        ralph, "_diagnose", lambda *_args, **_kwargs: ralph.CommandResult(1, "", "failure"),
    )
    monkeypatch.setattr(ralph, "changed_paths", lambda *_args, **_kwargs: ["data/scenarios/nasdaq_latest.json"])
    commands: list[list[str]] = []

    def fake_runner(command, _cwd, _env):
        commands.append(list(command))
        return ralph.CommandResult(0, "", "")

    state = {
        "run_id": "forbidden", "branch": "codex/timeseries-ralph-forbidden",
        "worktree": str(worktree), "status": "running", "iteration": 0,
        "max_iterations": 50, "max_hours": 24, "auto_merge": True,
        "started_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00", "deadline_epoch": 9e12,
        "frozen_hash": "frozen", "protected_hash": "protected",
        "iterations": [], "blocker_counts": {}, "stop_reason": None,
    }
    result = ralph.execute_run(
        state, runner=fake_runner,
        codex_executor=lambda *_: ralph.CommandResult(0, "changed", ""),
    )
    assert result["status"] == "blocked"
    assert result["iterations"][0]["result"] == "discarded_protected_scope"
    assert any(command[:3] == ["git", "reset", "--hard"] for command in commands)
