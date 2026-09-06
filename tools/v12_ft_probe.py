#!/usr/bin/env python
"""tools/v12_ft_probe.py — V8 run JSON 안의 first_touch 원자료 위치·규모 탐색 (읽기 전용, stdout 만)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "data/timeseries_v8/runs"


def main() -> None:
    for path in sorted(RUNS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        scores = data.get("scores", [])
        horizons = sorted({s["horizon"] for s in scores})
        dates = sorted({s["date"] for s in scores})
        ft = [s for s in scores if s.get("first_touch_probability") is not None]
        print(f"\n=== {path.name}")
        print(f"  label={data.get('experiment_label')!r} id={data.get('experiment_id')} "
              f"parent={data.get('parent_experiment_id')}")
        print(f"  window={data.get('window')} role={data.get('window_role')} "
              f"path_count={data.get('path_count')}")
        print(f"  scores={len(scores)} horizons={horizons} origins={len(dates)} "
              f"date=[{dates[0]}..{dates[-1]}] ft_rows={len(ft)}")
        for h in horizons:
            rows = [s for s in scores if s["horizon"] == h]
            p = [s["first_touch_probability"] for s in rows]
            y = [s["first_touch_actual"] for s in rows]
            print(f"    h={h:>2} n={len(rows)} p_mean={sum(p)/len(p):.4f} "
                  f"p_max={max(p):.4f} base={sum(y)/len(y):.4f} touches={sum(y)}")
        print(f"  summary.status={data.get('summary', {}).get('status')} "
              f"gate_pass={data.get('summary', {}).get('gate_pass')}")


if __name__ == "__main__":
    main()
