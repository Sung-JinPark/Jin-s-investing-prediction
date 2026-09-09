"""C5 Q4 자동화 테스트 (설계도 §7.2, 사용자 승인 C5-A3 2026-09-09).

고정하는 두 가지:
1. 자동 경로는 **첫 예측 미실행 질문을 먼저** 집는다 — 재예측은 게이트 문항 수에 0 기여.
2. 자동 경로는 **판정을 확정하지 않는다** — 초안까지만. 원장은 되돌릴 수 없다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ai_fc.models import DueItem
from ai_fc.registry import prioritize_forecast_targets

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "c5-resolve-draft.yml"


def _item(qid: str, kind: str = "forecast", last: datetime | None = None) -> DueItem:
    return DueItem(qid, kind, "reason", last)


# ── 1. 신규 질문 우선 ──────────────────────────────────────────────

def test_never_forecast_questions_come_first() -> None:
    due = [
        _item("old-a", last=datetime(2026, 9, 1)),
        _item("new-a", last=None),
        _item("old-b", last=datetime(2026, 9, 2)),
        _item("new-b", last=None),
    ]
    assert [d.question_id for d in prioritize_forecast_targets(due)] == [
        "new-a", "new-b", "old-a", "old-b"]


def test_ordering_is_stable_within_each_class() -> None:
    """같은 부류 안에서는 compute_due 의 순서를 흐트러뜨리지 않는다."""
    due = [_item(f"q{i}", last=datetime(2026, 9, 1)) for i in range(5)]
    assert [d.question_id for d in prioritize_forecast_targets(due)] == [
        f"q{i}" for i in range(5)]


def test_non_forecast_kinds_are_dropped() -> None:
    """resolve 는 사람 확정 경로, divergence 는 표시 전용 — 자동 실행 대상이 아니다."""
    due = [
        _item("r", kind="resolve"),
        _item("d", kind="divergence"),
        _item("m", kind="manual-review"),
        _item("s", kind="stale"),
        _item("f", kind="forecast", last=None),
    ]
    assert [d.question_id for d in prioritize_forecast_targets(due)] == ["f"]


def test_empty_input_is_empty_output() -> None:
    assert prioritize_forecast_targets([]) == []


def test_cli_uses_the_shared_prioritizer() -> None:
    """정렬 규칙이 CLI 에 다시 인라인되면 이 테스트가 먼저 깨진다."""
    source = (ROOT / "src" / "ai_fc" / "cli.py").read_text(encoding="utf-8")
    assert "prioritize_forecast_targets(due)" in source


# ── 2. 판정 확정 자동화 금지 ───────────────────────────────────────

def test_draft_workflow_exists() -> None:
    assert WORKFLOW.exists(), "c5-resolve-draft.yml 부재 — Q4 미종료"


def test_draft_workflow_never_confirms_a_verdict() -> None:
    """--draft 만 쓴다. --outcome 로 확정하거나 커밋하면 원장이 되돌릴 수 없게 오염된다."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "resolve --draft" in text
    # 어떤 실행 줄도 resolve 를 --outcome 과 함께 부르지 않아야 한다.
    # (사람에게 보여주는 안내문 안의 --outcome 은 echo 이므로 실행이 아니다.)
    for line in text.splitlines():
        if "ai_fc resolve" in line and not line.lstrip().startswith("echo"):
            assert "--outcome" not in line, f"자동 확정 경로: {line.strip()}"
            assert "--yes" not in line, f"자동 확정 경로: {line.strip()}"
    # 저장소를 쓰지 않는다
    for forbidden in ("git commit", "git push"):
        assert forbidden not in text, f"자동 경로 금지 동작: {forbidden}"


def test_draft_workflow_needs_no_secrets() -> None:
    """결정론 검사뿐 — 시크릿도 LLM 호출도 없다."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text
    assert "OPENAI" not in text and "ANTHROPIC" not in text


def test_draft_workflow_is_read_only_on_contents() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: read" in text


def test_investing_refresh_still_caps_paid_work() -> None:
    """자동 예측 경로의 상한이 사라지지 않았는지 (C5-A2 인상 후에도 상한은 유지)."""
    text = (ROOT / ".github" / "workflows" / "investing-refresh.yml").read_text(
        encoding="utf-8")
    assert "--max 1" in text
    assert 'AI_FC_MONTHLY_BUDGET: "25.00"' in text
