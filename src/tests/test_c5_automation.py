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
    assert "prioritize_forecast_targets(" in source
    assert ".sort(key=" not in source.split("def cmd_forecast")[1].split("def ")[0], \
        "정렬을 CLI 에 다시 인라인하지 말 것 — registry 의 순수 함수를 쓴다"


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
    assert "--max 3" in text      # C5-A3 2026-09-09: 1 -> 3 (신규 26문항 소화)
    assert 'AI_FC_MONTHLY_BUDGET: "25.00"' in text


# ── 마감 임박 우선 (2026-09-09 추가) ───────────────────────────────

def test_nearest_deadline_first_among_never_forecast() -> None:
    """미예측 묶음 안에서는 마감이 가까운 질문이 먼저다.

    실측 계기: Q3 신규 20문항 등록 직후 due 큐가 사실상 등록 순이라,
    마감 2일 남은 질문이 마감 6개월 남은 질문보다 뒤에 있었다.
    """
    from datetime import date
    due = [
        _item("far", last=None),
        _item("near", last=None),
        _item("mid", last=None),
    ]
    deadlines = {"far": date(2027, 3, 31), "near": date(2026, 9, 11),
                 "mid": date(2026, 10, 14)}
    assert [d.question_id for d in prioritize_forecast_targets(due, deadlines)] == [
        "near", "mid", "far"]


def test_urgent_reforecast_beats_distant_never_forecast() -> None:
    """마감 임박 재예측이 먼 미예측보다 앞선다 (2026-09-09 규칙 개정).

    **이 테스트는 이전 규칙을 의도적으로 뒤집은 것이다.** 원래는 "미예측이 항상 먼저"
    였는데(게이트 문항 수는 DISTINCT 라 재예측 기여가 0), 실측이 그 규칙의 대가를
    보여줬다: 재예측은 이 시스템에서 **유일하게 측정된 양(+) 지렛대**이고
    (다회차 13문항 첫→최신 p(1-p) −0.0209), "미예측 우선"만 적용하면 미예측 19건을
    주 3건으로 소진하는 7주 사이에 마감되는 질문의 D-3 sharpening 회차가 영구히
    사라진다(개정 시점 실측 4건). 마감 임박은 회차와 무관하게 '지금 아니면 없다'다.
    """
    from datetime import date
    due = [
        _item("reforecast-urgent", last=datetime(2026, 9, 1)),
        _item("new-far", last=None),
    ]
    deadlines = {"reforecast-urgent": date(2026, 9, 10),
                 "new-far": date(2027, 6, 30)}
    order = prioritize_forecast_targets(due, deadlines, today=date(2026, 9, 9))
    assert [d.question_id for d in order] == ["reforecast-urgent", "new-far"]


def test_never_forecast_still_wins_when_neither_is_urgent() -> None:
    """긴급이 아니면 옛 규칙이 그대로 산다 — 미예측이 재예측보다 먼저."""
    from datetime import date
    due = [
        _item("reforecast-soon", last=datetime(2026, 9, 1)),
        _item("new-later", last=None),
    ]
    deadlines = {"reforecast-soon": date(2026, 10, 1),      # 긴급 창(7일) 밖
                 "new-later": date(2027, 6, 30)}
    order = prioritize_forecast_targets(due, deadlines, today=date(2026, 9, 9))
    assert [d.question_id for d in order] == ["new-later", "reforecast-soon"]


def test_urgent_bucket_is_ordered_by_deadline_regardless_of_round() -> None:
    """긴급 묶음 안에서는 회차를 보지 않고 마감 순으로만 정렬한다."""
    from datetime import date
    due = [
        _item("u-new-later", last=None),
        _item("u-reforecast-first", last=datetime(2026, 9, 1)),
    ]
    deadlines = {"u-new-later": date(2026, 9, 14),
                 "u-reforecast-first": date(2026, 9, 11)}
    order = prioritize_forecast_targets(due, deadlines, today=date(2026, 9, 9))
    assert [d.question_id for d in order] == ["u-reforecast-first", "u-new-later"]


def test_urgent_window_boundary_is_inclusive() -> None:
    """마감이 정확히 today+7 이면 긴급, +8 이면 아니다."""
    from datetime import date, timedelta
    from ai_fc.registry import URGENT_WINDOW_DAYS
    assert URGENT_WINDOW_DAYS == 7
    today = date(2026, 9, 9)
    due = [_item("edge", last=datetime(2026, 9, 1)), _item("newq", last=None)]
    inside = {"edge": today + timedelta(days=7), "newq": date(2027, 1, 1)}
    outside = {"edge": today + timedelta(days=8), "newq": date(2027, 1, 1)}
    assert [d.question_id for d in prioritize_forecast_targets(due, inside, today)][0] == "edge"
    assert [d.question_id for d in prioritize_forecast_targets(due, outside, today)][0] == "newq"


def test_missing_or_rolling_deadline_sorts_last() -> None:
    """rolling·미정 마감은 '마감 없음'으로 보아 긴급이 아니고 뒤로 간다."""
    from datetime import date
    due = [_item("rolling", last=None), _item("dated", last=None)]
    order = prioritize_forecast_targets(due, {"dated": date(2026, 12, 1)},
                                        today=date(2026, 9, 9))
    assert [d.question_id for d in order] == ["dated", "rolling"]


def test_deadlines_argument_is_optional() -> None:
    """인자를 안 주면 미예측 우선만 적용되고 죽지 않는다 (마감 정보 없음 = 비긴급)."""
    due = [_item("a", last=datetime(2026, 9, 1)), _item("b", last=None)]
    assert [d.question_id for d in prioritize_forecast_targets(due)] == ["b", "a"]


def test_cli_passes_deadlines_and_today_to_prioritizer() -> None:
    """CLI 가 마감일과 기준일을 모두 넘겨야 긴급 창이 작동한다."""
    source = (ROOT / "src" / "ai_fc" / "cli.py").read_text(encoding="utf-8")
    block = source.split("def cmd_forecast")[1].split("@app.command")[0]
    assert "prioritize_forecast_targets(" in block
    assert "deadlines" in block and "datetime.now().date()" in block


# ── 등록필터 위반 질문의 배치 격리 (2026-09-10) ────────────────────

def test_due_batch_skips_filter_violations_instead_of_dying() -> None:
    """등록필터 위반 질문은 **건너뛰고 배치를 계속**해야 한다.

    실측 계기: 2026-08-31 에 '등록필터:' 근거 없이 등록된 질문 5건 때문에
    run_forecast 의 PreflightError 가 배치 전체를 죽여 주간 자동화가
    2026-09-05 부터 매주 실패했다(그 사이 자동 예측 0건). 한 질문의 등록 하자가
    나머지 준수 질문까지 막는 것은 과잉 차단이다.
    """
    source = (ROOT / "src" / "ai_fc" / "cli.py").read_text(encoding="utf-8")
    block = source.split("def cmd_forecast")[1].split("@app.command")[0]
    assert "factory_filter_violation" in block, "배치가 등록필터 위반을 걸러내지 않는다"
    assert "건너뜀" in block, "건너뛴 질문을 사용자에게 알리지 않는다"


def test_named_forecast_still_hard_fails_on_violation() -> None:
    """명시적으로 지목한 실행은 여전히 하드 에러 — 조용히 건너뛰면 안 된다."""
    orch = (ROOT / "src" / "ai_fc" / "orchestrator.py").read_text(encoding="utf-8")
    assert 'PreflightError(f"등록필터 위반' in orch,         "orchestrator 의 하드 게이트를 없애면 안 된다 (배치만 완화한다)"


def test_repo_has_no_unjustified_active_questions_in_the_top_queue() -> None:
    """실제 레지스트리 회귀 — 위반 질문이 있어도 배치 대상은 남아야 한다."""
    import sqlite3
    from datetime import datetime as _dt
    from ai_fc import config
    from ai_fc.registry import (compute_due, factory_filter_violation, load_registry,
                                prioritize_forecast_targets)
    from ai_fc.db import queries
    if not config.DB_PATH.exists():
        import pytest
        pytest.skip("파생 인덱스 미빌드")
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    qs = load_registry(config.ROOT / "questions" / "registry.yaml")
    due = compute_due(qs, queries.latest_forecasts(conn), queries.open_rolling_windows(conn),
                      queries.resolved_forecast_ids(conn), _dt.now())
    by_id = {q.question_id: q for q in qs}
    ordered = prioritize_forecast_targets(
        due, {q.question_id: q.deadline for q in qs}, _dt.now().date())
    survivors = [d.question_id for d in ordered
                 if not factory_filter_violation(by_id[d.question_id])]
    assert survivors, "등록필터 위반을 걸러내고 나면 배치 대상이 하나도 없다"
