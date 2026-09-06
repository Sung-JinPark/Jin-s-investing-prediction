#!/usr/bin/env python
"""tools/v12_s2_probe.py — S2-1/S2-2 진단 JSON 의 키 구조만 덤프 (읽기 전용).

S2-3 판정 스크립트가 어떤 경로에서 수치를 뽑을지 결정하기 위한 탐색용.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def walk(obj, prefix: str = "", depth: int = 0, maxdepth: int = 3) -> None:
    if depth > maxdepth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                kind = "dict" if isinstance(v, dict) else f"list[{len(v)}]"
                print(f"{'  ' * depth}{path} <{kind}>")
                walk(v, path, depth + 1, maxdepth)
            else:
                print(f"{'  ' * depth}{path} = {v!r}"[:180])
    elif isinstance(obj, list) and obj:
        print(f"{'  ' * depth}{prefix}[0]:")
        walk(obj[0], f"{prefix}[0]", depth + 1, maxdepth)


def main() -> int:
    for rel in (
        "data/timeseries_v12/diagnostics/first_touch_diagnostic.json",
        "data/timeseries_v12/diagnostics/reflection_baseline.json",
    ):
        print(f"\n########## {rel}")
        walk(json.loads((ROOT / rel).read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
