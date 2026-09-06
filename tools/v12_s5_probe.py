#!/usr/bin/env python
"""tools/v12_s5_probe.py — S5-1 정찰(읽기 전용). 최종 보고가 인용할 JSON 의 키 구조만 덤프한다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    "data/timeseries_v12/diagnostics/s3_verdict.json",
    "data/timeseries_v12/design/gate_design.json",
    "outputs/timeseries_v12/loop/checkpoint_monday.json",
    "docs/review/verdict_recompute.json",
]


def walk(obj, prefix: str, depth: int, maxdepth: int, out: list[str]) -> None:
    if depth > maxdepth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                n = len(v)
                out.append(f"{p}  <{type(v).__name__} n={n}>")
                walk(v, p, depth + 1, maxdepth, out)
            else:
                out.append(f"{p} = {v!r}"[:200])
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], (dict, list)):
            out.append(f"{prefix}[0] ...")
            walk(obj[0], f"{prefix}[0]", depth + 1, maxdepth, out)


def main() -> int:
    maxdepth = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    only = sys.argv[2] if len(sys.argv) > 2 else None
    for rel in TARGETS:
        if only and only not in rel:
            continue
        path = ROOT / rel
        print(f"===== {rel} =====")
        if not path.is_file():
            print("  (없음)")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        out: list[str] = []
        walk(data, "", 0, maxdepth, out)
        print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
