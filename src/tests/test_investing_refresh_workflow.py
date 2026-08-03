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

    assert "group: investing-data-writer" in full
    assert "group: investing-data-writer" in scenario
