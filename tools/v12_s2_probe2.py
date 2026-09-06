#!/usr/bin/env python
"""tools/v12_s2_probe2.py — 반사 기준선 변형(BGK) 블록의 키만 덤프 (읽기 전용)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S22 = "data/timeseries_v12/diagnostics/reflection_baseline.json"


def main() -> None:
    d = json.loads((ROOT / S22).read_text(encoding="utf-8"))
    v = d["per_horizon"]["21"]["variants"]["discrete_monitoring_bgk"]
    print(json.dumps(v, ensure_ascii=False, indent=2)[:2500])


if __name__ == "__main__":
    main()
