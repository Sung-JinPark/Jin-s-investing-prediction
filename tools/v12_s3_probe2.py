#!/usr/bin/env python
"""tools/v12_s3_probe2.py — 등록부 조항 원문 확인 (읽기 전용, 파일 무기록)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PR = json.loads((ROOT / "data/timeseries_v12/prereg/hypotheses.json").read_text(encoding="utf-8"))

for key in ("adoption", "pre_committed_interpretation", "reporting_contract", "prohibitions",
            "multiplicity", "power_notice_inherited", "results_seen_statement", "authority"):
    print(f"\n===== prereg.{key} =====")
    print(json.dumps(PR.get(key), ensure_ascii=False, indent=1)[:3500])

print("\n===== hypotheses ids =====")
for h in PR["hypotheses"]:
    print(h.get("id"), "|", str(h.get("prior_expectation"))[:150])
