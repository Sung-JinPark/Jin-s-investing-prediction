#!/usr/bin/env python
"""tools/v12_reflect_tables.py — S2-2 표 생성 (읽기 전용 입력, --out 한 파일만 씀).

수기 전사를 없애려고 reflection_baseline.json 에서 표를 직접 찍는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = "data/timeseries_v12/diagnostics/reflection_baseline.json"


def f(v: Any, digits: int = 4, sign: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v:+.{digits}f}" if sign else f"{v:.{digits}f}"


def ci(c: Any, digits: int = 4) -> str:
    if not c:
        return "—"
    return f"[{c['ci90_lower']:+.{digits}f}, {c['ci90_upper']:+.{digits}f}]"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="outputs/timeseries_v12/loop/_s2_2_tables.md")
    args = parser.parse_args()
    D = json.loads((ROOT / SRC).read_text(encoding="utf-8"))
    L: list[str] = []

    # ---------------------------------------------------------------- 헤드라인
    L.append("## 기준선 Brier 표 — 반사원리 2Φ vs V8 first_touch (417 원점, 설계창 2007-01-05~2014-12-24)")
    L.append("")
    L.append("| h | n | 터치 | base | BS V8 | BS 반사원리 | BS 상수기후 | BSS(V8\\|기후) | BSS(반사\\|기후) | BSS(V8\\|반사) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for h in ("1", "5", "21", "63"):
        b = D["per_horizon"][h]
        s = b["skill"]
        L.append(f"| {h} | {b['n']} | {b['touches']} | {b['base_rate']:.4f} | "
                 f"{b['brier']['v8_first_touch']:.5f} | {b['brier']['reflection']:.5f} | "
                 f"{b['brier']['climatology_insample']:.5f} | "
                 f"{f(s['bss_v8_vs_climatology'])} | {f(s['bss_reflection_vs_climatology'])} | "
                 f"{f(s['bss_v8_vs_reflection'])} |")
    L.append("")
    L.append("h1(터치 0건)·h5(4건)은 참고. 판정은 h21·h63 만.")
    L.append("")

    # ---------------------------------------------------------------- 쌍대
    L.append("## 쌍대 손실차 (양수 = 앞의 모델 우수). 블록 부트스트랩 ℓ=13·B=2000·seed 20260902")
    L.append("")
    L.append("| h | 비교 | 평균 손실차 | CI90 | 승리 원점 | 부트스트랩 P(앞≤뒤) | 결론 |")
    L.append("|---|---|---|---|---|---|---|")
    names = {"v8_vs_reflection": "V8 vs 반사원리",
             "reflection_vs_climatology": "반사원리 vs 상수기후",
             "v8_vs_climatology": "V8 vs 상수기후"}
    for h in ("21", "63"):
        for key, label in names.items():
            p = D["per_horizon"][h]["paired"][key]
            c = p["ci90"]
            if c and c["ci90_lower"] > 0:
                verdict = "앞이 엄밀히 우수"
            elif c and c["ci90_upper"] < 0:
                verdict = "뒤가 엄밀히 우수"
            else:
                verdict = "구분 불가"
            L.append(f"| {h} | {label} | {p['loss_diff']:+.6f} | {ci(c, 6)} | "
                     f"{p['sign_test_a_better_origins']}/{p['n']} | "
                     f"{p['bootstrap_p_a_not_better']:.4f} | {verdict} |")
    L.append("")

    # ---------------------------------------------------------------- 보정 구조
    L.append("## 보정 구조 대조 — 과신이 V8 특유인가")
    L.append("")
    L.append("| h | 모델 | p̄ | 평균 gap | 평균 gap CI90 | 상위분위 p̄ | 상위분위 관측 | 상위분위 gap | gap CI90 | 로짓 기울기 | 기울기 CI90 | AUC | AUC CI90 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for h in ("21", "63"):
        for tag, label in (("v8_diagnostic", "V8 first_touch"),
                           ("reflection_diagnostic", "반사원리 2Φ")):
            r = D["per_horizon"][h][tag]
            c = r.get("ci90") or {}
            L.append(f"| {h} | {label} | {r['p_mean']:.4f} | {f(r['mean_calibration_gap'])} | "
                     f"{ci(c.get('mean_calibration_gap'))} | {r['top_quintile_mean_p']:.4f} | "
                     f"{r['top_quintile_observed']:.4f} | {f(r['top_quintile_gap'])} | "
                     f"{ci(c.get('top_quintile_gap'))} | {f(r['logistic_slope'])} | "
                     f"{ci(c.get('logistic_slope'))} | {f(r['auc'])} | {ci(c.get('auc'))} |")
    L.append("")
    L.append("| h | 순위상관 ρ_s(p_V8, p_반사) | 평균 \\|Δp\\| | 반사가 더 높은 원점 비율 |")
    L.append("|---|---|---|---|")
    for h in ("21", "63"):
        a = D["per_horizon"][h]["agreement"]
        L.append(f"| {h} | {a['spearman_p_v8_vs_p_reflect']:.4f} | "
                 f"{a['mean_abs_difference']:.4f} | {a['reflection_higher_share']:.4f} |")
    L.append("")

    # ---------------------------------------------------------------- 5분위
    for h in ("21", "63"):
        r = D["per_horizon"][h]["reflection_diagnostic"]
        L.append(f"## h{h} 반사원리 5분위 신뢰도")
        L.append("")
        L.append("| bin | p 구간 | n | 터치 | 평균 p | 관측빈도 | gap(p−obs) | 관측 Wilson CI90 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for row in r["quantile_bins"]["table"]:
            if not row["n"]:
                continue
            w = row["observed_ci90_wilson"]
            L.append(f"| {row['bin']} | [{row['edges'][0]:.4f}, {row['edges'][1]:.4f}) | "
                     f"{row['n']} | {row['touches']} | {row['mean_p']:.4f} | "
                     f"{row['observed']:.4f} | {f(row['gap'])} | "
                     f"[{w[0]:.4f}, {w[1]:.4f}] |")
        L.append("")

    # ---------------------------------------------------------------- Murphy
    L.append("## Murphy 분해 대조 (5분위 binning)")
    L.append("")
    L.append("| h | 모델 | REL | RES | UNC | REL−RES+UNC | Brier | binning 잔차 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for h in ("21", "63"):
        for tag, label in (("v8_diagnostic", "V8"), ("reflection_diagnostic", "반사원리")):
            m = D["per_horizon"][h][tag]["murphy_quantile_bins"]
            L.append(f"| {h} | {label} | {m['reliability']:.5f} | {m['resolution']:.5f} | "
                     f"{m['uncertainty']:.5f} | {m['rel_minus_res_plus_unc']:.5f} | "
                     f"{m['brier']:.5f} | {m['binning_residual']:+.6f} |")
    L.append("")

    # ---------------------------------------------------------------- 국면
    L.append("## 국면 분해 — 국면 내 Brier·보정 (상위분위는 전역 경계 사용)")
    L.append("")
    L.append("| h | 국면 | n | 터치 | base | BS V8 | BS 반사 | BS 기후 | BSS내 V8 | BSS내 반사 | 상위 gap V8 | 상위 gap 반사 | 반사 gap CI90 | 쌍대(V8−반사) | 쌍대 CI90 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for h in ("21", "63"):
        for row in D["regimes"][h]:
            if row.get("skipped"):
                continue
            br, bss = row["brier"], row["bss_within_regime"]
            tg = row["top_quintile_gap"]
            p = row["paired_v8_vs_reflection"]
            L.append(f"| {h} | {row['regime']} | {row['n']} | {row['touches']} | "
                     f"{row['base_rate']:.4f} | {br['v8_first_touch']:.5f} | "
                     f"{br['reflection']:.5f} | {br['climatology_insample']:.5f} | "
                     f"{f(bss['v8'])} | {f(bss['reflection'])} | {f(tg['v8'])} | "
                     f"{f(tg['reflection'])} | {ci(row['ci90_reflection']['top_quintile_gap'])} | "
                     f"{p['loss_diff']:+.6f} | {ci(p['ci90'], 5)} |")
    L.append("")
    L.append("국면 부분표본(calm/storm)은 시간축이 비연속 — 블록 부트스트랩은 근사. "
             "storm_p80 은 전역 상위분위 경계가 부분표본 거의 전체를 덮어 상위 gap ≈ 평균 gap 이다 "
             "(h21 V8 59/61·반사 61/61, h63 V8 58/61·반사 61/61).")
    L.append("")

    # ---------------------------------------------------------------- 변형
    L.append("## 기준선 명세 민감도 — 헤드라인은 λ=0.97·연속 모니터링·μ=0 한 판본뿐")
    L.append("")
    L.append("| h | 변형 | BS | 기후 대비 BSS | p̄ | 상위분위 gap | 로짓 기울기 | 쌍대(V8−변형) | 쌍대 CI90 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    order = ["ewma_lambda_0.94", "ewma_lambda_0.97", "ewma_lambda_0.99",
             "ewma_lambda_v8_selected_per_origin", "ewma_includes_origin_day_return",
             "discrete_monitoring_bgk", "drift_mu_hat"]
    label = {
        "ewma_lambda_0.94": "λ=0.94",
        "ewma_lambda_0.97": "λ=0.97 (헤드라인)",
        "ewma_lambda_0.99": "λ=0.99",
        "ewma_lambda_v8_selected_per_origin": "λ = V8 이 원점별로 고른 값 {0.94, 0.97}",
        "ewma_includes_origin_day_return": "λ=0.97, 원점 당일 수익률 포함(지연 제거)",
        "discrete_monitoring_bgk": "λ=0.97 + 이산 모니터링 보정(BGK β=0.5826)",
        "drift_mu_hat": "λ=0.97 + 드리프트 μ̂ (정확 first-passage)",
    }
    for h in ("21", "63"):
        clim = D["per_horizon"][h]["brier"]["climatology_insample"]
        for key in order:
            v = D["per_horizon"][h]["variants"][key]
            p = v["paired_v8_vs_variant"]
            L.append(f"| {h} | {label[key]} | {v['brier']:.6f} | "
                     f"{f(1 - v['brier'] / clim)} | {v['p_mean']:.4f} | "
                     f"{f(v.get('top_quintile_gap'))} | {f(v.get('logistic_slope'))} | "
                     f"{p['loss_diff']:+.6f} | {ci(p['ci90'], 5)} |")
    L.append("")
    sel = D["per_horizon"]["21"]["variants"]["ewma_lambda_v8_selected_per_origin"]
    L.append(f"V8 run 의 원점별 λ 분포(h21 417 원점): {sel['lambda_counts']}. "
             "envelope 의 λ=.97 고정은 규격이지 V8 복제가 아니다.")
    L.append("")

    # ---------------------------------------------------------------- σ
    L.append("## 원점별 σ (EWMA λ=0.97, 일간)")
    L.append("")
    L.append("| 통계 | 값 |")
    L.append("|---|---|")
    s = D["per_horizon"]["21"]["sigma"]
    for key, name in (("mean", "평균"), ("median", "중앙값"), ("min", "최소"), ("max", "최대"),
                      ("annualized_mean_252", "평균 연율화(√252)")):
        L.append(f"| {name} | {s[key]:.5f} |")
    L.append("")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(L)} lines)")


if __name__ == "__main__":
    main()
