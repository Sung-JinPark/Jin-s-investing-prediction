"""U2a NYSE 휴장 계약 제자리 정정(revision 2) — XNAS 대조·저장 산출물 재생 동일·규칙 범위.

정정: 2025-01-09 일회성 휴장 추가, 신정 토요일 규칙(NYSE Rule 7.2 — 12/31 은 연 회계기간 말이라 개장).
저장소 파일은 읽기만 한다. 마감 2026-12-29(시나리오 asof 2026-12-30 지평에 2027-12-31 이 처음 들어간다).
"""

from __future__ import annotations

import glob
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from ai_fc.market_session import is_trading_day
from ai_fc.scenario import _holiday_for_rule, future_trading_days, load_calendar_contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data/contracts/nyse_holidays.yaml"
RESIDUAL_PRE_2025 = {"2004-06-11", "2007-01-02", "2012-10-29", "2012-10-30", "2018-12-05"}


def _xnas_sessions(start: date, end: date) -> set[str]:
    xcals = pytest.importorskip("exchange_calendars")
    # 달력 범위를 앞뒤로 넓혀 둔다 — 구간 첫날이 휴장일이면 sessions_in_range 가 범위 밖 오류를 낸다.
    calendar = xcals.get_calendar("XNAS", start=(start - timedelta(days=10)).isoformat(),
                                  end=(end + timedelta(days=10)).isoformat())
    return {label.date().isoformat() for label in calendar.sessions_in_range(start.isoformat(), end.isoformat())}


def _mismatches(start: date, end: date) -> set[str]:
    xnas = _xnas_sessions(start, end)
    out: set[str] = set()
    cursor = start
    while cursor <= end:
        ours = is_trading_day(cursor, root=ROOT)
        if ours != (cursor.isoformat() in xnas):
            out.add(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def test_xnas_agreement_from_2025_through_2028():
    assert _mismatches(date(2025, 1, 1), date(2028, 12, 28)) == set()


def test_pre_2025_residual_is_exactly_the_disclosed_one_off_closures():
    assert _mismatches(date(2004, 1, 2), date(2024, 12, 31)) == RESIDUAL_PRE_2025


def test_saturday_rules_keep_their_observance():
    calendar = load_calendar_contract(ROOT)
    assert not is_trading_day(date(2027, 12, 24), root=ROOT)  # 크리스마스 토요일 → 금요일 휴장
    assert not is_trading_day(date(2023, 1, 2), root=ROOT)    # 신정 일요일 → 월요일 휴장
    assert is_trading_day(date(2027, 12, 31), root=ROOT)      # 신정 토요일 → 12/31 개장(Rule 7.2)
    assert is_trading_day(date(2021, 12, 31), root=ROOT)
    assert not is_trading_day(date(2025, 1, 9), root=ROOT)    # 일회성 휴장
    new_year = next(rule for rule in calendar["rules"] if rule["id"] == "new_year")
    assert _holiday_for_rule(2028, new_year) is None
    assert _holiday_for_rule(2023, new_year) == date(2023, 1, 2)
    # saturday_observance 가 없는 규칙은 종전 그대로(토요일 → 금요일).
    legacy = {key: value for key, value in new_year.items() if key != "saturday_observance"}
    assert _holiday_for_rule(2028, legacy) == date(2027, 12, 31)


def test_future_labels_from_first_exposure_include_dec_31_2027():
    days = future_trading_days(date(2026, 12, 30), 252, load_calendar_contract(ROOT))
    assert date(2027, 12, 31) in days
    previous = future_trading_days(date(2026, 12, 29), 252, load_calendar_contract(ROOT))
    assert previous[-1] == date(2027, 12, 30), "asof 2026-12-29 지평은 2027-12-31 에 닿지 않는다(마감 근거)"


def _trading_day_lists() -> list[tuple[str, str, list[str]]]:
    found: list[tuple[str, str, list[str]]] = []

    def walk(node, path: str, name: str) -> None:
        if isinstance(node, dict):
            days = node.get("trading_days")
            if isinstance(days, list) and node.get("asof"):
                found.append((name, str(node["asof"]), days))
            for key, value in node.items():
                walk(value, f"{path}/{key}", name)
        elif isinstance(node, list):
            for value in node:
                walk(value, path, name)

    for name in sorted(glob.glob(str(ROOT / "data/scenarios/**/*.json"), recursive=True)):
        try:
            payload = json.loads(Path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        walk(payload, "", name)
    return found


def test_retained_scenario_artifacts_replay_identically():
    """저장 산출물의 trading_days 목록(2026-11-11 실측 74개, 지평 2026-08-04~2027-11-11)이 정정 달력으로 재생 동일."""
    calendar = load_calendar_contract(ROOT)
    lists = _trading_day_lists()
    assert len(lists) >= 74
    for name, asof, days in lists:
        expected = [day.isoformat() for day in future_trading_days(date.fromisoformat(asof[:10]), len(days), calendar)]
        assert expected == days, (name, asof)


def test_contract_metadata_is_revised_in_place():
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert payload["version"] == 1 and payload["registered_at"] == date(2026, 8, 3)
    assert "revised_at" in payload
    assert payload["one_off_closures"] == ["2025-01-09"]
    assert payload["revisions"][-1]["revision"] == 2
    assert payload["scope"] == "future-label-generation-only"


def test_saturday_observance_only_on_new_year():
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    carriers = [rule["id"] for rule in payload["rules"] if "saturday_observance" in rule]
    assert carriers == ["new_year"]
