#!/usr/bin/env python
"""tools/v12_reflect_dump.py — S2-2 산출 JSON 요약 출력 (읽기 전용, stdout 만)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = json.loads((ROOT / "data/timeseries_v12/diagnostics/reflection_baseline.json")
               .read_text(encoding="utf-8"))


def ci(c):
    return f"[{c['ci90_lower']:+.5f},{c['ci90_upper']:+.5f}]" if c else "—"


def main() -> None:
    for h in ("1", "5"):
        b = D["per_horizon"][h]
        print(f"===== h{h} (참고) n={b['n']} touches={b['touches']} base={b['base_rate']:.6f} "
              f"BS v8={b['brier']['v8_first_touch']:.6f} reflect={b['brier']['reflection']:.6f} "
              f"clim={b['brier']['climatology_insample']:.6f} "
              f"p̄_reflect={b['reflection_diagnostic']['p_mean']:.5f} "
              f"p̄_v8={b['v8_diagnostic']['p_mean']:.5f}")

    for h in ("21", "63"):
        b = D["per_horizon"][h]
        print(f"\n===== h{h}  n={b['n']} touches={b['touches']} base={b['base_rate']:.5f} "
              f"σ̄={b['sigma']['mean']:.5f} σ_ann={b['sigma']['annualized_mean_252']:.4f} "
              f"σ∈[{b['sigma']['min']:.5f},{b['sigma']['max']:.5f}]")
        print("  BS   v8=%.6f reflect=%.6f clim=%.6f" % (
            b["brier"]["v8_first_touch"], b["brier"]["reflection"],
            b["brier"]["climatology_insample"]))
        s = b["skill"]
        print("  BSS  v8|clim=%+.5f reflect|clim=%+.5f v8|reflect=%+.5f" % (
            s["bss_v8_vs_climatology"], s["bss_reflection_vs_climatology"],
            s["bss_v8_vs_reflection"]))
        for name, p in b["paired"].items():
            print(f"  paired {name:26s} Δ={p['loss_diff']:+.6f} CI90={ci(p['ci90'])} "
                  f"wins={p['sign_test_a_better_origins']}/{p['n']} "
                  f"boot_p(A≤B)={p['bootstrap_p_a_not_better']:.4f}")
        for tag in ("reflection_diagnostic", "v8_diagnostic"):
            r = b[tag]
            c = r.get("ci90") or {}
            print(f"  {tag}: p̄={r['p_mean']:.5f} med={r['p_median']:.5f} max={r['p_max']:.5f} "
                  f"meangap={r['mean_calibration_gap']:+.5f} CI90={ci(c.get('mean_calibration_gap'))}")
            print(f"     top-quintile edge={r['top_quintile_edge']:.5f} n={r['top_quintile_n']} "
                  f"p̄={r['top_quintile_mean_p']:.5f} obs={r['top_quintile_observed']:.5f} "
                  f"gap={r['top_quintile_gap']:+.5f} CI90={ci(c.get('top_quintile_gap'))}")
            print(f"     slope={r['logistic_slope']:.5f} CI90={ci(c.get('logistic_slope'))} "
                  f"AUC={r['auc']:.5f} CI90={ci(c.get('auc'))} "
                  f"REL={r['murphy_quantile_bins']['reliability']:.6f} "
                  f"RES={r['murphy_quantile_bins']['resolution']:.6f} "
                  f"UNC={r['murphy_quantile_bins']['uncertainty']:.6f}")
            print("     quintiles: " + " | ".join(
                f"n={row['n']} p̄={row['mean_p']:.4f} obs={row['observed']:.4f}"
                for row in r["quantile_bins"]["table"] if row["n"]))
        a = b["agreement"]
        print("  agreement: spearman=%.5f mean|Δp|=%.5f reflect_higher=%.4f" % (
            a["spearman_p_v8_vs_p_reflect"], a["mean_abs_difference"],
            a["reflection_higher_share"]))
        print("  variants:")
        for name, v in b["variants"].items():
            p = v["paired_v8_vs_variant"]
            extra = ""
            if "top_quintile_gap" in v:
                extra = (f" top_gap={v['top_quintile_gap']:+.4f} "
                         f"slope={v['logistic_slope']:.4f}")
            if "paired_variant_vs_climatology" in v:
                q = v["paired_variant_vs_climatology"]
                extra += f" vs_clim Δ={q['loss_diff']:+.6f} CI90={ci(q['ci90'])}"
            print(f"    {name:34s} BS={v['brier']:.6f} p̄={v['p_mean']:.5f} "
                  f"v8−variant Δ={p['loss_diff']:+.6f} CI90={ci(p['ci90'])}{extra}")

    for h in ("21", "63"):
        print(f"\n===== 국면 h{h}")
        for row in D["regimes"][h]:
            if row.get("skipped"):
                continue
            br, bss = row["brier"], row["bss_within_regime"]
            tg, mg = row["top_quintile_gap"], row["mean_calibration_gap"]
            p = row["paired_v8_vs_reflection"]
            cr = row["ci90_reflection"]
            def f(x):
                return "—" if x is None else f"{x:+.4f}"
            print(f"  {row['regime']:10s} n={row['n']:3d} touch={row['touches']:3d} "
                  f"base={row['base_rate']:.4f} | BS v8={br['v8_first_touch']:.5f} "
                  f"reflect={br['reflection']:.5f} clim={br['climatology_insample']:.5f}")
            print(f"     BSS_within v8={f(bss['v8'])} reflect={f(bss['reflection'])} | "
                  f"meangap v8={f(mg['v8'])} reflect={f(mg['reflection'])} "
                  f"CI90={ci(cr['mean_calibration_gap'])}")
            print(f"     top_gap v8={f(tg['v8'])}(n={tg['n']['v8']}) "
                  f"reflect={f(tg['reflection'])}(n={tg['n']['reflection']}) "
                  f"CI90={ci(cr['top_quintile_gap'])} | slope v8={f(row['logistic_slope']['v8'])} "
                  f"reflect={f(row['logistic_slope']['reflection'])} | "
                  f"AUC v8={row['auc']['v8']:.4f} reflect={row['auc']['reflection']:.4f}")
            print(f"     paired v8−reflect Δ={p['loss_diff']:+.6f} CI90={ci(p['ci90'])}")

    print("\n===== verdict")
    print(json.dumps(D["verdict"], ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()
