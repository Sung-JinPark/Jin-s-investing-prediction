#!/usr/bin/env python
"""tools/v12_ft_exact.py — result JSON 의 headline 블록을 진단 JSON 에서 그대로 생성 (읽기 전용).

손으로 옮겨 적다 자릿수를 틀리는 것을 막는 용도. stdout 만.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = json.loads((ROOT / "data/timeseries_v12/diagnostics/first_touch_diagnostic.json")
               .read_text(encoding="utf-8"))


def band(ci):
    return [ci["ci90_lower"], ci["ci90_upper"]] if ci else None


def main() -> None:
    out = {}
    for h in ("21", "63"):
        b = D["per_horizon"][h]
        ci = b["ci90"]
        top = b["quantile_bins"]["table"][-1]
        out[f"h{h}"] = {
            "n": b["n"], "touches": b["touches"], "base_rate": b["base_rate"],
            "brier": b["brier"],
            "climatology_brier_insample": b["climatology_brier_insample"],
            "bss_insample": b["brier_skill_vs_insample_climatology"],
            "bss_insample_ci90": band(ci.get("bss_insample")),
            "loss_diff_vs_insample_climatology": b["point_estimates"]["loss_diff_insample_fixed_b"],
            "loss_diff_vs_insample_climatology_ci90": band(ci.get("loss_diff_insample_fixed_b")),
            "bss_vs_expanding_climatology": b["expanding_climatology"]["bss_vs_expanding"],
            "loss_diff_vs_expanding": b["point_estimates"]["loss_diff_expanding"],
            "loss_diff_vs_expanding_ci90": band(ci.get("loss_diff_expanding")),
            "auc": b["auc"], "auc_ci90": band(ci.get("auc")),
            "logistic_slope": b["logistic_recalibration"]["slope"],
            "logistic_slope_ci90": band(ci.get("logistic_slope")),
            "top_quintile_mean_p": top["mean_p"],
            "top_quintile_observed": top["observed"],
            "top_quintile_gap": b["top_quintile_gap"],
            "top_quintile_gap_ci90": band(ci.get("top_quintile_gap")),
        }
    print(json.dumps({"headline": out}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
