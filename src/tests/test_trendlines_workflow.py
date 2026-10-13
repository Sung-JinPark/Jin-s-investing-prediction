"""Operational gates keep descriptive trendlines isolated from official writers."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def test_schedule_uses_three_market_close_windows_without_provider_credentials():
    document = workflow("trendlines-refresh.yml")
    events = document.get(True) or document["on"]
    assert events["schedule"] == [{"cron": "17 0,7,22 * * *"}]
    assert "workflow_dispatch" in events
    assert document["concurrency"]["cancel-in-progress"] is False
    assert document["jobs"]["publish"]["needs"] == "capture"
    assert document["permissions"] == {"contents": "read"}
    text = (ROOT / ".github/workflows/trendlines-refresh.yml").read_text(encoding="utf-8")
    assert "secrets." not in text and "--capture-only" in text
    assert "timeseries-forecast" not in text and "scenario-refresh" not in text


def test_publication_replays_latest_main_and_verifies_before_allowlisted_push():
    steps = workflow("trendlines-refresh.yml")["jobs"]["publish"]["steps"]
    script = next(step["run"] for step in steps if step.get("name", "").startswith("Replay raw"))
    order = [script.index(part) for part in (
        "git fetch --no-tags origin main", "git worktree add --detach", "trendlines-refresh --root",
        "trendlines-verify --root", "git add -- data/trendlines", "push origin HEAD:main")]
    assert order == sorted(order)
    assert "for attempt in 1 2 3" in script
    assert "--diff-filter=D" in script and "cannot delete history" in script
    assert "publication_allowed" in script and "type(value.get(k)) is not bool" in script
    for unsafe in ("--force", "git reset", "git add -A", "git pull --rebase"):
        assert unsafe not in script
    assert "data/trendlines/|docs/generated/inventory" in script
    dispatch = next(step for step in steps if step.get("name", "").startswith("Deploy only"))
    assert 'if [ "$changed" = "true" ]' in dispatch["run"]


def test_integrity_replay_is_required_by_both_publication_surfaces():
    for name in ("pages.yml", "verify.yml"):
        document = workflow(name)
        events = document.get(True) or document["on"]
        if name == "verify.yml":
            assert "trendlines-refresh" in events["workflow_run"]["workflows"]
        else:
            # The publisher dispatches Pages only on a meaningful change.
            assert "trendlines-refresh" not in events["workflow_run"]["workflows"]
        gates = [step for step in document["jobs"]["build" if name == "pages.yml" else "verify"]["steps"]
                 if "trendlines-verify" in step.get("run", "")]
        assert len(gates) == 1 and gates[0].get("continue-on-error") is not True
        assert "--replay" in gates[0]["run"]
    document = workflow("ops-failure-alert.yml")
    assert "trendlines-refresh" in (document.get(True) or document["on"])["workflow_run"]["workflows"]


def test_existing_skip_concurrency_guards_remain_intact():
    for name in ("pages.yml", "verify.yml"):
        document = workflow(name)
        assert "workflow_run.conclusion != 'success'" in document["concurrency"]["group"]
        assert "workflow_run.head_branch != 'main'" in document["concurrency"]["group"]
