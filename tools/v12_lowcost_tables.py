#!/usr/bin/env python
"""tools/v12_lowcost_tables.py — lowcost_options.json → 문서용 표(마크다운) 출력. 읽기 전용."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fmt(x: float | None, digits: int = 6) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "예" if x else "아니오"
    return f"{x:+.{digits}f}" if abs(x) < 1 else f"{x:+.{digits}f}"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:+.3f}%"


def share(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="docs/review/lowcost_options.json")
    args = ap.parse_args()
    data = json.loads((ROOT / args.src).read_text(encoding="utf-8"))

    a = data["A_v10_combination_grid"]
    print("### A-1. V10 축별 단독 (E0 대비, 417 origin)\n")
    print("| 실험 | 축 | 프록시 | h63 cov | 평균 Δ | 상대개선 | CI90 하한>0 | GFC 견인 | GFC 제외 평균 | 상위5% 제거 후 | 부호반전 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in a["singles"]:
        proxy = "PASS" if s.get("proxy_pass") else "FAIL"
        cov = s.get("h63_coverage_p10_p90")
        cov_s = f"{cov:.4f}" if cov is not None else "—"
        if s["identical_to_e0"]:
            print(f"| {s['label']} | {s['axis']} | {proxy} | {cov_s} | 0 (E0 동일) | — | — | — | — | — | — |")
            continue
        gfc = share(s["gfc_delta_share"]) if s.get("gfc_delta_share_interpretable") else \
            f"({share(s['gfc_delta_share'])})*"
        print(f"| {s['label']} | {s['axis']} | {proxy} | {cov_s} | {fmt(s['mean_delta'])} "
              f"| {pct(s['relative_improvement'])} | {fmt(s.get('ci90_lower_positive'))} | {gfc} "
              f"| {fmt(s['mean_excluding_gfc'])} | {fmt(s['top5pct']['mean_after_removal'])} "
              f"| {fmt(s['top5pct']['sign_flips'])} |")
    print("\n`*` = 순델타가 mde50 의 절반 미만이라 견인 비중의 분모가 불안정 — 해석하지 말 것.")

    print(f"\n### A-1b. 적격 조합 격자 (프록시 PASS 후보만: {', '.join(a['admissible_labels'])})\n")
    print("| 조합 | 평균 Δ | 상대개선 | CI90 | 하한>0 | GFC 견인 | GFC 제외/mde50 | 상위5% 제거 후 | 제거 후 CI90 | 인공물 판정 | 후반창(2011–14) 평균 | 후반 하한>0 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(a["admissible_grid"], key=lambda x: -x["mean_delta"]):
        ci = r.get("ci90")
        ci_s = f"[{ci[0]:+.2e}, {ci[1]:+.2e}]" if ci else "—"
        tci = r["top5pct"].get("ci90_after_removal")
        tci_s = f"[{tci[0]:+.2e}, {tci[1]:+.2e}]" if tci else "—"
        gfc = share(r["gfc_delta_share"]) if r.get("gfc_delta_share_interpretable") else \
            f"({share(r['gfc_delta_share'])})*"
        print(f"| {'+'.join(m.replace('V10_', '') for m in r['members'])} | {fmt(r['mean_delta'])} "
              f"| {pct(r['relative_improvement'])} | {ci_s} | {fmt(r.get('ci90_lower_positive'))} "
              f"| {gfc} | {r.get('mean_excluding_gfc_over_mde50', float('nan')):.3f} "
              f"| {fmt(r['top5pct']['mean_after_removal'])} | {tci_s} "
              f"| {fmt(r.get('artifact_verdict'))} | {fmt(r['post2010_mean'])} "
              f"| {fmt(r.get('post2010_ci90_lower_positive'))} |")

    print("\n### A-2. origin별 Δ 상관 (V10 축 후보 간)\n")
    corr = a["per_origin_delta_correlation"]
    keys = list(corr)
    print("| | " + " | ".join(k.replace("V10_", "") for k in keys) + " |")
    print("|---|" + "---|" * len(keys))
    for k in keys:
        print(f"| {k.replace('V10_', '')} | " + " | ".join(f"{corr[k][j]:+.3f}" for j in keys) + " |")

    print(f"\n### A-3. 조합 격자 {a['grid_size']}조합 요약\n")
    grid = a["grid"]
    esc = [c for c in grid if not c["top5pct"]["sign_flips"]]
    print(f"- 격자 크기: {a['grid_size']} (축별 미사용/후보1 전 조합, 2축 이상)")
    print(f"- 상위5% 제거 후에도 양수(=탈출 후보): **{len(esc)}조합**")
    print(f"- GFC 견인 비중 범위: {share(min(c['gfc_delta_share'] for c in grid))} ~ "
          f"{share(max(c['gfc_delta_share'] for c in grid))}")
    print(f"- 평균 Δ 최대 조합: {max(grid, key=lambda c: c['mean_delta'])['members']} "
          f"→ {fmt(max(c['mean_delta'] for c in grid))}")
    print(f"- GFC 제외 평균 최대 조합: {max(grid, key=lambda c: c['mean_excluding_gfc'])['members']} "
          f"→ {fmt(max(c['mean_excluding_gfc'] for c in grid))}")
    print(f"- 후반창(2011–14) 평균 최대: {max(grid, key=lambda c: c['post2010_mean'])['members']} "
          f"→ {fmt(max(c['post2010_mean'] for c in grid))}")

    print("\n### A-4. 부트스트랩한 대표 조합\n")
    print("| 조합 | 평균 Δ | 상대개선 | CI90 | GFC 견인 | GFC 제외 평균/mde50 | 상위5% 제거 후 | 인공물 판정 | 후반창 평균 (CI90 하한>0) |")
    print("|---|---|---|---|---|---|---|---|---|")
    rows = [a["all_axis_best_combo"]] + a["bootstrapped_selection"]
    for r in rows:
        ci = r.get("ci90")
        ci_s = f"[{ci[0]:+.2e}, {ci[1]:+.2e}]" if ci else "—"
        print(f"| {'+'.join(m.replace('V10_', '') for m in r['members'])} | {fmt(r['mean_delta'])} "
              f"| {pct(r['relative_improvement'])} | {ci_s} | {share(r['gfc_delta_share'])} "
              f"| {r.get('mean_excluding_gfc_over_mde50', float('nan')):.3f} "
              f"| {fmt(r['top5pct']['mean_after_removal'])} | {fmt(r.get('artifact_verdict'))} "
              f"| {fmt(r['post2010_mean'])} ({fmt(r.get('post2010_ci90_lower_positive'))}) |")

    b = data["B_v11_low_momentum_conditional"]
    print("\n### B. V11 저모멘텀 tertile 조건부 (S1-1 산출 재인용)\n")
    for name, key in (("저모멘텀 tertile", "low_mom_tertile"), ("P1 선형(참조)", "p1_linear_reference")):
        s = b[key]
        print(f"- **{name}**: 셀 {s['cells']} / 조합 {s['combos']} · 양방향 부호개선 "
              f"{len(s['both_directions_sign_improved'])} · **양방향 CI90 하한>0 "
              f"{len(s['both_directions_ci90_positive'])}** · forward만 CI90 하한>0 "
              f"{len(s['forward_only_ci90_positive'])} · 역방향 최악 CRPS 변화 "
              f"{pct(s['worst_reverse_relative_change'])}")
    pn = b["permutation_null"]
    print(f"- 순열 귀무({pn['replicates']}회, seed {pn['seed']}): 관측 {pn['observed']} · "
          f"귀무 평균 {pn['null_mean']:.3f} · **p(≥관측) = {pn['null_p_ge_observed']:.3f}**")
    print("\n| 지평 | 경계 | 방향 | 개선 평균 | CI90 | 하한>0 | CRPS 상대변화 | |효과|/mde50 |")
    print("|---|---|---|---|---|---|---|---|")
    for c in b["low_mom_tertile"]["cells_detail"]:
        print(f"| h{c['horizon']} | {c['boundary']} | {c['direction']} | {fmt(c['improvement_mean'])} "
              f"| [{c['ci90'][0]:+.2e}, {c['ci90'][1]:+.2e}] | {fmt(c['ci90_lower_positive'])} "
              f"| {pct(c['crps_relative_change'])} | {c['abs_effect_over_mde50']:.3f} |")

    c = data["C_track_combination"]
    idc = c["baseline_identity_check"]
    print("\n### C. 트랙 결합\n")
    print(f"- 기준선 동일성 실측: V11 프레임 crps vs V10 E0 crps — n={idc['n_compared']}, "
          f"max|Δ|={idc['max_abs_diff']:.3e}, mean|Δ|={idc['mean_abs_diff']:.3e} "
          f"(E0 장기 평균 CRPS {idc['v10_e0_mean_long_crps']:.6f})")
    v9id = idc["v9_e0_vs_v10_e0"]
    print(f"- V9 E0 vs V10 E0: n={v9id['n_compared']}, max|Δ|={v9id['max_abs_diff']:.3e}, "
          f"mean|Δ|={v9id['mean_abs_diff']:.3e} (V9 E0 장기 평균 CRPS {v9id['v9_e0_mean_long_crps']:.6f})")
    print(f"- V9 최선 = {c['v9_best_label']} · 전 exog 평균 Δ: "
          + ", ".join(f"{k.replace('V9_', '')}={v:+.2e}" for k, v in c["v9_all_means"].items()))
    vm = c["v11_recenter_meta"]
    print(f"- V11 recenter 발화 origin {vm['origins_fired']}/{vm['origins_total']} · "
          + " · ".join(f"h{h}: 검정 {m['test_n']}개, CRPS {pct(m['crps_relative_change'])}"
                       for h, m in vm["horizons"].items()))
    print("\n| 성분/결합 | 평균 Δ | 상대개선 | CI90 | GFC 견인 | 상위5% 제거 후 | 후반창(2011–14) 평균 | 후반 CI90 |")
    print("|---|---|---|---|---|---|---|---|")
    for name, p in c["profiles"].items():
        ci = p.get("ci90")
        ci_s = f"[{ci[0]:+.2e}, {ci[1]:+.2e}]" if ci else "—"
        pci = p.get("post2010_ci90")
        pci_s = f"[{pci[0]:+.2e}, {pci[1]:+.2e}]" if pci else "—"
        print(f"| {name} | {fmt(p['mean_delta'])} | {pct(p['relative_improvement'])} | {ci_s} "
              f"| {share(p['gfc_delta_share'])} | {fmt(p['top5pct']['mean_after_removal'])} "
              f"| {fmt(p['post2010_mean'])} | {pci_s} |")

    print("\n### C-2. 트랙 간 origin별 Δ 상관\n")
    cc = c["per_origin_delta_correlation"]
    keys = list(cc)
    print("| | " + " | ".join(keys) + " |")
    print("|---|" + "---|" * len(keys))
    for k in keys:
        print(f"| {k} | " + " | ".join(f"{cc[k][j]:+.3f}" for j in keys) + " |")

    print(f"\n(부트스트랩 호출 {data['bootstrap_usage']['calls']}/{data['bootstrap_usage']['budget']}, "
          f"예산 거부 {data['bootstrap_usage']['refused_due_to_budget']})")


if __name__ == "__main__":
    main()
