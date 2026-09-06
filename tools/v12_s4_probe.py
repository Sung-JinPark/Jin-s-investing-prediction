#!/usr/bin/env python
"""S4-1 준비 탐침 — 계약 draft 가 인용할 필드의 경로·값을 실측한다 (읽기 전용).

산출물이 아니다. 계약 생성기(tools/v12_s4_contract.py)가 어떤 키를 읽어야 하는지
확인하기 위한 일회용 덤프이며, 어떤 파일도 쓰지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def walk(obj, prefix="", depth=0, maxdepth=3):
    if depth > maxdepth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                n = len(v)
                print(f"{p}  <{type(v).__name__} n={n}>")
                walk(v, p, depth + 1, maxdepth)
            else:
                print(f"{p} = {v!r}"[:220])
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            print(f"{prefix}[0] keys = {sorted(obj[0].keys())}")
        elif obj:
            print(f"{prefix} = {obj!r}"[:220])


def dig(obj, path: str):
    for seg in path.split("."):
        if seg == "":
            continue
        if isinstance(obj, list):
            obj = obj[int(seg)]
        else:
            obj = obj[seg]
    return obj


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    depth = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    files = {
        "ft": "data/timeseries_v12/diagnostics/first_touch_diagnostic.json",
        "rb": "data/timeseries_v12/diagnostics/reflection_baseline.json",
        "s2": "data/timeseries_v12/diagnostics/s2_entry_verdict.json",
        "s3": "data/timeseries_v12/diagnostics/s3_verdict.json",
        "pre": "data/timeseries_v12/prereg/hypotheses.json",
    }
    path = sys.argv[3] if len(sys.argv) > 3 else ""
    for key, rel in files.items():
        if which not in ("all", key):
            continue
        print(f"\n===== {key}  {rel}  path={path!r} =====")
        obj = dig(load(rel), path)
        if isinstance(obj, (dict, list)):
            walk(obj, maxdepth=depth)
        else:
            print(repr(obj))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
