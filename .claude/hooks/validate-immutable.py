#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""불변 경로 보호 훅 — CLAUDE.md '불변성 규칙'을 기계로 강제한다.

CLAUDE.md 는 두 가지를 절대 규칙으로 못박고 있다.

  - `forecasts/` 아래 파일은 **생성 후 절대 수정·삭제 금지** (사후 수정은 캘리브레이션 조작)
  - `calibration/ledger.csv` 는 **append-only** (행 수정 금지)

사람이 규칙을 기억하는 것과 도구가 규칙을 못 지키게 막는 것은 다르다. 이 훅은 후자다.

동작: PreToolUse(Write|Edit) 로 들어온 JSON 을 stdin 에서 읽어, 대상 경로가 불변
영역이면 permissionDecision=deny 를 돌려준다. 그 외에는 아무것도 하지 않는다.

**fail-open**: 파싱 실패·예외는 전부 조용히 통과시킨다. 훅이 오작동해서 정상 작업을
막는 쪽이, 훅이 한 번 놓치는 쪽보다 나쁘다. 규칙의 최종 방어선은 여전히 사람과 리뷰다.
"""
import json
import os
import sys


def deny(reason: str) -> None:
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, sys.stdout)
    sys.exit(0)


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        return
    payload = json.loads(raw)
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return

    norm = path.replace("\\", "/")
    parts = [p for p in norm.split("/") if p]

    # 원장: 행을 고치는 어떤 편집도 막는다. 새 행 추가는 append 로 하는 일이라 이 도구를 타지 않는다.
    if norm.endswith("calibration/ledger.csv"):
        deny(
            "calibration/ledger.csv 는 append-only 원장입니다 (CLAUDE.md 불변성 규칙). "
            "기존 행을 고치거나 파일을 덮어쓸 수 없습니다 — 새 행 추가만 허용됩니다."
        )

    # 예측 기록: 생성은 허용, 이미 있는 파일에 대한 수정은 금지.
    if "forecasts" in parts and os.path.isfile(path):
        deny(
            "forecasts/ 아래 파일은 생성 후 수정·삭제 금지입니다 (CLAUDE.md 불변성 규칙). "
            "오타가 있어도 그대로 두고, 재예측은 새 파일 "
            "(YYYY-MM-DD_<question-id>_r<N>.md) 로 만드세요."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — 훅 오작동이 정상 작업을 막으면 안 된다
        pass
    sys.exit(0)
