"""Statistics publication must expose per-indicator failures after saving evidence."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def _events(document: dict) -> dict:
    return document.get("on") or document[True]


def test_statistics_refresh_audits_every_indicator_after_publication() -> None:
    workflow = _workflow("statistics-refresh.yml")
    steps = workflow["jobs"]["refresh"]["steps"]
    audit = next(step for step in steps if "statistics-freshness" in step.get("run", ""))
    publication = next(step for step in steps if "gh workflow run pages.yml" in step.get("run", ""))
    assert steps.index(publication) < steps.index(audit)
    assert audit["if"] == "${{ always() }}"
    assert "--strict" in audit["run"]
    assert '--output "$RUNNER_TEMP/statistics-freshness.json"' in audit["run"]
    assert 'tee -a "$GITHUB_STEP_SUMMARY"' in audit["run"]
    assert audit.get("continue-on-error") is not True
    evidence = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert steps.index(audit) < steps.index(evidence)
    assert evidence["if"] == "${{ always() }}"
    assert evidence["with"]["path"] == "${{ runner.temp }}/statistics-freshness.json"
    validation = next(step["run"] for step in steps if "pytest" in step.get("run", "") and "test_statistics_lab.py" in step["run"])
    assert "src/tests/test_statistics_freshness.py" in validation
    assert "src/tests/test_statistics_refresh_workflow.py" in validation


def test_edgar_watch_tests_before_sweep_and_refreshes_changed_statistics() -> None:
    workflow = _workflow("ipo-edgar-watch.yml")
    assert workflow["permissions"]["actions"] == "write"
    assert "github.ref != 'refs/heads/main'" in workflow["concurrency"]["group"]
    watch = workflow["jobs"]["watch"]
    assert "github.ref == 'refs/heads/main'" in watch["if"]
    steps = watch["steps"]
    assert steps[0]["with"]["ref"] == "main"
    validation = next(step for step in steps if "test_ipo_edgar_watch.py" in step.get("run", ""))
    sweep = next(step for step in steps if step.get("run") == "python -m ai_fc ipo-edgar-watch")
    assert steps.index(validation) < steps.index(sweep)
    commit = next(step for step in steps if step.get("id") == "commit")
    rebuild = next(step for step in steps if "gh workflow run statistics-refresh.yml" in step.get("run", ""))
    assert steps.index(commit) < steps.index(rebuild)
    assert "steps.commit.outputs.committed == 'true'" in rebuild["if"]
    assert "--ref main" in rebuild["run"]
    assert 'echo "committed=true"' in commit["run"]
    report = steps[-1]["run"]
    assert 'rows["status"] != "current" or rows["errors"]' in report
    assert "raise SystemExit" in report


def test_statistics_backfill_main_results_redeploy_and_verify() -> None:
    for name in ("pages.yml", "verify.yml"):
        document = _workflow(name)
        assert "statistics-backfill" in _events(document)["workflow_run"]["workflows"]
        job = document["jobs"]["build" if name == "pages.yml" else "verify"]
        assert "conclusion == 'success'" in job["if"]
        assert "head_branch == 'main'" in job["if"]
    # EDGAR changes first rebuild the statistics snapshot; that verified refresh
    # already publishes Pages. Its own completion only requests verification.
    assert "ipo-edgar-watch" in _events(_workflow("verify.yml"))["workflow_run"]["workflows"]
    assert "ipo-edgar-watch" not in _events(_workflow("pages.yml"))["workflow_run"]["workflows"]
