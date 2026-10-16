"""Explicit display precision never changes immutable research inputs."""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta

import pytest

from ai_fc import dashboard
from ai_fc.market_context import contracts as C, display as D
from test_market_context_delivery import _projection


def _run():
    run = _projection()
    offset = .123456789123
    run["anchor"] += offset
    run["score"] = 45.123456789
    run["representative"]["path_id"] = 12
    run["representative"]["values"] = [value + offset for value in run["representative"]["values"]]
    run["representative"]["path_hash"] = "a" * 64
    run["baseline_median"] = [value + offset for value in run["baseline_median"]]
    for row in run["records"]:
        row["index_quantiles"] = {key: value + offset for key, value in row["index_quantiles"].items()}
        for field in ("daily_return_quantiles", "drawdown_quantiles"):
            row[field] = {key: value + .0000000012345 for key, value in row[field].items()}
        row["probability_up_from_previous"] = .5555555555123
        row["probability_down_from_previous"] = .4444443333123
        row["probability_up_from_origin"] = .6000001234567
    days = []
    cursor = date.fromisoformat(run["anchor_date"])
    while len(days) < 400:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    days.reverse()
    run["history"] = {"dates": days, "index": [run["anchor"] - .01 * (len(days) - index - 1) for index in range(len(days))]}
    run["state_summary"]["axes"][0]["score"] = None
    run["attribution"] = {"inflation": {"5": .000123456789123, "21": .00123456789123, "63": None}}
    run["attribution_basis"] = {"inflation": [.000123456789123, 0., -.000023456789123]}
    run["run_path"] = "data/market_context/runs/display-fixture.json"
    run["content_hash"] = "b" * 64
    return run


def _stress_run():
    run = _run()
    run["state_summary"]["events"] = [
        {"event_id": f"event-{index}", "revision_id": f"event-{index}-r1", "axis": "inflation",
         "family": "cpi_model_innovation", "title": "시황 정량 이슈 공개 자료 " * 30,
         "source_url": "https://example.org/releases/" + "a" * 900 + f"?event={index}",
         "available_at": f"2026-10-{1+index//8:02d}T{index%8:02d}:00:00+00:00",
         "used_numerically": False, "reason": "원천 출처와 단위 검증을 기다리는 시황입니다. " * 25,
         "exclusion_reason": "missing_validated_asset_mapping"}
        for index in range(60)
    ]
    run["state_summary"]["total_event_count"] = 97
    run["state_summary"]["source_statuses"] = [
        {"source_id": f"source-{index}", "status": "failed" if index < 3 else "ok",
         "reason": ("원천 서버 응답 지연으로 수집 실패. " * 40) if index < 3 else None,
         "error": ("TimeoutError: " + "긴 상세 오류 " * 80) if index < 3 else None,
         "retrieved_at": run["as_of"], "requested_as_of": run["as_of"],
         "receipt": {"full_capture": "x" * 10000}, "capture_window": ["raw" * 1000]}
        for index in range(17)
    ]
    return run


def test_display_rounding_preserves_input_paths_probabilities_and_identity():
    run = _run()
    before = copy.deepcopy(run)
    projected = D.project_run(run)
    assert run == before
    for key in ("forecast_id", "as_of", "anchor_date", "input_hash", "contract_hash", "coefficient_hash"):
        assert projected[key] == run[key]
    assert len(projected["records"]) == 252 and len(projected["representative"]["values"]) == 253
    assert projected["representative"]["path_id"] == "simulation-12"
    assert projected["representative"]["path_hash"] == run["representative"]["path_hash"]
    assert projected["anchor"] == projected["representative"]["values"][0] == projected["baseline_median"][0] == projected["history"]["index"][-1]
    assert projected["history"]["dates"] == run["history"]["dates"][-253:]
    for actual, original in zip(projected["representative"]["values"], run["representative"]["values"]):
        assert abs(actual - original) <= 5.01e-7
    for actual, original in zip(projected["records"], run["records"]):
        for field in ("daily_return_quantiles", "drawdown_quantiles"):
            for level in C.QUANTILE_NAMES:
                assert abs(actual[field][level] - original[field][level]) <= 5.01e-9
        assert abs(actual["probability_up_from_previous"] - original["probability_up_from_previous"]) <= 5.01e-9
        assert abs(actual["probability_down_from_previous"] - original["probability_down_from_previous"]) <= 5.01e-9
        assert actual["probability_down_from_previous"] != 1 - actual["probability_up_from_previous"]
    assert projected["score"] == round(run["score"], 3)
    assert projected["attribution"]["inflation"]["21"] == round(run["attribution"]["inflation"]["21"], 10)
    assert projected["attribution"]["inflation"]["63"] is None
    assert projected["attribution_basis"]["inflation"] == [round(value, 10) for value in run["attribution_basis"]["inflation"]]
    assert projected["state_summary"]["axes"][0]["score"] is None
    metadata = projected["display_precision"]
    assert metadata["stored_run_unchanged"] and metadata["index_decimal_places"] == 6
    assert metadata["fraction_decimal_places"] == 8
    assert metadata["source_run_content_hash"] == run["content_hash"]
    assert projected["projection_hash"] == C.canonical_hash({key: value for key, value in projected.items() if key != "projection_hash"})


def test_realistic_long_card_payload_fits_and_declares_all_omissions():
    run = _stress_run()
    before = copy.deepcopy(run)
    projected = D.project_run(run)
    _, sidecar = dashboard.split_market_context_data({"market_context": projected})
    size = len(json.dumps(sidecar, ensure_ascii=False, default=str, separators=(",", ":")).encode())
    assert size <= dashboard.MARKET_CONTEXT_BUDGET_BYTES == D.ROUTE_BUDGET_BYTES
    assert run == before
    event_display = projected["state_summary"]["event_display"]
    assert event_display["total"] == 97
    assert event_display["shown"] in {10, 20}
    assert event_display["omitted"] == 97 - event_display["shown"]
    assert event_display["full_values_retained"]
    assert event_display["ledger_ref"] == "data/market_context/events.jsonl"
    assert len(projected["records"]) == 252 and len(projected["history"]["dates"]) == 253
    assert len(projected["state_summary"]["source_statuses"]) == 17
    assert [row["source_id"] for row in projected["state_summary"]["source_statuses"] if row["status"] == "failed"] == ["source-0", "source-1", "source-2"]
    assert projected["state_summary"]["source_status_display"]["all_failures_included"]
    for row in projected["state_summary"]["source_statuses"]:
        assert "receipt" not in row and "capture_window" not in row
        assert row.get("reason") is None or len(row["reason"]) <= 240
    for row in projected["state_summary"]["events"]:
        assert len(row["title"]) <= 240
        original = next(item for item in run["state_summary"]["events"] if item["event_id"] == row["event_id"])
        assert row["source_url"] == original["source_url"], "Source URLs are never shortened into broken links"
        assert "title" in row["display_excerpt_fields"]


def test_unavailable_representative_has_no_median_substitution():
    run = _run()
    run["representative"] = {"status": "unavailable", "reason": "typicality gate failed"}
    projected = D.project_run(run)
    assert projected["representative"] == run["representative"]
    assert "values" not in projected["representative"]


def test_oversized_cards_use_declared_ten_card_page_and_keep_all_failures():
    run = _stress_run()
    for event in run["state_summary"]["events"]:
        event["source_url"] += "b" * 800
    projected = D.project_run(run)
    _, sidecar = dashboard.split_market_context_data({"market_context": projected})
    assert len(json.dumps(sidecar, ensure_ascii=False, separators=(",", ":")).encode()) <= D.ROUTE_BUDGET_BYTES
    paging = projected["state_summary"]["event_display"]
    assert paging["shown"] == paging["applied_limit"] == 10
    assert paging["omitted"] == 87 and paging["total"] == 97
    assert len(projected["state_summary"]["source_statuses"]) == 17


def test_rounded_projection_still_validates_and_card_counts_are_visible(tmp_path):
    from test_market_context_ui import _run as _run_ui

    projected = D.project_run(_stress_run())
    result = _run_ui(tmp_path, "const mc=" + json.dumps(projected) + ";marketContextValidate(mc);const model=marketContextChartModel(mc);process.stdout.write(JSON.stringify({html:marketContextSources(mc),points:model.primary.length}));")
    assert result["points"] == 253
    assert "20 / 전체 97개" in result["html"] and "나머지 77개" in result["html"]
    assert "최대 240자 요약" in result["html"] and "수집 실패·대기" in result["html"]


@pytest.mark.parametrize("problem", ["unit", "out_of_bounds_probability", "crossed_quantiles", "invalid_drawdown", "nonfinite", "negative_price"])
def test_rounding_never_repairs_invalid_values(problem):
    run = _run()
    if problem == "unit":
        run["probability_unit"] = "percent"
    elif problem == "out_of_bounds_probability":
        run["records"][0]["probability_up_from_origin"] = 1 + 1e-10
    elif problem == "crossed_quantiles":
        row = run["records"][0]["drawdown_quantiles"]
        row["p25"] = row["p50"] + 1e-10
    elif problem == "invalid_drawdown":
        run["records"][0]["drawdown_quantiles"]["p95"] = 1e-10
    elif problem == "nonfinite":
        run["records"][0]["daily_return_quantiles"]["p50"] = float("nan")
    elif problem == "negative_price":
        run["records"][0]["index_quantiles"]["p05"] = -1e-10
    with pytest.raises(C.MarketContextError):
        D.project_run(run)
