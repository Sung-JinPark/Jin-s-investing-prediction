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


def test_track_panel_is_rendered_next_to_the_single_scenario_flow() -> None:
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    assert "function scenarioTrackPanel()" in script
    assert "const track=scenarioTrackPanel();if(track)graphPanels.original.appendChild(track);" \
        in script
    # 조건부 경로임을 화면에서 밝힌다 — 오차 부호를 실력으로 읽으면 안 된다
    assert "오차의 부호를 실력으로 읽으면 안 됩니다" in html
    # 백테스트 금지 원칙을 산출 방법에 명시한다
    assert "지금 모형을 과거로 되돌려 그리지 않습니다" in html
    assert "data-scenario-track-chart" in html
