from __future__ import annotations

import json
from pathlib import Path

from ai_fc.alert_notify import (
    STATE_PATH,
    compute_transitions,
    load_alerts,
    load_state,
    render_email,
    run_alert_notify,
)


def _snapshot(tmp_path: Path, statuses: dict[str, tuple[str, float]]) -> None:
    charts = []
    for chart_id, (status, proximity) in statuses.items():
        charts.append({
            "id": chart_id,
            "title": f"제목 {chart_id}",
            "approach_alert": {
                "kind": "dotcom_peak",
                "boundary_label": "닷컴 정점",
                "boundary_value": 100.0,
                "current_value": proximity,
                "proximity_percent": proximity,
                "status": status,
                "status_label": {"ok": "여유", "watch": "주의", "alert": "경고",
                                 "reached": "도달"}[status],
                "thresholds": {"watch_percent": 80.0, "alert_percent": 95.0},
                "signal_semantics": "display_convention_not_trade_signal",
            },
        })
    charts.append({"id": "no_alert_chart", "title": "경보 없는 차트"})
    target = tmp_path / "data/statistics/dotcom_statistics_latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"charts": charts}, ensure_ascii=False), encoding="utf-8")


def test_first_run_with_all_ok_sends_nothing_but_records_the_baseline(tmp_path: Path) -> None:
    _snapshot(tmp_path, {"a": ("ok", 42.0), "b": ("ok", 60.0)})
    result = run_alert_notify(tmp_path, now="2026-09-01T00:00:00+00:00")
    assert result["send"] is False and result["transitions"] == []
    state = json.loads((tmp_path / STATE_PATH).read_text(encoding="utf-8"))
    assert state["statuses"] == {"a": "ok", "b": "ok"}
    assert state["signal_semantics"] == "display_convention_not_trade_signal"


def test_escalation_sends_once_then_stays_silent_while_status_holds(tmp_path: Path) -> None:
    _snapshot(tmp_path, {"a": ("watch", 83.0), "b": ("ok", 50.0)})
    body = tmp_path / "body.md"
    first = run_alert_notify(tmp_path, body_out=body, now="2026-09-01T00:00:00+00:00")
    assert first["send"] is True
    assert "주의" in first["subject"] and "단계 상승" in first["subject"]
    text = body.read_text(encoding="utf-8")
    assert "여유 → **주의**" in text and "닷컴 정점 접근 83.0%" in text
    assert "매매 신호가 아닙니다" in text
    assert "전체 현황" in text and "제목 b" in text, "바뀐 것 외 전체 현황도 싣는다"

    # 같은 단계가 유지되는 다음 주에는 침묵한다.
    second = run_alert_notify(tmp_path, now="2026-09-08T00:00:00+00:00")
    assert second["send"] is False and second["transitions"] == []


def test_easing_back_to_ok_is_also_reported(tmp_path: Path) -> None:
    _snapshot(tmp_path, {"a": ("watch", 83.0)})
    run_alert_notify(tmp_path, now="2026-09-01T00:00:00+00:00")
    _snapshot(tmp_path, {"a": ("ok", 70.0)})
    result = run_alert_notify(tmp_path, body_out=tmp_path / "b.md",
                              now="2026-09-08T00:00:00+00:00")
    assert result["send"] is True
    assert result["transitions"][0]["direction"] == "eased"
    assert "완화" in result["subject"]


def test_transition_rules_treat_missing_history_as_ok() -> None:
    alerts = {
        "new_watch": {"title": "t", "status": "watch", "proximity_percent": 81.0,
                      "boundary_label": "닷컴 정점", "boundary_value": 100.0,
                      "current_value": 81.0},
        "new_ok": {"title": "t", "status": "ok", "proximity_percent": 10.0,
                   "boundary_label": "닷컴 정점", "boundary_value": 100.0,
                   "current_value": 10.0},
    }
    transitions = compute_transitions({}, alerts)
    assert [row["chart_id"] for row in transitions] == ["new_watch"], (
        "기록 없는 차트는 ok로 간주 — 첫 등장 ok는 알리지 않는다")


def test_worst_escalation_drives_the_subject() -> None:
    alerts = {
        "a": {"title": "A", "status": "alert", "proximity_percent": 96.0,
              "boundary_label": "닷컴 정점", "boundary_value": 100.0, "current_value": 96.0},
        "b": {"title": "B", "status": "watch", "proximity_percent": 82.0,
              "boundary_label": "닷컴 정점", "boundary_value": 100.0, "current_value": 82.0},
    }
    transitions = compute_transitions({"a": "watch", "b": "ok"}, alerts)
    subject, body = render_email(transitions, alerts, generated_at="2026-09-01")
    assert "경고" in subject and "2개 지표 단계 상승" in subject
    assert body.index("96.0%") < body.index("82.0%"), "전체 현황은 근접도 내림차순"


def test_test_mode_sends_a_wiring_check_without_transitions(tmp_path: Path) -> None:
    _snapshot(tmp_path, {"a": ("ok", 42.0)})
    body = tmp_path / "body.md"
    result = run_alert_notify(tmp_path, body_out=body,
                              now="2026-09-01T00:00:00+00:00", force_test=True)
    assert result["send"] is True and "개통 확인" in result["subject"]
    assert "발송 경로가 정상" in body.read_text(encoding="utf-8")


def test_loaders_ignore_malformed_state_and_charts(tmp_path: Path) -> None:
    _snapshot(tmp_path, {"a": ("ok", 42.0)})
    (tmp_path / STATE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / STATE_PATH).write_text("{broken", encoding="utf-8")
    assert load_state(tmp_path) == {}
    alerts = load_alerts(tmp_path)
    assert set(alerts) == {"a"}, "approach_alert 없는 차트는 무시"
