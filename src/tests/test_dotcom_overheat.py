"""닷컴 대비 과열도 지수 — 100% = 닷컴 정점 축의 결정론적 집계 검증."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

from ai_fc.dotcom_overheat import CONTRACT_RELATIVE, compute_index, dotcom_range_position

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
    (root / CONTRACT_RELATIVE).write_text(
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


def test_overheat_and_statistics_share_the_refreshed_snapshot(tmp_path: Path) -> None:
    from ai_fc.statistics_lab import statistics_dashboard_projection

    for relative in (CONTRACT_RELATIVE.as_posix(),
                     "data/statistics/dotcom_statistics_latest.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    original = compute_index(tmp_path)
    snapshot = tmp_path / "data/statistics/dotcom_statistics_latest.json"
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    spec = yaml.safe_load((tmp_path / CONTRACT_RELATIVE)
                          .read_text(encoding="utf-8"))["indicators"][0]
    chart = next(c for c in payload["charts"] if c["id"] == spec["chart"])
    series = next(s for s in chart["series"] if s["label"] == spec["current_series"])
    series["points"][-1]["value"] *= 1.1
    snapshot.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    index = compute_index(tmp_path)
    display = statistics_dashboard_projection(tmp_path)
    shown_chart = next(c for c in display["charts"] if c["id"] == spec["chart"])
    shown = next(s for s in shown_chart["series"] if s["label"] == spec["current_series"])
    row = next(r for r in index["indicators"] if r["id"] == spec["id"])
    old = next(r for r in original["indicators"] if r["id"] == spec["id"])
    assert row["current_value"] == shown["points"][-1]["value"]
    assert row["pct"] != old["pct"]
    assert index["generated_at"] == display["generated_at"] == payload["generated_at"]
    assert index["observation_through"] == display["observation_through"]


def test_daily_refresh_reaches_pages_and_failure_monitor() -> None:
    def workflow(name: str) -> dict:
        return yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text(encoding="utf-8"))

    refresh = workflow("statistics-refresh")
    triggers = refresh.get("on", refresh.get(True))
    assert triggers["schedule"] == [{"cron": "20 6 * * *"}]
    steps = refresh["jobs"]["refresh"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "python -m ai_fc statistics-refresh" in commands
    assert "python -m ai_fc official-data-workbook" in commands
    assert "data/statistics/official_store/ledgers" in commands
    assert "src/tests/test_dotcom_overheat.py" in commands
    # IPO 월별 건수는 통계 빌드 전에 갱신되고, 그 표들이 커밋 대상이어야 한다.
    assert commands.index("python -m ai_fc ipo-monthly-counts") < commands.index(
        "python -m ai_fc statistics-refresh")
    for path in ("data/statistics/ipo/ritter_ipoall_monthly.json",
                 "data/statistics/ipo/nasdaq_calendar_monthly.json",
                 "data/statistics/ipo/monthly_counts_status.json"):
        assert path in commands
    for name in ("pages", "ops-failure-alert"):
        doc = workflow(name)
        events = doc.get("on", doc.get(True))
        assert "statistics-refresh" in events["workflow_run"]["workflows"]
        assert "completed" in events["workflow_run"]["types"]


def test_indicators_carry_display_labels_from_the_statistics_cards() -> None:
    """통계 화면 패널이 지표를 통계 카드 제목으로 부르고 그 카드로 이동할 수 있어야 한다."""
    result = compute_index(ROOT)
    if result.get("status") != "ok":
        import pytest
        pytest.skip("statistics snapshot unavailable")
    payload = json.loads((ROOT / "data/statistics/dotcom_statistics_latest.json").read_text(encoding="utf-8"))
    titles = {chart["id"]: chart.get("title") for chart in payload["charts"]}
    for row in result["indicators"]:
        assert row["chart"] in titles
        assert row["title"] == titles[row["chart"]]
        assert row["why"]


def test_statistics_page_leads_with_the_overheat_panel() -> None:
    """2026-10-06 사용자 지시: 통계 화면은 제목 바로 아래 닷컴 대비 과열도부터 보인다."""
    from ai_fc import dashboard

    html = dashboard.render_html({}, mode="embed")
    render = html[html.index("function renderStatistics("):html.index("function timeseriesFeatureLabel")]
    assert render.index("statisticsOverheatPanel(DATA.dotcom_overheat)") < render.index("statistics-filters")
    panel = html[html.index("function statisticsOverheatPanel"):html.index("function renderStatistics(")]
    # 대표값은 산포와 함께, 확률 아님·100%=정점 라벨 유지
    assert "부문별 ${sig.lo}~${sig.hi}%" in panel
    assert "확률 아님 · 100% = 닷컴 사이클 정점" in panel and "참고 의견" in panel


def test_v2_contract_adds_the_ipo_count_and_keeps_v1_as_history() -> None:
    """2026-10-06 사용자 결정: IPO 건수(운영기업 12개월 합)를 새 계약 버전으로 편입."""
    assert CONTRACT_RELATIVE.name == "dotcom_overheat_index_v2.yaml"
    v1 = yaml.safe_load((ROOT / "data/contracts/dotcom_overheat_index_v1.yaml").read_text(encoding="utf-8"))
    v2 = yaml.safe_load((ROOT / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    assert v1["contract_id"] == "dotcom_overheat_index_v1"
    assert all(row["id"] != "ipo_count_operating_12m" for row in v1["indicators"])
    assert v2["contract_id"] == "dotcom_overheat_index_v2" and v2["supersedes"] == "dotcom_overheat_index_v1"
    assert v2["method"] == v1["method"] | {"known_limits": v2["method"]["known_limits"]}
    assert v1["indicators"] == v2["indicators"][:len(v1["indicators"])]
    ipo = next(row for row in v2["indicators"] if row["id"] == "ipo_count_operating_12m")
    assert ipo["chart"] == "ipo_count_operating_12m"
    assert (ipo["dotcom_series"], ipo["current_series"]) == ("닷컴", "현재")
    assert ipo["direction"] == "higher_is_hotter"
    assert ipo["sources"]["index_input"] == "ritter_ipoall_monthly"
    assert str(ipo["nasdaq_user_agent_authorization"]["authorized_on"]) == "2026-10-06"


def test_live_index_includes_the_confirmed_ipo_count_in_its_own_category() -> None:
    result = compute_index(ROOT)
    assert result["contract_id"] == "dotcom_overheat_index_v2"
    row = next(r for r in result["indicators"] if r["id"] == "ipo_count_operating_12m")
    assert row["category"] == "ipo"
    assert "ipo" in result["category_medians"]
    payload = json.loads((ROOT / "data/statistics/dotcom_statistics_latest.json").read_text(encoding="utf-8"))
    chart = next(c for c in payload["charts"] if c["id"] == "ipo_count_operating_12m")
    confirmed = next(s for s in chart["series"] if s["label"] == "현재")
    assert not confirmed.get("provisional")
    # 지수 입력은 확정 계열의 마지막 점이다 — 잠정 계열의 끝점이 아니다.
    assert row["current_value"] == confirmed["points"][-1]["value"]
    assert row["current_period"] == confirmed["points"][-1]["period"]


def test_provisional_series_never_enters_the_index(tmp_path: Path) -> None:
    """계약이 잠정 계열 라벨을 가리켜도 지수는 그 지표를 건너뛴다."""
    dotcom = list(range(10, 23))
    charts = [{"id": "ipo", "category": "ipo", "series": [
        _series("닷컴", "dotcom", dotcom),
        _series("현재", "current", [12] * 13),
        {**_series("현재 잠정", "current", [22] * 14), "provisional": True, "dash": "2 5"},
    ]}]
    spec = {"chart": "ipo", "dotcom_series": "닷컴", "direction": "higher_is_hotter"}
    _write(tmp_path, charts, [
        {"id": "confirmed", "current_series": "현재", **spec},
        {"id": "wrong", "current_series": "현재 잠정", **spec},
    ])
    result = compute_index(tmp_path)
    assert [row["id"] for row in result["indicators"]] == ["confirmed"]
    assert result["indicators"][0]["current_value"] == 12
    assert result["skipped"] == [{"id": "wrong", "reason": "잠정 계열은 지수 입력 아님"}]
