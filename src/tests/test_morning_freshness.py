# -*- coding: utf-8 -*-
"""아침 8시 최신성 규칙 (2026-10-07 사용자 지시).

KST 08:00 까지 화면의 공포·탐욕 · VIX · NASDAQ 은 마지막 마감 미국 세션을 싣는다.
여기서는 네트워크 없이 고정 시각·고정 응답으로 가드·병합·파서·판정·화면 배선을 묶는다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from ai_fc import market_quotes as mq
from ai_fc import market_session as ms
from ai_fc import vix_surface as vs

ROOT = Path(__file__).resolve().parents[2]
NY = ZoneInfo("America/New_York")
UTC = timezone.utc

# 2026-10-07 실측 응답(필드 축약).
VIX_QUOTE = {"timestamp": "2026-10-06 23:14:52", "data": {
    "symbol": "^VIX", "close": 15.01, "prev_day_close": 15.52, "current_price": 15.01,
    "last_trade_time": "2026-10-06T16:15:01"}}
NASDAQ_INFO = {"data": {
    "symbol": "COMP", "marketStatus": "After-Hours",
    "primaryData": {"lastSalePrice": "27,599.79", "lastTradeTimestamp": "Oct 6, 2026"},
    "keyStats": {"previousclose": {"label": "Previous Close:", "value": "27,477.31"}}}}


def _nasdaq(status: str = "After-Hours", stamp: str = "Oct 6, 2026") -> dict:
    payload = json.loads(json.dumps(NASDAQ_INFO))
    payload["data"]["marketStatus"] = status
    payload["data"]["primaryData"]["lastTradeTimestamp"] = stamp
    return payload


def _vix(stamp: str) -> dict:
    payload = json.loads(json.dumps(VIX_QUOTE))
    payload["data"]["last_trade_time"] = stamp
    return payload


# ── 마감 가드 (EDT · EST) ───────────────────────────────────────────

@pytest.mark.parametrize("now,expected", [
    # EDT: 마감 20:00 UTC, 가드 20:15 UTC
    (datetime(2026, 10, 6, 20, 14, tzinfo=UTC), date(2026, 10, 5)),
    (datetime(2026, 10, 6, 20, 15, tzinfo=UTC), date(2026, 10, 6)),
    (datetime(2026, 10, 6, 23, 9, tzinfo=UTC), date(2026, 10, 6)),
    # EST: 마감 21:00 UTC, 가드 21:15 UTC
    (datetime(2026, 12, 8, 21, 0, tzinfo=UTC), date(2026, 12, 7)),
    (datetime(2026, 12, 8, 21, 15, tzinfo=UTC), date(2026, 12, 8)),
    # 주말 → 금요일, 추수감사절(11/26) 다음 날 아침 → 11/25
    (datetime(2026, 10, 11, 12, 0, tzinfo=UTC), date(2026, 10, 9)),
    (datetime(2026, 11, 27, 12, 0, tzinfo=UTC), date(2026, 11, 25)),
])
def test_expected_latest_session_across_edt_est_and_holidays(now, expected) -> None:
    assert ms.expected_latest_session(now, root=ROOT) == expected


def test_regular_session_open_window() -> None:
    assert ms.is_regular_session_open(datetime(2026, 10, 6, 13, 30, tzinfo=UTC), root=ROOT)
    assert not ms.is_regular_session_open(datetime(2026, 10, 6, 13, 29, tzinfo=UTC), root=ROOT)
    assert ms.is_regular_session_open(datetime(2026, 10, 6, 20, 14, tzinfo=UTC), root=ROOT)
    assert not ms.is_regular_session_open(datetime(2026, 10, 6, 20, 15, tzinfo=UTC), root=ROOT)
    # EST 에는 같은 UTC 시각이 아직 장중이다.
    assert ms.is_regular_session_open(datetime(2026, 12, 8, 20, 30, tzinfo=UTC), root=ROOT)
    # 주말·휴장일
    assert not ms.is_regular_session_open(datetime(2026, 10, 10, 15, 0, tzinfo=UTC), root=ROOT)
    assert not ms.is_regular_session_open(datetime(2026, 11, 26, 16, 0, tzinfo=UTC), root=ROOT)


def test_kst_observation_maps_to_the_previous_us_session() -> None:
    assert ms.session_reflected_by(date(2026, 10, 7), root=ROOT) == date(2026, 10, 6)
    assert ms.session_reflected_by(date(2026, 10, 5), root=ROOT) == date(2026, 10, 2)


def test_target_session_is_today_on_a_trading_day() -> None:
    # KST 02:30 예약 = 13:30 EDT — 오늘 세션을 기다린다.
    assert ms.target_session(datetime(2026, 10, 6, 17, 30, tzinfo=UTC), root=ROOT) == date(2026, 10, 6)
    # 토요일 → 금요일(이미 마감)
    assert ms.target_session(datetime(2026, 10, 10, 17, 30, tzinfo=UTC), root=ROOT) == date(2026, 10, 9)


# ── VIX 지연 시세 병합 ──────────────────────────────────────────────

ROWS = [(date(2026, 10, 2), 16.3), (date(2026, 10, 5), 15.52)]
AFTER = datetime(2026, 10, 6, 23, 9, tzinfo=UTC)


def test_vix_quote_appends_the_closed_session() -> None:
    rows, appended = vs.merge_quote(ROWS, VIX_QUOTE, now=AFTER)
    assert appended and rows[-1] == (date(2026, 10, 6), 15.01)


@pytest.mark.parametrize("stamp,now", [
    ("2026-10-06T14:02:00", datetime(2026, 10, 6, 18, 2, tzinfo=UTC)),   # 장중
    ("2026-10-06T16:15:01", datetime(2026, 10, 6, 20, 10, tzinfo=UTC)),  # 정착 버퍼 전
    ("2026-10-06T21:30:00", datetime(2026, 10, 7, 1, 30, tzinfo=UTC)),   # 야간(GTH) 산출값
    ("2026-10-05T16:15:00", AFTER),                                       # CSV 와 같은 날
])
def test_vix_quote_is_ignored_unless_it_is_a_new_closed_session(stamp, now) -> None:
    rows, appended = vs.merge_quote(ROWS, _vix(stamp), now=now)
    assert not appended and rows == ROWS


def test_vix_refresh_marks_the_quote_row_and_survives_quote_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vs, "fetch_series", lambda **_: list(ROWS))
    projection = vs.refresh(tmp_path, today=date(2026, 10, 7), now=AFTER,
                            quote_fetcher=lambda: VIX_QUOTE)
    assert projection["observed_date"] == "2026-10-06" and projection["level"] == 15.01
    assert projection["latest_source"] == "cboe_delayed_quote"

    def boom():
        raise vs.VixSurfaceError("down")
    projection = vs.refresh(tmp_path, today=date(2026, 10, 7), now=AFTER, quote_fetcher=boom)
    assert projection["observed_date"] == "2026-10-05" and "latest_source" not in projection


# ── NASDAQ 최신 종가 ───────────────────────────────────────────────

def test_nasdaq_parser_reads_the_closed_session() -> None:
    record = mq.parse_nasdaq(NASDAQ_INFO, now=AFTER)
    assert record["session_date"] == "2026-10-06"
    assert record["close"] == 27599.79 and record["previous_close"] == 27477.31


@pytest.mark.parametrize("payload,now", [
    (_nasdaq("Open"), datetime(2026, 10, 6, 18, 0, tzinfo=UTC)),
    (_nasdaq("After-Hours"), datetime(2026, 10, 6, 20, 5, tzinfo=UTC)),   # 16:15 ET 전
    (_nasdaq("Closed", "Oct 7, 2026"), AFTER),                             # 미래 거래일
])
def test_nasdaq_parser_rejects_intraday_values(payload, now) -> None:
    with pytest.raises(mq.MarketQuoteError):
        mq.parse_nasdaq(payload, now=now)


def test_nasdaq_ledger_is_append_only_and_fallback_only_if_newer(tmp_path) -> None:
    record = mq.refresh_nasdaq(tmp_path, now=AFTER, nasdaq_fetcher=lambda: NASDAQ_INFO)
    assert record["display_only"] is True
    assert json.loads((tmp_path / mq.LATEST_RELATIVE).read_text(encoding="utf-8"))["close"] == 27599.79
    # 같은 세션 재실행 — 원장 행은 그대로 1행
    mq.refresh_nasdaq(tmp_path, now=AFTER, nasdaq_fetcher=lambda: NASDAQ_INFO)
    assert len(mq.load_history(tmp_path)) == 1

    def down():
        raise mq.MarketQuoteError("down")
    stale_fred = "observation_date,NASDAQCOM\n2026-10-02,27000.1\n2026-10-05,27477.31\n"
    with pytest.raises(mq.MarketQuoteError):
        mq.refresh_nasdaq(tmp_path, now=AFTER, nasdaq_fetcher=down, fred_fetcher=lambda: stale_fred)
    assert mq.load_latest(tmp_path)["session_date"] == "2026-10-06"

    fresh = tmp_path / "fresh"
    record = mq.refresh_nasdaq(fresh, now=AFTER, nasdaq_fetcher=down,
                               fred_fetcher=lambda: stale_fred)
    assert record["session_date"] == "2026-10-05" and "api_key" not in record["source_url"]


def test_new_request_headers_carry_no_contact_email() -> None:
    for agent in (mq.USER_AGENT, vs.QUOTE_USER_AGENT):
        assert "@" not in agent


# ── 최신성 판정 ────────────────────────────────────────────────────

def _seed(root: Path, *, fng_kst: str, vix: str, nasdaq: str) -> None:
    (root / "data/fear_greed").mkdir(parents=True)
    (root / "data/fear_greed/fng_history.jsonl").write_text(
        json.dumps({"observed_date": fng_kst, "value": 43}) + "\n", encoding="utf-8")
    (root / "data/vix").mkdir(parents=True)
    (root / "data/vix/vix_latest.json").write_text(
        json.dumps({"observed_date": vix}), encoding="utf-8")
    (root / "data/market_quotes").mkdir(parents=True)
    (root / mq.LATEST_RELATIVE).write_text(
        json.dumps({"session_date": nasdaq, "close": 1.0}), encoding="utf-8")


def test_freshness_marks_lagging_surfaces(tmp_path) -> None:
    _seed(tmp_path, fng_kst="2026-10-07", vix="2026-10-05", nasdaq="2026-10-06")
    status = mq.write_freshness_status(tmp_path, now=AFTER)
    assert status["expected_session"] == "2026-10-06"
    assert status["items"]["fng"] == {"session": "2026-10-06", "ok": True}
    assert status["items"]["vix"] == {"session": "2026-10-05", "ok": False}
    assert status["items"]["nasdaq"]["ok"] is True and status["all_ok"] is False
    assert (tmp_path / mq.FRESHNESS_RELATIVE).is_file()


# ── 일찍 띄우고 기다리기 ───────────────────────────────────────────

class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


def test_wait_polls_until_both_sources_show_the_close(tmp_path) -> None:
    # 17:30 UTC(KST 02:30) 시작 → 20:15 UTC 가드 이후 준비.
    clock = Clock(datetime(2026, 10, 6, 17, 30, tzinfo=UTC))

    def vix():
        stamp = "2026-10-06T16:15:01" if clock.now >= datetime(2026, 10, 6, 20, 15, tzinfo=UTC) \
            else "2026-10-06T13:30:00"
        return _vix(stamp)

    def nasdaq():
        return _nasdaq("Open" if clock.now < datetime(2026, 10, 6, 20, 0, tzinfo=UTC) else "After-Hours")

    result = mq.wait_for_close(tmp_path, now_fn=clock, sleep_fn=clock.sleep,
                               vix_fetcher=vix, nasdaq_fetcher=nasdaq)
    assert result["status"] == "ready" and result["target"] == "2026-10-06"
    assert clock.now == datetime(2026, 10, 6, 20, 15, tzinfo=UTC)
    assert set(clock.sleeps) == {300}


def test_wait_gives_up_at_the_deadline(tmp_path) -> None:
    clock = Clock(datetime(2026, 10, 6, 22, 0, tzinfo=UTC))

    def down():
        raise OSError("down")
    result = mq.wait_for_close(tmp_path, now_fn=clock, sleep_fn=clock.sleep,
                               vix_fetcher=down, nasdaq_fetcher=down)
    assert result["status"] == "deadline"
    assert clock.now <= datetime(2026, 10, 6, 23, 30, tzinfo=UTC)


def test_second_run_is_a_no_op_when_already_recorded(tmp_path) -> None:
    _seed(tmp_path, fng_kst="2026-10-07", vix="2026-10-06", nasdaq="2026-10-06")
    clock = Clock(datetime(2026, 10, 6, 21, 40, tzinfo=UTC))   # KST 10-07 06:40

    def never():
        raise AssertionError("이미 기록됐으면 원천을 부르지 않는다")
    result = mq.wait_for_close(tmp_path, now_fn=clock, sleep_fn=clock.sleep,
                               vix_fetcher=never, nasdaq_fetcher=never)
    assert result["status"] == "already_recorded" and not clock.sleeps


def test_weekend_run_still_writes_one_fng_row_per_kst_day(tmp_path) -> None:
    """주말에도 KST 하루 한 행 — 연속 수집 배지가 주말마다 끊기지 않게."""
    _seed(tmp_path, fng_kst="2026-10-10", vix="2026-10-09", nasdaq="2026-10-09")
    assert mq.already_recorded(tmp_path, date(2026, 10, 9), today_kst=date(2026, 10, 10))
    assert not mq.already_recorded(tmp_path, date(2026, 10, 9), today_kst=date(2026, 10, 11))


# ── 계약 · 규칙 문서 ───────────────────────────────────────────────

def test_contract_and_constitution_pin_the_rule() -> None:
    contract = yaml.safe_load(
        (ROOT / "data/contracts/morning_freshness_v1.yaml").read_text(encoding="utf-8"))
    assert contract["deadline_kst"] == "08:00"
    assert set(contract["surfaces"]) == {"fng", "vix", "nasdaq"}
    assert contract["triggers"]["primary"] == "github_schedule_early_start_with_wait"
    assert contract["triggers"]["fallback"] == "workflow_dispatch_manual"
    assert contract["triggers"]["crons_utc"] == ["30 17 * * *", "30 18 * * *"]
    assert contract["triggers"]["wait"]["give_up_utc"] == "23:30"
    assert contract["guard"]["intraday_values_never_recorded"] is True
    urls = json.dumps(contract["sources"])
    assert vs.QUOTE_URL in urls and mq.NASDAQ_URL in urls and "feargreedmeter" in urls
    constitution = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## 아침 8시 최신성 규칙 (2026-10-07 사용자 지시)" in constitution
    assert "클라우드 루틴" not in constitution


def test_signals_guards_fng_and_writes_nasdaq() -> None:
    cli = (ROOT / "src/ai_fc/cli.py").read_text(encoding="utf-8")
    body = cli[cli.index('@app.command("signals")'):cli.index('@app.command("wait-for-close")')]
    assert "is_regular_session_open(now_utc" in body and "refresh_nasdaq(root" in body
    assert '@app.command("freshness-check")' in cli


# ── 화면 ──────────────────────────────────────────────────────────

def _script() -> str:
    from ai_fc import dashboard
    return dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")


def test_header_uses_the_newer_of_latest_close_and_scenario_anchor() -> None:
    script = _script()
    header = script[script.index("function latestNasdaqClose()"):script.index("// ── 부트 ──")]
    assert "nasdaq_latest" in header and "String(q.session_date)>=String(sc.asof)" in header
    assert "Math.max(Number(sc.ath),latest.value)" in header
    assert "`${latest.session} · 전고점 대비" in header
    assert "railIndex.textContent='NASDAQ '+num(Math.round(latest.value))" in header
    assert "지연 · ${lag.session}" in header


def test_mood_cards_show_a_lag_chip() -> None:
    script = _script()
    assert "function moodLagChip(key)" in script and "지연 · ${esc(item.session)}" in script
    assert "${moodLagChip('vix')}" in script and "${moodLagChip('fng')}" in script
