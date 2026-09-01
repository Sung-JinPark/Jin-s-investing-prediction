"""접근-경보 단계 전이 알림 — 게시 스냅샷을 읽어 이메일 발송 여부를 결정한다.

통계 갱신 때마다 각 차트의 ``approach_alert`` 단계를 이전 상태와 비교해
**전이가 있을 때만** 알림을 만든다.  주의 단계에 몇 달 머물러도 매주 같은
메일을 반복 발송하지 않고, 단계가 오르내릴 때 한 번씩만 알린다.

이 모듈은 네트워크를 쓰지 않는다 — 발송은 워크플로의 메일 액션이 하고,
여기서는 (보낼지, 제목, 본문)과 다음 비교를 위한 상태 파일만 만든다.
경보 자체가 표시 규약이듯 이 알림도 참고 정보이지 매매 신호가 아니다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = Path("data/statistics/dotcom_statistics_latest.json")
STATE_PATH = Path("data/statistics/alert_notify_state.json")

#: 단계 심각도 순서 — 전이 방향(악화/완화) 판정용.
STATUS_RANK = {"ok": 0, "watch": 1, "alert": 2, "reached": 3}
STATUS_LABEL = {"ok": "여유", "watch": "주의", "alert": "경고", "reached": "도달"}


class AlertNotifyError(RuntimeError):
    pass


def load_alerts(root: Path) -> dict[str, dict[str, Any]]:
    """게시 스냅샷에서 chart_id → approach_alert 맵을 뽑는다."""
    path = root / SNAPSHOT_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlertNotifyError("published statistics snapshot cannot be read") from exc
    alerts: dict[str, dict[str, Any]] = {}
    for chart in payload.get("charts") or []:
        alert = chart.get("approach_alert")
        if not isinstance(alert, dict) or alert.get("status") not in STATUS_RANK:
            continue
        alerts[str(chart.get("id"))] = {
            "title": str(chart.get("title", chart.get("id"))),
            **alert,
        }
    return alerts


def load_state(root: Path) -> dict[str, str]:
    path = root / STATE_PATH
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    statuses = payload.get("statuses")
    if not isinstance(statuses, dict):
        return {}
    return {
        str(chart_id): str(status)
        for chart_id, status in statuses.items()
        if status in STATUS_RANK
    }


def compute_transitions(
    previous: dict[str, str], alerts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """알릴 가치가 있는 전이만 고른다.

    규칙: 이전 상태(기록 없으면 ok로 간주)와 현재 상태가 다르고, 둘 중
    하나라도 ok가 아니면 알린다.  첫 실행에서 전부 ok면 아무것도 알리지
    않고 기준 상태만 기록한다 — 개통 스팸 방지.
    """
    transitions = []
    for chart_id, alert in sorted(alerts.items()):
        old = previous.get(chart_id, "ok")
        new = str(alert["status"])
        if old == new:
            continue
        if old == "ok" and new == "ok":
            continue
        transitions.append({
            "chart_id": chart_id,
            "title": alert["title"],
            "from_status": old,
            "to_status": new,
            "direction": "escalated" if STATUS_RANK[new] > STATUS_RANK[old] else "eased",
            "proximity_percent": alert["proximity_percent"],
            "boundary_label": alert["boundary_label"],
            "boundary_value": alert["boundary_value"],
            "current_value": alert["current_value"],
        })
    return transitions


def render_email(
    transitions: list[dict[str, Any]], alerts: dict[str, dict[str, Any]],
    *, generated_at: str,
) -> tuple[str, str]:
    """(제목, 본문 markdown)을 만든다 — 전이가 없으면 호출하지 않는다."""
    escalated = [row for row in transitions if row["direction"] == "escalated"]
    worst = max(
        (row["to_status"] for row in escalated),
        key=lambda status: STATUS_RANK[status],
        default=None,
    )
    if worst:
        subject = (
            f"[투자 대시보드] 경계 접근 {STATUS_LABEL[worst]} — "
            f"{len(escalated)}개 지표 단계 상승"
        )
    else:
        subject = f"[투자 대시보드] 경계 접근 완화 — {len(transitions)}개 지표 단계 하락"

    lines = [
        f"# 경계 접근 경보 변화 ({generated_at})", "",
        "통계 비교 지표가 경계선(닷컴 정점·고점 저항 추세선)에 얼마나 다가섰는지의",
        "단계가 바뀌었습니다. 표시 규약(주의 80% · 경고 95%)이며 매매 신호가 아닙니다.", "",
        "## 바뀐 지표", "",
    ]
    for row in transitions:
        arrow = "↑" if row["direction"] == "escalated" else "↓"
        lines.append(
            f"- {arrow} **{row['title']}**: {STATUS_LABEL[row['from_status']]} → "
            f"**{STATUS_LABEL[row['to_status']]}** — {row['boundary_label']} 접근 "
            f"{row['proximity_percent']}% (현재 {row['current_value']} / "
            f"경계 {row['boundary_value']})"
        )
    lines += ["", "## 전체 현황", ""]
    for chart_id, alert in sorted(
        alerts.items(), key=lambda item: -float(item[1]["proximity_percent"]),
    ):
        lines.append(
            f"- {STATUS_LABEL[str(alert['status'])]} {alert['proximity_percent']}% — "
            f"{alert['title']} ({alert['boundary_label']})"
        )
    lines += [
        "",
        "대시보드: https://sung-jinpark.github.io/Jin-s-investing-prediction/#statistics/liquidity",
        "",
        "이 메일은 단계가 바뀔 때만 발송됩니다. 어떤 예측도 실전 자금 결정의",
        "단독 근거가 아닙니다 (참고 의견).",
    ]
    return subject, "\n".join(lines) + "\n"


def run_alert_notify(
    root: Path, *, body_out: Path | None = None, now: str | None = None,
    force_test: bool = False,
) -> dict[str, Any]:
    """상태를 갱신하고 발송 여부·제목을 돌려준다."""
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    alerts = load_alerts(root)
    previous = load_state(root)
    transitions = compute_transitions(previous, alerts)

    send = bool(transitions) or force_test
    subject = ""
    if transitions:
        subject, body = render_email(transitions, alerts, generated_at=stamp)
    elif force_test:
        subject = "[투자 대시보드] 경보 이메일 개통 확인"
        body = (
            f"# 개통 확인 ({stamp})\n\n발송 경로가 정상입니다. 현재 전이 없음 — "
            "이후로는 단계가 바뀔 때만 발송됩니다.\n\n## 전체 현황\n\n"
            + "\n".join(
                f"- {STATUS_LABEL[str(a['status'])]} {a['proximity_percent']}% — "
                f"{a['title']} ({a['boundary_label']})"
                for _, a in sorted(
                    alerts.items(),
                    key=lambda item: -float(item[1]["proximity_percent"]),
                )
            ) + "\n"
        )
    if send and body_out is not None:
        body_out.parent.mkdir(parents=True, exist_ok=True)
        body_out.write_text(body, encoding="utf-8")

    state_path = root / STATE_PATH
    state_path.write_text(
        json.dumps({
            "schema_version": 1,
            "dataset_id": "statistics_approach_alert_notify_state_v1",
            "checked_at": stamp,
            "statuses": {
                chart_id: str(alert["status"]) for chart_id, alert in sorted(alerts.items())
            },
            "signal_semantics": "display_convention_not_trade_signal",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "send": send,
        "subject": subject,
        "transitions": transitions,
        "tracked_charts": len(alerts),
    }
