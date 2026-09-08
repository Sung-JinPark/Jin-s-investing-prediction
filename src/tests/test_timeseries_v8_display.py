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


def test_missing_pointer_and_operational_hold_both_fall_back_to_none(tmp_path: Path) -> None:
    assert load_projection(tmp_path) is None
    path = tmp_path / display.LATEST_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_hold_latest(), ensure_ascii=False), encoding="utf-8")
    assert load_projection(tmp_path) is None


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
    load_projection은 None — 수치를 숨기고 validation_pending 표면으로 페일클로즈한다.
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
    assert load_projection(tmp_path) is None, "보류 임계 도달 — 표면을 닫아야 한다"
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
