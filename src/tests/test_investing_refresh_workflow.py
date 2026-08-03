from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_investing_refresh_scopes_secret_and_caps_paid_work() -> None:
    workflow = (ROOT / ".github" / "workflows" / "investing-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in workflow
    assert "python -m ai_fc forecast --due --max 1 --agents 2 --budget 1.50 --yes" in workflow
    assert 'AI_FC_OPENAI_MONTHLY_BUDGET: "10.00"' in workflow
    assert "gpt-5.6-terra" in workflow
    assert "cancel-in-progress: false" in workflow


def test_scenario_and_full_refresh_share_writer_lock() -> None:
    full = (ROOT / ".github" / "workflows" / "investing-refresh.yml").read_text(
        encoding="utf-8"
    )
    scenario = (ROOT / ".github" / "workflows" / "scenario-refresh.yml").read_text(
        encoding="utf-8"
    )
    ai_regime = (ROOT / ".github" / "workflows" / "ai-regime-refresh.yml").read_text(
        encoding="utf-8"
    )
    source_monitoring = (
        ROOT / ".github" / "workflows" / "source-monitoring.yml"
    ).read_text(encoding="utf-8")

    assert "group: investing-data-writer" in full
    assert "group: investing-data-writer" in scenario
    assert "group: investing-data-writer" in ai_regime
    assert "group: investing-data-writer" in source_monitoring
    assert "continue-on-error: true" in scenario
    assert "continue-on-error: true" in ai_regime
    assert "continue-on-error: true" in source_monitoring
    assert "python -m ai_fc market-extensions" in scenario
    assert "python -m ai_fc ai-capital-cycle" in ai_regime
    assert "python -m ai_fc source-monitor" in source_monitoring
    assert 'if [ -d "$optional_dir" ]' in scenario


def test_bot_data_commits_trigger_pages_and_verification() -> None:
    pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    verify = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")

    for workflow in (pages, verify):
        assert 'workflows: ["investing-refresh", "scenario-refresh", "ai-regime-refresh"]' in workflow
        assert "types: [completed]" in workflow

    ots = (ROOT / ".github" / "workflows" / "ots-stamp.yml").read_text(
        encoding="utf-8"
    )
    assert 'workflows: ["investing-refresh"]' in ots
