# -*- coding: utf-8 -*-
"""추정 마감 질문을 무인 경로가 예측하지 못하게 한다 (2026-09-14).

실측 계기: `orcl-eps-beat-fq1-2027` 의 마감은 `2026-09-14` 인데 질문 본문이 스스로
"9/8~9/14 **추정**"이라 적었고, 판정기준도 "기한은 발표 예상 상한 — 실제 발표일에
판정"이라고 적었다. 실제 발표는 **2026-09-10** 이었다. D-3 재예측 세그먼트는
**2026-09-11**(이벤트 다음 날) 에 열렸고 우선순위 함수는 이 질문을 1순위로 올렸다.
`forecast --due --max 3 --yes` 가 그대로 돌았다면 **이미 발표된 실적을 예측하는 회차**가
표본에 들어갔다 — 원칙 5(백테스트 절대 금지) 위반이고 예측 파일은 불변이라 되돌릴 수 없다.

기존 가드(`_assert_official_forecast_open`)는 `오늘 > 마감` 일 때만 막는다. 마감이
확정일이면 충분하지만 추정일이면 실제 이벤트가 먼저 올 수 있어 구멍이 난다.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from ai_fc.models import Question
from ai_fc.registry import (ESTIMATED_DEADLINE_WINDOW_DAYS, estimated_deadline_block,
                            load_registry)

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 9, 14)


def _q(*, deadline: date | None = date(2026, 10, 28), kind: str = "fixed",
       estimated: bool = True) -> Question:
    return Question(
        question_id="q", title="t", question="q?", deadline_kind=kind, deadline=deadline,
        rolling_days=90 if kind == "rolling" else None, resolution="r",
        resolution_source="s", domain="earnings", cadence_raw="r1 + D-3", schedule=[],
        action_link="", status="active", created=date(2026, 7, 20), notes="",
        required_snapshots=[], src_hash="h", deadline_estimated=estimated,
    )


def test_a_confirmed_deadline_is_never_blocked() -> None:
    """확정 마감은 D-0 이어도 무인 경로가 돈다 — 그것이 가장 값진 회차다."""
    assert estimated_deadline_block(_q(deadline=TODAY, estimated=False), TODAY) is None


def test_outside_the_window_an_estimated_deadline_passes() -> None:
    far = date.fromordinal(TODAY.toordinal() + ESTIMATED_DEADLINE_WINDOW_DAYS + 1)
    assert estimated_deadline_block(_q(deadline=far), TODAY) is None


@pytest.mark.parametrize("offset", [ESTIMATED_DEADLINE_WINDOW_DAYS, 3, 0, -1, -4])
def test_inside_the_window_an_estimated_deadline_is_blocked(offset: int) -> None:
    """orcl 은 D-4(실제 발표가 마감보다 4일 빨랐다) 지점에서 걸렸어야 했다."""
    deadline = date.fromordinal(TODAY.toordinal() + offset)
    reason = estimated_deadline_block(_q(deadline=deadline), TODAY)
    assert reason is not None and "추정" in reason


@pytest.mark.parametrize("kind,deadline", [("rolling", None), ("tbd", None)])
def test_only_fixed_deadlines_are_judged(kind: str, deadline: date | None) -> None:
    """rolling·tbd 에는 '이벤트가 먼저 온다'는 개념이 없다."""
    assert estimated_deadline_block(_q(kind=kind, deadline=deadline), TODAY) is None


# ── 레지스트리 회귀 ────────────────────────────────────────────────

def test_every_estimated_announcement_date_carries_the_flag() -> None:
    """발표일이 추정이라고 **본문이 말하는** 실적 질문은 전부 플래그를 달아야 한다.

    이 테스트가 없으면 다음 사람이 "(장후 추정)" 질문을 하나 더 등록하는 순간
    같은 구멍이 조용히 다시 열린다. 첫 괄호만 본다 — 뒤쪽 괄호의 '추정'은
    발표일이 아니라 방법론(예: 'advance estimate')을 가리키는 경우가 있다.
    """
    missing = []
    for q in load_registry(ROOT / "questions" / "registry.yaml"):
        if q.status != "active" or q.domain != "earnings":
            continue
        first = re.search(r"\(([^)]*)\)", q.question or "")
        if not first:
            continue
        if re.search(r"추정|예상", first.group(1)) and not q.deadline_estimated:
            missing.append(f"{q.question_id}: ({first.group(1)})")
    assert not missing, f"추정 발표일인데 deadline_estimated 미표기: {missing}"


def test_the_flag_is_not_sprayed_on_confirmed_dates() -> None:
    """반대 방향 — 근거 없이 달면 무인 경로가 쓸데없이 멈춘다."""
    flagged = [q.question_id for q in load_registry(ROOT / "questions" / "registry.yaml")
               if q.deadline_estimated]
    assert 1 <= len(flagged) <= 15, flagged
    assert "nvda-rev-miss-fq3-2027" not in flagged  # 마감 확정(2026-11-25)


def test_the_flag_is_not_part_of_the_judgement_hash(tmp_path: Path) -> None:
    """판정기준이 아니라 '그 날짜를 믿어도 되는가' 메타다 — src_hash 를 흔들면 안 된다.

    흔들면 "첫 예측 이후 판정기준 변경 금지" 검사가 **플래그를 단 것만으로** 위반을
    보고한다. 같은 질문에 플래그만 붙였다 뗐다 하며 해시가 같은지 직접 본다.
    """
    common = [
        "questions:",
        "  - id: probe",
        "    title: t",
        "    question: Q?",
        "    deadline: 2026-10-28",
    ]
    tail = [
        "    resolution: R",
        "    resolution_source: S",
        "    domain: earnings",
        "    cadence: r1 + D-3",
        "    status: active",
        "",
    ]
    newline = chr(10)
    plain = tmp_path / "plain.yaml"
    flagged = tmp_path / "flagged.yaml"
    plain.write_text(newline.join(common + tail), encoding="utf-8")
    flagged.write_text(
        newline.join(common + ["    deadline_estimated: true"] + tail), encoding="utf-8")

    before = load_registry(plain)[0]
    after = load_registry(flagged)[0]
    assert before.deadline_estimated is False and after.deadline_estimated is True
    assert before.src_hash == after.src_hash

