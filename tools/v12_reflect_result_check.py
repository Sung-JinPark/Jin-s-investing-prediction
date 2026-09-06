#!/usr/bin/env python
"""tools/v12_reflect_result_check.py — S2-2 result JSON 의 손으로 옮긴 수치를 원본과 대사 (읽기 전용).

result JSON 은 사람이 쓰는 파일이라 전사 오류가 들어갈 수 있다. headline 블록의 모든 수치를
reflection_baseline.json 과 자동 대조하고, 파싱 가능 여부와 artifacts sha256 도 확인한다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "outputs/timeseries_v12/loop/results/S2-2.json"
SRC = ROOT / "data/timeseries_v12/diagnostics/reflection_baseline.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    R = json.loads(RESULT.read_text(encoding="utf-8"))
    D = json.loads(SRC.read_text(encoding="utf-8"))
    ok = True

    print("== headline 대사 (result JSON vs reflection_baseline.json)")
    for h in ("21", "63"):
        b = D["per_horizon"][h]
        hd = R["headline"][f"h{h}"]
        pair = b["paired"]["v8_vs_reflection"]
        rd, vd = b["reflection_diagnostic"], b["v8_diagnostic"]
        checks = {
            "n": (hd["n"], b["n"], 0),
            "touches": (hd["touches"], b["touches"], 0),
            "base_rate": (hd["base_rate"], b["base_rate"], 1e-12),
            "brier_v8": (hd["brier_v8"], b["brier"]["v8_first_touch"], 1e-9),
            "brier_reflection": (hd["brier_reflection"], b["brier"]["reflection"], 1e-9),
            "brier_climatology_insample": (hd["brier_climatology_insample"],
                                           b["brier"]["climatology_insample"], 1e-12),
            "bss_v8_vs_climatology": (hd["bss_v8_vs_climatology"],
                                      b["skill"]["bss_v8_vs_climatology"], 1e-9),
            "bss_reflection_vs_climatology": (hd["bss_reflection_vs_climatology"],
                                              b["skill"]["bss_reflection_vs_climatology"], 1e-7),
            "bss_v8_vs_reflection": (hd["bss_v8_vs_reflection"],
                                     b["skill"]["bss_v8_vs_reflection"], 1e-7),
            "loss_diff_v8_minus_reflection": (hd["loss_diff_v8_minus_reflection"],
                                              pair["loss_diff"], 1e-9),
            "loss_diff_ci90_lo": (hd["loss_diff_ci90"][0], pair["ci90"]["ci90_lower"], 5e-7),
            "loss_diff_ci90_hi": (hd["loss_diff_ci90"][1], pair["ci90"]["ci90_upper"], 5e-7),
            "reflection_p_mean": (hd["reflection_p_mean"], rd["p_mean"], 1e-8),
            "reflection_top_quintile_gap": (hd["reflection_top_quintile_gap"],
                                            rd["top_quintile_gap"], 1e-8),
            "reflection_top_gap_ci90_lo": (hd["reflection_top_quintile_gap_ci90"][0],
                                           rd["ci90"]["top_quintile_gap"]["ci90_lower"], 5e-6),
            "reflection_top_gap_ci90_hi": (hd["reflection_top_quintile_gap_ci90"][1],
                                           rd["ci90"]["top_quintile_gap"]["ci90_upper"], 5e-6),
            "v8_top_gap_ci90_lo": (hd["v8_top_quintile_gap_ci90"][0],
                                   vd["ci90"]["top_quintile_gap"]["ci90_lower"], 5e-6),
            "v8_top_gap_ci90_hi": (hd["v8_top_quintile_gap_ci90"][1],
                                   vd["ci90"]["top_quintile_gap"]["ci90_upper"], 5e-6),
            "reflection_logistic_slope": (hd["reflection_logistic_slope"],
                                          rd["logistic_slope"], 5e-6),
            "reflection_auc": (hd["reflection_auc"], rd["auc"], 5e-6),
            "v8_auc": (hd["v8_auc"], vd["auc"], 5e-6),
            "spearman": (hd["spearman_p_v8_vs_p_reflect"],
                         b["agreement"]["spearman_p_v8_vs_p_reflect"], 5e-6),
        }
        win = pair["sign_test_a_better_origins"]
        checks["v8_win_origins"] = (hd["v8_win_origins"], f"{win}/{pair['n']}", None)
        for name, (got, want, tol) in checks.items():
            good = (got == want) if tol is None else abs(float(got) - float(want)) <= tol
            ok &= good
            if not good:
                print(f"  [FAIL] h{h}.{name}: result={got} vs src={want}")
        print(f"  h{h}: {len(checks)} 항목 대사")

    s = R["headline"]["sigma_ewma097"]
    src_s = D["per_horizon"]["21"]["sigma"]
    for k, sk in (("mean", "mean"), ("median", "median"), ("min", "min"), ("max", "max"),
                  ("annualized_mean_sqrt252", "annualized_mean_252")):
        good = abs(s[k] - src_s[sk]) <= 5e-6
        ok &= good
        if not good:
            print(f"  [FAIL] sigma.{k}: result={s[k]} vs src={src_s[sk]}")
    print(f"  sigma: 5 항목 대사")

    print("\n== verdict 대사")
    v = D["verdict"]
    pairs = [
        ("Q1_v8_beats_machine_baseline_both_horizons",
         v["Q1_does_v8_beat_the_machine_baseline"]["v8_beats_baseline_both_horizons"]),
        ("Q1_baseline_beats_v8_strictly_any_horizon",
         v["Q1_does_v8_beat_the_machine_baseline"]["baseline_beats_v8_any_horizon"]),
        ("Q2_baseline_also_overconfident_both_horizons",
         v["Q2_is_the_baseline_also_overconfident"]["baseline_overconfident_both_horizons"]),
    ]
    for key, want in pairs:
        good = R["verdict"][key] == want
        ok &= good
        print(f"  [{'OK ' if good else 'FAIL'}] {key} = {R['verdict'][key]}")
    q3 = v["Q3_shared_overconfidence_across_regimes"]
    want = f"{q3['both_positive_cells']}/{q3['cells_total']}"
    good = R["verdict"]["Q3_shared_overconfidence_cells"] == want
    ok &= good
    print(f"  [{'OK ' if good else 'FAIL'}] Q3 셀 = {R['verdict']['Q3_shared_overconfidence_cells']} (src {want})")

    print("\n== artifacts sha256 대사")
    for rel, want in R["artifacts"].items():
        path = ROOT / rel
        if not path.is_file():
            print(f"  [FAIL] 없음: {rel}")
            ok = False
            continue
        got = sha256(path)
        good = got == want
        ok &= good
        print(f"  [{'OK ' if good else 'FAIL'}] {rel}")
        if not good:
            print(f"         got={got}")

    print(f"\n== 전체: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
