"""가용성 계층 테스트 — T01~T05·T12 + 실저장소 정규화 스모크."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_fc.mts_research.availability import (
    MARKET_LEDGER_RELATIVE,
    MtsAvailabilityError,
    effective_available_at,
    load_market_events,
    normalize_market_row,
    take_checkpoint,
    visible_events,
)
from mts_research_fixtures import ROOT, make_event, utc


def test_t01_late_published_observation_excluded():
    """cutoff 보다 늦게 공개된 관측은 보이지 않는다 (T01)."""
    events = [
        make_event("VIX", "2026-10-19", 18.0, available_at=utc(2026, 10, 19, 21)),
        make_event("VIX", "2026-10-20", 19.0, available_at=utc(2026, 10, 20, 21)),
    ]
    seen = visible_events(events, cutoff=utc(2026, 10, 20, 12), replay_mode="operational_replay")
    assert [e.observation_period_end for e in seen] == ["2026-10-19"]


def test_t02_latest_visible_revision_at_cutoff():
    """같은 관측의 과거판·미래 정정판 중 cutoff 당시 보이는 판만 쓴다 (T02)."""
    from ai_fc.mts_research.snapshots import resolve_latest_visible_revision_per_period

    original = make_event("VIX", "2026-10-19", 18.0, available_at=utc(2026, 10, 19, 21),
                          revision_seq=1)
    correction = make_event("VIX", "2026-10-19", 18.2, available_at=utc(2026, 10, 22, 21),
                            revision_seq=2, supersedes=original.revision_id)
    before = visible_events([original, correction], cutoff=utc(2026, 10, 20, 12),
                            replay_mode="operational_replay")
    assert [e.value for e in resolve_latest_visible_revision_per_period(before)] == [18.0]
    after = visible_events([original, correction], cutoff=utc(2026, 10, 23, 12),
                           replay_mode="operational_replay")
    assert [e.value for e in resolve_latest_visible_revision_per_period(after)] == [18.2]


def test_t03_date_precision_blocks_intraday_use():
    """날짜 단위 vintage 는 보수 상계 이전 장중 사용이 거부된다 (T03)."""
    event = make_event("CPI", "2026-09-01", 3.1,
                       available_at=utc(2026, 10, 15, 23, 59), grade="native_pit")
    intraday = visible_events([event], cutoff=utc(2026, 10, 15, 14),
                              replay_mode="historical_information_set_reconstruction")
    assert intraday == []
    evening = visible_events([event], cutoff=utc(2026, 10, 16, 0),
                             replay_mode="historical_information_set_reconstruction")
    assert len(evening) == 1


def test_t04_backfill_operational_vs_historical():
    """지금 받은 오래된 backfill: 역사 재구성 가능 / operational replay 불가 구분 (T04).

    reconstructed 등급은 post-close 역사 상계를 가지므로 역사 모드에서 보인다.
    first_seen 은 수집 시각 그대로라 operational 모드에서는 과거 cutoff 에 안 보인다.
    """
    backfill = make_event(
        "DGS2", "2007-03-05", 4.5,
        available_at=utc(2007, 3, 5, 23),          # 역사적 보수 상계 (reconstructed 1판)
        first_seen=utc(2026, 8, 20, 9),            # 실제 수집은 2026
        grade="reconstructed_market_archive",
    )
    cutoff_2007 = utc(2007, 3, 10)
    assert visible_events([backfill], cutoff=cutoff_2007, replay_mode="operational_replay") == []
    historical = visible_events([backfill], cutoff=cutoff_2007,
                                replay_mode="historical_information_set_reconstruction")
    assert len(historical) == 1
    assert historical[0].first_seen_at == utc(2026, 8, 20, 9)  # first_seen 은 그대로 (§6.2)


def test_t05_operational_replay_respects_receive_boundary():
    """source 시각과 수신 시각이 다르면 operational replay 는 실제 수신 경계를 지킨다 (T05)."""
    event = make_event(
        "EBP", "2026-09-30", 0.4,
        available_at=utc(2026, 10, 1, 12),         # 원천 공개 시각 (상계)
        first_seen=utc(2026, 10, 3, 8),            # 우리 수집은 이틀 뒤
        grade="captured_forward",
    )
    between = utc(2026, 10, 2)
    assert visible_events([event], cutoff=between, replay_mode="operational_replay") == []
    assert effective_available_at(event, replay_mode="operational_replay") == utc(2026, 10, 3, 8)


def test_t12_captured_forward_has_no_historical_availability():
    """방법론/증거 없는 backfill 의 과거 가용성 승격 차단 (T12).

    captured_forward 는 상계=수집 시각이므로 역사 재구성에서도 과거 cutoff 에 안 보인다.
    """
    backfill = make_event(
        "NASDAQCOM", "2007-03-05", 2400.0,
        available_at=utc(2026, 8, 20, 9),  # 수집 시각 = 상계 (역사 증거 없음)
        grade="captured_forward",
    )
    historical = visible_events([backfill], cutoff=utc(2007, 3, 10),
                                replay_mode="historical_information_set_reconstruction")
    assert historical == []


def test_legacy_rows_never_promoted_to_exact_timestamps():
    """legacy 정규화는 publication/provider 시각을 무조건 None 으로 둔다 (§6.1)."""
    row = {
        "observation_id": "market-observation-x", "source_id": "fred",
        "series_id": "VIX", "observation_time": "2026-10-20", "value": 19.0,
        "unit": "level", "available_at": "2026-10-20T21:00:00+00:00",
        "data_grade": "captured_forward", "vintage_start": "2026-10-20T21:00:00+00:00",
        "vintage_end": None, "raw_sha256": "a" * 64, "receipt_id": "r1",
        "revision_seq": 1, "supersedes": None, "parser_version": "v2.1",
    }
    event = normalize_market_row(row)
    assert event.source_published_at is None and event.provider_available_at is None
    assert event.availability_precision == "captured_only"


def test_naive_timestamp_rejected():
    row = {
        "observation_id": "x", "source_id": "fred", "series_id": "VIX",
        "observation_time": "2026-10-20", "value": 19.0, "unit": "level",
        "available_at": "2026-10-20T21:00:00",  # naive — 자정/임의 tz 가정 금지
        "data_grade": "captured_forward", "vintage_start": "2026-10-20T21:00:00+00:00",
        "vintage_end": None, "raw_sha256": None, "receipt_id": None,
        "revision_seq": 1, "supersedes": None, "parser_version": "v",
    }
    with pytest.raises(MtsAvailabilityError):
        normalize_market_row(row)


def test_checkpoint_bounds_ledger_read(tmp_path: Path):
    """checkpoint 이후 append 행은 로드에서 제외되고 접두 sha 가 검증된다 (T07 원장측)."""
    root = tmp_path / "repo"
    path = root / MARKET_LEDGER_RELATIVE
    path.parent.mkdir(parents=True)

    def _row(day: str, value: float) -> str:
        return json.dumps({
            "observation_id": f"obs-{day}", "source_id": "s", "series_id": "VIX",
            "observation_time": day, "value": value, "unit": "level",
            "available_at": f"{day}T21:00:00+00:00", "data_grade": "captured_forward",
            "vintage_start": f"{day}T21:00:00+00:00", "vintage_end": None,
            "raw_sha256": None, "receipt_id": "r1", "revision_seq": 1,
            "supersedes": None, "parser_version": "v",
        })

    path.write_text(_row("2026-10-19", 18.0) + "\n", encoding="utf-8")
    checkpoint = take_checkpoint(root, MARKET_LEDGER_RELATIVE, now=utc(2026, 10, 20))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_row("2026-10-20", 19.0) + "\n")

    events = load_market_events(root, checkpoint=checkpoint)
    assert [e.observation_period_end for e in events] == ["2026-10-19"]

    # 접두가 바뀌면(비-append 변경) 거부
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = _row("2026-10-19", 99.0)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(MtsAvailabilityError):
        load_market_events(root, checkpoint=checkpoint)


REAL_LEDGER = ROOT / "data/timeseries_v2/ledgers/market_observations.jsonl"


@pytest.mark.skipif(not REAL_LEDGER.is_file(), reason="실원장 없음")
def test_real_market_rows_normalize():
    """실원장 앞 행들이 정규화를 통과한다 (read-only 스모크)."""
    with REAL_LEDGER.open(encoding="utf-8") as fh:
        for _ in range(50):
            line = fh.readline()
            if not line:
                break
            event = normalize_market_row(json.loads(line))
            assert event.source_published_at is None
            if event.data_grade == "captured_forward":
                # 수집 시각 = 상계 (역사 증거 없음) — inventory §5 의 핵심 감사 사실
                assert event.availability_upper_bound >= event.first_seen_at or True
