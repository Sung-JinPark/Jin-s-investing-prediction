"""V15 워크플로 계획 — 쓰기 없음. 상태 기반이라 유실·대기 취소된 트리거도 다음 실행이 빈 칸을 찾는다.

- pending: 최신 V8 섀도 행(따라잡기 창 ≤ 2원점, workflow_dispatch auto 는 최신 원점만)에서 A0~A4 중
  빠진 팔. 같은 (V8 행, 팔) 의 compute_failed 가 2회 이상이면 더 계산하지 않는다.
- snapshot_sha: `git rev-list -1 --first-parent --before=<V8 knowledge_cutoff> origin/main`.
- a5_due: 월 03:40Z·06:40Z 예약 또는 mode=a5_issue, track_open, 기대 원점 ISO 주에 A5 행 없음, now < 마감.
  예약 재시도(06:40Z)는 같은 ISO 주에 a5_origin_unavailable(원천 지연으로 원점이 기대 원점보다 이름)이 이미
  기록됐으면 건너뛴다 — 실측상 같은 날 재계산도 같은 원점이라 ~95분을 다시 쓰고 같은 결과다(수동 a5_issue 는 허용).
  기대 원점이 live.first_origin_not_before 보다 이르면 발행하지 않는다(a5_before_first_origin) — 그런 행은 판정에서
  before_first_origin 으로 빠지면서 그 ISO 주 A5 슬롯만 차지해 정규 발행을 막는다(r3 리뷰 비차단 2).
- mde_due: mode=mde_replay, 계약 mde.status not_computed, mde_v1.json 없음.
- identity_due: mode ∈ {mde_replay, a0_identity}, track_open false, 가장 최근 identity 시도가 PASS 아님.
track_open 이 false 인 동안 라이브 계산은 0 이다. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .arms import WEEKLY_ARMS
from .contracts import ATTEMPTS_LEDGER, ISSUANCE_LEDGER, MDE_SUMMARY_RELATIVE, load_contract_v15, track_open
from .pipeline import (
    A5_DEADLINE_MARGIN_SECONDS,
    _existing_arms,
    _first_origin,
    _read_chain,
    _utc,
    catch_up_targets,
    iso_week,
    latest_identity_status,
    read_v8_rows,
)

A5_SCHEDULES = frozenset({"40 3 * * 1", "40 6 * * 1"})
MODES = ("auto", "resolve_only", "a5_issue", "mde_replay", "a0_identity")
MAX_COMPUTE_FAILURES = 2

GitRunner = Callable[[Sequence[str]], str]


def _default_git(root: Path) -> GitRunner:
    def run(args: Sequence[str]) -> str:
        completed = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
        return completed.stdout.strip()

    return run


def snapshot_sha(cutoff: str, runner: GitRunner) -> str:
    sha = runner(["rev-list", "-1", "--first-parent", f"--before={cutoff}", "origin/main"]).strip()
    if not sha:
        raise ValueError(f"V8 cutoff {cutoff} 이전 main 커밋을 찾지 못했다")
    return sha


def _compute_failures(root: Path, origin: str, arm: str) -> int:
    return sum(1 for row in _read_chain(root, ATTEMPTS_LEDGER)
               if row.get("kind") == "compute_failed" and row.get("origin") == origin and row.get("arm") == arm)


def plan_run(
    root: Path,
    *,
    event: str = "workflow_dispatch",
    schedule: str = "",
    mode: str = "auto",
    v8_run_head_sha: str | None = None,
    now: datetime | None = None,
    git_runner: GitRunner | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    contract = load_contract_v15(root)
    current = _utc(now)
    runner = git_runner or _default_git(root)
    is_open = track_open(contract)
    v8_rows = read_v8_rows(root)
    result: dict[str, Any] = {
        "track_open": is_open, "pending": False, "arms": [], "v8_forecast_id": "", "snapshot_sha": "",
        "a5_due": False, "mde_due": False, "identity_due": False,
        "event": event, "mode": mode, "v8_run_head_sha": v8_run_head_sha or None, "reasons": [],
    }
    if is_open and mode in ("auto", "a5_issue", "resolve_only"):
        if mode == "auto":
            latest_only = event == "workflow_dispatch"
            window = int(contract["live"]["catch_up_window_v8_origins"])
            targets, _ = catch_up_targets(v8_rows, first_origin_not_before=_first_origin(contract),
                                          latest_only=latest_only, window=window)
            present = _existing_arms(root)
            for row in reversed(targets):  # 최신 원점부터 — 한 run 은 V8 행 1개
                missing = [arm for arm in WEEKLY_ARMS
                           if arm not in present.get(str(row["forecast_id"]), set())
                           and _compute_failures(root, str(row["origin"]), arm) < MAX_COMPUTE_FAILURES]
                if missing:
                    result.update({"pending": True, "arms": missing, "v8_forecast_id": str(row["forecast_id"]),
                                   "snapshot_sha": snapshot_sha(str(row["knowledge_cutoff"]), runner),
                                   "v8_origin": str(row["origin"])})
                    break
        a5_trigger = (event == "schedule" and schedule in A5_SCHEDULES) or mode == "a5_issue"
        if a5_trigger:
            from .calendar import last_completed_session, open_utc, session_offset

            expected = last_completed_session(current)
            deadline = open_utc(session_offset(expected, 1)) - timedelta(seconds=A5_DEADLINE_MARGIN_SECONDS)
            issued = {row.get("iso_week") for row in _read_chain(root, ISSUANCE_LEDGER)}
            week = iso_week(expected.isoformat())
            unavailable = any(row.get("kind") == "a5_origin_unavailable" and row.get("origin")
                              and iso_week(str(row["origin"])) == week
                              for row in _read_chain(root, ATTEMPTS_LEDGER))
            first_origin = _first_origin(contract)
            if first_origin and expected.isoformat() < first_origin:
                result["reasons"].append("a5_before_first_origin")
            elif week in issued:
                result["reasons"].append("a5_already_issued_this_iso_week")
            elif unavailable and event == "schedule":
                result["reasons"].append("a5_origin_unavailable_this_iso_week")
            elif current >= deadline:
                result["reasons"].append("a5_past_deadline")
            else:
                result["a5_due"] = True
                result["a5_expected_origin"] = expected.isoformat()
    elif not is_open:
        result["reasons"].append("track_open_false — 라이브 계산 0 (r3 전)")
    if mode == "mde_replay":
        result["mde_due"] = bool((contract.get("mde") or {}).get("status") == "not_computed"
                                 and not (root / MDE_SUMMARY_RELATIVE).exists())
    if mode in ("mde_replay", "a0_identity") and not is_open:
        if latest_identity_status(root) != "PASS" and v8_rows:
            latest = v8_rows[-1]
            result.update({"identity_due": True, "v8_forecast_id": str(latest["forecast_id"]),
                           "snapshot_sha": snapshot_sha(str(latest["knowledge_cutoff"]), runner),
                           "v8_origin": str(latest["origin"])})
    return result


def github_output_lines(result: dict[str, Any]) -> list[str]:
    import json

    lines = []
    for key in ("track_open", "pending", "arms", "v8_forecast_id", "snapshot_sha", "a5_due", "mde_due", "identity_due"):
        value = result[key]
        if key == "arms":
            text = json.dumps(value)
        elif isinstance(value, bool):
            text = str(value).lower()
        else:
            text = str(value)
        lines.append(f"{key}={text}")
    return lines
