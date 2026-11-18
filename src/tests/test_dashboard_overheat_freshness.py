"""Overheat indicator rows carry no freshness/provisional copy on screen.

2026-11-12 사용자 지시로 통계 기간·원천 확인 줄을 14개 행에서 뺐고, 2026-11-18 사용자 지시("굳이 유저가 볼 필요없는
설명 다 빼")로 IPO 행의 잠정 참고(…확정치와 정의가 달라 지수에 미반영)·주석(확정 원본은 약 연 1회 개정…)도 뺐다.
그 문구만 만들던 overheatIndicatorFreshness 도우미는 지웠다. 원천 갱신 상태는 statistics-freshness 점검과
overheat-watchdog 이 본다(화면 밖). 이 파일은 그 문구가 다시 들어오지 않게 막는다.
"""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "ai_fc/dashboard_parts/dashboard.js"


def test_freshness_helper_is_gone() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "function overheatIndicatorFreshness(" not in source
    assert "overheatIndicatorFreshness(" not in source


def test_indicator_rows_carry_no_period_check_or_provisional_copy() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    panel = source[source.index("function statisticsOverheatPanel("):
                   source.index("function predictionSectionNav(")]
    for removed in ("${esc(info.period)}", "${esc(info.check)}", "${esc(info.provisional)}", "${esc(info.note)}",
                    "info.provisional||info.note?", "oh-freshness", "data-oh-freshness"):
        assert removed not in panel, removed
    assert "data-oh-jump" in panel  # 행은 그대로 해당 통계 카드로 이동하는 단추다
    for removed in ("잠정 참고", "지수에 미반영", "확정 원본은 약 연 1회 개정"):
        assert removed not in source, removed
