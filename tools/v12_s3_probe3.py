#!/usr/bin/env python
"""tools/v12_s3_probe3.py — S2 판정 JSON 에서 상위분위 gap 필드 경로 찾기 (읽기 전용)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S2 = json.loads((ROOT / "data/timeseries_v12/diagnostics/s2_entry_verdict.json").read_text(encoding="utf-8"))
TR = json.loads((ROOT / "data/timeseries_v12/diagnostics/transfer_results.json").read_text(encoding="utf-8"))

targets = [0.1230, 0.2107]


def walk(node, path=""):
    if isinstance(node, dict):
        for k, val in node.items():
            yield from walk(val, f"{path}.{k}")
    elif isinstance(node, list):
        for i, val in enumerate(node):
            yield from walk(val, f"{path}[{i}]")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield path, node


for path, val in walk(S2, "s2"):
    if any(abs(val - t) < 5e-5 for t in targets):
        print(f"{path} = {val!r}")

print("\n--- T3 전→후 CI90 상한 ---")
for rec in TR["records"]:
    if rec["hypothesis_id"] == "T3" and rec["direction"] == "early_to_late":
        print(f"h{rec['horizon']}: upper={rec['ci90_upper']!r}  ({rec['ci90_upper']:+.6f})")
