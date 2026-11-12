"""닷컴 대비 과열도 v8 — 판단 가중 평균: 규칙에서 유도된 가중만 쓴다, 중복은 한 번만 센다, 닫힐 때 닫힌다 (네트워크 없음)."""

from __future__ import annotations

import copy
import statistics
from pathlib import Path

import pytest
import yaml

from ai_fc import dotcom_overheat_v7 as v7
from ai_fc import dotcom_overheat_v8 as v8
from ai_fc.overheat_watchdog import check_weighted

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = v8.load_contract(ROOT)
V7 = v7.load_contract(ROOT)
IDS = [spec["id"] for spec in CONTRACT["indicators"]]
CARD = [spec["id"] for spec in CONTRACT["indicators"] if spec["source"] == "v5"]
SPEED = [spec["id"] for spec in CONTRACT["indicators"] if spec["source"] == "profile"]


def _v5(values: dict[str, float]) -> dict:
    return {"status": "ok", "contract_id": "dotcom_overheat_index_v5", "overheat_pct": 54, "as_of": "2026-11-10",
            "indicators": [{"id": key, "pct": value} for key, value in values.items()]}


def _profile(values: dict[str, float]) -> dict:
    return {"status": "ok", "as_of": "2026-11-10",
            "families": [{"id": "speed", "indicators": [{"id": key, "status": "ok", "score_raw": value}
                                                         for key, value in values.items()]}]}


def _root(tmp_path: Path, contract: dict) -> Path:
    for relative, body in ((v8.CONTRACT_RELATIVE, contract), (v7.CONTRACT_RELATIVE, V7)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp_path


def test_contract_is_a_declared_judgment_and_frozen_block_derives_from_the_rules() -> None:
    assert CONTRACT["status"] == "declared_judgment" and CONTRACT["probability_space"] == "reference_only"
    assert CONTRACT["trading_signal"] is False and CONTRACT["model_use"] is False
    assert CONTRACT["official_forecast_input"] is False and CONTRACT["decided_by"] == "user"
    assert any("판단값" in line and "검증" in line for line in CONTRACT["disclosures"])  # 검증됐다고 말하지 않는다
    assert v8.frozen_problem(CONTRACT, V7) is None
    frozen = CONTRACT["frozen"]
    assert frozen == v8.derive_frozen(CONTRACT, V7) and frozen["rules_sha256"] == v8.rules_digest(CONTRACT)
    assert list(frozen["indicators"]) == IDS and len(IDS) == 16
    assert sum(row["weight"] for row in frozen["indicators"].values()) == pytest.approx(1.0, abs=1e-4)
    assert sum(frozen["group_weights"].values()) == pytest.approx(1.0, abs=1e-4)
    for row in frozen["indicators"].values():
        assert row["points"] == row["A"] + row["B"] + row["C"] and 0 <= row["points"] <= 10


def test_panel_scores_are_recorded_and_the_owner_override_is_the_only_hand_set_value() -> None:
    panel = CONTRACT["panel"]
    assert set(panel["values"]) == set(panel["median"]) == set(IDS)
    for key in IDS:
        assert len(panel["values"][key]) == 5 and all(0 <= v <= 5 for v in panel["values"][key])
        assert panel["median"][key] == statistics.median(panel["values"][key])
    override = CONTRACT["points"]["A"]["owner_override"]
    assert override == {"ipo_count_operating_12m": 5}  # "닷컴 때 중소 IPO 많아질 때 무너졌으니 그 부분이 영향도 높다"
    rows = CONTRACT["frozen"]["indicators"]
    assert [key for key in IDS if rows[key]["a_source"] == "owner"] == ["ipo_count_operating_12m"]
    for key in IDS:
        assert rows[key]["A"] == (override[key] if key in override else panel["median"][key])


def test_evidence_and_direction_points_are_read_mechanically() -> None:
    evidence = v8.evidence_by_candidate(V7)
    b_map, cut = CONTRACT["points"]["B"]["map"], CONTRACT["points"]["C"]["thresholds"]
    rows = CONTRACT["frozen"]["indicators"]
    for spec in CONTRACT["indicators"]:
        row = rows[spec["id"]]
        assert spec["v7_id"] in evidence  # v7 이 실제로 잰 후보에만 대응시킨다
        assert row["evidence"] == evidence[spec["v7_id"]] and row["B"] == b_map[row["evidence"]]
        end = spec["dotcom_end_position"]
        assert row["C"] == (2 if end >= cut["two"] else 1 if end >= cut["one"] else 0)
    assert rows["speed_r24"]["B"] == 3 and rows["corporate_bond_stock"]["B"] == 0  # 측정이 반대로 나온 것은 근거 0점
    assert rows["financial_conditions"]["C"] == 0 and rows["bond_spread"]["C"] == 0  # 정점 때 이미 조여지고 있었다


def test_duplicates_form_one_group_and_count_once() -> None:
    points = {"a": 8.0, "b": 8.0, "c": 8.0, "solo": 8.0, "weak": 2.0}
    groups = {"a": "dup", "b": "dup", "c": "dup", "solo": "one", "weak": "low"}
    share = v8.weights(points, groups, list(points))
    assert sum(share.values()) == pytest.approx(1.0)
    assert share["a"] + share["b"] + share["c"] == pytest.approx(share["solo"])  # 세 번 재도 한 번만 센다
    assert share["a"] == pytest.approx(share["solo"] / 3) and share["weak"] == pytest.approx(share["solo"] / 4)
    mixed = v8.weights({"a": 9.0, "b": 3.0, "solo": 6.0}, {"a": "dup", "b": "dup", "solo": "one"}, ["a", "b", "solo"])
    assert mixed["a"] + mixed["b"] == pytest.approx(mixed["solo"])  # 묶음 점수 = 구성 지표 점수의 평균
    flat = v8.weights(points, groups, list(points), "equal_indicators")
    assert set(flat.values()) == {0.2}
    even = v8.weights(points, groups, list(points), "equal_groups")
    assert even["solo"] == pytest.approx(1 / 3) and even["a"] == pytest.approx(1 / 9)
    with pytest.raises(v8.OverheatV8Error):
        v8.weights(points, groups, list(points), "fitted")
    frozen = CONTRACT["frozen"]
    by_group: dict[str, list[str]] = {}
    for spec in CONTRACT["indicators"]:
        by_group.setdefault(spec["group"], []).append(spec["id"])
    assert len(by_group["price_vs_money"]) == 3 and len(by_group["conditions"]) == 3 and len(by_group["speed"]) == 2
    for name, ids in by_group.items():
        assert {frozen["indicators"][key]["weight"] for key in ids} == {frozen["indicators"][ids[0]]["weight"]}
        assert frozen["group_points"][name] == pytest.approx(
            statistics.fmean(frozen["indicators"][key]["points"] for key in ids), abs=1e-4)


def test_weighted_average_is_the_declared_sum_and_clamps_only_inside_the_average() -> None:
    flat = v8.compute(ROOT, v5=_v5({key: 50.0 for key in CARD}), profile=_profile({key: 50.0 for key in SPEED}))
    assert flat["status"] == "ok" and flat["overheat_pct"] == 50 and flat["value_raw"] == 50.0
    assert flat["variants"] == {"declared": 50.0, "equal_groups": 50.0, "equal_indicators": 50.0}
    assert flat["range"]["low"] == flat["range"]["high"] == 50 and flat["live_weight"] == 1.0
    assert flat["weights_basis"] == "declared_judgment" and flat["probability_space"] == "reference_only"
    assert flat["trading_signal"] is False and flat["previous_formula"]["overheat_pct"] == 54

    readings = {key: float(10 * index) for index, key in enumerate(CARD)}
    readings["investment_share_gdp"] = 260.3
    readings["consumer_credit_growth"] = -80.0
    speed = {"speed_r24": 27.8, "speed_d200": -0.4}
    out = v8.compute(ROOT, v5=_v5(readings), profile=_profile(speed))
    weights = {key: row["weight"] for key, row in CONTRACT["frozen"]["indicators"].items()}
    clamp = lambda value: min(150.0, max(-50.0, value))  # noqa: E731
    expected = sum(weights[key] * clamp({**readings, **speed}[key]) for key in IDS)
    assert out["value_raw"] == pytest.approx(expected, abs=0.06) and out["overheat_pct"] == int(round(out["value_raw"]))
    rows = {row["id"]: row for row in out["indicators"]}
    assert rows["investment_share_gdp"]["reading"] == 260.3 and rows["investment_share_gdp"]["clamped"] is True
    assert rows["consumer_credit_growth"]["reading"] == -80.0 and rows["consumer_credit_growth"]["clamped"] is True
    assert out["clamped_count"] == 2 and rows["speed_r24"]["clamped"] is False  # 행에는 원값, 평균에만 자른 값
    assert sum(group["contribution"] for group in out["groups"]) == pytest.approx(out["value_raw"], abs=0.3)
    assert sum(group["weight_pct"] for group in out["groups"]) == pytest.approx(100.0, abs=0.3)
    assert out["range"]["low"] <= out["overheat_pct"] <= out["range"]["high"] or out["range"]["low_variant"] == "declared" \
        or out["range"]["high_variant"] == "declared"
    assert out["range"]["low"] == int(round(min(out["variants"].values())))
    assert out["range"]["high"] == int(round(max(out["variants"].values())))


def test_missing_readings_are_reweighted_and_too_little_live_weight_holds() -> None:
    card = {key: 40.0 for key in CARD}
    no_speed = v8.compute(ROOT, v5=_v5(card), profile={"status": "hold", "reason": "old"})
    assert no_speed["status"] == "ok" and no_speed["missing"] == SPEED and no_speed["overheat_pct"] == 40
    assert no_speed["speed_as_of"] is None and no_speed["included"] == 14 and 0.7 <= no_speed["live_weight"] < 1.0
    assert all(group["id"] != "speed" for group in no_speed["groups"])
    assert sum(group["weight_pct"] for group in no_speed["groups"]) == pytest.approx(100.0, abs=0.3)
    partial = dict(card)
    del partial["nasdaq_per_m2"]  # 묶음 안에서 먼저 다시 나눈다 — 남은 둘이 묶음 가중을 나눠 갖는다
    out = v8.compute(ROOT, v5=_v5(partial), profile=_profile({key: 40.0 for key in SPEED}))
    rows = {row["id"]: row for row in out["indicators"]}
    assert rows["nasdaq_per_m2"]["status"] == "missing" and "weight_pct" not in rows["nasdaq_per_m2"]
    assert rows["spx_per_federal_debt"]["weight_pct"] == rows["nasdaq_per_household_liquid_assets"]["weight_pct"]
    assert rows["spx_per_federal_debt"]["weight_pct"] > 100 * CONTRACT["frozen"]["indicators"]["spx_per_federal_debt"]["weight"]
    few = {key: 40.0 for key in ("unemployment_rate", "loan_standards", "bond_spread")}
    held = v8.compute(ROOT, v5=_v5(few), profile={})
    assert held["status"] == "hold" and held["overheat_pct"] is None and "live weight" in held["reason"]
    assert v8.compute(ROOT, v5={"status": "unavailable"}, profile={})["status"] == "hold"
    bad = v8.compute(ROOT, v5=_v5({**card, "margin_credit": True}), profile=_profile({"speed_r24": "28"}))
    assert set(bad["missing"]) == {"margin_credit", *SPEED}  # 숫자가 아닌 값은 값으로 치지 않는다


@pytest.mark.parametrize("mutate", [
    lambda c: c["frozen"]["indicators"]["ipo_count_operating_12m"].__setitem__("weight", 0.5),
    lambda c: c["frozen"]["indicators"]["speed_r24"].__setitem__("A", 0.0),
    lambda c: c["panel"]["median"].__setitem__("unemployment_rate", 5),
    lambda c: c["points"]["B"]["map"].__setitem__("opposite", 3),
    lambda c: c["indicators"][0].__setitem__("group", "valuation"),
    lambda c: c.__setitem__("frozen", {}),
])
def test_a_contract_that_no_longer_derives_closes_instead_of_using_hand_edited_weights(tmp_path: Path, mutate) -> None:
    contract = copy.deepcopy(CONTRACT)
    mutate(contract)
    root = _root(tmp_path, contract)
    out = v8.compute(root, v5=_v5({key: 50.0 for key in CARD}), profile=_profile({key: 50.0 for key in SPEED}))
    assert out["status"] == "unavailable" and out["overheat_pct"] is None
    assert out["probability_space"] == "reference_only" and out["trading_signal"] is False


def test_untouched_copy_stays_open_and_missing_files_never_raise(tmp_path: Path) -> None:
    root = _root(tmp_path / "ok", copy.deepcopy(CONTRACT))
    out = v8.compute(root, v5=_v5({key: 50.0 for key in CARD}), profile=_profile({key: 50.0 for key in SPEED}))
    assert out["status"] == "ok" and out["overheat_pct"] == 50
    empty = v8.compute(tmp_path / "nothing", v5={}, profile={})
    assert empty["status"] == "unavailable" and empty["overheat_pct"] is None


def test_repository_state_computes_from_the_committed_inputs() -> None:
    out = v8.compute(ROOT)
    assert out["status"] in {"ok", "hold"}  # 프로필이 오래되면 속도 2종이 빠질 뿐 값은 난다(가중 85%)
    assert out["contract_id"] == "dotcom_overheat_index_v8" and out["weights_basis"] == "declared_judgment"
    assert out["previous_formula"]["contract_id"] == "dotcom_overheat_index_v5"
    if out["status"] == "ok":
        assert -50 <= out["value_raw"] <= 150 and out["range"]["low"] <= out["range"]["high"]
        assert {row["id"] for row in out["indicators"]} == set(IDS) and "판단값" in out["note"]


def test_dashboard_shows_the_weighted_value_as_headline_and_says_the_weights_are_a_judgment() -> None:
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    builder = (ROOT / "src/ai_fc/dashboard.py").read_text(encoding="utf-8")
    assert '"dotcom_overheat_weighted": dotcom_overheat_weighted' in builder
    assert "_dotcom_overheat_weighted(root, v5=dotcom_overheat, profile=dotcom_overheat_profile)" in builder
    rubric = script[script.index("function overheatRubricBlock"):script.index("function statisticsOverheatPanel")]
    assert "가중치는 판단값" in rubric and "검증한 값 아님" in rubric and "소유자 지정" in rubric
    assert "확률 아님" in rubric and "매매 신호 아님" in rubric and "참고 의견" in rubric
    assert "reduce(" not in rubric and "<svg" not in rubric  # JS 는 그리기만 한다 — 가중·평균은 파이썬이 낸다
    panel = script[script.index("function statisticsOverheatPanel"):script.index("function predictionSectionNav")]
    assert "판단 가중 평균" in panel and "이전 산식" in panel and "가중에 따라" in panel
    assert "부문별 ${sig.lo}~${sig.hi}%" in panel  # 닫히면 이전 산식 화면으로 돌아간다
    assert "reduce(" not in panel
    signal = script[script.index("function dotcomOverheatSignal"):script.index("function dotcomCycleSignal")]
    assert "overheatWeighted(DATA?.dotcom_overheat_weighted)" in signal and "weighted:true" in signal
    assert "category_span" in signal  # 이전 산식 경로가 남아 있다
    home = script[script.index("${card('닷컴 대비 과열도'"):script.index("'닷컴 대비 과열도 상세 보기'")]
    assert "heat.weighted?" in home and "가중에 따라" in home and "분야별 ${heat.lo}~${heat.hi}" in home


def test_watchdog_reports_when_the_site_fell_back_to_the_previous_formula() -> None:
    assert check_weighted(None) == []
    assert check_weighted({})[0]["status"] == "warn"
    closed = check_weighted({"dotcom_overheat_weighted": {"status": "hold", "reason": "live weight", "overheat_pct": None}})
    assert closed[0]["status"] == "warn" and "이전 산식" in closed[0]["detail"]
    partial = check_weighted({"dotcom_overheat_weighted": {"status": "ok", "overheat_pct": 57, "included": 14,
                                                           "missing": ["speed_r24", "speed_d200"]}})
    assert partial[0]["status"] == "warn" and "speed_r24" in partial[0]["detail"]
    fine = check_weighted({"dotcom_overheat_weighted": {"status": "ok", "overheat_pct": 58, "included": 16, "missing": []}})
    assert fine[0]["status"] == "ok" and "58%" in fine[0]["detail"]
