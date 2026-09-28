# -*- coding: utf-8 -*-
"""시장 심리 표시 표면 — VIX · 공포탐욕 · V13 라이브 전진 누적 (2026-09-15).

세 표면이 공유하는 성질 하나를 집중해서 고정한다: **원천이 없거나 낡으면 숫자를
비운다.** 마지막 값을 재사용하는 순간 화면은 '어제 시장'을 오늘로 보여 주고, 그것은
빈칸보다 나쁘다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ai_fc import fear_greed as fg
from ai_fc import vix_surface as vs

ROOT = Path(__file__).resolve().parents[2]


# ── 공포탐욕 ──────────────────────────────────────────────────────

LD = ('<script type="application/ld+json">'
      '{"@graph":[{"@type":"QuantitativeValue","name":"Crypto Fear and Greed Index","value":69},'
      '{"@type":"QuantitativeValue","name":"Stock Market Fear and Greed Index","value":31,'
      '"unitText":"Fear"}]}</script>')


def test_the_stock_index_is_picked_not_the_crypto_one() -> None:
    """같은 페이지에 암호화폐 지수도 있다 — 이름을 고정하지 않으면 자산군이 섞인다."""
    value, name = fg.extract_value(LD)
    assert value == 31 and name == fg.SCHEMA_NAME


def test_a_missing_node_fails_instead_of_guessing() -> None:
    with pytest.raises(fg.FearGreedError):
        fg.extract_value('<script type="application/ld+json">{"@type":"Thing"}</script>')


@pytest.mark.parametrize("value,slug", [(0, "extreme_fear"), (24, "extreme_fear"),
                                        (25, "fear"), (44, "fear"), (45, "neutral"),
                                        (55, "neutral"), (56, "greed"), (74, "greed"),
                                        (75, "extreme_greed"), (100, "extreme_greed")])
def test_band_boundaries_match_the_published_scale(value: int, slug: str) -> None:
    assert fg.band_of(value)[0] == slug


def test_the_ledger_never_overwrites_a_day(tmp_path: Path) -> None:
    """하루 여러 번 돌아도 **첫 값이 그날의 값**이다. 나중 값으로 덮으면 그때 무엇을
    보고 있었는지가 지워진다."""
    first = fg.FearGreedReading("2026-09-15", "2026-09-15T00:00:00+00:00", 31, "fear",
                                "공포", fg.SCHEMA_NAME, fg.ENDPOINT, 200)
    later = fg.FearGreedReading("2026-09-15", "2026-09-15T09:00:00+00:00", 44, "fear",
                                "공포", fg.SCHEMA_NAME, fg.ENDPOINT, 200)
    assert fg.append_reading(tmp_path, first) is True
    assert fg.append_reading(tmp_path, later) is False
    rows = fg.load_history(tmp_path)
    assert len(rows) == 1 and rows[0]["value"] == 31


def test_streak_breaks_on_a_missing_day(tmp_path: Path) -> None:
    for day, value in (("2026-09-10", 40), ("2026-09-12", 38), ("2026-09-13", 36)):
        fg.append_reading(tmp_path, fg.FearGreedReading(
            day, day + "T00:00:00+00:00", value, "fear", "공포", fg.SCHEMA_NAME,
            fg.ENDPOINT, 200))
    # 09-11 이 비었으므로 09-13 부터 세면 2 에서 끊긴다 — '총 행 수'가 아니라 '연속'이다.
    assert fg.consecutive_successful_days(tmp_path, today=date(2026, 9, 13)) == 2


def test_an_empty_ledger_yields_no_number(tmp_path: Path) -> None:
    projection = fg.projection(tmp_path)
    assert projection["status"] == "absent" and "value" not in projection


# ── VIX ───────────────────────────────────────────────────────────

CSV = "DATE,VIXCLS\n2026-08-14,19.90\n2026-09-10,17.84\n2026-09-11,15.84\n"


@pytest.mark.parametrize("level,slug", [(12.9, "very_low"), (13.0, "calm"),
                                        (19.99, "calm"), (20.0, "watch"),
                                        (24.99, "watch"), (25.0, "hard_rule"),
                                        (29.9, "hard_rule"), (30.0, "stress"),
                                        (40.0, "crisis"), (80.0, "crisis")])
def test_bands_are_the_registered_question_thresholds(level: float, slug: str) -> None:
    """구간 경계는 지어낸 것이 아니라 레지스트리의 VIX 질문 임계(13·20·25·30·40)다.

    화면의 경계와 원장의 임계가 다르면 읽는 사람이 둘을 대조할 수 없다.
    """
    assert vs.band_of(level)[0] == slug


def test_the_hard_rule_distance_is_reported_not_judged() -> None:
    projection = vs.build_projection(vs.parse_csv(CSV), today=date(2026, 9, 15))
    assert projection["level"] == 15.84
    assert projection["hard_rule"] == {"level": 25.0, "distance": 9.16, "breached": False}
    assert projection["change_1d"] == -2.0


def test_an_empty_series_is_refused() -> None:
    with pytest.raises(vs.VixSurfaceError):
        vs.parse_csv("DATE,VIXCLS\n2026-09-11,.\n")


def test_a_stale_projection_hides_the_number(tmp_path: Path) -> None:
    """낡은 값을 그대로 띄우면 '어제 시장'을 오늘로 보여 주게 된다."""
    (tmp_path / "data" / "vix").mkdir(parents=True)
    payload = vs.build_projection(vs.parse_csv(CSV))
    (tmp_path / vs.LATEST_RELATIVE).write_text(json.dumps(payload), encoding="utf-8")
    fresh = vs.load_projection(tmp_path, today=date(2026, 9, 14))
    stale = vs.load_projection(tmp_path, today=date(2026, 9, 30))
    assert fresh["status"] == "live" and fresh["level"] == 15.84
    assert stale["status"] == "stale" and "level" not in stale


# ── V13 라이브 전진 누적 ──────────────────────────────────────────

def test_the_live_scoreboard_never_carries_a_verdict() -> None:
    """계약이 셀당 60 전에는 판정을 막는다 — 페이로드에 판정 자리를 비워 둬서
    화면이 '통과/실패' 문구를 만들지 못하게 한다."""
    from ai_fc.timeseries_v13.live_scoreboard import projection

    result = projection(ROOT)
    assert result["verdict"] is None
    assert result["minimum"] >= 1
    assert all(not cell["gate_met"] or cell["matured"] >= result["minimum"]
               for cell in result["cells"])


def test_the_scoreboard_survives_an_empty_ledger(tmp_path: Path) -> None:
    from ai_fc.timeseries_v13.live_scoreboard import projection

    result = projection(tmp_path, minimum=60)
    assert result["status"] == "empty" and result["matured_total"] == 0
    assert result["cells"] and all("brier_model" not in c for c in result["cells"])


# ── 배선 ──────────────────────────────────────────────────────────

def test_the_daily_batch_refreshes_both_surfaces() -> None:
    text = (ROOT / ".github/workflows/source-monitoring.yml").read_text(encoding="utf-8")
    assert "python -m ai_fc signals" in text
    assert "FRED_API_KEY: ${{ secrets.FRED_API_KEY }}" in text
    assert "data/fear_greed" in text and "data/vix" in text


def test_mood_refresh_runs_after_the_us_close_and_deploys() -> None:
    """공포·탐욕은 미국 마감 직후 갱신되고, 그 커밋이 곧바로 배포돼야 한다.

    2026-09-18 KST 13시: 원천 29, 화면 26(= 9/16 종가). source-monitoring 의 02:45 UTC
    예약이 매일 약 5시간 늦게 떴고, 그 커밋은 pages 트리거 목록에도 없었다.
    """
    import yaml

    directory = ROOT / ".github/workflows"
    text = (directory / "market-mood-refresh.yml").read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    on = document.get(True) or document.get("on")
    crons = [item["cron"] for item in on["schedule"]]
    assert crons, "예약이 없으면 사람이 돌릴 때까지 화면이 멈춘다"
    for cron in crons:
        minute, hour = (int(part) for part in cron.split()[:2])
        utc = hour * 60 + minute
        # 미국 정규장 마감(EST 21:00 UTC) 이후 ~ 다음 개장(13:30 UTC) 이전 — 장중 값을
        # KST 관측일의 값으로 잠그지 않는다. 자정을 넘기는 창이라 둘로 나눠 본다.
        assert utc >= 21 * 60 + 30 or utc <= 9 * 60, cron
    assert "python -m ai_fc signals" in text
    assert "FRED_API_KEY: ${{ secrets.FRED_API_KEY }}" in text
    assert "data/fear_greed" in text and "data/vix" in text
    assert "group: investing-data-writer" in text
    assert "steps.mood.outcome == 'failure'" in text, "부분 실패도 감시에 걸려야 한다"

    pages = (directory / "pages.yml").read_text(encoding="utf-8")
    assert '"market-mood-refresh"' in pages and '"source-monitoring"' in pages


def test_the_surfaces_declare_themselves_display_only() -> None:
    """확률 공간이 아니라는 사실이 계약·페이로드 양쪽에 있어야 한다."""
    import yaml

    contract = yaml.safe_load(
        (ROOT / "data/contracts/fear_greed_index.yaml").read_text(encoding="utf-8"))
    assert contract["probability_space"] == "not_a_probability"
    assert contract["model_use"] is False and contract["trading_signal"] is False
    assert contract["extraction"]["on_miss"] == "fail"


# ── 1차 출처 시드 (2026-09-15 추가) ───────────────────────────────

def test_seeded_rows_do_not_inflate_the_daily_collection_streak(tmp_path: Path) -> None:
    """안정성 배지가 재는 것은 **우리 일일 수집**이 며칠째 끊기지 않았는가다.

    과거를 한 번 심어 두고 그 행까지 세면 첫날부터 14/14 가 되어 배지가 거짓말을 한다.
    """
    path = tmp_path / fg.HISTORY_RELATIVE
    path.parent.mkdir(parents=True)
    rows = [{"observed_date": f"2026-09-{day:02d}", "value": 40, "band": "fear",
             "band_label": "공포", "seeded": True} for day in range(1, 15)]
    rows.append({"observed_date": "2026-09-15", "value": 31, "band": "fear",
                 "band_label": "공포", "value_raw": 30.94})
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    assert fg.consecutive_successful_days(tmp_path, today=date(2026, 9, 15)) == 1
    projection = fg.projection(tmp_path, today=date(2026, 9, 15))
    assert projection["history_days"] == 15 and projection["seeded_days"] == 14
    assert projection["stability"]["gate_met"] is False


def test_the_real_ledger_carries_a_year_of_history_with_provenance() -> None:
    """심은 행은 출처를 밝힌다 — 어느 행이 어디서 왔는지 섞이면 대조가 불가능하다."""
    history = fg.load_history(ROOT)
    assert len(history) >= 200, "1년치 시드가 있어야 통계 그래프가 그려진다"
    seeded = [row for row in history if row.get("seeded")]
    assert seeded and all(row.get("source_id") == "cnn_graphdata" for row in seeded)
    assert all(0 <= row["value"] <= 100 for row in history)
    dates = [row["observed_date"] for row in history]
    assert dates == sorted(dates) and len(dates) == len(set(dates))


# ── 구성요소 실험실 (통계 탭) ─────────────────────────────────────

def test_components_carry_all_seven_with_raw_series() -> None:
    """CNN 이 쓰는 7축이 전부 있어야 한다 — 하나라도 빠지면 합성값을 설명하지 못한다."""
    lab = fg.components_projection(ROOT)
    assert lab["status"] == "live"
    expected = {"market_momentum_sp500", "stock_price_strength", "stock_price_breadth",
                "put_call_options", "market_volatility_vix", "junk_bond_demand",
                "safe_haven_demand"}
    assert set(lab["components"]) == expected
    for name, component in lab["components"].items():
        assert 0 <= component["score"] <= 100, name
        assert component["rating"] and component["label"] and component["unit"]
        assert len(component["series"]) == len(lab["dates"]), name


def test_nasdaq_is_joined_on_the_same_axis() -> None:
    """겹쳐 보려면 두 계열이 **같은 날짜 축** 위에 있어야 한다.

    NASDAQ 은 우리 봉인 아카이브에서 붙인다 — 상관을 주장하려는 것이 아니라 같은
    구간을 두 눈금으로 읽게 하려는 것이다.
    """
    lab = fg.components_projection(ROOT)
    assert len(lab["nasdaq"]) == len(lab["dates"])
    filled = [v for v in lab["nasdaq"] if v is not None]
    assert len(filled) == len(lab["dates"]), "빈 칸이 있으면 선이 끊긴다"
    assert min(filled) > 1000, "지수 레벨이어야 한다(수익률·지수화 아님)"


def test_component_series_are_raw_inputs_not_scores() -> None:
    """점수 시계열은 공표되지 않는다 — 원자료를 점수처럼 그리면 없는 데이터를 지어내는 것이다.

    S&P500 모멘텀 축은 지수 레벨(수천), VIX 축은 20 안팎이다. 둘 다 0~100 이 아니다.
    """
    lab = fg.components_projection(ROOT)
    momentum = lab["components"]["market_momentum_sp500"]["series"]
    vix = lab["components"]["market_volatility_vix"]["series"]
    assert min(momentum) > 1000 and max(vix) < 60
    assert lab["components"]["market_momentum_sp500"]["score"] <= 100


def test_the_lab_declares_its_provenance_and_status() -> None:
    lab = fg.components_projection(ROOT)
    assert lab["source"] == "cnn_graphdata"
    assert lab["license_status"] == "review_required"
    assert lab["method"] == "real_browser_session"
