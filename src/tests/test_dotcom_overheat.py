"""닷컴 대비 과열도 지수 — 사전등록 계약의 결정론적 집계 검증."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

from ai_fc.dotcom_overheat import compute_index, midrank_percentile

ROOT = Path(__file__).resolve().parents[2]


def _series(label: str, era: str, values: list[float], start: int = 0) -> dict:
    return {"label": label, "era": era,
            "points": [{"period": start + i, "date": f"{1995 + i // 12}-01-01", "value": v}
                       for i, v in enumerate(values)]}


def _write(root: Path, charts: list[dict], indicators: list[dict], *, minimum: int = 12) -> None:
    (root / "data/statistics").mkdir(parents=True, exist_ok=True)
    (root / "data/contracts").mkdir(parents=True, exist_ok=True)
    (root / "data/statistics/dotcom_statistics_latest.json").write_text(
        json.dumps({"status": "ok", "as_of": "2026-09-04", "charts": charts}, ensure_ascii=False),
        encoding="utf-8")
    (root / "data/contracts/dotcom_overheat_index_v1.yaml").write_text(
        yaml.safe_dump({"contract_id": "t", "version": "t",
                        "method": {"minimum_reference_points": minimum},
                        "indicators": indicators, "excluded": []}, allow_unicode=True),
        encoding="utf-8")


def test_midrank_percentile_is_bounded_and_handles_ties() -> None:
    assert midrank_percentile(0, [1, 2, 3]) == 0.0
    assert midrank_percentile(9, [1, 2, 3]) == 100.0
    assert midrank_percentile(2, [1, 2, 3]) == 50.0          # 1 below + half of one tie
    assert midrank_percentile(5, [5, 5, 5, 5]) == 50.0


def test_reference_window_is_cut_at_the_current_cycle_phase(tmp_path: Path) -> None:
    """닷컴 전 구간과 비교하면 43개월차 값이 59개월차 정점에 눌려 체계적으로 낮아진다."""
    charts = [{"id": "c", "category": "valuation",
               "series": [_series("닷컴", "dotcom", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 99, 99]),
                          _series("현재", "current", [50] * 13)]}]
    _write(tmp_path, charts, [{"id": "i", "chart": "c", "dotcom_series": "닷컴",
                               "current_series": "현재", "direction": "higher_is_hotter"}])
    row = compute_index(tmp_path)["indicators"][0]
    # 현재 최신 period 는 12 → 닷컴 period 0..12 (마지막 99 하나 포함) 만 본다
    assert row["reference_n"] == 13
    assert row["pct"] == 92.3          # 12/13 below → 92.3, 전 구간(14개)이면 85.7 로 낮아진다


def test_direction_contract_inverts_lower_is_hotter(tmp_path: Path) -> None:
    charts = [{"id": "c", "category": "rates",
               "series": [_series("닷컴", "dotcom", list(range(1, 14))),
                          _series("현재", "current", [1] * 13)]}]
    spec = {"id": "i", "chart": "c", "dotcom_series": "닷컴", "current_series": "현재"}
    _write(tmp_path, charts, [{**spec, "direction": "higher_is_hotter"}])
    hotter_high = compute_index(tmp_path)["indicators"][0]["pct"]
    _write(tmp_path, charts, [{**spec, "direction": "lower_is_hotter"}])
    hotter_low = compute_index(tmp_path)["indicators"][0]["pct"]
    assert hotter_high < 10 and hotter_low > 90
    assert round(hotter_high + hotter_low, 1) == 100.0


def test_thin_reference_windows_are_skipped_not_guessed(tmp_path: Path) -> None:
    charts = [{"id": "c", "category": "credit",
               "series": [_series("닷컴", "dotcom", [1, 2, 3]),
                          _series("현재", "current", [9, 9, 9])]}]
    _write(tmp_path, charts, [{"id": "thin", "chart": "c", "dotcom_series": "닷컴",
                               "current_series": "현재", "direction": "higher_is_hotter"}])
    result = compute_index(tmp_path)
    assert result["status"] == "unavailable"          # 남는 지표가 없으면 숫자를 내지 않는다
    assert "집계 가능한 지표 없음" in result["reason"]


def test_category_median_removes_the_indicator_count_bias(tmp_path: Path) -> None:
    """부문을 한 번 거치는 이유 — 평평한 중앙값은 차트가 몇 개 있느냐에 끌려간다.

    credit 4종이 전부 차갑고 valuation 1종이 뜨거우면, 평평한 중앙값은 credit 쪽으로
    쏠린다. 지표 개수는 설계가 아니라 어떤 차트가 존재하느냐의 부산물이다.
    """
    cold = [_series("닷컴", "dotcom", list(range(1, 14))), _series("현재", "current", [0] * 13)]
    hot = [_series("닷컴", "dotcom", list(range(1, 14))), _series("현재", "current", [99] * 13)]
    charts = [{"id": f"cold{i}", "category": "credit", "series": cold} for i in range(4)]
    charts.append({"id": "hot", "category": "valuation", "series": hot})
    indicators = [{"id": f"cold{i}", "chart": f"cold{i}", "dotcom_series": "닷컴",
                   "current_series": "현재", "direction": "higher_is_hotter"} for i in range(4)]
    indicators.append({"id": "hot", "chart": "hot", "dotcom_series": "닷컴",
                       "current_series": "현재", "direction": "higher_is_hotter"})
    _write(tmp_path, charts, indicators)
    result = compute_index(tmp_path)
    flat = statistics.median([row["pct"] for row in result["indicators"]])
    assert flat == 0.0                                  # 평평한 중앙값은 credit 4종에 눌린다
    assert result["overheat_pct"] == 50                 # 부문 중앙값 [0, 100] 의 중앙값
    assert result["category_span"] == [0, 100]


def test_live_contract_matches_the_shipped_statistics_payload() -> None:
    """계약이 지목한 차트·계열 라벨이 실제 payload 에 존재해야 한다 (라벨 오타 조기 검출)."""
    result = compute_index(ROOT)
    assert result["status"] == "ok", result
    assert result["skipped"] == [], result["skipped"]    # 전 지표가 실제로 집계됐다
    assert 0 <= result["overheat_pct"] <= 100
    assert result["probability_space"] == "reference_only"
    assert result["model_use"] is False and result["official_forecast_input"] is False
    lo, hi = result["category_span"]
    assert lo <= result["overheat_pct"] <= hi
