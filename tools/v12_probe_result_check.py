#!/usr/bin/env python
"""tools/v12_probe_result_check.py — S1-3 result JSON 의 인용 수치가 산출 JSON 과 일치하는지 대사."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    src = json.loads((ROOT / "docs/review/lowcost_options.json").read_text(encoding="utf-8"))
    res = json.loads((ROOT / "outputs/timeseries_v12/loop/results/S1-3.json").read_text(encoding="utf-8"))
    q4 = res["answers"]["Q4_missed_lowcost_options"]

    adm = {tuple(c["members"]): c for c in src["A_v10_combination_grid"]["admissible_grid"]}
    best = q4["v10_combination_grid"]["best_combo"]
    actual = adm[tuple(best["members"])]
    checks = [
        ("best.mean_delta", best["mean_delta"], actual["mean_delta"]),
        ("best.rel", best["relative_improvement"], actual["relative_improvement"]),
        ("best.ci90_lo", best["ci90"][0], actual["ci90"][0]),
        ("best.ci90_hi", best["ci90"][1], actual["ci90"][1]),
    ]

    prof = src["C_track_combination"]["profiles"]
    tc = q4["track_combination"]
    v9lab = f"v9_best({src['C_track_combination']['v9_best_label']})"
    checks += [
        ("v9_best", tc["v9_best_mean_delta"], prof[v9lab]["mean_delta"]),
        ("v11_recenter", tc["v11_recenter_mean_delta"], prof["v11_recenter"]["mean_delta"]),
        ("v10+v9", tc["v10_plus_v9"], prof[f"v10_champion+{v9lab}"]["mean_delta"]),
        ("v10+v11", tc["v10_plus_v11"], prof["v10_champion+v11_recenter"]["mean_delta"]),
        ("all_three", tc["all_three"], prof[f"v10_champion+{v9lab}+v11_recenter"]["mean_delta"]),
    ]

    bad = 0
    for name, cited, actual_v in checks:
        ok = abs(cited - actual_v) <= max(1e-12, abs(actual_v) * 1e-4)
        if not ok:
            bad += 1
        print(f"{'OK ' if ok else 'MISMATCH'} {name}: 인용 {cited!r} vs 산출 {actual_v!r}")

    corr = src["C_track_combination"]["per_origin_delta_correlation"]
    cited_corr = res["answers"]["Q3_efficient_market_wall"]["cross_track_delta_correlation"]
    pairs = [("v10_v9", "v10_champion", v9lab), ("v10_v11", "v10_champion", "v11_recenter"),
             ("v9_v11", v9lab, "v11_recenter")]
    for key, a, b in pairs:
        ok = abs(cited_corr[key] - corr[a][b]) < 1e-12
        bad += 0 if ok else 1
        print(f"{'OK ' if ok else 'MISMATCH'} corr.{key}: {cited_corr[key]} vs {corr[a][b]}")

    over1 = [c for c in adm.values() if c["relative_improvement"] > 0.01 and c["ci90_lower_positive"]]
    ok = len(over1) == q4["v10_combination_grid"]["combos_over_1pct_with_ci90_lower_positive"]
    bad += 0 if ok else 1
    print(f"{'OK ' if ok else 'MISMATCH'} >1%&CI하한>0 조합 수: 인용 "
          f"{q4['v10_combination_grid']['combos_over_1pct_with_ci90_lower_positive']} vs 산출 {len(over1)}")
    print(f"\n불일치 {bad}건")


if __name__ == "__main__":
    main()
