"""V15 섀도 워크플로 구조 — 트리거·타임아웃·직렬 push·health 분리·3곳 등록·보호 glob 회피 (spec_U3 §8 W1~W12).

워크플로 파일만 읽는다(쓰기 0). W6(3곳 등록)은 공유 등록 웨이브(W2)가 pages·verify·ops 목록을 고친 뒤
초록이 된다(계획 §3.0-7 의 정상 대기 실패). 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase

import yaml

from v15_coherence_fixtures import ROOT

WORKFLOW = ROOT / ".github/workflows/v15-coherence-shadow.yml"
NAME = "v15-coherence-shadow"
PROTECTED_GLOBS = (
    ".github/workflows/timeseries*.yml", "tools/*timeseries*", "tools/*scenario*", "tools/*v6*",
    "src/tests/test_multivariate_timeseries*.py",
)
NEW_FILES = (
    "src/ai_fc/timeseries_v15/__init__.py", "src/ai_fc/timeseries_v15/contracts.py",
    "src/ai_fc/timeseries_v15/arms.py", "src/ai_fc/timeseries_v15/vol.py", "src/ai_fc/timeseries_v15/model.py",
    "src/ai_fc/timeseries_v15/backtest.py", "src/ai_fc/timeseries_v15/features.py",
    "src/ai_fc/timeseries_v15/labels.py", "src/ai_fc/timeseries_v15/calendar.py",
    "src/ai_fc/timeseries_v15/bundle.py", "src/ai_fc/timeseries_v15/pipeline.py",
    "src/ai_fc/timeseries_v15/plan.py", "src/ai_fc/timeseries_v15/verdict.py", "src/ai_fc/timeseries_v15/mde.py",
    "data/contracts/multivariate_timeseries_v15_coherence.yaml",
    "data/timeseries_v15/prereg/fork_patch_v1.json", "data/timeseries_v15/ledgers/approvals.jsonl",
    ".github/workflows/v15-coherence-shadow.yml",
    "src/tests/test_v15_coherence_contract.py", "src/tests/test_v15_coherence_fork.py",
    "src/tests/test_v15_coherence_arms.py", "src/tests/test_v15_coherence_labels.py",
    "src/tests/test_v15_coherence_pipeline.py", "src/tests/test_v15_coherence_verdict.py",
    "src/tests/test_v15_coherence_workflow.py", "src/tests/v15_coherence_fixtures.py",
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _on(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def test_w1_triggers() -> None:
    triggers = _on(_workflow())
    assert triggers["workflow_run"] == {"workflows": ["timeseries-v8-shadow"], "types": ["completed"]}
    assert [item["cron"] for item in triggers["schedule"]] == ["40 3 * * 1", "40 6 * * 1", "15 14 * * 2-6"]
    mode = triggers["workflow_dispatch"]["inputs"]["mode"]
    assert mode["type"] == "choice" and mode["options"] == ["auto", "resolve_only", "a5_issue", "mde_replay", "a0_identity"]


def test_w2_timeouts_and_concurrency() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    for name in ("forecast", "a5-compute", "a0-identity"):
        assert jobs[name]["timeout-minutes"] == 240, name
    assert jobs["mde"]["timeout-minutes"] == 300
    assert workflow["concurrency"] == {"group": NAME, "cancel-in-progress": False}


def test_w3_every_install_has_exchange_calendars() -> None:
    lines = [line for line in WORKFLOW.read_text(encoding="utf-8").splitlines() if "pip install" in line]
    assert lines and all('"exchange-calendars>=4.6,<5"' in line for line in lines)


def test_w4_no_continue_on_error_and_true_only_on_grep() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in text
    for line in text.splitlines():
        if "|| true" in line:
            assert line.strip().startswith('unexpected="$(git diff --cached --name-only | grep -Ev'), line


def test_w5_commit_allowlists_are_v15_only() -> None:
    patterns = re.findall(r"grep -Ev '([^']+)'", WORKFLOW.read_text(encoding="utf-8"))
    assert patterns
    for pattern in patterns:
        assert pattern in ("^(data/timeseries_v15/.*|docs/generated/inventory.generated.md)$",
                           "^(data/timeseries_v15/prereg/.*|docs/generated/inventory.generated.md)$"), pattern


def test_w6_registered_in_pages_verify_and_ops_alert() -> None:
    pages = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    verify = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    ops = (ROOT / ".github/workflows/ops-failure-alert.yml").read_text(encoding="utf-8")
    assert f'"{NAME}"' in pages, "pages.yml workflow_run 목록"
    assert f'"{NAME}"' in verify, "verify.yml workflow_run 목록"
    assert re.search(rf"^\s*-\s*{NAME}\b", ops, flags=re.MULTILINE), "ops-failure-alert 감시 목록"


def test_w7_new_file_names_avoid_protected_globs() -> None:
    for relative in NEW_FILES:
        assert (ROOT / relative).exists(), relative
        assert not [pattern for pattern in PROTECTED_GLOBS if fnmatchcase(relative, pattern)], relative


def test_w8_verdict_verb_is_never_automated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "timeseries-v15-verdict" not in text
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        assert "timeseries-v15-verdict" not in path.read_text(encoding="utf-8"), path.name


def test_w9_snapshot_worktree_and_data_root() -> None:
    jobs = _workflow()["jobs"]
    for name in ("forecast", "a0-identity"):
        runs = "\n".join(step.get("run", "") for step in jobs[name]["steps"])
        assert 'git worktree add --detach "$RUNNER_TEMP/v8snap"' in runs, name
        assert '--data-root "$RUNNER_TEMP/v8snap"' in runs, name


def test_w10_health_runs_after_commits_and_verify_is_integrity_only() -> None:
    jobs = _workflow()["jobs"]
    assert set(jobs["health"]["needs"]) >= {"collect", "a5-commit", "resolve"}
    assert "always()" in jobs["health"]["if"]
    runs = "\n".join(step.get("run", "") for step in jobs["health"]["steps"])
    assert "timeseries-v15-health --fail-on-identity-streak" in runs
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if "timeseries-v15-verify" in line:
            assert "identity" not in line and "streak" not in line


def test_w11_push_jobs_are_serialized() -> None:
    jobs = _workflow()["jobs"]
    assert "collect" in jobs["a5-commit"]["needs"] and "always()" in jobs["a5-commit"]["if"]
    assert "mde-commit" in jobs["a0-identity-commit"]["needs"] and "always()" in jobs["a0-identity-commit"]["if"]
    assert set(jobs["resolve"]["needs"]) >= {"collect", "a5-commit"}


def test_w12_mde_matrix_and_snapshot_sha() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["mde"]["strategy"]["matrix"]["arm"] == ["A0", "A1", "A2", "A3", "A4", "A5"]
    steps = jobs["mde"]["steps"]
    runs = "\n".join(step.get("run", "") for step in steps)
    # 기록 SHA = 실제 체크아웃 HEAD — 6팔 모두 디스패치 커밋(github.sha)을 체크아웃한다(ref: main 금지:
    # 디스패치와 체크아웃 사이 봇 커밋이 들어오면 기록 SHA 와 사용 데이터가 갈리고 팔끼리 커밋이 달라진다)
    checkouts = [step for step in steps if str(step.get("uses", "")).startswith("actions/checkout")]
    assert len(checkouts) == 1 and checkouts[0]["with"]["ref"] == "${{ github.sha }}"
    assert "timeseries-v15-mde-replay" in runs and '--data-snapshot-sha "$(git rev-parse HEAD)"' in runs
    assert '--data-snapshot-sha "${{ github.sha }}"' not in runs
    replay = next(step for step in steps if "timeseries-v15-mde-replay" in step.get("run", ""))
    assert replay.get("shell") == "bash"
    assert 'test "${{ github.ref }}" = "refs/heads/main"' in runs  # main 이외 디스패치 거부
    assert "A0_LIVE_IDENTITY" not in WORKFLOW.read_text(encoding="utf-8")
