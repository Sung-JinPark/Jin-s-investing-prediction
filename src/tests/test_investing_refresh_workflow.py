from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_investing_refresh_scopes_secret_and_caps_paid_work() -> None:
    workflow = (ROOT / ".github" / "workflows" / "investing-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in workflow
    # C5-A4 (2026-09-11): 자동 경로의 유료 호출은 키 생존 smoke 하나뿐이다.
    assert "python -m ai_fc openai-smoke" in workflow
    assert 'AI_FC_OPENAI_MONTHLY_BUDGET: "2.00"' in workflow
    assert "gpt-5.6-terra" in workflow
    assert "cancel-in-progress: false" in workflow


def test_no_unattended_path_produces_an_official_forecast() -> None:
    """사람이 안 보는 자리에서 게이트 표본에 회차가 들어가지 않는다.

    T05 는 `openai:gpt-5.6-terra` + 축소 핀 조합을 0/4 ok 로 은퇴시켰는데, 은퇴가
    레지스트리의 `tier: lite` **라벨**에만 걸려 그 라벨을 만들던 예약 실행은 그대로
    남아 있었다. lite 가 standard 로 승격된 뒤에는 같은 조합이 `pipeline_tier:
    standard` 로 게이트 표본에 들어간다 — 라벨만 바꿔 계속 돌리는 쪽이 더 나쁘다.
    게이트 회차는 로컬 anthropic cli/api 경로 전용이다(C5-A4 2026-09-11).
    """
    import re

    import yaml

    offenders: list[str] = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"python -m ai_fc forecast", text):
            continue
        document = yaml.safe_load(text)
        # PyYAML 은 YAML 1.1 규칙으로 `on:` 키를 True 로 읽는다
        on = document.get(True) or document.get("on") or {}
        if isinstance(on, dict) and {"schedule", "workflow_run"} & set(on):
            offenders.append(path.name)
    assert not offenders, f"무인 실행이 공식 회차를 생산한다: {offenders}"


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


def test_every_unattended_data_writer_is_watched_for_failure() -> None:
    """사람이 안 보는 자리에서 데이터를 쓰는 워크플로는 전부 실패 감시 대상이다.

    감시가 timeseries-refresh·timeseries-v2-refresh 두 개뿐이던 동안
    timeseries-v5-refresh 는 2026-08-25 부터 12일 연속 실패했고,
    timeseries-v13-vol-live 는 사흘간 라이브 전진 표본을 못 쌓았다. 둘 다 아무
    신호도 남기지 않았다. 예약·연쇄 트리거는 지켜보는 사람이 없다는 뜻이므로
    푸시하는 워크플로라면 감시 목록에 있어야 한다.
    """
    import re

    import yaml

    directory = ROOT / ".github" / "workflows"
    alert = yaml.safe_load((directory / "ops-failure-alert.yml").read_text(encoding="utf-8"))
    # PyYAML 은 YAML 1.1 규칙으로 `on:` 키를 True 로 읽는다
    triggers = alert.get(True) or alert.get("on")
    watched = set(triggers["workflow_run"]["workflows"])

    unwatched: list[str] = []
    for path in sorted(directory.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"\bgit push\b", text):
            continue
        document = yaml.safe_load(text)
        on = document.get(True) or document.get("on") or {}
        if not isinstance(on, dict):
            continue
        if not {"schedule", "workflow_run"} & set(on):
            continue  # push·dispatch 전용은 방금 행동한 사람이 결과를 본다
        name = document["name"]
        if name not in watched and name != "ops-failure-alert":
            unwatched.append(f"{path.name} ({name})")
    assert not unwatched, f"실패가 조용히 묻히는 데이터 라이터: {unwatched}"


def test_every_data_commit_replays_on_the_fresh_tip() -> None:
    """봇 데이터 커밋의 `git push` 는 반드시 rebase 재생을 앞세운다.

    checkout 과 push 사이에 main 은 늘 움직인다 — 다른 데이터 라이터 워크플로,
    그리고 PR 병합. 재생이 없으면 non-fast-forward 로 그 회차 산출물이 통째로
    버려진다(2026-08-25·27·28·29 source-monitoring, 2026-09-09 scenario-refresh).
    산출물이 전부 추가·재생성형이라 재생은 안전하다.
    """
    import re

    bare: list[str] = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if re.fullmatch(r"\s*git push\s*", line):
                window = "\n".join(lines[max(0, index - 10):index])
                if "pull --rebase" not in window:
                    bare.append(f"{path.name}:{index + 1}")
    assert not bare, f"rebase 재생 없는 데이터 푸시: {bare}"
