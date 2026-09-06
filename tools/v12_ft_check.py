#!/usr/bin/env python
"""tools/v12_ft_check.py — S2-1 본문 인용 수치 대사 (읽기 전용, stdout 만)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = json.loads((ROOT / "data/timeseries_v12/diagnostics/first_touch_diagnostic.json")
               .read_text(encoding="utf-8"))


def main() -> None:
    print("run_sha256:", D["target"]["run"]["run_sha256"])
    print("run_path  :", D["target"]["run"]["run_path"])
    for h in ("21", "63"):
        b = D["per_horizon"][h]
        m5, m10 = b["murphy_quantile_bins"], b["murphy_fixed_bins"]
        print(f"h{h}: p_zero_count={b['p_zero_count']} p_max={b['p_max']:.4f} "
              f"RES-REL 5분위={m5['resolution'] - m5['reliability']:+.5f} "
              f"10등간={m10['resolution'] - m10['reliability']:+.5f} "
              f"REL/UNC={m5['reliability'] / m5['uncertainty']:.4f}~"
              f"{m10['reliability'] / m10['uncertainty']:.4f}")
        print(f"      expanding: eligible={b['expanding_climatology']['eligible_n']} "
              f"maturity_days={b['expanding_climatology']['maturity_days']} "
              f"clim_mean={b['expanding_climatology']['climatology_mean']:.4f}")
        gfc = [r for r in D["regimes"][h] if r["regime"] == "gfc"][0]
        print(f"      gfc top_quintile_n={gfc['top_quintile_n']} / pooled top n="
              f"{b['quantile_bins']['table'][-1]['n']}")
        neg = [r for r in D["regimes"][h]
               if not r.get("skipped") and (r["brier_skill_vs_insample_climatology"] or 0) < 0]
        print(f"      국면내 BSS 음수 셀: {[r['regime'] for r in neg]}")
        calm = [r for r in D["regimes"][h] if r["regime"] == "calm_p80"][0]
        print(f"      calm n={calm['n']}/{b['n']} = {calm['n'] / b['n']:.4f} "
              f"thr={calm['primary_threshold_p80']:.6f} missing={calm['primary_missing']}")
    print("cells(top_gap>0):", D["verdict"]["direction_only_replication"]["top_gap_positive_cells"],
          "/", D["verdict"]["direction_only_replication"]["cells_total"])
    print("slope<1 cells:", D["verdict"]["direction_only_replication"]["slope_below_one_cells"],
          D["verdict"]["direction_only_replication"]["slope_exceptions"])
    print("h5:", {k: D["per_horizon"]["5"][k] for k in
                  ("touches", "brier_skill_vs_insample_climatology", "auc")})


if __name__ == "__main__":
    main()
