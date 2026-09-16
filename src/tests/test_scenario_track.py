"""기록된 S1 빈티지 vs 실제 종가 대조(scenario_track)의 계약."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ai_fc import dashboard
from ai_fc.scenario_track import _dates_from_week_labels, load_scenario_track

ROOT = Path(__file__).resolve().parents[2]


def _archive(root: Path, asof: str, *, anchor: float, values: list[float],
             week_dates: list[str] | None = None, weeks: list[str] | None = None,
             prob: int = 80, ath: float = 27000.0) -> None:
    payload: dict = {
        "asof": asof, "anchor": anchor, "ath": ath,
        "paths": {"S1": {"label": "상승·ATH 돌파", "prob": prob, "values": values},
                  "S3": {"label": "조정·횡보", "prob": 10, "values": values}},
    }
    if week_dates is not None:
        payload["week_dates"] = week_dates
    if weeks is not None:
        payload["weeks"] = weeks
        payload["schema_version"] = 1
    directory = root / "data" / "scenarios" / "archive"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{asof}.json").write_text(json.dumps(payload, ensure_ascii=False),
                                            encoding="utf-8")


def test_week_labels_recover_iso_dates_and_roll_the_year() -> None:
    """schema v1 은 week_dates 가 없다 — 'M/D' 라벨에서 날짜를 되살린다."""
    assert _dates_from_week_labels(["7/30", "8/6"], "2026-07-30") == \
        ["2026-07-30", "2026-08-06"]
    # 월이 줄어드는 지점이 연도 롤오버다
    assert _dates_from_week_labels(["12/31", "1/7"], "2026-12-31") == \
        ["2026-12-31", "2027-01-07"]
    assert _dates_from_week_labels(["7/30", "쓰레기"], "2026-07-30") is None


def test_track_scores_every_overlapping_week_point(tmp_path: Path) -> None:
    """마지막 한 점만 채점하면 같은 선의 앞구간 오차가 통계에서 사라진다."""
    _archive(tmp_path, "2026-07-30", anchor=25000.0,
             values=[25000.0, 25500.0, 26000.0], weeks=["7/30", "8/6", "8/13"])
    _archive(tmp_path, "2026-08-06", anchor=25100.0,
             values=[25100.0, 25600.0],
             week_dates=["2026-08-06", "2026-08-13"])
    _archive(tmp_path, "2026-08-13", anchor=25200.0,
             values=[25200.0], week_dates=["2026-08-13"])

    track = load_scenario_track(tmp_path)
    assert track["status"] == "ok"
    assert track["scenario_key"] == "S1"
    # 실제 종가 계열은 아카이브 anchor 그대로 — 외부 조회 없음
    assert track["actual"] == [["2026-07-30", 25000.0],
                               ["2026-08-06", 25100.0],
                               ["2026-08-13", 25200.0]]

    first = track["vintages"][0]
    assert first["match_count"] == 2, "8/6·8/13 두 점 모두 채점돼야 한다"
    assert first["realized"]["date"] == "2026-08-13"
    assert first["realized"]["error_pct"] == pytest.approx(
        (26000.0 - 25200.0) / 25200.0 * 100, abs=0.01)
    # 3건 중 마지막 빈티지는 미래 주차점이 없어 미실현이다
    assert track["stats"]["scored_vintage_count"] == 2
    assert track["stats"]["scored_point_count"] == 3


def test_track_drops_vintages_whose_dates_do_not_line_up(tmp_path: Path) -> None:
    """날짜와 값의 길이가 어긋나면 조용히 어긋난 선을 그리느니 버린다."""
    _archive(tmp_path, "2026-07-30", anchor=25000.0, values=[25000.0, 25500.0],
             week_dates=["2026-07-30"])          # 길이 불일치 → 제외
    _archive(tmp_path, "2026-08-06", anchor=25100.0, values=[25100.0],
             week_dates=["2026-08-06"])
    assert load_scenario_track(tmp_path)["status"] == "unavailable"


def test_track_horizon_follows_the_realized_window(tmp_path: Path) -> None:
    """빈티지는 252거래일까지 뻗는다 — 전량을 실으면 겹치는 구간이 화면에서 눌린다.

    이 화면의 용도는 겹침을 보는 것이므로 마지막 실제 종가에서 LEAD_DAYS 만큼만 더 그린다.
    """
    _archive(tmp_path, "2026-07-30", anchor=25000.0,
             values=[25000.0, 26000.0, 30000.0],
             week_dates=["2026-07-30", "2026-09-10", "2027-06-30"])
    _archive(tmp_path, "2026-08-06", anchor=25100.0, values=[25100.0],
             week_dates=["2026-08-06"])
    track = load_scenario_track(tmp_path)
    assert track["cut"] == "2026-09-17", "마지막 실제 2026-08-06 + 42일"
    assert [day for day, _ in track["vintages"][0]["values"]] == \
        ["2026-07-30", "2026-09-10"]


def test_real_repository_track_starts_at_the_first_archived_record() -> None:
    """실제 저장소: 기록이 시작된 날부터이고, 그 이전은 그리지 않는다.

    백테스트 금지(5원칙 ⑤) 때문에 기록 이전 기간으로 선을 늘릴 수 없다.
    """
    track = load_scenario_track(ROOT)
    assert track["status"] == "ok"
    first = track["stats"]["first_asof"]
    assert first == track["actual"][0][0]
    assert all(row["asof"] >= first for row in track["vintages"])
    # 각 선의 첫 점은 자기 예측일이다 — 과거로 뻗지 않는다
    for row in track["vintages"]:
        assert row["values"][0][0] == row["asof"]
    assert track["stats"]["mean_abs_error_pct"] is not None
    # 겹침이 화면에서 눌리면 대조가 목적인 그래프가 제 일을 못 한다 — 실현 구간이
    # 가로 지평의 3분의 1은 넘어야 한다.
    span = (date.fromisoformat(track["cut"])
            - date.fromisoformat(track["actual"][0][0])).days
    realized = (date.fromisoformat(track["actual"][-1][0])
                - date.fromisoformat(track["actual"][0][0])).days
    assert realized / span > 1 / 3


def test_actual_is_overlaid_inside_the_original_graph_not_a_second_one() -> None:
    """실제 종가는 별도 그래프가 아니라 최초 버전 그래프 안에 검은 선으로 들어간다.

    인덱스 축에서는 앵커 왼쪽(이미 지나간 구간)에 자리가 없다 — 가로축을 날짜로 잡아야
    실제 선이 그려질 자리가 생긴다.

    선은 현재 S1 경로 하나만 둔다. 지난 빈티지를 전부 겹치면 빗각으로 퍼지는 선다발이 되어
    실제 주가 그래프처럼 읽히지 않는다. 지난 예측의 적중은 선이 아니라 오차율과 표로 읽는다.
    """
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")

    # 별도 그래프 패널은 없다 — 요약과 표만 같은 패널 안으로 접힌다
    assert "function scenarioTrackPanel" not in script
    assert "function drawScenarioTrack" not in script
    assert "data-scenario-track-chart" not in html
    # 과거 대조 요약 박스(scenarioTrackSummary)는 2026-09-16 제거됐다 — 소유자 지시:
    # 오차율 표·박스가 화면을 어지럽힌다. 그래프 자체(실제 선 오버레이)만 남는다.
    assert "function scenarioTrackSummary" not in script
    assert "겹치는 구간 평균 절대오차" not in html
    assert "예측일별 오차" not in html

    # 최초 버전 그래프는 실제 선을 직접 그린다
    flow = script.split("function drawOriginalWeeklyFlow")[1].split("const ORIGINAL_FLOW_KEY")[0]
    assert "data-track-actual" in flow, "실제 종가 선을 그래프 안에서 그려야 한다"
    assert "const dateX=day=>" in flow, "가로축은 날짜 기반이어야 실제 선 자리가 생긴다"
    # 빗각 선다발 금지 — 그려지는 경로는 현재 S1 하나뿐이다
    assert "data-track-vintage" not in flow
    assert "priorVintages" not in script
    # 실제 선은 일간이라고 밝힌다
    assert "실제 종가 (일간)" in html


def test_chart_labels_stay_inside_the_drawing_area() -> None:
    """축 왼쪽 여백보다 긴 라벨을 anchor:end 로 두면 viewBox 밖으로 잘린다.

    '−10%선 누적 터치확률' 은 약 104px 인데 왼쪽 여백은 ML=58 뿐이라, x=ML-8 에 오른쪽
    정렬하면 −53px 까지 삐져나가 글자가 잘린 채 보인다. 띠 위에 왼쪽 정렬로 둔다.
    """
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    assert "tx(ML-8,RY+19,'−10%선 누적 터치확률'" not in script, "잘리는 배치가 되돌아왔다"
    assert script.count("tx(ML,RY-6,'−10%선 누적 터치확률',{fill:'#5f5d57',fs:11,w:650})") == 2,         "같은 버그가 두 그래프에 있었다 — 둘 다 고쳐진 상태여야 한다"


def test_vintage_uses_the_path_that_was_actually_drawn(tmp_path: Path) -> None:
    """그날 화면에 그려진 선은 원시 GBM 중앙값이 아니라 굴곡을 입힌 구조 경로다.

    원시 값을 쓰면 매끈한 우상향 직선이 나와, 그날 화면과 다른 그림을 놓고
    "얼마나 맞았나"를 묻게 된다. dashboard.js 의 flowDisplayPath 와 같은 규칙을 쓴다.
    """
    payload = {
        "asof": "2026-08-06", "anchor": 26348.0, "ath": 27000.0,
        "week_dates": ["2026-08-06", "2026-08-13", "2026-08-20"],
        "paths": {"S1": {"label": "상승·ATH 돌파", "prob": 80,
                         "values": [26348.0, 26500.0, 26650.0]}},          # 매끈한 원시
        "structural_forecast": {
            "paths": {"S1": {"values": [26348.0, 25655.0, 26900.0]}},      # 굴곡 입힌 선
        },
    }
    directory = tmp_path / "data" / "scenarios" / "archive"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "2026-08-06.json").write_text(json.dumps(payload, ensure_ascii=False),
                                               encoding="utf-8")
    _archive(tmp_path, "2026-08-13", anchor=26000.0, values=[26000.0],
             week_dates=["2026-08-13"])

    track = load_scenario_track(tmp_path)
    drawn = next(row for row in track["vintages"] if row["asof"] == "2026-08-06")
    assert drawn["path_source"] == "structural"
    assert [value for _, value in drawn["values"]][:2] == [26348, 25655], "원시 값을 그렸다"
    # 채점도 그려진 선으로 한다 — 음영과 표가 다른 선을 가리키면 안 된다
    assert drawn["realized"]["predicted"] == 25655


def test_pre_curvature_archives_fall_back_without_pretending(tmp_path: Path) -> None:
    """굴곡 도입 전(schema v1) 아카이브는 원시 값이 곧 그려진 선이었다 — 폴백이 사실이다."""
    _archive(tmp_path, "2026-07-30", anchor=25000.0,
             values=[25000.0, 25500.0], weeks=["7/30", "8/6"])
    _archive(tmp_path, "2026-08-06", anchor=25100.0, values=[25100.0],
             week_dates=["2026-08-06"])
    track = load_scenario_track(tmp_path)
    assert track["vintages"][0]["path_source"] == "gbm_median"


def test_past_orange_overlay_is_removed_future_line_and_actual_remain() -> None:
    """2026-09-16 소유자 지시로 과거 구간의 주황(기록된 예측) 오버레이를 뺐다.

    과거~오늘은 검은 실제 선만 남고, 오늘~미래는 지금 기록된 S1 하나로 그대로 이어진다.
    이 테스트는 옛 드로잉 코드(비교선·이음새·간격 채움)가 되돌아오지 않는지 고정한다.
    """
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    flow = script.split("function drawOriginalWeeklyFlow")[1].split("const ORIGINAL_FLOW_KEY")[0]
    for gone in (
        "data-track-compare", "data-track-gap", "pastSegments", "comparePoints",
        "compare.asof<sc.asof", "realizedEnd", "handover_label",
    ):
        assert gone not in flow, f"과거 주황선 드로잉이 되돌아옴: {gone}"
    html = dashboard.load_template()
    for gone in ("comparable", "defaultCompare", "data-original-compare", "맞대 볼 예측일"):
        assert gone not in html, f"예측일 선택기가 되돌아옴: {gone}"

    # 미래 구간(오늘→앞)의 주황 선은 그대로다
    assert "stroke:CHART_COL[key],'stroke-width':2.6" in flow
    assert "data-original-path" in flow
    # 검은 실제 선은 유지
    assert "data-track-actual" in flow

def test_axis_ticks_are_thinned_by_pixel_gap() -> None:
    """'전체 전망'으로 축이 길어지면 주차 눈금과 실현 구간 날짜가 겹쳐 글자가 뭉개진다."""
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    flow = script.split("function drawOriginalWeeklyFlow")[1].split("const ORIGINAL_FLOW_KEY")[0]
    assert "TICK_MIN_GAP" in flow, "눈금을 픽셀 간격으로 솎지 않는다"
    assert "tickCandidates" in flow, "두 출처의 눈금을 한 목록으로 합치지 않는다"


def test_legend_does_not_pull_the_next_block_over_itself() -> None:
    """범례가 두 줄로 접히면 음수 마진으로 당겨진 다음 블록이 그 위를 덮는다(실측 8px)."""
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")
    assert ".flow-shape-controls{margin:-8px" not in css, "음수 마진이 되돌아왔다"
    assert ".band-inline{margin-bottom:" in css


def test_past_line_hands_over_to_the_richer_record(tmp_path: Path) -> None:
    """더 촘촘한 기록이 생긴 날부터는 그쪽으로 바통을 넘긴다.

    성긴 기록(주간)만 끝까지 끌면 오늘까지 직선 몇 개로 남는다. 촘촘함의 순위는
    일별 252점 > 굴곡 주간 52점 > 원시 주간이고, 각 구간은 그때 기록된 값 그대로다.
    """
    _archive(tmp_path, "2026-07-30", anchor=25000.0,
             values=[25000.0, 25200.0, 25400.0], weeks=["7/30", "8/6", "8/13"])
    curved = {
        "asof": "2026-08-06", "anchor": 26000.0, "ath": 27000.0,
        "week_dates": ["2026-08-06", "2026-08-13", "2026-08-20"],
        "paths": {"S1": {"label": "상승·ATH 돌파", "prob": 80,
                         "values": [26000.0, 26100.0, 26200.0]}},
        "structural_forecast": {"paths": {"S1": {"values": [26000.0, 25400.0, 26300.0]}}},
    }
    (tmp_path / "data" / "scenarios" / "archive" / "2026-08-06.json").write_text(
        json.dumps(curved, ensure_ascii=False), encoding="utf-8")
    _archive(tmp_path, "2026-08-20", anchor=26500.0, values=[26500.0],
             week_dates=["2026-08-20"])

    line = load_scenario_track(tmp_path)["past_line"]
    assert line["handover_from"] == "2026-08-06"
    assert line["handover_label"] == "굴곡 기록"
    assert [seg["asof"] for seg in line["segments"]] == ["2026-07-30", "2026-08-06"]

    first, second = line["segments"]
    assert first["values"][-1][0] == "2026-08-06", "바통 넘김 지점에서 끝나야 한다"
    assert second["path_source"] == "structural"
    # 굴곡 구간은 굴곡 값을 쓴다 — 원시 26100 이 아니라 25400
    assert second["values"][1][1] == 25400
    # 이음점 단차는 지우지 않는다 — 앞 기록이 그때까지 얼마나 빗나가 있었는지다
    assert first["values"][-1][1] != second["values"][0][1]
    # 앞 구간이 다음 구간 시작을 넘어가면 두 선이 갈래처럼 보인다
    assert first["values"][-1][0] <= second["values"][0][0]


def test_past_line_reaches_the_junction_across_a_holiday_gap(tmp_path: Path) -> None:
    """주차 격자가 휴일 보정으로 오늘을 건너뛰면, 오늘에서 끊어 빈 구간을 만들면 안 된다.

    실제 저장소의 2026-08-06 빈티지는 9/03 다음이 9/11 이라 오늘(9/10)이 격자에 없다.
    """
    _archive(tmp_path, "2026-07-30", anchor=25000.0,
             values=[25000.0, 25200.0, 25400.0],
             week_dates=["2026-07-30", "2026-09-03", "2026-09-11"])
    _archive(tmp_path, "2026-09-10", anchor=26000.0, values=[26000.0],
             week_dates=["2026-09-10"])

    line = load_scenario_track(tmp_path)["past_line"]
    last = line["segments"][-1]["values"][-1][0]
    assert last >= "2026-09-10", f"오늘 이전({last})에서 끊겨 현재 경로와 이어지지 않는다"


def test_daily_series_fills_in_only_where_no_structural_path_exists(tmp_path: Path) -> None:
    """일별은 **구조 경로가 없을 때의 차선책**이다.

    일별 축은 asof **다음** 거래일부터라 그날 확정 종가를 앞에 붙여 선이 그날에서 출발한다.
    구조 경로가 있으면 그쪽이 이긴다 — 점 수가 아니라 모양의 현실성이 기준이다.
    """
    payload = {
        "asof": "2026-08-06", "anchor": 26000.0, "ath": 27000.0,
        "week_dates": ["2026-08-06", "2026-08-13"],
        "paths": {"S1": {"label": "상승·ATH 돌파", "prob": 80, "values": [26000.0, 26500.0]}},
        "quantile_table": {
            "trading_days": ["2026-08-07", "2026-08-10", "2026-08-11"],
            "per_scenario_p50": {"S1": [26100.0, 26050.0, 26200.0]},
        },
    }
    directory = tmp_path / "data" / "scenarios" / "archive"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "2026-08-06.json").write_text(json.dumps(payload, ensure_ascii=False),
                                               encoding="utf-8")
    _archive(tmp_path, "2026-08-11", anchor=26150.0, values=[26150.0],
             week_dates=["2026-08-11"])

    row = next(v for v in load_scenario_track(tmp_path)["vintages"] if v["asof"] == "2026-08-06")
    assert row["path_source"] == "daily_p50"
    assert [day for day, _ in row["values"]] == \
        ["2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]
    assert row["values"][0][1] == 26000, "그날 확정 종가에서 출발해야 한다"


def test_real_repository_draws_a_shaped_path_not_a_monotone_median() -> None:
    """실제 저장소 회귀 — 그려지는 경로는 **모양이 있는** 구조 경로여야 한다.

    일별 252점이 더 촘촘하지만 그것은 9,000 경로의 조건부 중앙값이라 거의 단조 상승한다
    (실측 1년 최대 낙폭 0.07%, 그리는 창에서는 하락 0회). 가격 경로로 내보이면 비현실적이라
    점이 많다고 더 나은 것이 아니다 — 구조 경로는 같은 기간 최대 낙폭 12.15%.
    """
    track = load_scenario_track(ROOT)
    sources = [row["path_source"] for row in track["vintages"]]
    assert sources.count("structural") > len(sources) / 2,         f"구조 경로가 주류여야 한다: {sorted(set(sources))}"

    def max_drawdown_pct(values: list[float]) -> float:
        peak, worst = values[0], 0.0
        for value in values:
            peak = max(peak, value)
            worst = max(worst, (peak - value) / peak * 100)
        return worst

    # 오늘까지 덮는 과거 구간은 단조 상승이면 안 된다 — 그 자체가 비현실의 신호다
    tail = track["past_line"]["segments"][-1]
    assert tail["path_source"] == "structural", tail["path_source"]
    assert max_drawdown_pct([value for _, value in tail["values"]]) > 1.0,         "과거 구간이 낙폭 없이 우상향한다 — 조건부 중앙값으로 되돌아갔다"


def test_chart_draws_the_current_path_from_the_daily_table() -> None:
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    assert "function dailyScenarioPath(" in script
    flow = script.split("function drawOriginalWeeklyFlow")[1].split("const ORIGINAL_FLOW_KEY")[0]
    assert "!usingStructural)?dailyScenarioPath(sc,key,cut)" in flow,         "구조 경로가 있는데도 일별로 그린다"
    assert "'data-path-grid'" in flow, "어느 격자로 그렸는지 표시하지 않는다"
