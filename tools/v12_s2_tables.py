#!/usr/bin/env python
"""tools/v12_s2_tables.py — S2-3 진단서용 표 렌더 (읽기 전용).

s2_entry_verdict.json / first_touch_diagnostic.json / reflection_baseline.json 에서
표를 **직접 렌더**한다. 진단서 본문은 이 출력을 붙여 넣는다 — 수기 전사 없음.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
V = "data/timeseries_v12/diagnostics/s2_entry_verdict.json"
S21 = "data/timeseries_v12/diagnostics/first_touch_diagnostic.json"
S22 = "data/timeseries_v12/diagnostics/reflection_baseline.json"

REGIME_KO = {"gfc": "GFC", "non_gfc": "비GFC", "calm_p80": "calm p80", "storm_p80": "storm p80"}


def load(rel: str) -> dict[str, Any]:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def ci(d: dict[str, Any] | None, fmt: str = "+.4f") -> str:
    if not d:
        return "—"
    return f"[{d['ci90_lower']:{fmt}}, {d['ci90_upper']:{fmt}}]"


def yn(v: bool) -> str:
    return "**충족**" if v else "미달"


def main() -> None:
    v, s21, s22 = load(V), load(S21), load(S22)
    r, p, verd = v["rules"], v["split_power"], v["verdict"]

    print("### 표 A — S2 통과 조건의 네 조작화 (전부 공표)\n")
    print("| 조작화 | 정의 | h21 | h63 | 판정 |")
    print("|---|---|---|---|---|")
    r0 = r["R0"]
    print(f"| **R0** (사전등록) | 설계도 §1 문자 — 부호 재현 | "
          f"{'양수' if r0['by_horizon']['h21'] else '음수'} | "
          f"{'양수' if r0['by_horizon']['h63'] else '음수'} | {yn(r0['pass'])} "
          f"(국면 셀 {r0['cells_both_positive']}) |")
    for key in ("R1", "R2"):
        row = r[key]
        subj = "V8" if key == "R1" else "표적 구조(반사 기준선)"
        print(f"| **{key}** | 엄격 · 주체={subj} — top-quintile gap CI90 하한>0 | "
              f"{row['ci90_lower']['h21']:+.4f} {'✓' if row['by_horizon']['h21'] else '✗'} | "
              f"{row['ci90_lower']['h63']:+.4f} {'✓' if row['by_horizon']['h63'] else '✗'} | "
              f"{yn(row['pass'])} |")
    r3 = r["R3"]["by_horizon"]
    print(f"| **R3** (보강·판정 미포함) | 로짓 기울기 CI90 상한<1 | "
          f"V8 {r3['h21']['v8_slope_ci90_upper']:.4f} / 반사 {r3['h21']['reflection_slope_ci90_upper']:.4f} | "
          f"V8 {r3['h63']['v8_slope_ci90_upper']:.4f} / 반사 {r3['h63']['reflection_slope_ci90_upper']:.4f} | "
          f"{yn(r['R3']['pass'])} |")

    print("\n### 표 B — 지평별 과신 계측 (두 모델 나란히)\n")
    print("| 지평 | n / 터치 | base | 모델 | 상위분위 p̄→관측 | gap | gap CI90 | 로짓 기울기 | 기울기 CI90 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for h in (21, 63):
        hh = r["horizons"][f"h{h}"]
        a = s21["per_horizon"][str(h)]["quantile_bins"]["table"][-1]
        b = s22["per_horizon"][str(h)]["reflection_diagnostic"]
        print(f"| h{h} | {hh['n']} / {hh['touches']} | {hh['base_rate']:.4f} | V8 | "
              f"{a['mean_p']:.4f}→{a['observed']:.4f} | "
              f"{hh['v8_top_gap']:+.4f} | {ci(hh['v8_top_gap_ci90'])} | "
              f"{hh['v8_slope']:.4f} | {ci(hh['v8_slope_ci90'])} |")
        print(f"| h{h} | \" | \" | 반사 기준선 | "
              f"{b['top_quintile_mean_p']:.4f}→{b['top_quintile_observed']:.4f} | "
              f"{hh['reflection_top_gap']:+.4f} | {ci(hh['reflection_top_gap_ci90'])} | "
              f"{hh['reflection_slope']:.4f} | {ci(hh['reflection_slope_ci90'])} |")

    print("\n### 표 B2 — 기계 기준선 대비 (풀표본 417 원점)\n")
    print("| 지평 | BS V8 | BS 반사 | BS 기후 | BSS V8\\|기후 | BSS 반사\\|기후 | 쌍대 Δ(V8−반사) | CI90 | ρ_s(p_V8,p_반사) | AUC V8 / 반사 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for h in (21, 63):
        ph = s22["per_horizon"][str(h)]
        sk, pa = ph["skill"], ph["paired"]["v8_vs_reflection"]
        print(f"| h{h} | {ph['brier']['v8_first_touch']:.6f} | {ph['brier']['reflection']:.6f} | "
              f"{ph['brier']['climatology_insample']:.6f} | "
              f"{sk['bss_v8_vs_climatology']:+.4f} | {sk['bss_reflection_vs_climatology']:+.4f} | "
              f"{pa['loss_diff']:+.6f} | {ci(pa['ci90'], '+.5f')} | "
              f"{ph['agreement']['spearman_p_v8_vs_p_reflect']:.4f} | "
              f"{ph['v8_diagnostic']['auc']:.4f} / {ph['reflection_diagnostic']['auc']:.4f} |")

    print("\n### 표 C — 국면 초월 재현 (8 셀)\n")
    print("| 지평 | 국면 | n / 터치 | V8 gap | 반사 gap | 두 모델 부호 | 반사 CI90 하한>0 | V8 CI90 하한>0 |")
    print("|---|---|---|---|---|---|---|---|")
    for c in r["regime_cells"]:
        print(f"| h{c['horizon']} | {REGIME_KO[c['regime']]} | {c['n']} / {c['touches']} | "
              f"{c['v8_top_gap']:+.4f} | {c['reflection_top_gap']:+.4f} | "
              f"{'양수' if c['both_top_gap_positive'] else '불일치'} | "
              f"{'✓' if c['reflection_top_gap_ci90_lower_positive'] else '✗'} "
              f"({(c['reflection_top_gap_ci90'] or {}).get('ci90_lower', float('nan')):+.4f}) | "
              f"{'✓' if c['v8_top_gap_ci90_lower_positive'] else '✗'} "
              f"({(c['v8_top_gap_ci90'] or {}).get('ci90_lower', float('nan')):+.4f}) |")
    s = r["regime_cell_summary"]
    print(f"\n합계: 부호 동시 양수 **{s['both_top_gap_positive']}/{s['cells']}** (평균 gap 기준 "
          f"{s['both_mean_gap_positive']}/{s['cells']}) · 셀 CI90 하한>0 은 반사 "
          f"{s['reflection_ci90_lower_positive']}/{s['cells']} · V8 {s['v8_ci90_lower_positive']}/{s['cells']}.")

    print("\n### 표 D — S3 분할창 검정력 사실 (S3-0 입력 · 후보 맵 미생성)\n")
    print("| 지평 | 창 | n / 터치 | base | V8 BS | 쌍대 Δ(V8−반사) | CI90 | MDE(1.645·se) | MDE/BS | 상위5원점 절대비중 | 상위5% 제거 부호반전 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for h in (21, 63):
        for key, ko in (("early_2007_2010", "전반 07–10"), ("late_2011_2014", "후반 11–14")):
            w = p[f"h{h}"][key]
            con = w["concentration"]
            print(f"| h{h} | {ko} | {w['n']} / {w['touches']} | {w['base_rate']:.4f} | "
                  f"{w['brier_v8']:.6f} | {w['paired_v8_minus_reflection']:+.6f} | "
                  f"{ci(w['paired_ci90'], '+.5f')} | {w['mde_1645se']:.6f} | "
                  f"{w['mde_as_share_of_window_brier']:.1%} | "
                  f"{con['top5_abs_share_of_sum']:.1%} | "
                  f"{'예' if con['sign_flips_after_drop'] else '아니오'} |")

    print("\n### 표 E — 판정\n")
    print(f"- 채택 규칙(결과 무관 고정): {verd['adoption_rule']}")
    print(f"- R0 {verd['R0_pass']} · R1 {verd['R1_pass']} · R2 {verd['R2_pass']} · R3 {verd['R3_pass']}")
    print(f"- **판정 = {verd['decision']}**")
    print(f"- 반대 기록: {verd['dissent']}")
    print("\n| 사전 제약 | 사실 | 처방 |")
    print("|---|---|---|")
    for k in verd["prereg_constraints"]:
        print(f"| `{k['id']}` | {k['fact']} | {k['prescription']} |")


if __name__ == "__main__":
    main()
