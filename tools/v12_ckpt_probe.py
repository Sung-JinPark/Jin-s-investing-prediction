#!/usr/bin/env python
"""tools/v12_ckpt_probe.py — CKPT 준비 정찰: 결과 JSON 9종의 artifacts 키 모양·존재 여부 (읽기 전용)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "outputs/timeseries_v12/loop/results"

for p in sorted(RES.glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    arts = d.get("artifacts")
    kind = type(arts).__name__
    n = len(arts) if isinstance(arts, (dict, list)) else 0
    print(f"{p.name}: status={d.get('status')} artifacts={kind}({n}) keys={sorted(d.keys())}")
    if isinstance(arts, dict):
        for rel, h in arts.items():
            exists = (ROOT / rel).is_file()
            print(f"    {'OK ' if exists else 'MISS'} {rel} {str(h)[:12]}")
    elif isinstance(arts, list):
        for a in arts:
            print(f"    LIST {a}")
