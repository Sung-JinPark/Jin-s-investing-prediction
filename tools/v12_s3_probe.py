#!/usr/bin/env python
"""tools/v12_s3_probe.py — S3-2 판정 작성 전 입력 구조 확인 (읽기 전용, 파일 무기록)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TR = json.loads((ROOT / "data/timeseries_v12/diagnostics/transfer_results.json").read_text(encoding="utf-8"))
PR = json.loads((ROOT / "data/timeseries_v12/prereg/hypotheses.json").read_text(encoding="utf-8"))


def shape(obj, depth=0, prefix=""):
    pad = "  " * depth
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}: {type(v).__name__}({len(v)})")
                if depth < 2:
                    shape(v, depth + 1)
            else:
                print(f"{pad}{k} = {v!r}"[:180])
    elif isinstance(obj, list) and obj:
        print(f"{pad}[0] ->")
        shape(obj[0], depth + 1)


for key in ("schema", "task_id", "target", "method", "verdict", "adoption", "t5_negative_control",
            "multiplicity_null", "t4_full_sample", "timing", "prereg", "generated_by"):
    print(f"\n===== transfer.{key} =====")
    shape(TR.get(key))

print("\n===== transfer.cells[0] =====")
shape(TR["cells"][0] if isinstance(TR["cells"], list) else TR["cells"])
print("\n===== transfer.records[0] =====")
print(json.dumps(TR["records"][0], ensure_ascii=False, indent=1)[:4000])
print("\n===== transfer.caveats =====")
print(json.dumps(TR["caveats"], ensure_ascii=False, indent=1)[:2500])
print("\n===== prereg top keys =====")
print(list(PR))
