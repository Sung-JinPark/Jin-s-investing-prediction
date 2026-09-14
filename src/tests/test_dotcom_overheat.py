"""닷컴 대비 과열도 지수 — 100% = 닷컴 정점 축의 결정론적 집계 검증."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

from ai_fc.dotcom_overheat import compute_index, dotcom_range_position

ROOT = Path(__file__).resolve().parents[2]


def _series(label: str, era: str, values: list[float]) -> dict:
    return {"label": label, "era": era,
            "points": [{"period": i, "date": f"{1995 + i // 12}-01-01", "value": v}
                       for i, v in enumerate(values)]}


def _write(root: Path, charts: list[dict], indicators: list[dict], *, minimum: int = 12) -> None:
    (root / "data/statistics").mkdir(parents=True, exist_ok=True)
    (root / "data/contracts").mkdir(parents=True, exist_ok=True)
    (root / "data/statistics/dotcom_statistics_latest.json").write_text(
        json.dumps({"status": "ok", "as_of": "2026-09-04", "charts": charts}, ensure_ascii=False),
        encoding="utf-8")
    (root / "data/contracts/dotcom_overheat_index_v1.yaml").write_text(
        yaml.safe_dump({"contract_id": "t", "version": "t",
                        "method": {"scale": "dotcom_range_position",
                                   "minimum_reference_points": minimum},
                        "indicators": indicators, "excluded": []}, allow_unicode=True),
        encoding="utf-8")


def test_hundred_percent_means_the_dotcom_extreme() -> None:
    reference = [10, 20, 30, 40]
    assert dotcom_range_position(40, reference, "higher_is_hotter") == 100.0
    assert dotcom_range_position(10, reference, "higher_is_hotter") == 0.0
    assert dotcom_range_position(25, reference, "higher_is_hotter") == 50.0
    # lower_is_hotter 는 축이 뒤집힌다 — 닷컴 최저가 100%
    assert dotcom_range_position(10, reference, "lower_is_hotter") == 100.0
    assert dotcom_range_position(40, reference, "lower_is_hotter") == 0.0


def test_beyond_the_dotcom_peak_is_reported_not_clipped() -> None:
    """정점 초과를 100% 로 자르면 '닷컴보다 뜨겁다' 는 사실이 사라진다."""
    assert dotcom_range_position(50, [10, 20, 30, 40], "higher_is_hotter") == 400 / 3
    assert dotcom_range_position(0, [10, 20, 30, 40], "higher_is_hotter") < 0


def test_a_flat_dotcom_series_is_skipped_rather_than_divided_by_zero(tmp_path: Path) -> None:
    charts = [{"id": "c", "category": "credit",
               "series": [_series("닷컴", "dotcom", [5.0] * 13),
                          _series("현재", "current", [9.0] * 13)]}]
    _write(tmp_path, charts, [{"id": "flat", "chart": "c", "dotcom_series": "닷컴",
                               "current_series": "현재", "direction": "higher_is_hotter"}])
    result = compute_index(tmp_path)
    assert result["status"] == "unavailable"
    assert "집계 가능한 지표 없음" in result["reason"]


def test_narrow_start_to_peak_span_does_not_explode(tmp_path: Path) -> None:
    """계약이 기각한 cycle_start_anchor 의 실패 모드가 이 축에서는 재현되지 않아야 한다.

    시작 14.14, 정점 14.19 인 계열에 (현재-시작)/(정점-시작) 을 쓰면 분모가 0.05 라
    실측에서 -23,615% 가 나왔다. 닷컴 전 구간 범위를 분모로 쓰면 유한하게 남는다.
    """
    dotcom = [14.14, 4.9, 14.19] + [8.0] * 10          # 시작≈정점, 실제 범위는 넓다
    charts = [{"id": "c", "category": "credit",
               "series": [_series("닷컴", "dotcom", dotcom),
                          _series("현재", "current", [2.43] * 13)]}]
    _write(tmp_path, charts, [{"id": "narrow", "chart": "c", "dotcom_series": "닷컴",
                               "current_series": "현재", "direction": "higher_is_hotter"}])
    pct = compute_index(tmp_path)["indicators"][0]["pct"]
    assert -100 < pct < 100, pct                       # 폭발하지 않는다


def test_reference_is_the_full_dotcom_cycle_not_the_matched_phase(tmp_path: Path) -> None:
    """위험의 기준점은 1999-2000 의 정점이지 현재와 같은 개월차의 값이 아니다."""
    charts = [{"id": "c", "category": "valuation",
               "series": [_series("닷컴", "dotcom", [10] * 13 + [100]),   # 정점은 마지막에만
                          _series("현재", "current", [55] * 13)]}]        # 현재는 12개월차까지
    _write(tmp_path, charts, [{"id": "i", "chart": "c", "dotcom_series": "닷컴",
                               "current_series": "현재", "direction": "higher_is_hotter"}])
    row = compute_index(tmp_path)["indicators"][0]
    assert row["reference_n"] == 14                     # 위상으로 자르지 않는다
    assert row["dotcom_high"] == 100                    # 뒤에 오는 정점을 참조에 포함
    assert row["pct"] == 50.0


def test_category_median_removes_the_indicator_count_bias(tmp_path: Path) -> None:
    """부문을 한 번 거치는 이유 — 평평한 중앙값은 차트가 몇 개 있느냐에 끌려간다."""
    cold = [_series("닷컴", "dotcom", list(range(1, 14))), _series("현재", "current", [1] * 13)]
    hot = [_series("닷컴", "dotcom", list(range(1, 14))), _series("현재", "current", [13] * 13)]
    charts = [{"id": f"cold{i}", "category": "credit", "series": cold} for i in range(4)]
    charts.append({"id": "hot", "category": "valuation", "series": hot})
    indicators = [{"id": f"cold{i}", "chart": f"cold{i}", "dotcom_series": "닷컴",
                   "current_series": "현재", "direction": "higher_is_hotter"} for i in range(4)]
    indicators.append({"id": "hot", "chart": "hot", "dotcom_series": "닷컴",
                       "current_series": "현재", "direction": "higher_is_hotter"})
    _write(tmp_path, charts, indicators)
    result = compute_index(tmp_path)
    assert statistics.median([row["pct"] for row in result["indicators"]]) == 0.0
    assert result["overheat_pct"] == 50                 # 부문 중앙값 [0, 100] 의 중앙값
    assert result["category_span"] == [0, 100]


def test_live_contract_matches_the_shipped_statistics_payload() -> None:
    """계약이 지목한 차트·계열 라벨이 실제 payload 에 존재해야 한다 (라벨 오타 조기 검출)."""
    result = compute_index(ROOT)
    assert result["status"] == "ok", result
    assert result["skipped"] == [], result["skipped"]
    assert result["scale"] == "dotcom_range_position"
    assert result["probability_space"] == "reference_only"
    assert result["model_use"] is False and result["official_forecast_input"] is False
    lo, hi = result["category_span"]
    assert lo <= result["overheat_pct"] <= hi
    assert result["beyond_peak_count"] == sum(
        1 for row in result["indicators"] if row["pct"] > 100)
