#!/usr/bin/env python
"""tools/v12_reflect_doc_check.py — S2-2 리뷰 문서의 손으로 쓴 수치를 원본과 대사 (읽기 전용).

문서는 사람이 쓴다. 여기서는 원본 JSON 에서 문자열을 **포맷해서 만들고**, 그 문자열이 문서
안에 실제로 존재하는지 확인한다. 하나라도 없으면 전사 오류이거나 원본이 바뀐 것이다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/review/V12_S2_2_REFLECTION_BASELINE.md"
SRC = ROOT / "data/timeseries_v12/diagnostics/reflection_baseline.json"


def main() -> None:
    D = json.loads(SRC.read_text(encoding="utf-8"))
    text = DOC.read_text(encoding="utf-8").replace("−", "-")   # 문서는 U+2212 를 쓴다
    checks: list[tuple[str, str]] = []

    def want(tag: str, s: str) -> None:
        checks.append((tag, s))

    for h in ("21", "63"):
        b = D["per_horizon"][h]
        want(f"h{h} BS v8", f"{b['brier']['v8_first_touch']:.5f}")
        want(f"h{h} BS reflect", f"{b['brier']['reflection']:.5f}")
        want(f"h{h} BS clim", f"{b['brier']['climatology_insample']:.5f}")
        pair = b["paired"]["v8_vs_reflection"]
        want(f"h{h} 쌍대 점추정", f"{pair['loss_diff']:+.6f}")
        want(f"h{h} 쌍대 CI90",
             f"[{pair['ci90']['ci90_lower']:+.6f}, {pair['ci90']['ci90_upper']:+.6f}]")
        want(f"h{h} 승리원점", f"{pair['sign_test_a_better_origins']}/{pair['n']}")
        rd, vd = b["reflection_diagnostic"], b["v8_diagnostic"]
        want(f"h{h} reflect top_gap", f"{rd['top_quintile_gap']:+.4f}")
        want(f"h{h} v8 top_gap", f"{vd['top_quintile_gap']:+.4f}")
        want(f"h{h} reflect top_gap CI",
             f"[{rd['ci90']['top_quintile_gap']['ci90_lower']:+.4f}, "
             f"{rd['ci90']['top_quintile_gap']['ci90_upper']:+.4f}]")
        want(f"h{h} spearman", f"{b['agreement']['spearman_p_v8_vs_p_reflect']:.4f}")
        want(f"h{h} reflect AUC", f"{rd['auc']:.4f}")
        want(f"h{h} v8 AUC", f"{vd['auc']:.4f}")
        want(f"h{h} reflect slope", f"{rd['logistic_slope']:.4f}")
        want(f"h{h} v8 slope", f"{vd['logistic_slope']:.4f}")
        want(f"h{h} BSS v8|clim", f"{b['skill']['bss_v8_vs_climatology'] * 100:+.2f}%"
             .replace("+", "+"))
        for key in ("discrete_monitoring_bgk", "drift_mu_hat", "ewma_lambda_0.94",
                    "ewma_lambda_v8_selected_per_origin"):
            want(f"h{h} variant {key} BS", f"{b['variants'][key]['brier']:.6f}")
        # 국면 쌍대
        for row in D["regimes"][h]:
            if row.get("skipped"):
                continue
            p = row["paired_v8_vs_reflection"]
            want(f"h{h}/{row['regime']} 쌍대", f"{p['loss_diff']:+.6f}")

    # 명시 인용된 개별 수치
    want("h21 reflect RES", f"{D['per_horizon']['21']['reflection_diagnostic']['murphy_quantile_bins']['resolution']:.5f}")
    want("h63 reflect RES", f"{D['per_horizon']['63']['reflection_diagnostic']['murphy_quantile_bins']['resolution']:.5f}")
    want("h21 v8 RES", f"{D['per_horizon']['21']['v8_diagnostic']['murphy_quantile_bins']['resolution']:.5f}")
    want("h63 v8 RES", f"{D['per_horizon']['63']['v8_diagnostic']['murphy_quantile_bins']['resolution']:.5f}")
    sel = D["per_horizon"]["21"]["variants"]["ewma_lambda_v8_selected_per_origin"]
    want("h21 λ 분포 0.94", str(sel["lambda_counts"]["0.94"]))
    want("h21 λ 분포 0.97", str(sel["lambda_counts"]["0.97"]))

    missing = [(tag, s) for tag, s in checks if s not in text]
    for tag, s in checks:
        if s in text:
            continue
    print(f"== 문서 수치 대사: {len(checks)} 항목 중 {len(checks) - len(missing)} 일치")
    for tag, s in missing:
        print(f"  [FAIL] {tag}: 문서에 '{s}' 없음")
    print(f"\n== 전체: {'PASS' if not missing else 'FAIL'}")
    raise SystemExit(0 if not missing else 1)


if __name__ == "__main__":
    main()
