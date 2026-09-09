from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_investing_refresh_scopes_secret_and_caps_paid_work() -> None:
    workflow = (ROOT / ".github" / "workflows" / "investing-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in workflow
    # C5-A3 (2026-09-09): 주 1건 -> 3건. 신규 26문항을 마감 전에 소화하려면
    # 1건/주(20주 소요)로는 부족하다. 3 x $1.50 x 4.3주 = 약 $19/월 < sub-cap $25.
    assert "python -m ai_fc forecast --due --max 3 --agents 2 --budget 1.50 --yes" in workflow
    assert 'AI_FC_OPENAI_MONTHLY_BUDGET: "25.00"' in workflow  # C5-A2 2026-09-09
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
    assert "id: market_extensions" in scenario
    assert "Report partial refresh failures" in scenario
    assert "steps.market_extensions.outcome == 'failure'" in scenario
    assert "python -m ai_fc inventory" in scenario
    assert "git add docs/generated/inventory.generated.md" in scenario
    assert "python -m ai_fc ai-capital-cycle" in ai_regime
    assert "python -m ai_fc source-monitor" in source_monitoring
    assert 'if [ -d "$optional_dir" ]' in scenario


def test_bot_data_commits_trigger_pages_and_verification() -> None:
    pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    verify = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")

    assert '"Pillow>=10"' in pages, "Pages OG image build requires Pillow"
    # V2/V8 data commits are pushed with GITHUB_TOKEN, which never fires push
    # events for other workflows — without these workflow_run entries the V8
    # gate flip stayed invisible on the live site (observed 2026-09-01).
    # timeseries-v13-vol-live (2026-09-08): V13-VOL 포인터 커밋도 GITHUB_TOKEN 푸시라 같은 이유로 등록.
    expected = (
        'workflows: ["investing-refresh", "scenario-refresh", "ai-regime-refresh", '
        '"statistics-refresh", "timeseries-refresh", "timeseries-v5-refresh", '
        '"timeseries-v2-refresh", "timeseries-v8-shadow", "timeseries-v13-vol-live"]'
    )
    for workflow in (pages, verify):
        assert expected in workflow
        assert "types: [completed]" in workflow

    ots = (ROOT / ".github" / "workflows" / "ots-stamp.yml").read_text(
        encoding="utf-8"
    )
    assert 'workflows: ["investing-refresh"]' in ots
