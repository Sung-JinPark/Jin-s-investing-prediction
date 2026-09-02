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
