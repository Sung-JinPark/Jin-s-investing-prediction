# -*- coding: utf-8 -*-
"""월 예산 규칙 (2026-11-16 — 상한 $15, 주 1건 체제).

여기서 지키려는 것은 금액 하나가 아니라 **규칙들이 서로 모순되지 않는다**는 성질이다.
상한을 올릴 때마다 케이던스·예비 구간·회차당 상한이 따로 놀아서, 상한은 $40 인데
문서는 $20 이라고 적혀 있고 자동 경로는 $25 를 자기 상한으로 들고 있는 상태가 됐었다.
"""

from __future__ import annotations

from datetime import date
import sqlite3

import pytest

from ai_fc import config
from ai_fc.db import queries
from ai_fc.models import Question
from ai_fc.orchestrator import budget_headroom_block_reason, reserve_zone_block_reason


# 2026-09-11 실측 (cost_log, anthropic cli/api 표준 회차 n=5):
# asml r2 $2.42 · cpi-sep2026 $2.31 · nfp-sep2026 $2.11 · nvda-miss $1.92 · nvda-surprise $2.75
MEASURED_UNIT_COST = 2.303
MEASURED_UNIT_COST_MAX = 2.75
ROUNDS_PER_MONTH = config.WEEKLY_FORECAST_CADENCE * 13 / 3  # 주 N건 -> 월 회차 (4.33주)


def _q(question_id: str = "q", *, kind: str = "fixed",
       deadline: date | None = date(2026, 10, 1)) -> Question:
    return Question(
        question_id=question_id, title="t", question="q?", deadline_kind=kind,
        deadline=deadline, rolling_days=90 if kind == "rolling" else None,
        resolution="r", resolution_source="s", domain="macro", cadence_raw="manual",
        schedule=[], action_link="", status="active", created=date(2026, 9, 1),
        notes="", required_snapshots=[], src_hash="h",
    )


# ── 금액 ──────────────────────────────────────────────────────────

def test_monthly_cap_is_the_user_set_fifteen() -> None:
    assert config.MONTHLY_BUDGET == 15.00


def test_the_only_gate_producer_is_not_capped_below_the_global_cap() -> None:
    """생산자가 하나뿐일 때 그 하나에 더 낮은 캡을 걸면 전역 상한이 거짓말이 된다.

    남는 금액을 쓸 수 있는 주체가 없어서, 사용자가 정한 $15가 사실상 그 sub-cap 으로
    내려앉는다. 생산을 조이는 것은 캡이 아니라 예비 구간 규칙과 케이던스다.
    """
    assert config.ANTHROPIC_MONTHLY_BUDGET == config.MONTHLY_BUDGET


def test_the_retired_openai_path_keeps_a_manual_diagnostic_cap() -> None:
    """예약 smoke 는 제거했지만 명시적 수동 진단에는 별도 방어선이 남는다."""
    assert config.OPENAI_MONTHLY_BUDGET == 2.00
    assert config.OPENAI_MONTHLY_BUDGET < config.MONTHLY_BUDGET


def test_pipeline_cap_clears_the_measured_worst_round() -> None:
    """회차당 상한이 실측 상단보다 낮으면 회차가 중간에 죽는다 — 돈은 쓰고 기록은 없다."""
    assert config.DEFAULT_PIPELINE_BUDGET > MEASURED_UNIT_COST_MAX


# ── 케이던스와 예비 구간이 서로 모순되지 않는가 ──────────────────

def test_the_normal_cadence_never_reaches_the_reserve_zone() -> None:
    """정상 케이던스가 예비 구간을 건드리면 그 구간은 예비가 아니라 상시 상태다."""
    floor = config.MONTHLY_BUDGET * (1 - config.MONTHLY_BUDGET_RESERVE_RATIO)
    assert ROUNDS_PER_MONTH * MEASURED_UNIT_COST < floor


def test_the_reserve_zone_spans_the_measured_worst_round() -> None:
    """마지막 20%가 실측 최악 회차보다 작아지지는 않는다."""
    reserve = config.MONTHLY_BUDGET * config.MONTHLY_BUDGET_RESERVE_RATIO
    assert reserve >= MEASURED_UNIT_COST_MAX


def test_full_round_headroom_is_required_before_paid_work() -> None:
    assert budget_headroom_block_reason(11.00, 15.00, 4.00, "전체") is None
    reason = budget_headroom_block_reason(11.01, 15.00, 4.00, "전체")
    assert reason is not None
    assert "남은 $3.99" in reason and "필요 $4.00" in reason


def test_spend_at_or_above_the_cap_is_blocked() -> None:
    assert "월 예산 초과" in budget_headroom_block_reason(15.00, 15.00, 4.00, "전체")


def test_failed_cost_rows_count_toward_the_same_monthly_cap() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE cost_log (ts TEXT, stage TEXT, cost_usd REAL, provider TEXT)")
    conn.executemany(
        "INSERT INTO cost_log VALUES (?,?,?,?)",
        [
            ("2026-11-01T10:00:00+09:00", "inference", 7.60, "anthropic"),
            ("2026-11-02T10:00:00+09:00", "failed", 3.50, "anthropic"),
            ("2026-11-03T10:00:00+09:00", "smoke", 0.50, "openai"),
        ],
    )
    spent = queries.month_cost(conn, 2026, 11, "anthropic")
    assert spent == pytest.approx(11.10)
    assert budget_headroom_block_reason(spent, 15.00, 4.00, "Anthropic") is not None


# ── 예비 구간 가드 ────────────────────────────────────────────────

def test_below_the_floor_nothing_is_blocked() -> None:
    assert reserve_zone_block_reason(0.0, _q(), date(2026, 9, 11)) is None
    below = config.MONTHLY_BUDGET * (1 - config.MONTHLY_BUDGET_RESERVE_RATIO) - 0.01
    assert reserve_zone_block_reason(below, _q(deadline=date(2027, 6, 1)),
                                     date(2026, 9, 11)) is None


def test_in_the_reserve_zone_an_imminent_deadline_passes() -> None:
    floor = config.MONTHLY_BUDGET * (1 - config.MONTHLY_BUDGET_RESERVE_RATIO)
    today = date(2026, 9, 11)
    edge = today.toordinal() + config.RESERVE_DEADLINE_DAYS
    assert reserve_zone_block_reason(floor, _q(deadline=date.fromordinal(edge)),
                                     today) is None


def test_in_the_reserve_zone_a_distant_deadline_is_blocked() -> None:
    floor = config.MONTHLY_BUDGET * (1 - config.MONTHLY_BUDGET_RESERVE_RATIO)
    today = date(2026, 9, 11)
    one_day_late = date.fromordinal(today.toordinal() + config.RESERVE_DEADLINE_DAYS + 1)
    reason = reserve_zone_block_reason(floor, _q("far", deadline=one_day_late), today)
    assert reason is not None
    assert "far" in reason and "예비 구간" in reason


@pytest.mark.parametrize("kind,deadline", [("rolling", None), ("tbd", None),
                                           ("fixed", None)])
def test_a_question_without_a_fixed_deadline_fails_closed(kind: str,
                                                          deadline: date | None) -> None:
    """임박한지 판정할 수 없으면 통과가 아니라 차단이다."""
    floor = config.MONTHLY_BUDGET * (1 - config.MONTHLY_BUDGET_RESERVE_RATIO)
    reason = reserve_zone_block_reason(floor, _q("x", kind=kind, deadline=deadline),
                                       date(2026, 9, 11))
    assert reason is not None


def test_the_guard_scales_with_the_cap_not_with_a_hardcoded_number() -> None:
    """상한을 다시 올릴 때 예비 구간이 따라오지 않으면 규칙이 또 갈라진다."""
    original = config.MONTHLY_BUDGET
    try:
        config.MONTHLY_BUDGET = 100.0
        today = date(2026, 9, 11)
        far = _q("far", deadline=date(2027, 6, 1))
        assert reserve_zone_block_reason(79.0, far, today) is None   # 80 미만
        assert reserve_zone_block_reason(80.0, far, today) is not None
    finally:
        config.MONTHLY_BUDGET = original
