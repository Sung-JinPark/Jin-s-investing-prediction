#!/usr/bin/env python
"""tools/v12_lens3_dump.py — V11 적대적 검증 렌즈3 원본 기록 덤프 (읽기 전용).

S1-1 의 V11 재구성이 원 기록과 일치하는지 대사하기 위한 조회 전용 스크립트.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "outputs/timeseries_v11/reports/CALM_SIGNAL_ADVERSARIAL_VERIFY_20260903.json"


def main() -> int:
    payload = json.loads(SRC.read_text(encoding="utf-8"))

    def walk(node: object) -> object | None:
        """'렌즈3' 을 담은 dict 를 깊이우선으로 찾는다 (워크플로 산출 JSON은 중첩 구조)."""
        if isinstance(node, dict):
            if any("렌즈3" in str(v) for v in node.values() if isinstance(v, str)):
                return node
            for value in node.values():
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found is not None:
                    return found
        elif isinstance(node, str) and "렌즈3" in node:
            return node
        return None

    hit = walk(payload)
    if hit is None:
        print(json.dumps(list(payload.keys()), ensure_ascii=False))
        return 1
    print(json.dumps(hit, indent=2, ensure_ascii=False) if isinstance(hit, dict) else hit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
