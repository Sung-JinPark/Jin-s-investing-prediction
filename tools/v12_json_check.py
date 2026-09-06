#!/usr/bin/env python
"""tools/v12_json_check.py — 손으로 쓴 JSON(결과 리포트 등)의 파싱 검증 (읽기 전용).

루프 산출 result JSON 은 사람이 직접 쓰므로 감독 스크립트가 읽기 전에 깨지지 않았는지 확인한다.
파일을 쓰지 않는다. 인자로 받은 경로를 하나씩 파싱하고 최상위 키만 보고한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    paths = sys.argv[1:]
    if not paths:
        print("usage: v12_json_check.py <path> [...]", file=sys.stderr)
        return 2
    failed = 0
    for raw in paths:
        path = Path(raw) if Path(raw).is_absolute() else ROOT / raw
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — 어떤 파싱 실패든 그대로 보고
            failed += 1
            print(f"FAIL {raw}: {type(exc).__name__}: {exc}")
            continue
        keys = list(payload) if isinstance(payload, dict) else f"<{type(payload).__name__}>"
        print(f"OK   {raw}: {len(keys) if isinstance(keys, list) else keys} top-level keys")
        if isinstance(keys, list):
            print(f"     {keys}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
