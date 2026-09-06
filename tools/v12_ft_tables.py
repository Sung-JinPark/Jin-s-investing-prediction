#!/usr/bin/env python
"""tools/v12_ft_tables.py — S2-1 진단 JSON → 본문 인용용 표 (읽기 전용, stdout 만)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/timeseries_v12/diagnostics/first_touch_diagnostic.json"


def f(v, nd=4):
    return "—" if v is None else f"{v:+.{nd}f}"


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))

    print("## 지평별 요약")
    print("| h | n | 터치 | base | Brier | 기후 Brier(상수) | BSS(상수) | BSS CI90 | "
          "BSS(확장기후) | AUC | AUC CI90 | 로짓 기울기 | 기울기 CI90 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for h in ("1", "5", "21", "63"):
        b = d["per_horizon"][h]
        ci = (b.get("ci90") or {})
        bss, ac, sl = ci.get("bss_insample"), ci.get("auc"), ci.get("logistic_slope")
        fit = b.get("logistic_recalibration")
        band = lambda c: (f"[{f(c['ci90_lower'])}, {f(c['ci90_upper'])}]" if c else "—")
        print(f"| {h} | {b['n']} | {b['touches']} | {b['base_rate']:.4f} | {b['brier']:.5f} | "
              f"{b['climatology_brier_insample']:.5f} | "
              f"{f(b['brier_skill_vs_insample_climatology'])} | {band(bss)} | "
              f"{f(b['expanding_climatology'].get('bss_vs_expanding'))} | "
              f"{f(b.get('auc'))} | {band(ac)} | "
              f"{f(fit['slope'] if fit else None)} | {band(sl)} |")

    print("\n## 기후 대비 쌍대 손실차 (양수 = 모델 우수)")
    print("| h | 기준선 | 평균 손실차 | CI90 | 하한>0 |")
    print("|---|---|---|---|---|")
    for h in ("21", "63"):
        b = d["per_horizon"][h]
        for key, label in (("loss_diff_insample_fixed_b", "상수기후(b 고정)"),
                           ("loss_diff_insample_replicate_b", "상수기후(b 복제내 재추정)"),
                           ("loss_diff_expanding", "확장기후(전향적)")):
            ci = (b.get("ci90") or {}).get(key)
            pt = b.get("point_estimates", {}).get(key)
            print(f"| {h} | {label} | {f(pt, 6)} | "
                  f"{'[' + f(ci['ci90_lower'], 6) + ', ' + f(ci['ci90_upper'], 6) + ']' if ci else '—'} | "
                  f"{'예' if ci and ci['ci90_lower'] > 0 else '아니오'} |")

    print("\n## Murphy 분해")
    print("| h | binning | REL | RES | UNC | REL−RES+UNC | Brier | binning 잔차 | 유효 bin |")
    print("|---|---|---|---|---|---|---|---|---|")
    for h in ("21", "63"):
        for key, label in (("murphy_quantile_bins", "5분위"), ("murphy_fixed_bins", "10등간")):
            m = d["per_horizon"][h][key]
            print(f"| {h} | {label} | {m['reliability']:.5f} | {m['resolution']:.5f} | "
                  f"{m['uncertainty']:.5f} | {m['rel_minus_res_plus_unc']:.5f} | "
                  f"{m['brier']:.5f} | {m['binning_residual']:+.6f} | {m['bins_used']} |")

    for h in ("21", "63"):
        b = d["per_horizon"][h]
        meta = b["quantile_bins"]["meta"]
        print(f"\n## h{h} 5분위 신뢰도 (유효 bin {meta['effective_bins']}"
              f"{' · 동점 붕괴' if meta['collapsed_by_ties'] else ''})")
        print("| bin | p 구간 | n | 터치 | 평균 p | 관측빈도 | gap(p−obs) | 관측 Wilson CI90 |")
        print("|---|---|---|---|---|---|---|---|")
        for r in b["quantile_bins"]["table"]:
            if r["n"] == 0:
                continue
            w = r["observed_ci90_wilson"]
            print(f"| {r['bin']} | [{r['edges'][0]:.4f}, {r['edges'][1]:.4f}) | {r['n']} | "
                  f"{r['touches']} | {r['mean_p']:.4f} | {r['observed']:.4f} | {f(r['gap'])} | "
                  f"[{w[0]:.4f}, {w[1]:.4f}] |")

    for h in ("21", "63"):
        print(f"\n## h{h} 10등간 신뢰도 (비어있지 않은 bin)")
        print("| p 구간 | n | 터치 | 평균 p | 관측빈도 | gap |")
        print("|---|---|---|---|---|---|")
        for r in d["per_horizon"][h]["fixed_bins"]["table"]:
            if r["n"] == 0:
                continue
            print(f"| [{max(r['edges'][0], 0):.2f}, {min(r['edges'][1], 1):.2f}) | {r['n']} | "
                  f"{r['touches']} | {r['mean_p']:.4f} | {r['observed']:.4f} | {f(r['gap'])} |")

    print("\n## 국면 분해")
    print("| h | 국면 | n | 터치 | base | 평균 p | Brier | BSS(국면내 상수기후) | 평균 gap | "
          "평균 gap CI90 | 상위분위 n | 상위분위 gap | 상위분위 gap CI90 | 로짓 기울기 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for h in ("21", "63"):
        for r in d["regimes"][h]:
            if r.get("skipped"):
                continue
            ci = r.get("ci90", {})
            mg, tg = ci.get("mean_calibration_gap"), ci.get("top_quintile_gap")
            print(f"| {h} | {r['regime']} | {r['n']} | {r['touches']} | {r['base_rate']:.4f} | "
                  f"{r['p_mean']:.4f} | {r['brier']:.5f} | "
                  f"{f(r['brier_skill_vs_insample_climatology'])} | {f(r['mean_calibration_gap'])} | "
                  f"{'[' + f(mg['ci90_lower']) + ', ' + f(mg['ci90_upper']) + ']' if mg else '—'} | "
                  f"{r['top_quintile_n']} | {f(r['top_quintile_gap'])} | "
                  f"{'[' + f(tg['ci90_lower']) + ', ' + f(tg['ci90_upper']) + ']' if tg else '—'} | "
                  f"{f(r['logistic_slope'])} |")

    print("\n## 판정 조건")
    v = d["verdict"]
    for name, cond in v["conditions"].items():
        print(f"- **{name}** — {cond['statement']} → pass={cond['pass']}")
        for hk, hv in cond["by_horizon"].items():
            print(f"    - {hk}: {json.dumps({k: x for k, x in hv.items() if k != 'regimes'}, ensure_ascii=False)}")
    do = v["direction_only_replication"]
    print(f"- **부호만(설계도 문자 조건)** — 상위분위 gap>0 {do['top_gap_positive_cells']}/"
          f"{do['cells_total']} 셀 · 평균 gap>0 {do['mean_gap_positive_cells']}/{do['cells_total']} · "
          f"기울기<1 {do['slope_below_one_cells']}/{do['cells_total']} "
          f"(예외 {do['slope_exceptions']}) → pass={do['pass']}")
    print(f"- **S3 진입: 엄격(O1&O3)={v['s3_entry_condition_met_strict']} · "
          f"문자 조건={v['s3_entry_condition_met_design_literal']}**")

    print("\n## 설계도 §0 주장 대사")
    c = d["design_section0_claim_check"]
    print("| 항목 | 설계도 주장 | 재계산 |")
    print("|---|---|---|")
    print(f"| BSS h21 | {c['claimed']['bss_h21']:+.3f} | "
          f"{c['recomputed']['bss_h21_vs_insample_climatology']:+.4f} |")
    print(f"| BSS h63 | {c['claimed']['bss_h63']:+.3f} | "
          f"{c['recomputed']['bss_h63_vs_insample_climatology']:+.4f} |")
    print(f"| h21 상위분위 p→관측 | {c['claimed']['h21_top_bin_p']:.2f}→{c['claimed']['h21_top_bin_observed']:.2f} | "
          f"{c['recomputed']['h21_top_quintile_mean_p']:.4f}→{c['recomputed']['h21_top_quintile_observed']:.4f} |")
    print(f"| h63 상위분위 p→관측 | {c['claimed']['h63_top_bin_p']:.2f}→{c['claimed']['h63_top_bin_observed']:.2f} | "
          f"{c['recomputed']['h63_top_quintile_mean_p']:.4f}→{c['recomputed']['h63_top_quintile_observed']:.4f} |")

    print("\n## 지평 단조성 / S3 split 검정력")
    print(json.dumps(d["horizon_monotonicity"], ensure_ascii=False))
    print(json.dumps(d["s3_split_power"], ensure_ascii=False))


if __name__ == "__main__":
    main()
