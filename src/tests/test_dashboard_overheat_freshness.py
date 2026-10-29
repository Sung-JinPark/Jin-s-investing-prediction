"""Overheat rows must explain observation periods and independently checked source health."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "ai_fc/dashboard_parts/dashboard.js"


def _labels(tmp_path: Path, rows: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    source = SCRIPT.read_text(encoding="utf-8")
    timestamp = source[source.index("function formatKstTimestamp("):
                       source.index("function freshnessInfo(")]
    helper = source[source.index("function overheatIndicatorFreshness("):
                    source.index("function statisticsOverheatPanel(")]
    program = tmp_path / "freshness.js"
    program.write_text(timestamp + helper + "\nprocess.stdout.write(JSON.stringify("
                       + json.dumps(rows, ensure_ascii=False)
                       + ".map(overheatIndicatorFreshness)));", encoding="utf-8")
    result = subprocess.run([node, str(program)], capture_output=True, text=True,
                            encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_quarter_and_source_check_are_distinct_and_timezone_explicit(tmp_path: Path) -> None:
    result = _labels(tmp_path, [{"id": "investment_share_gdp", "current_date": "2026-04-01",
                               "freshness": {"period_label": "2026년 2분기",
                                             "latest_observation": "2026-04-01",
                                             "source_observation_through": "2026-04-01",
                                             "last_successful_check": "2026-10-28T12:57:05Z",
                                             "status": "current"}}])[0]
    assert result["period"] == "통계 기간 2026년 2분기"
    assert result["check"] == "원천 확인 2026-10-28 21:57 KST · 정상 확인"


def test_weekly_source_endpoint_remains_visible_for_a_monthly_average(tmp_path: Path) -> None:
    result = _labels(tmp_path, [{"id": "financial_conditions", "freshness": {
        "period_label": "2026-10 월평균", "latest_observation": "2026-10-01",
        "source_observation_through": "2026-10-23", "status": "current",
    }}])[0]
    assert result["period"] == "통계 기간 2026-10 월평균 · 원자료 2026-10-23까지"
    assert "시각 미상" in result["check"]


@pytest.mark.parametrize("indicator_id", ["nasdaq_per_household_liquid_assets", "spx_per_federal_debt"])
def test_quarter_end_ratio_explains_june_without_labeling_its_balance_as_april_data(tmp_path: Path, indicator_id: str) -> None:
    result = _labels(tmp_path, [{"id": indicator_id, "freshness": {
        "period_label": "2026년 2분기", "latest_observation": "2026-06-01",
        "source_observation_through": "2026-04-01", "status": "current",
        "sources": [{"frequency": "daily"}, {"frequency": "quarterly"}],
    }}])[0]
    assert result["period"] == "통계 기간 2026년 2분기 · 분기말 월 2026-06"
    assert "2026-04" not in result["period"]


def test_quarterly_source_in_an_earlier_quarter_remains_visible(tmp_path: Path) -> None:
    result = _labels(tmp_path, [{"id": "spx_per_federal_debt", "freshness": {
        "period_label": "2026년 2분기", "latest_observation": "2026-06-01",
        "source_observation_through": "2026-01-01", "status": "observation_overdue",
        "sources": [{"frequency": "monthly"}, {"frequency": "quarterly"}],
    }}])[0]
    assert result["period"] == "통계 기간 2026년 2분기 · 원자료 2026-01-01까지"


def test_ipo_confirmed_period_and_provisional_definition_are_explicit(tmp_path: Path) -> None:
    result = _labels(tmp_path, [{"id": "ipo_count_operating_12m", "freshness": {
        "period_label": "2025-12 최근 12개월", "status": "source_waiting",
        "last_successful_check": "2026-10-29T00:00:00Z", "provisional_through": "2026-09-01",
        "provisional_value": 218,
    }}])[0]
    assert result["period"] == "확정 통계 기간 2025-12 최근 12개월"
    assert "원천 응답 대기" in result["check"]
    assert "2026-09 최근 12개월 218건" in result["provisional"]
    assert "확정치와 정의가 달라 지수에 미반영" in result["provisional"]


def test_missing_check_metadata_never_claims_a_successful_refresh(tmp_path: Path) -> None:
    result = _labels(tmp_path, [{"id": "legacy", "current_date": "2026-09-01"},
                               {"freshness": {"status": "check_overdue"}}])
    assert result[0]["status"] == "unverified"
    assert result[0]["check"] == "원천 확인 시각 미상 · 확인 정보 없음"
    assert "원천 재확인 필요" in result[1]["check"]


def test_check_and_provisional_information_are_visible_inside_each_indicator_row() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    panel = source[source.index("function statisticsOverheatPanel("):
                   source.index("function predictionSectionNav(")]
    assert "overheatIndicatorFreshness(r)" in panel
    assert "${esc(info.period)}" in panel
    assert "${esc(info.check)}" in panel
    assert "${esc(info.provisional)}" in panel
