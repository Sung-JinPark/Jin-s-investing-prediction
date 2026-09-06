#!/usr/bin/env python
"""tools/v12_reflect_verify.py — S2-2 헤드라인 독립 재계산 (읽기 전용, stdout 만).

v12_reflect_baseline.py 와 **다른 경로**로 같은 수를 다시 만든다. 목적은 자기표절 검증이 아니라
구현 실수 탐지다.

  V1 σ 경로: 원점마다 학습 슬라이스 endog[:i+1] 에 재귀를 새로 돌린다
             (본 계산의 '계열 한 번 재귀 후 위치 읽기' 지름길이 정확히 같은지)
  V2 Φ 경로: statistics.NormalDist 대신 math.erfc 로 정규 CDF
  V3 Brier : run JSON·parquet 에서 직접 (진단 JSON 을 경유하지 않음)
  V4 항등식: BS == REL − RES + UNC + binning_residual (Murphy 분해)
  V5 λ    : V8 run 전 행의 ewma_lambda 가 0.97 인지 (기준선 λ 가 V8 자신의 선택과 같은지)
  V6 쌍대 : loss_diff(v8 vs reflect) == BS_reflect − BS_v8
  V7 단조 : p_reflect 가 σ 에 대해 단조증가 (지평 고정)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_first_touch_diag as ft   # noqa: E402
import v12_reflect_baseline as rb   # noqa: E402

D = json.loads((ROOT / "data/timeseries_v12/diagnostics/reflection_baseline.json")
               .read_text(encoding="utf-8"))

LOG_B = math.log(0.90)
TOL = 1e-10


def phi_erfc(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def report(name: str, ok: bool, detail: str) -> bool:
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def main() -> None:
    import pandas as pd

    frame = pd.read_parquet(ROOT / "data/timeseries_v2/parquet/features_C1.parquet")
    dates_all = [d.date().isoformat() for d in frame.index]
    r = frame["nasdaq_return"].to_numpy(dtype=float)
    pos = {d: i for i, d in enumerate(dates_all)}
    run = json.loads((ROOT / "data/timeseries_v8/runs/dev_tsv8-exp-61cee7b7fb7c41399534.json")
                     .read_text(encoding="utf-8"))

    ok = True
    print("== S2-2 독립 재검증")

    # ---- V5: V8 이 원점마다 고른 λ.
    # 최초 가설 "run 은 언제나 0.97" 은 이 검사에서 **반증됐다**(0.94 도 쓴다). 가설을 바꾸지 않고
    # 반증 사실을 그대로 남기고, 대신 기준선 쪽에 V8 선택 λ 변형을 추가했다.
    lams = {float(s["ewma_lambda"]) for s in run["scores"]}
    counts = {}
    for s in run["scores"]:
        counts[float(s["ewma_lambda"])] = counts.get(float(s["ewma_lambda"]), 0) + 1
    ok &= report("V5 ewma_lambda ⊆ {0.94,0.97}", lams <= {0.94, 0.97},
                 f"run 전 {len(run['scores'])} 행 λ 분포 = {counts} "
                 f"— 최초 가설(항상 0.97) 반증됨, envelope 의 λ=.97 은 고정 규격이지 V8 복제가 아님")
    sel = D["per_horizon"]["21"]["variants"]["ewma_lambda_v8_selected_per_origin"]
    ok &= report("V5b V8 선택 λ 변형 기록", "lambda_counts" in sel,
                 f"h21 원점 λ 분포 = {sel.get('lambda_counts')}")

    for h in (21, 63):
        blk = D["per_horizon"][str(h)]
        dates = sorted({str(s["date"]) for s in run["scores"] if int(s["horizon"]) == h})
        p_v8 = np.array([float(s["first_touch_probability"]) for s in
                         sorted((s for s in run["scores"] if int(s["horizon"]) == h),
                                key=lambda s: s["date"])])
        y = np.array([1.0 if s["first_touch_actual"] else 0.0 for s in
                      sorted((s for s in run["scores"] if int(s["horizon"]) == h),
                             key=lambda s: s["date"])])
        stored_sigma = np.array(blk["sigma_per_origin"])
        stored_pr = np.array(blk["p_reflect"])

        # ---- V1: 원점별 슬라이스 재귀
        slice_sigma = []
        for d in dates:
            i = pos[d]
            v = rb.ewma_variance_series(r[: i + 1], 0.97)
            slice_sigma.append(math.sqrt(max(float(v[-1]), 1e-16)))
        slice_sigma = np.array(slice_sigma)
        dmax = float(np.max(np.abs(slice_sigma - stored_sigma)))
        ok &= report(f"V1 σ h{h}", dmax < TOL, f"슬라이스별 재귀 vs 저장값 max|Δ|={dmax:.3e}")

        # ---- V2: erfc 경로
        pr2 = np.array([min(1.0, 2.0 * phi_erfc(LOG_B / (s * math.sqrt(h))))
                        for s in slice_sigma])
        dmax = float(np.max(np.abs(pr2 - stored_pr)))
        ok &= report(f"V2 Φ h{h}", dmax < TOL, f"erfc 경로 vs 저장값 max|Δ|={dmax:.3e}")

        # ---- V3: Brier 직접
        bs_v8 = float(np.mean((p_v8 - y) ** 2))
        bs_re = float(np.mean((pr2 - y) ** 2))
        base = float(y.mean())
        bs_cl = float(np.mean((base - y) ** 2))
        d1 = abs(bs_v8 - blk["brier"]["v8_first_touch"])
        d2 = abs(bs_re - blk["brier"]["reflection"])
        d3 = abs(bs_cl - blk["brier"]["climatology_insample"])
        ok &= report(f"V3 Brier h{h}", max(d1, d2, d3) < TOL,
                     f"v8 Δ={d1:.3e} reflect Δ={d2:.3e} clim Δ={d3:.3e}")

        # ---- V4: Murphy 항등식
        for tag in ("reflection_diagnostic", "v8_diagnostic"):
            m = blk[tag]["murphy_quantile_bins"]
            lhs = m["brier"]
            rhs = m["reliability"] - m["resolution"] + m["uncertainty"] + m["binning_residual"]
            ok &= report(f"V4 Murphy h{h}/{tag}", abs(lhs - rhs) < 1e-12,
                         f"BS−(REL−RES+UNC+resid) = {lhs - rhs:.3e}")

        # ---- V6: 쌍대 손실차 항등식
        pair = blk["paired"]["v8_vs_reflection"]["loss_diff"]
        ok &= report(f"V6 쌍대 h{h}", abs(pair - (bs_re - bs_v8)) < TOL,
                     f"loss_diff−(BS_reflect−BS_v8) = {pair - (bs_re - bs_v8):.3e}")

        # ---- V7: σ 단조성
        order = np.argsort(stored_sigma)
        mono = bool(np.all(np.diff(stored_pr[order]) >= -1e-15))
        ok &= report(f"V7 단조 h{h}", mono,
                     f"σ 오름차순에서 p_reflect 비감소 = {mono} "
                     f"(σ∈[{stored_sigma.min():.5f},{stored_sigma.max():.5f}] → "
                     f"p∈[{stored_pr.min():.5f},{stored_pr.max():.5f}])")

        # ---- 부수: 상위분위 gap 재계산
        edges, _ = ft.quantile_edges(stored_pr)
        top = stored_pr >= edges[-2]
        gap = float(stored_pr[top].mean() - y[top].mean())
        ok &= report(f"V8x top_gap h{h}",
                     abs(gap - blk["reflection_diagnostic"]["top_quintile_gap"]) < TOL,
                     f"reflect 상위분위 gap={gap:+.6f} (n={int(top.sum())})")

    print(f"\n== 전체: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
