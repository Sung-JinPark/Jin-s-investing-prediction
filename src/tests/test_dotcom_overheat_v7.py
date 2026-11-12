"""닷컴 대비 과열도 v7(영향도 점수제) — 식·표본·점수·가중·닫힘을 합성 자료로 고정한다 (네트워크·원장 없음)."""

from __future__ import annotations

import copy
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc import dotcom_overheat_v7 as v7

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = yaml.safe_load((ROOT / v7.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
PEAKS = [date(1973, 1, 10), date(1980, 2, 8), date(1987, 8, 25), date(2000, 3, 10), date(2007, 10, 31),
         date(2021, 11, 19)]


def _heat(day: date) -> float:
    """정점 2년 전부터 차오르고 정점 뒤 1년에 걸쳐 빠지는 합성 '열기'(0~1)."""
    best = 0.0
    for peak in PEAKS:
        gap = (day - peak).days
        if -730 <= gap <= 0:
            best = max(best, 1.0 + gap / 730.0)
        elif 0 < gap <= 365:
            best = max(best, 1.0 - gap / 365.0)
    return best


def _months(start: tuple[int, int], end: tuple[int, int]) -> list[date]:
    out, (y, m) = [], start
    while (y, m) <= end:
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


@pytest.fixture(scope="module")
def store() -> v7.Store:
    day, sessions = date(1968, 1, 1), []
    while day <= date(2026, 11, 10):
        if day.weekday() < 5:
            sessions.append(day)
        day += timedelta(days=1)
    level, nasdaq = math.log(100.0), []
    for i, d in enumerate(sessions):
        crashing = any(0 < (d - p).days <= 300 for p in PEAKS)
        level += -0.0022 if crashing else 0.0007 + 0.0009 * _heat(d)
        nasdaq.append((d, math.exp(level + 0.01 * math.sin(i / 7.0))))
    months = _months((1965, 1), (2026, 10))
    quarters = [m for m in months if m.month in (1, 4, 7, 10) and m <= date(2026, 7, 1)]
    wave = lambda d, k: math.sin(d.toordinal() / k)  # noqa: E731 — 열기와 무관한 잡음
    series: dict[str, list] = {"NASDAQCOM": nasdaq}
    series["T10Y3M"] = [(d, 2.0 - 2.5 * _heat(d) + 0.2 * wave(d, 40.0)) for d in sessions[::2]]
    series["T10Y2Y"] = [(d, 1.0 - 1.2 * _heat(d) + 0.2 * wave(d, 55.0)) for d in sessions[::2]]
    series["DCOILWTICO"] = [(d, 40.0 + 10.0 * wave(d, 300.0)) for d in sessions[::3]]
    series["NFCI"] = [(d, -0.5 * _heat(d) + 0.1 * wave(d, 90.0)) for d in sessions[::5]]
    for sid, fn in {
        "M2SL": lambda d, i: 500.0 * 1.005 ** i,
        "FEDFUNDS": lambda d, i: 3.0 + 3.0 * _heat(d) + 0.3 * wave(d, 200.0),
        "GS10": lambda d, i: 5.0 + 0.5 * wave(d, 400.0),
        "HQMCB10YR": lambda d, i: 6.5 + 0.5 * wave(d, 400.0) - 0.8 * _heat(d),
        "CPIAUCSL": lambda d, i: 30.0 * 1.0025 ** i * (1.0 + 0.01 * wave(d, 500.0)),
        "UNRATE": lambda d, i: 6.0 - 2.0 * _heat(d) + 0.2 * wave(d, 150.0),
        "TOTALSL": lambda d, i: 100.0 * 1.004 ** i * (1.0 + 0.02 * _heat(d)),
        "SPASTT01USM661N": lambda d, i: 10.0 * 1.005 ** i * (1.0 + 0.6 * _heat(d)),
    }.items():
        series[sid] = [(d, fn(d, i)) for i, d in enumerate(months)]
    gdp = {q: 1000.0 * 1.012 ** i for i, q in enumerate(quarters)}
    for sid, fn in {
        "GDP": lambda q: gdp[q], "GFDEBTN": lambda q: gdp[q] * 400.0,
        "DRTSCILM": lambda q: 10.0 - 25.0 * _heat(q) + 5.0 * wave(q, 300.0),
        "W328RC1Q027SBEA": lambda q: gdp[q] * 0.06, "Y001RC1Q027SBEA": lambda q: gdp[q] * 0.04,
        "Y034RC1Q027SBEA": lambda q: gdp[q] * (0.02 + 0.008 * _heat(q)),
        "NCBEILQ027S": lambda q: gdp[q] * 1000.0 * (0.8 + 0.9 * _heat(q)),
        "BOGZ1LM153064475Q": lambda q: 2.0 + 1.2 * _heat(q), "BOGZ1LM893064105Q": lambda q: gdp[q] * 1000.0 * (1.0 + _heat(q)),
        "DABSHNO": lambda q: gdp[q] * 0.9, "BOGZ1FL010000346Q": lambda q: 10.0 + wave(q, 700.0),
        "FL663067003": lambda q: gdp[q] * 1000.0 * (0.012 + 0.012 * _heat(q)),
        "FL103163005": lambda q: gdp[q] * 1000.0 * (0.20 + 0.02 * wave(q, 900.0)),
        "FA103163005": lambda q: gdp[q] * 1000.0 * (0.01 + 0.004 * wave(q, 250.0)),
    }.items():
        series[sid] = [(q, fn(q)) for q in quarters]
    ritter = _months((1962, 1), (2025, 12))
    series["RITTER_NET"] = [(m, float(round(10 + 35 * _heat(m)))) for m in ritter]
    series["RITTER_FIRST"] = [(m, 12.0 + 40.0 * _heat(m)) for m in ritter]
    return v7.Store(series, CONTRACT["series_lag_days"], CONTRACT["staleness_limits_days"])


@pytest.fixture(scope="module")
def panel(store: v7.Store) -> v7.Panel:
    return v7.Panel(store, CONTRACT)


@pytest.fixture(scope="module")
def base(panel: v7.Panel, store: v7.Store) -> dict:
    return v7.build_spec(panel, store, CONTRACT, v7.Options())


# ── 계약과 식 ─────────────────────────────────────────────────────────────


def test_contract_fixes_rules_directions_and_every_candidate_has_a_formula() -> None:
    assert CONTRACT["rules_fixed_at"] != "PENDING" and CONTRACT["probability_space"] == "reference_only"
    assert CONTRACT["trading_signal"] is False and CONTRACT["weights"]["nothing_else_is_estimated"] is True
    ids = [row["id"] for row in CONTRACT["candidates"]]
    assert sorted(ids) == sorted(v7.FORMULAS) and len(ids) == len(set(ids)) == 35
    assert {row["sign"] for row in CONTRACT["candidates"]} == {1, -1}  # 방향은 선언돼 있다
    assert {row["group"] for row in CONTRACT["candidates"]} == {"heat", "pressure"}
    assert all(row["group"] == "pressure" for row in CONTRACT["candidates"]
               if row["family"] in {"rates", "curve", "inflation"})
    used = {sid for sid in v7.FREQUENCY if not sid.startswith("RITTER")} - {"NASDAQCOM"}
    assert used <= set(CONTRACT["series_lag_days"])  # 계열마다 발표 지연이 있다
    assert [g["id"] for g in CONTRACT["gates"]] == [f"G{n}" for n in range(1, 13)]
    assert set(v7.VARIANTS) | {"drop_top"} == {row["id"] for row in CONTRACT["measurement_band"]["variants"]}


def test_observations_become_visible_only_after_their_publication_lag(store: v7.Store) -> None:
    lag = CONTRACT["series_lag_days"]["GDP"]
    release = date(2010, 3, 31) + timedelta(days=lag)  # 2010Q1 은 분기 말 + 지연 뒤에야 보인다
    before = v7.read(store, "it_equipment_gdp", store.session_index(release - timedelta(days=1)))
    after = v7.read(store, "it_equipment_gdp", store.session_index(release + timedelta(days=4)))
    assert "2009Q4" in before[1] and "2010Q1" in after[1]
    live = v7.read(store, "it_equipment_gdp", store.session_index(date(2010, 3, 31)), use_lags=False)
    assert "2010Q1" in live[1]
    month = v7.read(store, "policy_rate_change_12m", store.session_index(date(2010, 6, 4)))
    assert month[1] == ("2010-04",)  # 5월 치는 5월 말 + 5일 뒤에 보인다


def test_formulas_follow_the_contract_definitions(store: v7.Store) -> None:
    i = store.session_index(date(2015, 6, 30))
    calc = v7.Calc(store, i)
    base24 = float(np.mean(store.close[i - 524:i - 484]))
    assert v7.read(store, "speed_r24", i)[0] == pytest.approx(math.log(store.close[i] / base24))
    assert v7.read(store, "speed_d200", i)[0] == pytest.approx(store.close[i] / np.mean(store.close[i - 199:i + 1]) - 1)
    ff = calc.window("FEDFUNDS", 36)[0]
    assert v7.read(store, "policy_tightening_36m", i)[0] == pytest.approx(ff[-1] - min(ff))
    assert v7.read(store, "policy_rate_change_12m", i)[0] == pytest.approx(ff[-1] - ff[-13])
    cpi = calc.window("CPIAUCSL", 13)[0]
    inflation = 100.0 * (cpi[-1] / cpi[0] - 1)
    assert v7.read(store, "inflation_yoy", i)[0] == pytest.approx(inflation)
    assert v7.read(store, "real_policy_rate", i)[0] == pytest.approx(ff[-1] - inflation)
    profits = calc.window("W328RC1Q027SBEA", 12)[0]
    assert v7.read(store, "equity_profit_smoothed", i)[0] == pytest.approx(
        calc.val("NCBEILQ027S")[0] / (1000.0 * sum(profits) / 12))
    assert v7.read(store, "ipo_count_12m", i)[0] == sum(calc.window("RITTER_NET", 12)[0])
    shocked = v7.read(store, "nasdaq_m2", i, close=store.close[i] * 1.1)[0]
    assert shocked == pytest.approx(1.1 * v7.read(store, "nasdaq_m2", i)[0])
    assert v7.read(store, "speed_r24", 100) is None


def test_stale_inputs_drop_out(store: v7.Store) -> None:
    short = v7.Store({"NASDAQCOM": list(zip(store.sessions, store.close.tolist())),
                      "UNRATE": [(d, v) for d, v in zip(store.obs["UNRATE"]["start"], store.obs["UNRATE"]["value"])
                                 if d < date(2020, 1, 1)]},
                     CONTRACT["series_lag_days"], CONTRACT["staleness_limits_days"])
    assert v7.read(short, "unemployment_rate", short.session_index(date(2020, 3, 2))) is not None
    assert v7.read(short, "unemployment_rate", short.session_index(date(2020, 9, 1))) is None  # 120일 한도


# ── 결과·표본·통계 ────────────────────────────────────────────────────────


def test_forward_drawdown_and_near_high_definitions() -> None:
    close = np.array([100.0, 110.0, 90.0, 95.0, 120.0, 60.0, 80.0])
    dd = v7.forward_drawdown(close, 2)
    assert dd[0] == pytest.approx(0.10) and dd[1] == pytest.approx(1 - 90 / 110) and dd[2] == 0.0  # 오르기만 하면 0
    assert dd[4] == pytest.approx(0.5) and np.isnan(dd[5]) and np.isnan(dd[6])  # 창이 끝까지 없으면 결측
    assert v7.near_high(close, 4) and not v7.near_high(close, 6)


def test_bear_episode_state_machine_restarts_after_a_thirty_percent_recovery() -> None:
    days = [date(2000, 1, 3) + timedelta(days=i) for i in range(9)]
    close = np.array([100.0, 120.0, 95.0, 88.0, 80.0, 105.0, 130.0, 96.0, 99.0])
    episodes = v7.bear_episodes(days, close)
    assert [(e["peak"], e["trigger"]) for e in episodes] == [(days[1], days[3]), (days[6], days[7])]
    assert episodes[0]["low"] == days[4]  # 저점 80 → 105 는 30% 넘는 회복이라 다시 센다(역대 고점 회복을 기다리지 않는다)


def test_rank_statistics_handle_ties_and_blocks() -> None:
    a, b = np.array([1.0, 2.0, 2.0, 4.0, 5.0]), np.array([10.0, 20.0, 20.0, 40.0, 50.0])
    assert v7.spearman(a, b) == pytest.approx(1.0) and v7.spearman(a, -b) == pytest.approx(-1.0)
    assert v7.spearman(a, np.ones(5)) is None
    hot = np.concatenate([np.arange(20.0), 1000.0 + np.arange(20.0)])       # 블록 사이 수준 차이
    outcome = np.concatenate([np.arange(20.0), -np.arange(20.0)])           # 블록 1 은 정방향, 블록 2 는 역방향
    blocks = np.array([0] * 20 + [1] * 20)
    pooled, per = v7.pooled_spearman(hot, outcome, blocks)
    assert per[0][0] == pytest.approx(1.0) and per[1][0] == pytest.approx(-1.0) and pooled == pytest.approx(0.0)


def test_point_formulas_use_the_contract_thresholds() -> None:
    n = 240
    blocks = np.array([0] * 80 + [1] * 80 + [2] * 80)
    hot = np.tile(np.arange(80.0), 3)
    dd = np.tile(np.arange(80.0) / 100.0, 3)  # 완전한 순위 일치, 상위 20% 는 모두 0.20 이상 하락
    perfect = v7.core_points(hot, dd, dd, blocks)
    assert perfect["P1"] == 35.0 and perfect["P2"] == 25.0 and perfect["P4"] == 20.0 and perfect["E_core"] == 100.0
    opposite = v7.core_points(-hot, dd, dd, blocks)
    assert opposite["P1"] == 0.0 and opposite["P4"] == 0.0 and opposite["rbar"] == 0.0  # 선언 방향과 반대면 0점
    flat = v7.core_points(np.sin(np.arange(n) * 1.7), dd, dd, blocks)
    assert flat["E_core"] < 40.0
    one_bad = np.concatenate([np.arange(80.0), np.arange(80.0), -np.arange(80.0)])
    assert v7.core_points(one_bad, dd, dd, blocks)["P4"] == 8.0


# ── 채점·자격·가중 ────────────────────────────────────────────────────────


def test_scores_reward_indicators_that_lead_drawdowns_and_never_estimate(base: dict, panel: v7.Panel) -> None:
    scores = base["scores"]
    assert set(scores) == set(panel.candidates) | set(panel.controls)
    informative, noise = scores["speed_r24"], scores["household_debt_service"]
    assert informative["eligible"] and informative["E"] > 60 and informative["rbar"] > 0.3
    assert noise["E"] < 20 and not noise["eligible"] and noise["reason"]  # 관계없는 지표는 사유와 함께 '참고'
    assert scores["policy_rate_change_12m"]["reason"] == "중복(policy_tightening_36m)"  # 같은 것을 두 번 세지 않는다
    assert scores["margin_mktcap"]["reason"] == "점수 35 미만"
    for row in scores.values():
        if row["status"] in {"dropped", "not_scoreable"}:
            continue
        assert 0.0 <= row["E"] <= 100.0 and row["placebo90"] is not None
        if row["eligible"]:
            assert row["rbar"] > 0 and row["E_core"] > row["placebo90"] and row["E"] >= 35
    assert all(not scores[k]["eligible"] for k in panel.controls)  # 대조군은 어떤 경우에도 가중에 들어가지 않는다
    assert scores["nasdaq_m2"]["P3"] is None and scores["nasdaq_m2"]["p3"]["reason"] == "price term"
    ranks = sorted(row["rank"] for row in scores.values())
    assert ranks == list(range(1, len(scores) + 1))


def test_weights_follow_score_shares_under_every_cap(base: dict, panel: v7.Panel) -> None:
    heat = base["lines"]["heat"]
    assert heat is not None and sum(heat["weights"].values()) == pytest.approx(100.0, abs=1e-4)
    families: dict[str, float] = {}
    for key, weight in heat["weights"].items():
        assert base["scores"][key]["eligible"] and base["scores"][key]["group"] == "heat"
        families[panel.candidates[key]["family"]] = families.get(panel.candidates[key]["family"], 0.0) + weight
    assert max(heat["weights"].values()) <= 25 + 1e-6 and max(families.values()) <= 40 + 1e-6
    assert sum(w for k, w in heat["weights"].items() if panel.candidates[k]["price_term"]) <= 50 + 1e-6
    assert v7._fill({"a": 3.0, "b": 1.0}, 100.0, 60.0) == {"a": 60.0, "b": 40.0}
    assert v7._fill({"a": 1.0, "b": 1.0, "c": 2.0}, 100.0, 25.0) is None  # 상한 합이 100 에 못 미치면 불능
    assert v7._fill({"a": 1.0, "b": 1.0}, 100.0, 80.0) == {"a": 50.0, "b": 50.0}


def test_too_few_eligible_indicators_means_no_line(panel: v7.Panel, store: v7.Store) -> None:
    strict = v7.build_spec(panel, store, CONTRACT, v7.Options(threshold=101.0))
    assert strict["lines"] == {"heat": None, "pressure": None}
    assert all(not row["eligible"] for row in strict["scores"].values())
    dropped = v7.build_spec(panel, store, CONTRACT, v7.Options(drop_families=["valuation"]))
    assert all(row["status"] == "dropped" for row in dropped["scores"].values() if row["family"] == "valuation")


# ── 합산·척도 ─────────────────────────────────────────────────────────────


def test_headline_is_100_at_the_peak_and_zero_at_the_median(base: dict, store: v7.Store) -> None:
    heat = base["lines"]["heat"]
    assert v7.heat_today(store, heat, index=store.session_index(v7.PEAK_DAY)) == pytest.approx(100.0)
    grid = [i for i in store.month_ends if v7.STD_WINDOW[0] <= store.sessions[i] <= v7.STD_WINDOW[1]]
    values = [v7.heat_today(store, heat, index=i) for i in grid]
    assert float(np.median([v for v in values if v is not None])) == pytest.approx(0.0, abs=1e-6)
    quiet = v7.heat_today(store, heat, index=store.session_index(date(2014, 6, 30)))
    assert quiet < 40 < v7.heat_today(store, heat, index=store.session_index(date(2021, 11, 19)))
    out = v7.composite(store, len(store.sessions) - 1, heat, detail=True)
    assert out["live_weight"] == pytest.approx(100.0) and set(out["rows"]) == set(heat["weights"])
    assert v7.z_reading(1e9, 1.0, {"median": 0.0, "mad": 1.0}) == 10.0  # 이상값 방어는 합산에만
    assert v7.percentile_of(0.0, [-1.0, 0.0, 1.0, 2.0]) == 50.0 and v7.percentile_of(None, [1.0]) is None


def test_composite_holds_when_live_weight_is_short(store: v7.Store) -> None:
    anchor = {"median": 0.0, "mad": 0.1}
    spec = {"weights": {"speed_r24": 60.0, "speed_d200": 40.0}, "signs": {"speed_r24": 1.0, "speed_d200": 1.0},
            "anchors": {"speed_r24": anchor, "speed_d200": anchor}}
    early = v7.composite(store, 300, spec)  # 2년 상승률은 아직 계산할 수 없다 — 살아 있는 가중 40
    assert early["value"] is None and early["live_weight"] == 40.0
    assert v7.composite(store, 600, spec)["value"] is not None


# ── 닫힘 ──────────────────────────────────────────────────────────────────


def _frozen(base: dict, verdict: str = "passed") -> dict:
    heat = base["lines"]["heat"]
    contract = copy.deepcopy(CONTRACT)
    contract["frozen"] = {
        "verdict": verdict, "rules_sha256": v7.rules_digest(contract),
        "scores": {k: {"E": row["E"]} for k, row in base["scores"].items()},
        "heat": {"weights": heat["weights"], "signs": heat["signs"], "anchors": heat["anchors"],
                 "C0": heat["scale"]["C0"], "Cpk": heat["scale"]["Cpk"], "grid": heat["scale"]["grid"]},
    }
    return contract


def test_index_is_published_only_with_a_passed_verdict_bound_to_the_rules(base: dict, store: v7.Store,
                                                                         tmp_path: Path) -> None:
    now = datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc)
    opened = v7.build_latest(tmp_path, now=now, ledger=store, contract=_frozen(base))
    assert opened["status"] == "ok" and opened["probability_space"] == "reference_only"
    assert opened["trading_signal"] is False and isinstance(opened["index"], int)
    assert sum(row["weight"] for row in opened["indicators"]) == pytest.approx(100.0, abs=0.6)
    assert opened["weights_basis"].startswith("가중은 과거 자료 기준")
    assert v7.build_latest(tmp_path, now=now, ledger=store, contract=_frozen(base, "failed"))["reason"] == "gates not passed"
    edited = _frozen(base)
    edited["scoring"]["P1_rank_association"]["max"] = 50  # 판정 뒤 규칙이 바뀌면 닫힌다
    assert v7.build_latest(tmp_path, now=now, ledger=store, contract=edited)["status"] == "unavailable"
    stale = v7.build_latest(tmp_path, now=now + timedelta(days=40), ledger=store, contract=_frozen(base))
    assert stale["status"] == "hold" and "index" not in stale
    moved = _frozen(base)
    moved["frozen"]["heat"]["Cpk"] *= 1.2  # 원장으로 다시 잰 기준값과 어긋나면 보류
    assert v7.build_latest(tmp_path, now=now, ledger=store, contract=moved)["status"] == "hold"


def test_repository_state_is_closed_until_a_passed_verdict_is_recorded() -> None:
    problem = v7.frozen_problem(CONTRACT)
    frozen = CONTRACT.get("frozen") or {}
    assert (problem is None) == (frozen.get("verdict") == "passed" and frozen.get("rules_sha256") == v7.rules_digest(CONTRACT))
    if problem:
        assert v7.build_latest(ROOT, contract=CONTRACT)["status"] == "unavailable"


# ── 실행 전 감사에서 고친 것 ──────────────────────────────────────────────


def test_lookback_is_by_calendar_period_not_by_row_position() -> None:
    """발표되지 않은 달이 있으면 '12개월 전' 을 13행 전으로 대신하지 않는다."""
    days = [date(2019, 1, 1) + timedelta(days=i) for i in range(1300) if (date(2019, 1, 1) + timedelta(days=i)).weekday() < 5]
    months = [m for m in _months((2018, 1), (2022, 3)) if m != date(2019, 10, 1)]  # 2019-10 은 끝내 없다
    series = {"NASDAQCOM": [(d, 100.0 + i) for i, d in enumerate(days)],
              "CPIAUCSL": [(m, 100.0 * 1.01 ** ((m.year - 2018) * 12 + m.month - 1)) for m in months]}
    store = v7.Store(series, CONTRACT["series_lag_days"], CONTRACT["staleness_limits_days"])
    ok = v7.read(store, "inflation_yoy", store.session_index(date(2020, 9, 30)))    # 2020-08 대 2019-08
    assert ok[0] == pytest.approx(100.0 * (1.01 ** 12 - 1)) and ok[1] == ("2020-08",)
    assert v7.read(store, "inflation_yoy", store.session_index(date(2020, 11, 30))) is None  # 2020-10 은 2019-10 이 필요하다
    after = v7.read(store, "inflation_yoy", store.session_index(date(2020, 12, 31)))
    assert after[0] == pytest.approx(100.0 * (1.01 ** 12 - 1)) and after[1] == ("2020-11",)
    calc = v7.Calc(store, store.session_index(date(2020, 3, 31)))
    assert calc.window("CPIAUCSL", 3) is not None and calc.window("CPIAUCSL", 6) is None  # 이어지지 않은 창


def test_staleness_runs_from_first_visibility() -> None:
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(1300) if (date(2020, 1, 1) + timedelta(days=i)).weekday() < 5]
    oil = [(d, 50.0) for d in days if d <= date(2020, 2, 28)]
    store = v7.Store({"NASDAQCOM": [(d, 100.0) for d in days], "DCOILWTICO": oil},
                     CONTRACT["series_lag_days"], CONTRACT["staleness_limits_days"])
    lag, limit = CONTRACT["series_lag_days"]["DCOILWTICO"], CONTRACT["staleness_limits_days"]["daily"]
    last = date(2020, 2, 28)
    assert store.visible("DCOILWTICO", last + timedelta(days=lag + limit)) >= 0      # 보인 지 10일째까지는 쓴다
    assert store.visible("DCOILWTICO", last + timedelta(days=lag + limit + 3)) == -1
    assert store.visible("DCOILWTICO", last + timedelta(days=limit + 1), use_lags=False) == -1
    assert store.visible("UNKNOWN", last) == -1


def test_loaders_refuse_a_store_with_a_missing_series() -> None:
    with pytest.raises(v7.OverheatV7Error):
        v7._require_all({"NASDAQCOM": [1]}, "ledger")


def test_caps_are_per_line_and_pressure_needs_three_indicators() -> None:
    caps = CONTRACT["weights"]["caps"]
    assert caps["heat"] == {"indicator": 25, "family": 40, "price_term_total": 50}
    assert caps["pressure"] == {"indicator": 40, "family": 60}
    assert CONTRACT["scoring"]["minimum_eligible"] == {"heat": 4, "pressure": 3}
    assert len(CONTRACT["pre_run_amendments"]["changes"]) == 3 and "lookback" in CONTRACT["clarifications"]
    assert CONTRACT["rules_amended_before_run_at"] > CONTRACT["rules_fixed_at"]


def _tool():
    import importlib.util

    spec = importlib.util.spec_from_file_location("measure_overheat_influence_v7",
                                                  ROOT / "tools/measure_overheat_influence_v7.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measurement_tool_runs_once_and_its_frozen_block_drives_production(store: v7.Store, tmp_path: Path,
                                                                           monkeypatch) -> None:
    """합성 자료로 끝에서 끝까지: 공식 실행 → frozen → 재현 대조 → 매일의 값. 시험 실행과 재작성은 거부한다."""
    import json as _json

    tool = _tool()
    contract = copy.deepcopy(CONTRACT)
    contract["frozen"] = {}
    path = tmp_path / v7.CONTRACT_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False) , encoding="utf-8")
    (tmp_path / v7.INPUTS_RELATIVE).parent.mkdir(parents=True)
    (tmp_path / v7.INPUTS_RELATIVE).write_text(_json.dumps({"sha256": "synthetic"}), encoding="utf-8")
    monkeypatch.setattr(v7, "load_analysis_store", lambda _root, _contract: store)
    monkeypatch.setattr(v7, "load_ledger_store", lambda _root, _contract: store)
    monkeypatch.setattr(v7, "ritter_fingerprint", lambda _root: "synthetic")
    monkeypatch.setattr(tool, "ROOT", tmp_path)

    monkeypatch.setattr("sys.argv", ["tool", "--root", str(tmp_path)])
    with pytest.raises(SystemExit):  # frozen 이 비어 있는데 적지 않는 실행은 없다
        tool.main()
    (tmp_path / "docs/audit").mkdir(parents=True)
    monkeypatch.setattr("sys.argv", ["tool", "--root", str(tmp_path), "--write-frozen",
                                     "--report", "docs/audit/overheat_v7_test.md"])
    assert tool.main() == 0
    frozen = yaml.safe_load(path.read_text(encoding="utf-8"))["frozen"]
    report = _json.loads((tmp_path / "docs/audit/overheat_v7_test.json").read_text(encoding="utf-8"))
    assert frozen["verdict"] == report["verdict"] and frozen["rules_sha256"] == v7.rules_digest(contract)
    assert set(report["gates"]) == {f"G{n}" for n in range(1, 13)} and set(report["pressure_gates"]) == {"Q1", "Q2"}
    assert set(frozen["scores"]) == {row["id"] for row in CONTRACT["candidates"]} | {"nc_time_trend", "nc_shifted_nasdaq_m2"}
    assert frozen["episodes"] and all(e["low"] for e in frozen["episodes"])
    assert "| 순위 | 지표 |" in (tmp_path / "docs/audit/overheat_v7_test.md").read_text(encoding="utf-8")
    for gate in report["gates"].values():  # 값이 없는 게이트가 통과로 적히지 않는다
        assert not (gate["passed"] and gate.get("value") is None)

    monkeypatch.setattr("sys.argv", ["tool", "--root", str(tmp_path), "--write-frozen"])
    with pytest.raises(SystemExit):  # 한 번 적힌 판정은 다시 쓰지 않는다
        tool.main()
    monkeypatch.setattr("sys.argv", ["tool", "--root", str(tmp_path), "--report", "docs/audit/overheat_v7_test.md"])
    assert tool.main() == 0
    again = _json.loads((tmp_path / "docs/audit/overheat_v7_test.json").read_text(encoding="utf-8"))
    assert again["matches_frozen"] == {"verdict": True, "failed_gates": True, "heat_weights": True,
                                       "pressure_weights": True, "scores": True}

    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    now = datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc)
    live = v7.build_latest(tmp_path, now=now, ledger=store, contract=stored)
    if frozen["verdict"] == "passed":
        assert live["status"] == "ok" and live["index_raw"] == pytest.approx(report["measurement_band"]["base"], abs=0.11)
    else:
        assert live["status"] == "unavailable" and live["reason"] == "gates not passed"
    forced = copy.deepcopy(stored)  # 판정만 통과로 바꿔도, 값은 동결 숫자에서 그대로 나온다
    forced["frozen"]["verdict"] = "passed"
    if forced["frozen"].get("heat"):
        opened = v7.build_latest(tmp_path, now=now, ledger=store, contract=forced)
        assert opened["status"] == "ok" and opened["index_raw"] == pytest.approx(report["measurement_band"]["base"], abs=0.11)
        assert opened["family_band"] is None or opened["family_band"]["lo"] <= opened["family_band"]["hi"]


# ── 저장소에 기록된 판정과 순위표 표시 ────────────────────────────────────


def test_recorded_verdict_is_a_failed_composite_with_a_published_ranking() -> None:
    frozen = CONTRACT["frozen"]
    assert frozen["verdict"] == "failed" and frozen["heat"] is None and frozen["pressure"] is None
    assert frozen["rules_sha256"] == v7.rules_digest(CONTRACT) and frozen["gate_as_of"] == CONTRACT["gate_as_of"]
    assert set(frozen["scores"]) == {row["id"] for row in CONTRACT["candidates"]} | {"nc_time_trend", "nc_shifted_nasdaq_m2"}
    eligible = sorted(k for k, row in frozen["scores"].items() if row["status"] == "eligible")
    assert eligible == ["curve_10y_ff", "nasdaq_m2", "oil_change_12m", "shares_federal_debt", "speed_r24", "unemployment_rate"]
    assert all(frozen["scores"][k]["status"] == "control" for k in ("nc_time_trend", "nc_shifted_nasdaq_m2"))
    assert v7.frozen_problem(CONTRACT) == "gates not passed"
    assert v7.build_latest(ROOT, contract=CONTRACT)["status"] == "unavailable"  # 지수는 닫혀 있다

    shown = v7.load_influence(ROOT)
    assert shown["status"] == "ok" and shown["composite"] is None and shown["index_verdict"] == "failed"
    assert shown["candidates"] == 35 and shown["beyond_chance"] == 6 and shown["trading_signal"] is False
    assert [row["rank"] for row in shown["rows"]] == list(range(1, 36))
    assert not any(row["id"].startswith("nc_") for row in shown["rows"])  # 대조군은 화면에 없다
    assert all(row["weight"] is None for row in shown["rows"])  # 가중은 정해지지 않았다
    assert {row["evidence"] for row in shown["rows"]} <= {"beyond_chance", "duplicate", "chance", "weak", "none", "unscored"}
    assert shown["rows"][0]["id"] == "speed_r24" and shown["rows"][0]["score"] == 89


def test_ranking_is_shown_as_a_table_and_the_index_is_not_wired() -> None:
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    block = script[script.index("function overheatInfluenceBlock"):script.index("function statisticsOverheatPanel")]
    assert "합산 지수 아님" in block and "대표값 가중치 아님" in block and "참고 의견" in block
    assert "reduce(" not in block and "<svg" not in block  # 화면에서도 합치지 않고, 글자는 HTML 로만
    panel = script[script.index("function statisticsOverheatPanel"):script.index("function predictionSectionNav")]
    assert panel.count("overheatInfluenceBlock(DATA.dotcom_overheat_influence)") == 1
    board = (ROOT / "src/ai_fc/dashboard.py").read_text(encoding="utf-8")
    assert '"dotcom_overheat_influence": dotcom_overheat_influence' in board
    assert "build_latest" not in board.split("dotcom_overheat_v7 import")[1].split("\n")[0]  # 순위표만 읽는다
    workflow = (ROOT / ".github/workflows/statistics-refresh.yml").read_text(encoding="utf-8")
    assert "overheat_v7" not in workflow and "overheat-v7" not in workflow  # 닫힌 지수는 갱신 배선에 넣지 않는다


def test_ranking_loader_never_raises_and_closes_when_rules_change(tmp_path: Path) -> None:
    assert v7.load_influence(tmp_path)["status"] == "unavailable"  # 계약이 없다
    edited = copy.deepcopy(CONTRACT)
    edited["scoring"]["P1_rank_association"]["max"] = 50
    path = tmp_path / v7.CONTRACT_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(edited, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert v7.load_influence(tmp_path)["reason"] == "ranking not measured for the current rules"
    path.write_text("not: [valid", encoding="utf-8")
    assert v7.load_influence(tmp_path)["status"] == "unavailable"
