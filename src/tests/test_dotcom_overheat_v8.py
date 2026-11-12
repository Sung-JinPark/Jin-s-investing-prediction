"""닷컴 대비 과열도 v8 — 판단 가중 평균: 규칙에서 유도된 가중만 쓴다, 중복은 한 번만 센다, 닫힐 때 닫힌다 (네트워크 없음)."""

from __future__ import annotations

import copy
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ai_fc import dotcom_overheat_v7 as v7
from ai_fc import dotcom_overheat_v8 as v8
from ai_fc.overheat_watchdog import check_weight_basis, check_weighted

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
    return {"status": "ok", "as_of": "2026-11-10", "max_age_days": 10,
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
    assert "사람 패널이 아니다" in CONTRACT["panel"]["method"] and "언어모델" in CONTRACT["panel"]["method"]
    assert "증거금" in CONTRACT["groups"]["basis"] and "작성자 판단" in CONTRACT["groups"]["basis"]  # v7 중복 판정을 숨기지 않는다
    record = json.loads((ROOT / CONTRACT["panel"]["record"]).read_text(encoding="utf-8"))
    assert record["table"] == {key: {"values": CONTRACT["panel"]["values"][key], "median": CONTRACT["panel"]["median"][key]}
                               for key in IDS}
    assert "prompt_template" in record and len(record["lenses"]) == 5 and "사람 패널이 아니다" in record["what_this_is"]
    assert all(set(calls) == {"StructuredOutput"} for calls in record["tool_calls"]["by_agent"])  # 파일을 읽지 않았다
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
    assert out["value_raw"] == pytest.approx(expected, abs=0.06) and out["overheat_pct"] == math.floor(expected + 0.5)
    rows = {row["id"]: row for row in out["indicators"]}
    # 행에는 원값, 평균에만 자른 값. 어느 쪽에서 잘렸는지 구분한다 — 하한에서 잘린 것을 '상한'이라 부르면 반대 말이 된다.
    assert rows["investment_share_gdp"]["reading"] == 260.3 and rows["investment_share_gdp"]["clamped"] == "high"
    assert rows["consumer_credit_growth"]["reading"] == -80.0 and rows["consumer_credit_growth"]["clamped"] == "low"
    assert rows["speed_r24"]["clamped"] is None and rows["speed_r24"]["group_label"] == "상승 속도"
    assert out["clamped_high_count"] == 1 and out["clamped_low_count"] == 1 and "clamped_count" not in out
    groups = {group["id"]: group for group in out["groups"]}
    assert groups["real_investment"]["clamped"] == "high" and groups["household_debt"]["clamped"] == "low"
    assert groups["speed"]["clamped"] is None
    both = v8.compute(ROOT, v5=_v5({**readings, "household_debt_service": 400.0}), profile=_profile(speed))
    assert {g["id"]: g for g in both["groups"]}["household_debt"]["clamped"] == "both"
    assert sum(group["contribution"] for group in out["groups"]) == pytest.approx(out["value_raw"], abs=0.3)
    assert sum(group["weight_pct"] for group in out["groups"]) == pytest.approx(100.0, abs=0.3)
    flat_index = sum(clamp({**readings, **speed}[key]) for key in IDS) / len(IDS)
    assert out["variants"]["equal_indicators"] == pytest.approx(flat_index, abs=0.06)  # 변형은 실제로 다른 가중이다
    assert out["variants"]["equal_groups"] != out["variants"]["declared"] != out["variants"]["equal_indicators"]
    assert out["range"]["low_raw"] == min(out["variants"].values()) and out["range"]["high_raw"] == max(out["variants"].values())
    assert out["range"]["low"] == math.floor(min(out["variants"].values()) + 0.5)
    assert out["range"]["low_raw"] <= out["value_raw"] <= out["range"]["high_raw"]  # 같은 자릿수로는 범위 안이다


def test_display_integer_rounds_half_up_and_non_finite_readings_are_not_values() -> None:
    assert [v8._half_up(x) for x in (57.46, 57.5, 58.5, -0.5, -30.9)] == [57, 58, 59, 0, -31]
    assert v8._number(float("nan")) is None and v8._number(float("inf")) is None and v8._number(10 ** 400) is None
    assert v8._number(True) is None and v8._number("28") is None and v8._number(3) == 3.0
    card = {key: 40.0 for key in CARD}
    for poison in (float("nan"), float("inf"), 10 ** 400):
        out = v8.compute(ROOT, v5=_v5({**card, "unemployment_rate": poison}), profile=_profile({key: 40.0 for key in SPEED}))
        assert out["status"] == "ok" and out["missing"] == ["unemployment_rate"] and out["overheat_pct"] == 40


def test_missing_readings_are_reweighted_and_too_little_live_weight_holds() -> None:
    card = {key: 40.0 for key in CARD}
    both_speed = _profile({key: 40.0 for key in SPEED})
    # 매일 움직이는 묶음이 통째로 없으면 재배분하지 않고 닫는다 — 가중은 85% 가 살아 있어도.
    assert CONTRACT["missing"]["required_groups"] == ["speed"]
    for dead in ({"status": "hold", "reason": "profile is 11 days old"}, {}, None, _profile({}),
                 {"status": "ok", "as_of": "2026-11-10", "max_age_days": 10,
                  "families": [{"id": "speed", "indicators": [{"id": key, "status": "hold"} for key in SPEED]},
                               {"id": "valuation", "indicators": [{"id": "val_nasdaq_m2", "status": "ok", "score_raw": 98.0}]}]}):
        no_speed = v8.compute(ROOT, v5=_v5(card), profile=dead if dead is not None else {"status": "unavailable"})
        assert no_speed["status"] == "hold" and no_speed["overheat_pct"] is None and "speed" in no_speed["reason"]
        assert no_speed["missing"] == SPEED and 0.7 <= no_speed["live_weight"] < 1.0
        assert no_speed["speed_as_of"] is None and no_speed["speed_max_age_days"] is None  # 다른 부문 행은 속도 값이 아니다
    one_speed = v8.compute(ROOT, v5=_v5(card), profile=_profile({"speed_r24": 40.0}))
    assert one_speed["status"] == "ok" and one_speed["missing"] == ["speed_d200"] and one_speed["overheat_pct"] == 40
    assert one_speed["speed_as_of"] == "2026-11-10" and one_speed["speed_max_age_days"] == 10
    # 값이 서로 다를 때의 재배분을 계약 규칙으로 손계산해 대조한다: 묶음 점수 = 살아 있는 구성원 점수의 평균, 묶음 사이는 점수 비례.
    points = {key: row["points"] for key, row in CONTRACT["frozen"]["indicators"].items()}
    group_of = {spec["id"]: spec["group"] for spec in CONTRACT["indicators"]}
    varied = {key: float(7 * index - 20) for index, key in enumerate(CARD)}
    del varied["nasdaq_per_m2"], varied["loan_standards"]
    varied_speed = {"speed_r24": 61.0}
    varied.update(varied_speed)
    members: dict[str, list[str]] = {}
    for key in varied:
        members.setdefault(group_of[key], []).append(key)
    score = {name: statistics.fmean(points[key] for key in ids) for name, ids in members.items()}
    by_hand = sum(score[name] / sum(score.values()) * statistics.fmean(varied[key] for key in ids)
                  for name, ids in members.items())
    hand = v8.compute(ROOT, v5=_v5({k: v for k, v in varied.items() if k not in varied_speed}), profile=_profile(varied_speed))
    assert hand["status"] == "ok" and hand["value_raw"] == pytest.approx(by_hand, abs=0.06)
    assert set(hand["missing"]) == {"nasdaq_per_m2", "loan_standards", "speed_d200"}
    assert sum(group["weight_pct"] for group in hand["groups"]) == pytest.approx(100.0, abs=0.3)
    assert v8.compute(ROOT, v5=_v5(card), profile=both_speed)["speed_max_age_days"] == 10
    partial = dict(card)
    del partial["nasdaq_per_m2"]  # 묶음 안에서 먼저 다시 나눈다 — 남은 둘이 묶음 가중을 나눠 갖는다
    out = v8.compute(ROOT, v5=_v5(partial), profile=_profile({key: 40.0 for key in SPEED}))
    rows = {row["id"]: row for row in out["indicators"]}
    assert rows["nasdaq_per_m2"]["status"] == "missing" and "weight_pct" not in rows["nasdaq_per_m2"]
    assert rows["spx_per_federal_debt"]["weight_pct"] == rows["nasdaq_per_household_liquid_assets"]["weight_pct"]
    assert rows["spx_per_federal_debt"]["weight_pct"] > 100 * CONTRACT["frozen"]["indicators"]["spx_per_federal_debt"]["weight"]
    few = {key: 40.0 for key in ("unemployment_rate", "loan_standards", "bond_spread")}
    held = v8.compute(ROOT, v5=_v5(few), profile=both_speed)
    assert held["status"] == "hold" and held["overheat_pct"] is None and "live weight" in held["reason"]
    no_v5 = v8.compute(ROOT, v5={"status": "unavailable"}, profile={})
    assert no_v5["status"] == "hold" and no_v5["contract_id"] == held["contract_id"] == "dotcom_overheat_index_v8"
    assert no_v5["weights_basis"] == "declared_judgment"  # 닫힌 출력도 같은 이름표를 단다
    bad = v8.compute(ROOT, v5=_v5({**card, "margin_credit": True}), profile=_profile({"speed_r24": "28", "speed_d200": 5.0}))
    assert bad["status"] == "ok" and set(bad["missing"]) == {"margin_credit", "speed_r24"}  # 숫자가 아닌 값은 값으로 치지 않는다


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
    # 커밋된 프로필이 오래됐으면 속도 2종이 빠진 채 ok(가중 85%)이고, 통계 스냅샷이 ok 가 아니면 hold 다 — 둘 다 예외는 아니다.
    assert out["status"] in {"ok", "hold"}
    assert out["contract_id"] == "dotcom_overheat_index_v8" and out["weights_basis"] == "declared_judgment"
    if out["status"] == "ok":
        assert out["previous_formula"]["contract_id"] == "dotcom_overheat_index_v5"
        assert -50 <= out["value_raw"] <= 150 and out["range"]["low"] <= out["range"]["high"]
        assert {row["id"] for row in out["indicators"]} == set(IDS) and "판단값" in out["note"]


def test_direction_points_still_match_the_statistics_ledger_and_drift_is_reported(tmp_path: Path) -> None:
    assert v8.end_position_drift(ROOT) == []  # 계약에 적은 1999년 말 위치가 지금 원장과 같은 점수 칸에 있다
    assert [row["status"] for row in check_weight_basis(ROOT)] == ["ok"]
    for relative in (v8.CONTRACT_RELATIVE, v8.V5_CONTRACT_RELATIVE):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_bytes((ROOT / relative).read_bytes())
    payload = json.loads((ROOT / v8.STATISTICS_RELATIVE).read_text(encoding="utf-8"))
    chart = next(c for c in payload["charts"] if c["id"] == "unemployment_rate")
    series = next(s for s in chart["series"] if s["label"] == "닷컴")
    series["points"][-1]["value"] = max(p["value"] for p in series["points"])  # 1999년 말 실업률이 구간 최고였다고 개정됐다면
    (tmp_path / v8.STATISTICS_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / v8.STATISTICS_RELATIVE).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    drift = v8.end_position_drift(tmp_path)
    assert len(drift) == 1 and drift[0].startswith("unemployment_rate") and "점수 칸이 바뀜" in drift[0]
    assert check_weight_basis(tmp_path)[0]["status"] == "warn"
    assert check_weight_basis(tmp_path / "nothing")[0]["status"] == "warn"  # 못 읽어도 감시는 죽지 않는다


def test_dashboard_shows_the_weighted_value_as_headline_and_says_the_weights_are_a_judgment() -> None:
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    builder = (ROOT / "src/ai_fc/dashboard.py").read_text(encoding="utf-8")
    assert '"dotcom_overheat_weighted": dotcom_overheat_weighted' in builder
    assert "_dotcom_overheat_weighted(root, v5=dotcom_overheat, profile=dotcom_overheat_profile)" in builder
    rubric = script[script.index("function overheatRubricBlock"):script.index("function statisticsOverheatPanel")]
    assert "가중치는 판단값" in rubric and "검증한 값 아님" in rubric and "소유자 지정" in rubric
    assert "AI 평가 5회" in rubric and "같은 언어모델" in rubric and "5인" not in rubric  # 사람 패널처럼 읽히지 않게
    assert "overheatClampNote(w)" in rubric and "'빠짐'" in rubric and "r.group_label" in rubric
    gate = script[script.index("function overheatWeighted"):script.index("function overheatRubricBlock")]
    assert "w.speed_as_of" in gate and "w.speed_max_age_days" in gate and "limit+1" in gate  # 프로필 블록과 같은 나이 판정
    assert "if(w.speed_as_of)" not in gate  # 기준일이 없는 것은 통과가 아니라 닫힘이다
    assert "상한 ${hi}개" in gate and "하한 ${lo}개" in gate
    assert "확률 아님" in rubric and "매매 신호 아님" in rubric and "참고 의견" in rubric
    assert "reduce(" not in rubric and "<svg" not in rubric  # JS 는 그리기만 한다 — 가중·평균은 파이썬이 낸다
    panel = script[script.index("function statisticsOverheatPanel"):script.index("function predictionSectionNav")]
    assert "판단 가중 평균" in panel and "이전 산식" in panel and "가중에 따라" in panel
    assert "검증된 값 아님" in panel and "빠짐(가중 재배분)" in panel and "low_raw" in panel  # 대표값 바로 아래 줄
    assert "{high:' · 상한',low:' · 하한',both:' · 상·하한'}" in panel
    assert "const gated=overheatWeighted(DATA.dotcom_overheat_weighted)" in panel and "dotcomOverheatSignal(idx,gated)" in panel
    assert panel.count("overheatWeighted(") == 1  # 시각에 따라 달라지는 게이트를 한 번만 판정한다
    assert "부문별 ${sig.lo}~${sig.hi}%" in panel  # 닫히면 이전 산식 화면으로 돌아간다
    assert "reduce(" not in panel
    signal = script[script.index("function dotcomOverheatSignal"):script.index("function dotcomCycleSignal")]
    assert "function dotcomOverheatSignal(idx,weighted)" in signal and "weighted:true" in signal
    assert "DATA" not in signal.split("*/")[-1]  # 신호 함수는 바깥을 읽지 않는다 — 게이트는 호출부가 건다
    assert "category_span" in signal  # 이전 산식 경로가 남아 있다
    home = script[script.index("${card('닷컴 대비 과열도'"):script.index("'닷컴 대비 과열도 상세 보기'")]
    assert "heat.weighted?" in home and "판단 가중 · 가중에 따라" in home and "분야별 ${heat.lo}~${heat.hi}" in home
    assert "heat.missing" in home and "빠짐(가중 재배분)" in home  # 홈 카드도 재배분된 값임을 말한다
    assert "missing:Array.isArray(w.missing)?w.missing.length:0" in signal
    assert "dotcomOverheatSignal(DATA.dotcom_overheat,overheatWeighted(DATA.dotcom_overheat_weighted))" in script
    blocks = script[script.index("function overheatProfileBlock"):script.index("function overheatWeighted")]
    assert "overheatSpeedCount(overheatWeighted(DATA.dotcom_overheat_weighted))" in blocks  # 실제로 들어간 속도 지표 수를 말한다
    assert "판정만 대표값 점수의 과거 근거로 읽음" in blocks and "위 닮음과 합치지 않음" in blocks


def test_watchdog_reports_when_the_site_fell_back_to_the_previous_formula() -> None:
    now = datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc)
    v5_ok = {"dotcom_overheat": {"status": "ok", "overheat_pct": 54}}
    fresh = {"status": "ok", "overheat_pct": 58, "included": 16, "missing": [], "speed_as_of": "2026-11-10",
             "speed_max_age_days": 10}
    assert check_weighted(None, now=now) == []
    absent = check_weighted(v5_ok, now=now)
    assert absent[0]["status"] == "warn" and "이전 산식(v5)이 대표값" in absent[0]["detail"]
    closed = check_weighted({**v5_ok, "dotcom_overheat_weighted": {"status": "hold", "reason": "live weight",
                                                                   "overheat_pct": None}}, now=now)
    assert closed[0]["status"] == "warn" and "이전 산식" in closed[0]["detail"]
    nothing = check_weighted({"dotcom_overheat": {"status": "unavailable"},
                              "dotcom_overheat_weighted": {"status": "hold", "reason": "v5 readings unavailable"}}, now=now)
    assert nothing[0]["status"] == "warn" and "대표값 없음" in nothing[0]["detail"]  # v5 도 없으면 v5 가 보인다고 말하지 않는다
    partial = check_weighted({**v5_ok, "dotcom_overheat_weighted": {**fresh, "overheat_pct": 45, "included": 15,
                                                                    "missing": ["investment_share_gdp"]}}, now=now)
    assert partial[0]["status"] == "warn" and "investment_share_gdp" in partial[0]["detail"]
    fine = check_weighted({**v5_ok, "dotcom_overheat_weighted": fresh}, now=now)
    assert fine[0]["status"] == "ok" and "58%" in fine[0]["detail"]
    # 화면과 같은 나이 판정: 속도 값이 한도보다 오래되면 화면은 이미 이전 산식이다 — '정상 58%' 라고 보고하지 않는다.
    late = datetime(2026, 11, 22, 3, 0, tzinfo=timezone.utc)
    assert check_weighted({**v5_ok, "dotcom_overheat_weighted": fresh}, now=late)[0]["status"] == "warn"
    assert check_weighted({**v5_ok, "dotcom_overheat_weighted": fresh},
                          now=datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc))[0]["status"] == "ok"  # 한도 + 1일까지
    for broken in ({**fresh, "speed_as_of": None}, {**fresh, "speed_as_of": "soon"}, {**fresh, "speed_max_age_days": None}):
        assert check_weighted({**v5_ok, "dotcom_overheat_weighted": broken}, now=now)[0]["status"] == "warn"
    assert check_weighted({**v5_ok, "dotcom_overheat_weighted": {**fresh, "missing": 5}}, now=now)[0]["status"] == "ok"  # 죽지 않는다
