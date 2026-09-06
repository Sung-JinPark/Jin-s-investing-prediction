#!/usr/bin/env python
"""tools/v12_reflect_headline.py — S2-2 result JSON 의 headline 블록을 원본에서 그대로 생성 (읽기 전용).

손으로 옮겨 적다 자릿수를 틀리는 것을 막는 용도. stdout 만. (S2-1 의 v12_ft_exact.py 와 같은 역할)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = json.loads((ROOT / "data/timeseries_v12/diagnostics/reflection_baseline.json")
               .read_text(encoding="utf-8"))


def band(c):
    return [c["ci90_lower"], c["ci90_upper"]] if c else None


def main() -> None:
    out = {}
    for h in ("21", "63"):
        b = D["per_horizon"][h]
        pair = b["paired"]["v8_vs_reflection"]
        rd, vd = b["reflection_diagnostic"], b["v8_diagnostic"]
        out[f"h{h}"] = {
            "n": b["n"], "touches": b["touches"], "base_rate": b["base_rate"],
            "brier_v8": b["brier"]["v8_first_touch"],
            "brier_reflection": b["brier"]["reflection"],
            "brier_climatology_insample": b["brier"]["climatology_insample"],
            "bss_v8_vs_climatology": b["skill"]["bss_v8_vs_climatology"],
            "bss_reflection_vs_climatology": b["skill"]["bss_reflection_vs_climatology"],
            "bss_v8_vs_reflection": b["skill"]["bss_v8_vs_reflection"],
            "loss_diff_v8_minus_reflection": pair["loss_diff"],
            "loss_diff_ci90": band(pair["ci90"]),
            "v8_win_origins": f"{pair['sign_test_a_better_origins']}/{pair['n']}",
            "reflection_p_mean": rd["p_mean"],
            "reflection_top_quintile_gap": rd["top_quintile_gap"],
            "reflection_top_quintile_gap_ci90": band(rd["ci90"]["top_quintile_gap"]),
            "v8_top_quintile_gap_ci90": band(vd["ci90"]["top_quintile_gap"]),
            "reflection_logistic_slope": rd["logistic_slope"],
            "reflection_auc": rd["auc"],
            "v8_auc": vd["auc"],
            "spearman_p_v8_vs_p_reflect": b["agreement"]["spearman_p_v8_vs_p_reflect"],
        }
    s = D["per_horizon"]["21"]["sigma"]
    out["sigma_ewma097"] = {
        "mean": s["mean"], "median": s["median"], "min": s["min"], "max": s["max"],
        "annualized_mean_sqrt252": s["annualized_mean_252"],
    }
    print(json.dumps({"headline": out}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
