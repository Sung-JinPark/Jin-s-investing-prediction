"""The V8 display projection must fail closed and map returns honestly."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ai_fc import timeseries_v8_display as display
from ai_fc.timeseries_v8.contracts import MODEL_ID, canonical_hash
from ai_fc.timeseries_v8_display import (
    TimeSeriesV8DisplayError,
    build_projection,
    load_projection,
    validate_latest,
)


def _finish(body: dict) -> dict:
    return {**body, "content_hash": canonical_hash(body)}


def _hold_latest() -> dict:
    return _finish({
        "schema_version": 1,
        "model_id": MODEL_ID,
        "model_version": 8,
        "status": "shadow_operational_hold",
        "display_state": "validation_pending",
        "as_of": "2026-08-14",
        "knowledge_cutoff": "2026-08-31T01:31:55+00:00",
        "probability_unit": "fraction",
        "probability_space": "research_timeseries_v8_conditional",
        "publication": {
            "customer_numbers_visible": False,
            "combined_with_official_forecasts": False,
            "combined_with_scenario_v5_2": False,
            "reference_opinion_only": True,
        },
        "gate": {
            "sealed_gate_pass": True,
            "sealed_run_id": "tsv8-sealed-test",
            "operational_pass": False,
            "reasons": ["필수 시장 입력 신선도 초과: NASDAQCOM"],
        },
        "footnote": "*미국 시장·미국 공식 거시자료 기준 · 참고 의견",
    })


def _visible_latest() -> dict:
    horizon = {
        "p10": -0.08, "p25": -0.02, "p50": 0.01, "p75": 0.04, "p90": 0.09,
        "probability_up": 0.62,
    }
    return _finish({
        "schema_version": 1,
        "model_id": MODEL_ID,
        "model_version": 8,
        "status": "shadow_live",
        "display_state": "research_reference",
        "as_of": "2026-08-28",
        "knowledge_cutoff": "2026-09-01T03:10:00+00:00",
        "probability_unit": "fraction",
        "probability_space": "research_timeseries_v8_conditional",
        "publication": {
            "customer_numbers_visible": True,
            "combined_with_official_forecasts": False,
            "combined_with_scenario_v5_2": False,
            "reference_opinion_only": True,
        },
        "gate": {
            "sealed_gate_pass": True,
            "sealed_run_id": "tsv8-sealed-test",
            "operational_pass": True,
            "reasons": [],
        },
        "horizons": {key: dict(horizon) for key in ("1", "5", "21", "63")},
        "footnote": "*미국 시장·미국 공식 거시자료 기준 · 참고 의견",
    })


def _sealed_row() -> dict:
    return {
        "run_id": "tsv8-sealed-test",
        "summary": {
            "gate_pass": True,
            "origin_count": 1011,
            "horizons": {
                "21": {"crps_improvement_vs_best": 0.0396, "coverage_p10_p90": 0.8131},
                "63": {"crps_improvement_vs_best": 0.0342, "coverage_p10_p90": 0.8012},
            },
        },
    }


def test_missing_pointer_falls_back_to_none(tmp_path: Path) -> None:
    assert load_projection(tmp_path) is None


def test_operational_hold_keeps_v8_metadata_and_hides_all_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {key: value for key, value in _hold_latest().items() if key != "content_hash"}
    body["operational"] = {"freshness": [{"group": "NASDAQCOM", "age_hours": 50.0}]}
    body["daily"] = {"anchor": {"series_id": "NASDAQCOM", "value": 21000.0}}
    body["history"] = {"index": [21000.0]}
    latest = _finish(body)
    path = tmp_path / display.LATEST_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
    original = path.read_bytes()

    def unexpected_read(*args, **kwargs):
        pytest.fail("HOLD metadata must not read numerical artifacts")

    for name in ("_sealed_row", "_anchor_and_history", "_daily_anchor_and_history", "_realized_after_origin"):
        monkeypatch.setattr(display, name, unexpected_read)
    projection = load_projection(tmp_path)
    assert projection is not None
    assert projection["model_id"] == MODEL_ID and projection["model_version"] == 8
    assert projection["status"] == latest["status"]
    assert projection["as_of"] == latest["as_of"]
    assert projection["knowledge_cutoff"] == latest["knowledge_cutoff"]
    assert projection["gate"] == latest["gate"]
    assert projection["publication"] == latest["publication"]
    assert projection["display_state"] == "validation_pending"
    assert projection["numbers_visible"] is False
    assert projection["combined_with_existing_models"] is False
    assert projection["horizons"] == {} and projection["path"] == {}
    assert not {"anchor", "history", "realized", "freshness_summary", "operational", "daily", "sealed_metrics"}.intersection(projection)
    assert path.read_bytes() == original


def test_newer_daily_hold_owns_the_v8_surface(tmp_path: Path) -> None:
    weekly = _visible_latest()
    body = {key: value for key, value in _hold_latest().items() if key != "content_hash"}
    body["as_of"] = "2026-09-02"
    daily = _finish(body)
    for relative, pointer in ((display.LATEST_RELATIVE, weekly), (display.DAILY_LATEST_RELATIVE, daily)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
    projection = load_projection(tmp_path)
    assert projection["cadence"] == "daily"
    assert projection["as_of"] == daily["as_of"]
    assert projection["weekly_as_of"] == weekly["as_of"]
    assert projection["gate"]["reasons"] == daily["gate"]["reasons"]
    assert projection["numbers_visible"] is False


def test_tampered_content_hash_fails_closed() -> None:
    latest = _hold_latest()
    latest["as_of"] = "2026-08-21"
    with pytest.raises(TimeSeriesV8DisplayError, match="content hash"):
        validate_latest(latest)


def test_visibility_may_not_outrun_the_operational_gate() -> None:
    body = {key: value for key, value in _visible_latest().items() if key != "content_hash"}
    body["gate"] = {**body["gate"], "operational_pass": False, "reasons": ["stale"]}
    with pytest.raises(TimeSeriesV8DisplayError, match="both gate decisions"):
        validate_latest(_finish(body))


def test_hold_surface_must_hide_numbers_and_visible_quantiles_must_be_sane() -> None:
    body = {key: value for key, value in _hold_latest().items() if key != "content_hash"}
    body["horizons"] = {"1": {"p50": 0.01}}
    with pytest.raises(TimeSeriesV8DisplayError, match="hide numerical"):
        validate_latest(_finish(body))

    crossing = {key: value for key, value in _visible_latest().items() if key != "content_hash"}
    crossing["horizons"]["21"]["p25"] = 0.05
    with pytest.raises(TimeSeriesV8DisplayError, match="quantile crossing"):
        validate_latest(_finish(crossing))

    escaped = {key: value for key, value in _visible_latest().items() if key != "content_hash"}
    escaped["horizons"]["5"]["probability_up"] = 62.0
    with pytest.raises(TimeSeriesV8DisplayError, match="fraction bounds"):
        validate_latest(_finish(escaped))


def test_projection_maps_log_returns_to_index_levels_around_the_anchor() -> None:
    latest = _visible_latest()
    validate_latest(latest)
    projection = build_projection(latest, anchor_value=20000.0, sealed_row=_sealed_row())
    row = projection["horizons"]["21"]
    assert row["median_index"] == pytest.approx(20000.0 * math.exp(0.01))
    assert row["point_return"] == pytest.approx(math.expm1(0.01))
    assert row["band_index"]["p10"] == pytest.approx(20000.0 * math.exp(-0.08))
    assert row["probability_up"] == pytest.approx(0.62)
    assert projection["numbers_visible"] is True
    assert projection["status"] == "shadow_live"
    assert projection["display_state"] == "research_reference"
    assert projection["combined_with_existing_models"] is False
    assert projection["publication"]["reference_opinion_only"] is True
    assert projection["sealed_metrics"]["origin_count"] == 1011
    assert projection["sealed_metrics"]["horizons"]["63"]["coverage_p10_p90"] == \
        pytest.approx(0.8012)


def test_projection_rejects_wrong_sealed_row_or_broken_anchor() -> None:
    latest = _visible_latest()
    with pytest.raises(TimeSeriesV8DisplayError, match="run id"):
        build_projection(
            latest, anchor_value=20000.0,
            sealed_row={**_sealed_row(), "run_id": "tsv8-sealed-other"})
    with pytest.raises(TimeSeriesV8DisplayError, match="did not pass"):
        build_projection(
            latest, anchor_value=20000.0,
            sealed_row={"run_id": "tsv8-sealed-test", "summary": {"gate_pass": False}})
    with pytest.raises(TimeSeriesV8DisplayError, match="anchor"):
        build_projection(latest, anchor_value=0.0, sealed_row=_sealed_row())
    with pytest.raises(TimeSeriesV8DisplayError, match="HOLD"):
        build_projection(_hold_latest(), anchor_value=20000.0, sealed_row=_sealed_row())


def test_load_projection_serves_the_visible_surface_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    latest = _visible_latest()
    path = tmp_path / display.LATEST_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
    ledger = tmp_path / display.SEALED_LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(_sealed_row(), ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        display, "_anchor_and_history",
        lambda root, origin, cutoff: (
            21000.0, {"dates": ["2026-08-27", "2026-08-28"], "index": [20950.0, 21000.0]}))
    projection = load_projection(tmp_path)
    assert projection is not None
    assert projection["anchor"]["value"] == pytest.approx(21000.0)
    assert projection["as_of"] == "2026-08-28"
    assert projection["gate"]["operational_pass"] is True


def test_projection_carries_gate_widget_and_history_only_when_visible() -> None:
    """UI/UX 설계 260902: freshness 요약·과거선은 visible 투영에만 실린다."""
    latest = _visible_latest()
    body = {key: value for key, value in latest.items() if key != "content_hash"}
    body["operational"] = {"freshness": [
        {"group": "NASDAQCOM", "age_hours": 5.6, "limit_hours": 48.0, "status": "fresh"},
        {"group": "DTWEXBGS_or_DTWEXB", "age_hours": 77.6, "limit_hours": 216.0, "status": "fresh"},
    ]}
    projection = build_projection(
        _finish(body), anchor_value=20000.0, sealed_row=_sealed_row(),
        history={"dates": ["2026-08-27", "2026-08-28"], "index": [19950.0, 20000.0]})
    assert [row["group"] for row in projection["freshness_summary"]] == \
        ["NASDAQCOM", "DTWEXBGS_or_DTWEXB"]
    assert projection["history"]["index"][-1] == pytest.approx(20000.0)


def test_projection_marks_horizons_already_matured_by_build_time() -> None:
    """검수 2차: 원점 이후 실측이 있으면 만기가 지난 지평은 열린 전망이 아니다.

    실측은 별도 배열(realized)로만 싣고 history(원점까지의 입력 이력)에 섞지 않는다.
    라이브 원장 채점은 별도 성숙 판정 경로가 맡으므로 여기서는 표시용 사후 대조만 한다.
    """
    latest = _visible_latest()
    realized = {
        "dates": ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
        "index": [19980.0, 19800.0, 19900.0, 20150.0, 20100.0],
    }
    projection = build_projection(
        latest, anchor_value=20000.0, sealed_row=_sealed_row(),
        history={"dates": ["2026-08-27", "2026-08-28"], "index": [19950.0, 20000.0]},
        realized=realized,
    )
    assert projection["origin_age_sessions"] == 5
    assert projection["realized"] == realized
    assert projection["history"]["dates"][-1] == "2026-08-28", "history는 원점에서 끝나야 한다(PIT)"
    h1, h5, h21 = (projection["horizons"][key] for key in ("1", "5", "21"))
    assert h1["elapsed"] is True and h1["realized_index"] == pytest.approx(19980.0)
    assert h1["realized_date"] == "2026-08-31"
    assert h1["realized_return"] == pytest.approx(-0.001)
    assert isinstance(h1["realized_inside_p10_p90"], bool)
    assert h5["elapsed"] is True and h5["realized_date"] == "2026-09-04"
    assert h21["elapsed"] is False and "realized_index" not in h21
    # 실측이 없으면 아무 지평도 만기로 표시하지 않고 realized는 None이다.
    bare = build_projection(latest, anchor_value=20000.0, sealed_row=_sealed_row())
    assert bare["origin_age_sessions"] == 0 and bare["realized"] is None
    assert all(row["elapsed"] is False for row in bare["horizons"].values())


def test_forward_block_counts_direction_and_names_the_live_baseline() -> None:
    """검수 2차: 확정 행이 있으면 그 결과(기준선 대비·방향)를 센다 — 성숙 원점 0을 근거로
    유일한 표본외 증거의 존재를 부정하지 않는다."""
    rows = [
        {"forecast_id": "f1", "origin": "2026-08-14", "horizon": 1, "resolved_session": "2026-08-17",
         "model_crps": 0.0038, "baseline_crps": 0.0034, "direction_correct": False, "covered_p10_p90": True},
        {"forecast_id": "f1", "origin": "2026-08-14", "horizon": 5, "resolved_session": "2026-08-21",
         "model_crps": 0.0157, "baseline_crps": 0.0153, "direction_correct": False, "covered_p10_p90": True},
    ]
    block = display._forward_block({"operational": {"monitoring": {"matured_shadow_origins": 0}}}, rows)
    assert block["resolved_rows"] == 2 and block["unique_forecasts"] == 1
    assert block["model_better_rows"] == 0
    assert block["direction_rows"] == 2 and block["direction_correct_rows"] == 0
    assert block["covered_p10_p90_rows"] == 2
    assert block["baseline"] == "historical_simulation"
    assert block["matured_origins"] == 0


def test_origin_age_policy_holds_the_surface_after_two_missed_weekly_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """사용자 결정 2026-09-07(2단 임계): 원점 경과가 hold_after_sessions(10)에 닿으면
    load_projection은 V8 HOLD 메타데이터를 유지하며 수치를 숨긴다.
    그 아래(9)에서는 표면을 유지하되 정책 임계를 투영에 싣는다."""
    latest = _visible_latest()
    path = tmp_path / display.LATEST_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
    ledger = tmp_path / display.SEALED_LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(_sealed_row(), ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        display, "_anchor_and_history",
        lambda root, origin, cutoff: (
            21000.0, {"dates": ["2026-08-27", "2026-08-28"], "index": [20950.0, 21000.0]}))
    monkeypatch.setattr(
        display, "_origin_age_policy",
        lambda root: {"warn_after_sessions": 1, "hold_after_sessions": 10})

    def realized(sessions: int):
        return lambda root, origin, cutoff: {
            "dates": [f"2026-09-{day:02d}" for day in range(1, sessions + 1)],
            "index": [21000.0 + day for day in range(1, sessions + 1)],
        }

    monkeypatch.setattr(display, "_realized_after_origin", realized(9))
    kept = load_projection(tmp_path)
    assert kept is not None and kept["origin_age_sessions"] == 9
    assert kept["origin_age_policy"] == {"warn_after_sessions": 1, "hold_after_sessions": 10}
    monkeypatch.setattr(display, "_realized_after_origin", realized(10))
    original = path.read_bytes()
    held = load_projection(tmp_path)
    assert held["model_id"] == MODEL_ID and held["status"] == "shadow_operational_hold"
    assert held["numbers_visible"] is False and held["gate"]["operational_pass"] is False
    assert held["gate"]["sealed_gate_pass"] is True
    assert held["gate"]["reasons"] == ["예측 원점 경과 거래일 10: 보류 임계 10 도달"]
    assert held["as_of"] == latest["as_of"] and held["knowledge_cutoff"] == latest["knowledge_cutoff"]
    assert held["horizons"] == {} and held["path"] == {}
    assert not {"anchor", "history", "realized", "freshness_summary", "sealed_metrics"}.intersection(held)
    assert path.read_bytes() == original, "표시용 보류가 저장된 포인터를 바꾸면 안 된다"
    assert latest["gate"]["operational_pass"] is True and latest["gate"]["reasons"] == []
    # 정책 블록이 없으면(계약 미존재) 보류하지 않는다 — 표시 계층은 계약 없이 게이트를 지어내지 않는다.
    monkeypatch.setattr(display, "_origin_age_policy", lambda root: {})
    assert load_projection(tmp_path) is not None


def test_origin_age_policy_lives_outside_the_frozen_contract_coordinates() -> None:
    """계약 개정이 봉인·섀도 원장이 고정한 contract_hash를 바꾸면 안 된다 — 정책 섹션은
    frozen_coordinates 밖이어야 한다."""
    from ai_fc import config
    from ai_fc.timeseries_v8.contracts import frozen_coordinates, frozen_hash, load_contract_v8

    contract = load_contract_v8(Path(config.ROOT))
    assert contract["origin_age_policy"]["hold_after_sessions"] == 10
    assert contract["origin_age_policy"]["warn_after_sessions"] == 1
    assert "origin_age_policy" not in frozen_coordinates(contract)
    assert frozen_hash(contract).startswith("7c56ee4eaa569782"), "봉인평가 원장의 contract_hash와 달라졌다"


def _score_disclosure(**overrides):
    horizons = {
        key: {
            "crps_improvement_vs_best": 0.0, "coverage_p10_p90": 0.8,
            "coverage_p25_p75": 0.5, "dm_p_value": 0.5,
        }
        for key in ("1", "5", "21", "63")
    }
    disclosure = {
        "sealed_window": {"horizons": horizons},
        "loss_diff_ci90": {"lower": -0.01, "upper": 0.01},
        "regimes": [
            {"key": "great_financial_crisis_2008", "coverage_p10_p90": 0.8, "origins": 10},
            {"key": "pandemic_2020", "coverage_p10_p90": 0.8, "origins": 10},
            {"key": "tightening_2022", "coverage_p10_p90": 0.8, "origins": 10},
        ],
        "forward": {"resolved_rows": 0, "model_better_rows": 0, "covered_p10_p90_rows": 0},
    }
    disclosure.update(overrides)
    return disclosure


def test_score100_anchors_are_fixed_rules() -> None:
    """100점 환산 앵커: 기준선 동급=정확도 50, 공칭 일치=만점, 표본 0개 위기=0점."""
    from ai_fc.timeseries_v8_display import SCORE100_WEIGHTS, score100

    assert sum(SCORE100_WEIGHTS.values()) == 100
    neutral = score100(_score_disclosure())
    assert neutral["pillars"]["accuracy"]["score"] == 50.0
    assert neutral["pillars"]["calibration"]["score"] == 100.0
    assert neutral["pillars"]["robustness"]["score"] == 100.0
    assert neutral["pillars"]["confidence"]["score"] == 0.0
    # 라이브 0건 = 사전값 그대로 중립(승률 50점·적중 만점의 평균)
    assert neutral["pillars"]["live"]["score"] == 75.0
    # 15 + 0 + 30 + 15 + 11.25 = 71.25
    assert neutral["total"] == 71 and neutral["grade"] == "B"

    better = _score_disclosure()
    for row in better["sealed_window"]["horizons"].values():
        row["crps_improvement_vs_best"] = 0.10
    assert score100(better)["pillars"]["accuracy"]["score"] == 100.0

    # 허용대역 끝(80% 구간 −4pp) = 75점, 그 4배 = 0점
    edge = _score_disclosure()
    for row in edge["sealed_window"]["horizons"].values():
        row["coverage_p10_p90"] = 0.76
        row["coverage_p25_p75"] = None
    assert score100(edge)["pillars"]["calibration"]["score"] == 75.0

    untested = _score_disclosure()
    untested["regimes"][0] = {"key": "great_financial_crisis_2008", "coverage_p10_p90": None, "origins": 0}
    robust = score100(untested)["pillars"]["robustness"]
    assert robust["score"] == round(200 / 3, 1)
    assert robust["detail"]["untested"] == ["great_financial_crisis_2008"]


def test_score100_live_shrinks_small_samples_and_needs_sealed_window() -> None:
    from ai_fc.timeseries_v8_display import score100

    lucky = score100(_score_disclosure(forward={
        "resolved_rows": 2, "model_better_rows": 2, "covered_p10_p90_rows": 2}))
    # 2전 2승이어도 승률 점수는 (2+5)/12 → 58.3, 만점 근처로 튀지 않는다
    assert lucky["pillars"]["live"]["detail"]["evidence_weight"] == 2 / 12
    assert lucky["pillars"]["live"]["score"] < 80
    # 봉인창이 없으면 점수 자체가 없다 — 전체창(개발기간 포함)으로 대체하지 않는다
    assert score100({"full_backtest": {"horizons": {"21": {"crps_improvement_vs_best": 0.05}}}}) is None


def test_score100_rides_on_live_projection() -> None:
    from pathlib import Path

    from ai_fc import config
    from ai_fc.timeseries_v8_display import load_projection

    projection = load_projection(Path(config.ROOT))
    if projection is None or projection.get("numbers_visible") is not True:
        import pytest
        pytest.skip("V8 projection not visible in this checkout")
    sealed = projection["sealed_metrics"]
    score = sealed["score100"]
    assert 0 <= score["total"] <= 100
    points = sum(pillar["points"] for pillar in score["pillars"].values())
    assert abs(points - score["total"]) <= 1.0
    row = sealed["sealed_window"]["horizons"]["63"]
    # 절대 CRPS는 공개 개선율의 분자·분모와 정확히 맞물린다
    assert abs((1 - row["crps"] / row["best_baseline_crps"]) - row["crps_improvement_vs_best"]) < 1e-4


def test_score100_bounds_fix_the_sealed_pillars_and_bound_the_live_axis() -> None:
    """봉인 4축은 불변, 실전 축만 0~15 — 상한·하한은 score100 과 같은 반올림 규칙으로 산출한다."""
    from ai_fc.timeseries_v8_display import score100, score100_bounds

    score = score100(_score_disclosure())
    bounds = score100_bounds(score)
    # 중립 입력: 15 + 0 + 30 + 15 = 60.0 고정 → 하한 60(실전 0점) · 상한 75(실전 만점) · 등급 B 고정
    assert bounds["fixed_pillars"] == ["accuracy", "confidence", "calibration", "robustness"]
    assert bounds["fixed_points"] == 60.0
    assert (bounds["floor_total"], bounds["ceiling_total"]) == (60, 75)
    assert bounds["floor_grade"] == bounds["ceiling_grade"] == "B" and bounds["grade_locked"] is True
    assert bounds["variable_weight"] == 15 and bounds["live_points"] == score["pillars"]["live"]["points"]
    assert bounds["floor_total"] <= score["total"] <= bounds["ceiling_total"]
    assert bounds["method"] == score["method"]
    # 봉인 축이 등급 경계에 걸치면 등급은 잠기지 않는다 (−4% 개선 → 정확도 30점 = 9.0 → 고정 54.0)
    weak = _score_disclosure()
    for row in weak["sealed_window"]["horizons"].values():
        row["crps_improvement_vs_best"] = -0.04
    open_bounds = score100_bounds(score100(weak))
    assert (open_bounds["floor_total"], open_bounds["ceiling_total"]) == (54, 69)
    assert (open_bounds["floor_grade"], open_bounds["ceiling_grade"]) == ("C", "B")
    assert open_bounds["grade_locked"] is False
    assert score100_bounds(None) is None and score100_bounds({"pillars": {}}) is None


def test_shadow_progress_counts_nyse_sessions_after_the_first_origin() -> None:
    """섀도 세션은 첫 원점 다음 거래일부터 NYSE 휴장 달력으로 센다 — 원점 수가 아니다."""
    from ai_fc import config
    from ai_fc.scenario import load_calendar_contract
    from ai_fc.timeseries_v8_display import shadow_progress

    calendar = load_calendar_contract(Path(config.ROOT))
    progress = shadow_progress(
        ["2026-08-28", "2026-08-14"], as_of_session="2026-10-20", calendar=calendar,
        required_sessions=126)
    assert progress["first_origin"] == "2026-08-14" and progress["origins"] == 2
    # 08-14(금) 다음 세션 08-17부터, 노동절 09-07 제외 → 10-20까지 46세션
    assert progress["sessions_elapsed"] == 46 and progress["sessions_remaining"] == 80
    assert progress["first_h63_maturity_date"] == "2026-11-12" and progress["first_h63_matured"] is False
    # 추수감사절·성탄절·신정·MLK·대통령의 날 제외
    assert progress["required_session_date"] == "2027-02-16"
    assert progress["promotion_automatic"] is False and progress["calendar"] == "NYSE"
    assert progress["maturity_sessions"] == 63 and progress["as_of_session"] == "2026-10-20"
    assert shadow_progress([], as_of_session="2026-10-20", calendar=calendar, required_sessions=126) is None
    assert shadow_progress(["2026-08-14"], as_of_session="2026-10-20", calendar=calendar, required_sessions=0) is None
    same_day = shadow_progress(["2026-08-14"], as_of_session="2026-08-14", calendar=calendar, required_sessions=126)
    assert same_day["sessions_elapsed"] == 0
    done = shadow_progress(["2026-08-14"], as_of_session="2027-06-30", calendar=calendar, required_sessions=126)
    assert done["sessions_elapsed"] == 126 and done["sessions_remaining"] == 0 and done["first_h63_matured"] is True


def test_live_projection_carries_shadow_progress_and_score_bounds() -> None:
    from ai_fc import config
    from ai_fc.timeseries_v8_display import load_projection

    projection = load_projection(Path(config.ROOT))
    if projection is None or projection.get("numbers_visible") is not True:
        pytest.skip("V8 projection not visible in this checkout")
    sealed = projection["sealed_metrics"]
    progress = sealed["shadow_progress"]
    assert progress["required_sessions"] == 126, "계약 promotion.minimum_shadow_sessions"
    assert progress["first_origin"] == min(sealed["forward"]["origins"])
    assert 0 <= progress["sessions_elapsed"] <= progress["required_sessions"]
    assert progress["as_of_session"] >= str(projection["as_of"])[:10]
    bounds = sealed["score100_bounds"]
    assert bounds["floor_total"] <= sealed["score100"]["total"] <= bounds["ceiling_total"]
    assert bounds["ceiling_total"] - bounds["floor_total"] == 15
