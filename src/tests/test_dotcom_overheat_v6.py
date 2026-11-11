"""닷컴 대비 과열도 v6 — 계산 규칙·발표 지연·보류·이력(추가 전용)과 두 계약의 판정 기록 (네트워크·원장 없음)."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from ai_fc import dotcom_overheat_v6 as v6
from ai_fc.ipo_monthly_counts import IPOMonthlyCountsError, parse_ritter_first_day_returns_rows

ROOT = Path(__file__).resolve().parents[2]
V60 = yaml.safe_load((ROOT / v6.REGISTERED_V60_RELATIVE).read_text(encoding="utf-8"))
V61 = yaml.safe_load((ROOT / v6.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
BUDGETS = {f: float(v["budget"]) for f, v in V61["families"].items()}
MEMBERS = {"speed": ["speed_r24", "speed_d200"], "valuation": ["val_nasdaq_m2"], "ipo": ["ipo_count_12m"],
           "participation": [], "real": ["real_it_equipment_gdp"]}


def _bump(day: date) -> float:
    """2000-03-10 에 1, 양옆으로 1년쯤에 걸쳐 0 으로 — 합성 '닷컴' 봉우리."""
    return math.exp(-(((day - v6.PEAK_DAY).days / 300.0) ** 2))


def _quarters(first_year: int, last_year: int) -> list[date]:
    return [date(y, m, 1) for y in range(first_year, last_year + 1) for m in (1, 4, 7, 10)]


@pytest.fixture(scope="module")
def inp() -> v6.Inputs:
    day, sessions = date(1992, 1, 1), []
    while day <= date(2026, 11, 9):
        if day.weekday() < 5:
            sessions.append(day)
        day += timedelta(days=1)
    wave = lambda d: 0.08 * math.sin(d.toordinal() / 9.0) + 0.05 * math.sin(d.toordinal() / 37.0)
    rows = {"NASDAQCOM": [{"date": d.isoformat(),
                           "value": 500.0 * math.exp(0.00012 * i + 1.3 * _bump(d) + wave(d))}
                          for i, d in enumerate(sessions)]}
    months = [date(y, m, 1) for y in range(1994, 2027) for m in range(1, 13) if (y, m) <= (2026, 9)]
    rows["M2SL"] = [{"date": d.isoformat(), "value": 3000.0 * 1.004 ** i} for i, d in enumerate(months)]
    quarters = [q for q in _quarters(1994, 2026) if q <= date(2026, 7, 1)]
    gdp = {q: 7000.0 * 1.011 ** i for i, q in enumerate(quarters)}
    rows["GDP"] = [{"date": q.isoformat(), "value": gdp[q]} for q in quarters]
    rows["Y034RC1Q027SBEA"] = [{"date": q.isoformat(), "value": gdp[q] * (0.02 + 0.008 * _bump(q))} for q in quarters]
    rows["W328RC1Q027SBEA"] = [{"date": q.isoformat(), "value": gdp[q] * 0.06} for q in quarters]
    z1 = [q for q in quarters if q <= date(2026, 4, 1)]
    rows["NCBEILQ027S"] = [{"date": q.isoformat(), "value": gdp[q] * 1000 * (1.0 + 1.5 * _bump(q))} for q in z1]
    rows["FL663067003"] = [{"date": q.isoformat(), "value": gdp[q] * 1000 * (0.014 + 0.012 * _bump(q))} for q in z1]
    rows["BOGZ1LM153064475Q"] = [{"date": q.isoformat(), "value": 2.0 + 1.0 * _bump(q)} for q in z1]
    rows["DABSHNO"] = [{"date": q.isoformat(), "value": 1.0} for q in z1]
    rows["BOGZ1LM893064105Q"] = [{"date": q.isoformat(), "value": gdp[q] * 1000 * 1.5} for q in z1]
    ritter = {f"{y:04d}-{m:02d}": {"net": float(round(10 + 35 * _bump(date(y, m, 1)))),
                                   "first_day": 15.0 + 60.0 * _bump(date(y, m, 1))}
              for y in range(1990, 2026) for m in range(1, 13)}
    return v6.Inputs(rows, ritter)


@pytest.fixture(scope="module")
def contract(inp: v6.Inputs) -> dict:
    contract = copy.deepcopy(V61)
    contract["frozen"] = {**v6.admission(inp, contract), "verdict": "passed",
                          "rules_sha256": v6.rules_digest(contract)}
    return contract


# ── 가중 규칙 ─────────────────────────────────────────────────────────────


def test_registered_cap_rule_funnels_the_excess_into_one_family() -> None:
    """v6.0 이 탈락한 이유 — 단일 지표 부문이 셋이면 등록 규칙이 speed 에 70 을 준다."""
    assert v6.contract_cap(V60) == 10.0
    weights = v6.family_weights(BUDGETS, MEMBERS, v6.contract_cap(V60))
    assert {f: round(w, 6) for f, w in weights.items()} == {"speed": 70.0, "valuation": 10.0, "ipo": 10.0, "real": 10.0}


def test_amended_rule_renormalises_declared_budgets_without_new_numbers() -> None:
    assert v6.contract_cap(V61) is None
    weights = v6.family_weights(BUDGETS, MEMBERS, v6.contract_cap(V61))
    assert weights == {"speed": 31.25, "valuation": 31.25, "ipo": 18.75, "real": 18.75}
    full = {f: ["x", "y"] for f in BUDGETS}
    assert v6.family_weights(BUDGETS, full, None) == {f: b for f, b in BUDGETS.items()}  # 다 차면 선언 예산 그대로
    assert v6.family_weights(BUDGETS, {f: [] for f in BUDGETS}, None) == {}


def test_aggregate_is_linear_and_holds_when_live_weight_is_short() -> None:
    weights = v6.family_weights(BUDGETS, MEMBERS, None)
    scores = {"speed_r24": 30.0, "speed_d200": 10.0, "val_nasdaq_m2": 200.0, "ipo_count_12m": -80.0,
              "real_it_equipment_gdp": 100.0}
    out = v6.aggregate(scores, MEMBERS, weights, clamp=(-50.0, 150.0), hold_below=70.0)
    assert out["status"] == "ok" and out["live_weight"] == 100.0
    assert out["composite"] == pytest.approx(sum(out["contributions"].values()))
    assert out["families"]["valuation"] == 150.0 and out["families"]["ipo"] == -50.0  # 합산 때만 제한
    assert sum(out["indicator_weights"].values()) == pytest.approx(100.0)
    unclamped = v6.aggregate(scores, MEMBERS, weights, clamp=None, hold_below=70.0)
    assert unclamped["families"]["valuation"] == 200.0

    missing = {k: v for k, v in scores.items() if k != "speed_d200"}  # 부문 안에서 재정규화
    out = v6.aggregate(missing, MEMBERS, weights, clamp=(-50.0, 150.0), hold_below=70.0)
    assert out["indicator_weights"]["speed_r24"] == pytest.approx(31.25) and out["live_weight"] == pytest.approx(84.4)

    short = {"speed_r24": 30.0, "speed_d200": 10.0, "ipo_count_12m": 5.0}  # 31.25 + 18.75 = 50 < 70
    out = v6.aggregate(short, MEMBERS, weights, clamp=(-50.0, 150.0), hold_below=70.0)
    assert out["status"] == "hold" and out["composite"] is None


# ── 지표와 발표 지연 ──────────────────────────────────────────────────────


def test_quarterly_value_is_not_used_before_its_fixed_publication_lag(inp: v6.Inputs, contract: dict) -> None:
    spec = v6.Spec(contract)
    lag = int(contract["publication_lags_days"]["GDP"])
    release = date(2010, 3, 31) + timedelta(days=lag)  # 2010Q1 은 분기말 + 지연 뒤에야 보인다
    before = v6.indicator_value(inp, "real_it_equipment_gdp", inp.session_index(release - timedelta(days=1)), spec)
    after = v6.indicator_value(inp, "real_it_equipment_gdp", inp.session_index(release + timedelta(days=3)), spec)
    assert before["period"] == "2009Q4" and after["period"] == "2010Q1"
    live = v6.indicator_value(inp, "real_it_equipment_gdp", inp.session_index(date(2010, 3, 31)), spec.with_lags(False))
    assert live["period"] == "2010Q1" and spec.lags is True  # with_lags 는 원본을 바꾸지 않는다


def test_daily_indicators_follow_the_registered_definitions(inp: v6.Inputs, contract: dict) -> None:
    spec, index = v6.Spec(contract), inp.session_index(date(2015, 6, 30))
    base = sum(inp.close[index - 524:index - 484]) / 40
    assert v6.indicator_value(inp, "speed_r24", index, spec)["value"] == pytest.approx(math.log(inp.close[index] / base))
    mean200 = sum(inp.close[index - 199:index + 1]) / 200
    assert v6.indicator_value(inp, "speed_d200", index, spec)["value"] == pytest.approx(inp.close[index] / mean200 - 1)
    shocked = v6.indicator_value(inp, "speed_d200", index, spec, close=inp.close[index] * 1.1)["value"]
    assert shocked > v6.indicator_value(inp, "speed_d200", index, spec)["value"]
    m2 = v6.indicator_value(inp, "val_nasdaq_m2", index, spec)
    assert m2["period"] == "2015-05"  # 5월 말 + 28일 ≤ 6월 30일, 6월 치는 아직
    assert v6.indicator_value(inp, "speed_r24", 100, spec) is None


def test_estimate_marks_a_carried_quarter_to_market_and_is_labelled(inp: v6.Inputs, contract: dict) -> None:
    index = inp.session_index(date(2015, 8, 20))
    carried = v6.indicator_value(inp, "part_household_equity", index, v6.Spec(contract))
    spec = v6.Spec(contract, betas={"part_household_equity": 0.6}, estimated=["part_household_equity"])
    est = v6.indicator_value(inp, "part_household_equity", index, spec)
    anchor = inp.close[inp.session_index(date(2015, 3, 31))]
    assert carried["basis"] == "carried" and est["basis"] == "estimate" and est["period"] == carried["period"] == "2015Q1"
    assert est["value"] == pytest.approx(carried["value"] * (inp.close[index] / anchor) ** 0.6)


def test_first_day_return_is_unscored_below_the_deal_floor(inp: v6.Inputs) -> None:
    assert v6.ritter_value(inp, "ipo_count_12m", "2010-06", min_deals=50) == 120.0
    assert v6.ritter_value(inp, "ipo_first_day_12m", "2010-06", min_deals=50) == pytest.approx(15.0, abs=0.01)
    assert v6.ritter_value(inp, "ipo_first_day_12m", "2010-06", min_deals=500) is None  # A7
    assert v6.ritter_value(inp, "ipo_count_12m", "1990-05", min_deals=0) is None  # 12개월이 안 찬다


def test_first_day_return_parser_keeps_missing_cells_missing() -> None:
    rows = [["Month", "Year", "Avg 1st day", "Gross", "Net"], [1, 99, 62.5, 50, 40], [2, 99, ".", 30, 20],
            [3, 0, "na", 10, 5], [4, 0, None, 9, 4]]
    assert parse_ritter_first_day_returns_rows(rows) == {"1999-01": 62.5, "1999-02": None, "2000-03": None,
                                                        "2000-04": None}
    with pytest.raises(IPOMonthlyCountsError):
        parse_ritter_first_day_returns_rows([[1, 99, 5000.0, 50, 40]])
    with pytest.raises(IPOMonthlyCountsError):
        parse_ritter_first_day_returns_rows([[1, 99, 5.0, 50, 40], [1, 99, 6.0, 50, 40]])


# ── 합성 자료 끝에서 끝까지 ───────────────────────────────────────────────


def test_anchors_scale_and_admission_are_reproducible(inp: v6.Inputs, contract: dict) -> None:
    frozen = contract["frozen"]
    assert frozen["anchors"]["speed_r24"]["zero"] == 0.0  # 수익률형의 0 은 자연 0
    official = dict(v6.official_quarterly(inp, "real_it_equipment_gdp"))
    assert frozen["anchors"]["real_it_equipment_gdp"]["peak"] == pytest.approx(official[v6.PEAK_QUARTER])
    assert set(frozen["tests"]) == {row["id"] for row in contract["indicators"]}  # 탈락도 기록
    assert sum(frozen["weights"].values()) == pytest.approx(100.0, abs=0.01)
    assert v6.anchor_drift(inp, contract) == []
    moved = copy.deepcopy(contract)
    key = next(iter(sum(frozen["members"].values(), [])))
    moved["frozen"]["anchors"][key]["peak"] *= 1.05
    assert key in v6.anchor_drift(inp, moved)
    assert v6.spec_digest(moved) != v6.spec_digest(contract)


def test_evaluate_band_and_gates_are_consistent(inp: v6.Inputs, contract: dict) -> None:
    cache: dict = {}
    last = len(inp.sessions) - 1
    today = v6.evaluate(inp, contract, last, cache=cache, detail=True)
    assert today["status"] == "ok"
    assert today["composite"] == pytest.approx(sum(today["contributions"].values()))
    band = v6.band(inp, contract, last, cache)
    assert band["lo"] <= today["composite"] <= band["hi"] and band["held_variants"] == []
    assert set(band["variants"]) == {"base", *v6.variant_ids(contract)}
    peak = v6.evaluate(inp, contract, inp.session_index(v6.PEAK_DAY), cache=cache)["composite"]
    quiet = v6.evaluate(inp, contract, inp.session_index(date(2013, 6, 28)), cache=cache)["composite"]
    assert peak > 60 and abs(quiet) < 25  # 봉우리에서 뜨겁고 평온기에 0 근처

    history = v6.replay(inp, contract, start=date(1996, 1, 2), cache=cache)
    gates = v6.evaluate_gates(inp, contract, history, cache)
    assert set(gates["construction_checks"]) == {"C1", "C2", "C3", "C4", "C5"}
    assert set(gates["falsifiable"]) == {f"V{n}" for n in range(1, 13)}
    assert gates["construction_checks"]["C5"]["passed"] is None  # 여기서 판정하지 않는다
    assert gates["failed"] == [k for k, g in gates["falsifiable"].items() if not g["passed"]]

    short = v6.evaluate_gates(inp, contract, history[-300:], cache)  # 구간이 비면 예외가 아니라 실패
    assert short["falsifiable"]["V5"]["passed"] is False and "not evaluable" in short["falsifiable"]["V5"]["reason"]
    assert short["all_falsifiable_passed"] is False


def test_unknown_variant_is_rejected(inp: v6.Inputs, contract: dict) -> None:
    with pytest.raises(v6.OverheatV6Error):
        v6.evaluate(inp, contract, len(inp.sessions) - 1, variant="made_up", cache={})


# ── 산출물: 닫힌 상태·보류·추가 전용 이력 ─────────────────────────────────


def _root(tmp_path: Path, contract: dict) -> Path:
    path = tmp_path / v6.CONTRACT_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(contract, allow_unicode=True), encoding="utf-8")
    return tmp_path


NOW = datetime(2026, 11, 10, 1, 0, tzinfo=timezone.utc)


def test_nothing_is_published_unless_the_frozen_verdict_passed(tmp_path: Path, contract: dict, monkeypatch) -> None:
    failed = copy.deepcopy(contract)
    failed["frozen"]["verdict"] = "failed"
    root = _root(tmp_path, failed)
    monkeypatch.setattr(v6, "load_inputs", lambda _root: pytest.fail("ledger must not be read"))
    out = v6.materialize(root, now=NOW)
    assert out["latest"]["status"] == "unavailable" and out["latest"]["reason"] == "gates not passed"
    assert out["history_appended"] == 0 and not (root / v6.HISTORY_RELATIVE).exists()
    assert v6.load_latest(root)["status"] == "unavailable"

    edited = copy.deepcopy(contract)  # 판정 뒤 규칙이 바뀌면 통과 판정도 무효다
    edited["families"]["speed"]["budget"] = 60
    assert v6.frozen_binding_problem(edited) == "frozen block does not match the contract rules"
    assert v6.build_latest(root, contract=edited)["status"] == "unavailable"
    forged = copy.deepcopy(contract)  # 동결 가중이 규칙이 내는 가중과 다르면 닫는다
    forged["frozen"]["weights"] = {f: 100.0 / len(forged["frozen"]["weights"]) + (5 if i == 0 else 0)
                                   for i, f in enumerate(forged["frozen"]["weights"])}
    assert v6.frozen_binding_problem(forged) == "frozen weights do not match the weight rule"
    assert v6.frozen_binding_problem(contract) is None
    unfrozen = copy.deepcopy(contract)
    unfrozen["frozen"] = {}
    assert v6.frozen_binding_problem(unfrozen) == "contract not frozen"


def test_materialize_backfills_once_and_only_appends(tmp_path: Path, inp: v6.Inputs, contract: dict, monkeypatch) -> None:
    root = _root(tmp_path, contract)
    monkeypatch.setattr(v6, "load_inputs", lambda _root: inp)
    first = v6.materialize(root, now=NOW)
    latest = first["latest"]
    assert latest["status"] == "ok" and latest["comparison_basis"] == "history"
    assert latest["probability_space"] == "reference_only" and latest["trading_signal"] is False
    assert latest["band"]["lo"] <= latest["index"] <= latest["band"]["hi"]
    assert sum(row["contribution"] for row in latest["indicators"]) == pytest.approx(latest["index_raw"], abs=0.1)
    assert sum(latest["data_age_split"].values()) == pytest.approx(100.0, abs=0.2)
    assert [f["id"] for f in latest["unmeasured_families"]] == [f for f, ids in contract["frozen"]["members"].items()
                                                                 if not ids]
    history_path = root / v6.HISTORY_RELATIVE
    before = history_path.read_bytes()
    rows = [json.loads(line) for line in before.decode("utf-8").splitlines()]
    assert first["history_appended"] == len(rows) > 7000
    assert rows[-1]["basis"] == "as_published" and rows[-1]["date"] == latest["as_of"]
    assert {row["basis"] for row in rows[:-1]} == {"retro_backfill"} and {row["spec"] for row in rows} == {latest["spec"]}

    again = v6.materialize(root, now=NOW)  # 같은 날 같은 값 — 아무것도 덧붙이지 않는다
    assert again["history_appended"] == 0 and history_path.read_bytes() == before

    changed = copy.deepcopy(contract)  # 사양이 바뀌면 새 지문으로 다시 채우고 옛 행은 그대로 둔다
    changed["frozen"]["anchors"][next(iter(sum(contract["frozen"]["members"].values(), [])))]["zero"] = -0.5
    _root_path = root / v6.CONTRACT_RELATIVE
    _root_path.write_text(yaml.safe_dump(changed, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(v6, "anchor_drift", lambda _inp, _contract: [])
    third = v6.materialize(root, now=NOW)
    after = history_path.read_bytes()
    assert after.startswith(before) and third["history_appended"] == len(rows)
    shown = v6.history_for_display(root)
    assert shown[-1] == [latest["as_of"], third["latest"]["index_raw"], "p"] and shown[-2][2] == "r"
    assert len(shown) < 1000  # 월말 + 최근 거래일만

    assert v6.load_latest(root)["status"] == "ok"
    stale = dict(third["latest"], spec="another-spec")  # 다른 사양의 산출물은 화면에 내보내지 않는다
    (root / v6.LATEST_RELATIVE).write_text(json.dumps(stale), encoding="utf-8")
    assert v6.load_latest(root)["reason"] == "v6 output belongs to another frozen specification"
    assert v6.history_for_display(root) == []


def test_stale_nasdaq_and_anchor_drift_close_the_index(tmp_path: Path, inp: v6.Inputs, contract: dict, monkeypatch) -> None:
    root = _root(tmp_path, contract)
    monkeypatch.setattr(v6, "load_inputs", lambda _root: inp)
    late = v6.materialize(root, now=NOW + timedelta(days=30))
    assert late["latest"]["status"] == "hold" and "NASDAQ ledger" in late["latest"]["reason"]
    assert late["history_appended"] == 0 and not (root / v6.HISTORY_RELATIVE).exists()  # 보류 중에는 이력을 쓰지 않는다
    monkeypatch.setattr(v6, "anchor_drift", lambda _inp, _contract: ["val_nasdaq_m2"])
    drift = v6.materialize(root, now=NOW)
    assert drift["latest"]["status"] == "hold" and "anchor drift" in drift["latest"]["reason"]
    assert not (root / v6.HISTORY_RELATIVE).exists()


def test_history_index_prefers_published_rows_of_the_current_spec() -> None:
    rows = [{"date": "2026-11-06", "index_raw": 1.0, "basis": "retro_backfill", "spec": "old"},
            {"date": "2026-11-06", "index_raw": 2.0, "basis": "retro_backfill", "spec": "new"},
            {"date": "2026-11-09", "index_raw": 3.0, "basis": "as_published", "spec": "new"},
            {"date": "2026-11-09", "index_raw": 4.0, "basis": "retro_backfill", "spec": "new"},
            {"date": "2026-11-09", "index_raw": 5.0, "basis": "as_published", "spec": "new"}]
    index = v6._history_index(rows, "new")
    assert index["2026-11-06"]["index_raw"] == 2.0 and index["2026-11-09"]["index_raw"] == 5.0


def test_gate_dates_beyond_the_replay_are_not_substituted() -> None:
    history = [{"date": date(2020, 1, 2), "composite": 1.0}, {"date": date(2020, 1, 3), "composite": 2.0}]
    assert v6._value_on(history, date(2020, 1, 3)) == 2.0
    assert v6._value_on(history, date(2020, 1, 6)) is None  # 마지막 값으로 대신하지 않는다
    assert v6._value_on(history, date(2019, 12, 31)) is None


def _tool():
    spec = importlib.util.spec_from_file_location("verify_overheat_v6_shadow",
                                                  ROOT / "tools/verify_overheat_v6_shadow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_never_rewrites_a_judged_frozen_block(tmp_path: Path) -> None:
    tool = _tool()
    empty = tmp_path / "empty.yaml"
    empty.write_text("version: x\n\nfrozen: {}   # 채운다\n", encoding="utf-8")
    tool.write_frozen(empty, {"verdict": "failed", "failed_gates": ["V8"]})
    assert yaml.safe_load(empty.read_text(encoding="utf-8")) == {
        "version": "x", "frozen": {"verdict": "failed", "failed_gates": ["V8"]}}
    with pytest.raises(SystemExit):  # 이미 판정이 적혀 있다
        tool.write_frozen(empty, {"verdict": "passed"})
    trailing = tmp_path / "trailing.yaml"
    trailing.write_text("version: x\n\nfrozen: {}\nlater_key: 1\n", encoding="utf-8")
    with pytest.raises(SystemExit):  # frozen 뒤에 다른 내용이 있으면 자르지 않는다
        tool.write_frozen(trailing, {"verdict": "failed"})
    assert "later_key" in trailing.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        tool.report_path(ROOT, "data/contracts/overheat_v6_x.md")
    with pytest.raises(SystemExit):
        tool.report_path(ROOT, "docs/audit/other_report.md")
    assert tool.report_path(ROOT, "docs/audit/overheat_v6_x.md").name == "overheat_v6_x.md"


# ── 두 계약의 판정 기록 ───────────────────────────────────────────────────


def test_both_contracts_are_recorded_as_failed_and_v5_stays_public() -> None:
    assert V60["frozen"]["verdict"] == "failed" and V60["frozen"]["failed_gates"] == ["V9", "V10", "V12"]
    assert V61["frozen"]["verdict"] == "failed" and V61["frozen"]["failed_gates"] == ["V8", "V12"]
    assert V60["frozen"]["gate_as_of"] == V61["frozen"]["gate_as_of"] == V61["gate_as_of"]
    assert V60["frozen"]["input_sha256"] == V61["frozen"]["input_sha256"] == V61["gate_input_sha256"]
    assert V60["frozen"]["members"] == V61["frozen"]["members"]  # 편입은 같고 가중 규칙만 다르다
    assert v6.frozen_binding_problem(V60) == v6.frozen_binding_problem(V61) == "gates not passed"
    assert len(V61["errata"]) >= 7  # 판정 뒤 찾은 과장·오기는 지우지 않고 적는다
    assert v6.build_latest(ROOT)["status"] == "unavailable"
    assert v6.load_latest(ROOT)["status"] == "unavailable"
    for name in ("dashboard.py", "dashboard_parts/dashboard.js", "statistics_freshness.py"):
        assert "overheat_v6" not in (ROOT / "src/ai_fc" / name).read_text(encoding="utf-8"), name


def test_amendment_changes_only_the_weight_rule() -> None:
    for group in ("construction_checks", "falsifiable"):
        assert [(g["id"], g["rule"]) for g in V60["gates"][group]] == [(g["id"], g["rule"]) for g in V61["gates"][group]]
        assert {g["blindness"] for g in V61["gates"][group]} == {"seen_after_v6_0"}
    for key in ("scale", "publication_lags_days", "staleness_limits_days", "hold_when_live_weight_below", "families",
                "indicators", "admission_tests", "aggregation", "band", "estimate"):
        assert V60[key] == V61[key], key
    assert "single_member_family_cap" in V60["weight_rule"] and "single_member_family_cap" not in V61["weight_rule"]
    assert V61["amends"] == "dotcom_overheat_index_v6" and "stop_rule" in V61["revision"]
    for contract in (V60, V61):
        assert contract["probability_space"] == "reference_only" and contract["trading_signal"] is False
