#!/usr/bin/env python
"""tools/v12_probe_proxy.py — V10 원장의 프록시 게이트 필드 구조 확인 (읽기 전용, stdout 만)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    path = ROOT / "data/timeseries_v10/ledgers/development_experiments.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    print("proxy 키 구조:", json.dumps(rows[0].get("proxy"), ensure_ascii=False)[:600])
    print("checks 키 구조:", json.dumps(rows[0].get("checks"), ensure_ascii=False)[:600])
    print()
    for r in rows:
        proxy = r.get("proxy") or {}
        checks = r.get("checks") or {}
        print(f"{r['experiment_label']:26s} proxy.pass={proxy.get('pass')} "
              f"checks.pass={checks.get('pass') if isinstance(checks, dict) else None} "
              f"h63cov={r['horizons']['63'].get('coverage_p10_p90')} "
              f"gate_margin.h63_upper={r.get('gate_margin', {}).get('h63_p10_p90_upper')}")


if __name__ == "__main__":
    main()
