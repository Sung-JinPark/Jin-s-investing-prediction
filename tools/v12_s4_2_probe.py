#!/usr/bin/env python
"""S4-2 탐침 — 게이트 설계서가 인용할 값의 소재를 확인한다 (읽기 전용).

용법: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_2_probe.py [json경로 ...]
인자가 없으면 S4-2 가 쓰는 기본 4개 파일의 키 트리를 깊이 제한 없이 출력한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = [
    "data/timeseries_v12/diagnostics/first_touch_diagnostic.json",
    "data/timeseries_v12/diagnostics/reflection_baseline.json",
    "data/timeseries_v12/diagnostics/s2_entry_verdict.json",
    "data/timeseries_v12/diagnostics/s3_verdict.json",
]


def walk(node, path, out, depth=0):
    if isinstance(node, dict):
        out.append(f"{path}  <dict n={len(node)}>")
        for k, v in node.items():
            walk(v, f"{path}.{k}" if path else str(k), out, depth + 1)
    elif isinstance(node, list):
        if node and all(isinstance(x, (int, float)) for x in node):
            out.append(f"{path}  <num list n={len(node)} head={node[:3]}>")
        elif len(node) > 6:
            out.append(f"{path}  <list n={len(node)}>")
            walk(node[0], f"{path}[0]", out, depth + 1)
        else:
            out.append(f"{path}  <list n={len(node)}>")
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", out, depth + 1)
    else:
        out.append(f"{path} = {node!r}")


def main() -> int:
    targets = sys.argv[1:] or DEFAULTS
    for rel in targets:
        p = ROOT / rel
        print(f"===== {rel} =====")
        if not p.is_file():
            print("  (없음)")
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        out: list[str] = []
        walk(data, "", out)
        for line in out:
            print(line)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
