#!/usr/bin/env python
"""S4-2 게이트 설계 산술 — 게이트 산술·MDE·예산·파생층 배포 경계의 수치를 만든다 (읽기 전용).

실행:
    .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_2_gate_design.py \
        [--out data/timeseries_v12/design/gate_design.json]

이 스크립트가 하는 일 (전부 커밋된 산출물의 재분석 — 백테스트·홀드아웃·봉인 0):
  A 게이트 산술을 원배열에서 독립 재유도하고 계약값과 대사한다.
  B MDE 층 — 셀별 MDE·상대 MDE·현 효과를 유의하게 만들 표본수 n* 를 계산한다.
  C G4(reliability) 의 '감소 요건' 을 부트스트랩 se 로 정량화한다 (S4-1 open_question 1).
  D G1 병기 의무의 표본 문제(eligible_n 불일치)를 분해한다 (S4-1 open_question 4).
  E 예산 — 셀·다중검정·데이터·계산 예산의 산술.
  F 파생층 배포 경계 — 현 표시면의 실측 스캔.

어떤 후보 맵도 만들지 않는다. 새 가설을 세우지도, 문턱을 낮추지도 않는다.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_first_touch_diag as ft        # noqa: E402
import v12_reflect_baseline as rb        # noqa: E402

HS = (21, 63)
Z95 = statistics.NormalDist().inv_cdf(0.95)          # 1.6448536269514722 (게이트 규약)
Z_DIAG = 1.645                                       # 진단 규약 (mde50)

DIAG = ROOT / "data/timeseries_v12/diagnostics/first_touch_diagnostic.json"
REFL = ROOT / "data/timeseries_v12/diagnostics/reflection_baseline.json"
S2V = ROOT / "data/timeseries_v12/diagnostics/s2_entry_verdict.json"
S3V = ROOT / "data/timeseries_v12/diagnostics/s3_verdict.json"
PREREG = ROOT / "data/timeseries_v12/prereg/hypotheses.json"
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml"
V8_CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v8.yaml"

OUT_DEFAULT = ROOT / "data/timeseries_v12/design/gate_design.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- 적재

def load_all() -> dict[str, Any]:
    data = ft.load_first_touch()
    refl = jload(REFL)
    diag = jload(DIAG)
    per: dict[int, dict[str, Any]] = {}
    for h in HS:
        blk = data["per_horizon"][h]
        rh = refl["per_horizon"][str(h)]
        p = blk["p"]
        y = blk["y"]
        sigma = np.asarray(rh["sigma_per_origin"], dtype=float)
        p_2phi = np.asarray(rh["p_reflect"], dtype=float)
        p_bgk = rb.p_reflect_discrete(sigma, h)
        per[h] = {"dates": blk["dates"], "p": p, "y": y, "sigma": sigma,
                  "p_2phi": p_2phi, "p_bgk": p_bgk,
                  "diag": diag["per_horizon"][str(h)], "refl": rh}
    return {"run": data, "per": per, "diag": diag, "refl": refl}


# --------------------------------------------------------------------------- 공통 통계

def paired(p_a: np.ndarray, p_b: np.ndarray, y: np.ndarray,
           draws: list[np.ndarray]) -> dict[str, Any]:
    """손실차 d_i = (p_b−y)² − (p_a−y)² 의 평균과 블록부트 CI90. 양수 = A 우수."""
    d = (p_b - y) ** 2 - (p_a - y) ** 2
    boot = np.array([float(d[idx].mean()) for idx in draws])
    lo, hi = (float(v) for v in np.percentile(boot, [5, 95]))
    se = float(np.std(boot, ddof=1))
    return {"loss_diff": float(d.mean()), "ci90_lower": lo, "ci90_upper": hi,
            "bootstrap_se": se, "mde_z95": Z95 * se, "mde50_diag": Z_DIAG * se,
            "replicates": len(draws), "n": int(y.size)}


def murphy_both(p: np.ndarray, y: np.ndarray) -> dict[str, dict[str, float]]:
    qedges, _ = ft.quantile_edges(p)
    fedges = np.linspace(0.0, 1.0, ft.FIXED_BINS + 1)
    fedges[0] = -1e-12
    fedges[-1] = 1.0 + 1e-12
    return {"quantile_bins": ft.murphy(p, y, qedges),
            "fixed_bins": ft.murphy(p, y, fedges)}


def top_quintile_gap(p: np.ndarray, y: np.ndarray) -> float | None:
    qedges, _ = ft.quantile_edges(p)
    mask = p >= qedges[-2]
    if not mask.any():
        return None
    return float(p[mask].mean() - y[mask].mean())


# --------------------------------------------------------------------------- A 게이트 산술

def section_a(per: dict[int, dict[str, Any]], draws: dict[int, list[np.ndarray]],
              contract: dict[str, Any]) -> dict[str, Any]:
    """계약의 게이트 문턱을 원배열에서 독립 재유도하고 계약값과 대사."""
    th = contract["gates"]["G2_skill_vs_reflection"]["thresholds"]
    out: dict[str, Any] = {
        "identity": "요구 후보 BS = 기준선 BS − z·se(쌍대 V8−기준선) · "
                    "요구 BSS = 1 − 요구 후보 BS / 기후 BS",
        "z_convention": {"gate_multiplier": Z95, "diagnostic_multiplier": Z_DIAG,
                         "difference": Z_DIAG - Z95},
        "by_horizon": {},
    }
    for h in HS:
        b = per[h]
        p, y = b["p"], b["y"]
        base = float(y.mean())
        clim = np.full_like(p, base)
        bs_v8 = ft.brier(p, y)
        bs_clim = ft.brier(clim, y)
        row: dict[str, Any] = {
            "n": int(y.size), "touches": int(y.sum()), "base_rate": base,
            "brier_v8": bs_v8, "brier_climatology_insample": bs_clim,
            "climatology_identity_base_times_1_minus_base": base * (1 - base),
            "climatology_identity_residual": bs_clim - base * (1 - base),
            "bss_v8_vs_insample_climatology": 1 - bs_v8 / bs_clim,
            "baselines": {},
        }
        # 완전 재보정(REL→0) 가상 후보의 BSS 상한 — 점추정 기준. 독립 재유도.
        mb = murphy_both(p, y)
        ceil = {k: 1 - (bs_v8 - mb[k]["reliability"]) / bs_clim
                for k in ("fixed_bins", "quantile_bins")}
        cfe = contract["gate_feasibility_arithmetic"]["by_horizon"][f"h{h}"][
            "recalibration_ceiling_bss"]
        row["recalibration_ceiling_bss"] = {
            **ceil, "max": max(ceil.values()),
            "contract_fixed_bins": cfe["fixed_bins"],
            "contract_quantile_bins": cfe["quantile_bins"],
            "residual_fixed_bins": ceil["fixed_bins"] - cfe["fixed_bins"],
            "residual_quantile_bins": ceil["quantile_bins"] - cfe["quantile_bins"],
            "definition": "1 − (BS_V8 − REL)/BS_기후 — REL 을 0 으로 만든 가상 후보의 BSS. "
                          "점추정 상한이며 CI 를 만족시킨다는 뜻이 아니다.",
        }
        for name, arr, ckey in (("reflection_2phi", b["p_2phi"], "vs_reflection_2phi"),
                                ("reflection_bgk", b["p_bgk"], "vs_reflection_bgk")):
            bs_base = ft.brier(arr, y)
            pr = paired(p, arr, y, draws[h])          # d = (기준선−y)² − (V8−y)²
            mde = Z95 * pr["bootstrap_se"]
            req_bs = bs_base - mde
            req_bss = 1 - req_bs / bs_clim
            c = th[f"h{h}"][ckey]
            gap_to_ceiling = row["recalibration_ceiling_bss"]["max"] - req_bss
            row["baselines"][name] = {
                "required_bss_vs_recalibration_ceiling_headroom": gap_to_ceiling,
                "reachable_by_recalibration_point_estimate": bool(gap_to_ceiling >= 0),
                "baseline_brier_recomputed": bs_base,
                "baseline_brier_contract": c["baseline_brier"],
                "baseline_brier_residual": bs_base - c["baseline_brier"],
                "paired_v8_minus_baseline_loss_diff": pr["loss_diff"],
                "paired_bootstrap_se": pr["bootstrap_se"],
                "paired_ci90_lower": pr["ci90_lower"],
                "paired_ci90_upper": pr["ci90_upper"],
                "mde_z95_recomputed": mde,
                "mde_contract": c["mde_1645se"],
                "mde_residual": mde - c["mde_1645se"],
                "required_candidate_brier_recomputed": req_bs,
                "required_candidate_brier_contract": c["required_candidate_brier_max"],
                "required_candidate_brier_residual": req_bs - c["required_candidate_brier_max"],
                "required_bss_recomputed": req_bss,
                "required_bss_contract": c["required_brier_skill_vs_climatology_min"],
                "required_bss_residual": req_bss
                - c["required_brier_skill_vs_climatology_min"],
                "required_brier_reduction_from_v8": bs_v8 - req_bs,
                "required_brier_reduction_share_of_v8": (bs_v8 - req_bs) / bs_v8,
            }
        out["by_horizon"][f"h{h}"] = row
    # 계약 대사 요약 — 잔차 최대값
    resid = []
    for hrow in out["by_horizon"].values():
        resid += [abs(hrow["recalibration_ceiling_bss"]["residual_fixed_bins"]),
                  abs(hrow["recalibration_ceiling_bss"]["residual_quantile_bins"])]
        for brow in hrow["baselines"].values():
            resid += [abs(brow["baseline_brier_residual"]), abs(brow["mde_residual"]),
                      abs(brow["required_candidate_brier_residual"]),
                      abs(brow["required_bss_residual"])]
    out["contract_reconciliation"] = {
        "values_compared": len(resid), "max_abs_residual": max(resid),
        "tolerance": 1e-6, "all_within_tolerance": max(resid) < 1e-6,
        "note": "계약 YAML 은 6자리 반올림 저장이라 잔차는 반올림 오차 규모여야 한다.",
    }
    return out


# --------------------------------------------------------------------------- B MDE 층

def section_b(per: dict[int, dict[str, Any]], draws: dict[int, list[np.ndarray]],
              sec_a: dict[str, Any]) -> dict[str, Any]:
    """셀별 MDE·상대 MDE·현 효과를 유의하게 만들 표본수 n*."""
    out: dict[str, Any] = {
        "definition_mde": "MDE = z(0.95)·se_boot(쌍대 손실차). |Δ| < MDE 인 셀은 부호와 무관하게 "
                          "'결정적 증거 없음' (계약 G5.mde).",
        "definition_n_star": "n* = n·(z·se/|Δ̂|)² — se ∝ n^(−1/2) 와 효과·의존구조 불변을 가정한 "
                             "1차 근사. 현재 점추정을 CI90 하한>0 으로 만들려면 필요한 원점 수.",
        "n_star_caveats": [
            "se ∝ n^(−1/2) 는 블록부트에서 근사일 뿐 — 블록 길이 대비 표본이 커질수록만 성립.",
            "|Δ̂| 가 참값이라는 가정 — 점추정은 그 자체가 잡음이며 winner's curse 로 과대일 수 있다.",
            "Δ̂ ≤ 0 인 셀에는 정의되지 않는다 (개선이 없으므로 표본을 늘려도 통과하지 않는다).",
            "새 표본은 새 국면이므로 효과가 유지된다는 보장이 없다 — 이 수는 '필요 조건의 하한'.",
        ],
        "by_cell": {},
    }
    for h in HS:
        b = per[h]
        p, y = b["p"], b["y"]
        base = float(y.mean())
        bs_clim = ft.brier(np.full_like(p, base), y)
        dates = b["dates"]
        span_days = (ft._to_date(dates[-1]) - ft._to_date(dates[0])).days
        years = span_days / 365.25
        per_year = y.size / years
        comparisons = {
            "vs_climatology_insample": np.full_like(p, base),
            "vs_reflection_2phi": b["p_2phi"],
            "vs_reflection_bgk": b["p_bgk"],
        }
        for name, arr in comparisons.items():
            pr = paired(p, arr, y, draws[h])
            d = pr["loss_diff"]
            se = pr["bootstrap_se"]
            mde = Z95 * se
            bs_base = ft.brier(arr, y)
            cell: dict[str, Any] = {
                "horizon": h, "baseline": name, "n": int(y.size),
                "loss_diff_v8_minus_baseline": d,
                "bootstrap_se": se, "mde_z95": mde,
                "abs_effect_over_mde": abs(d) / mde if mde > 0 else None,
                "significant_ci90_lower_gt_0": pr["ci90_lower"] > 0,
                "ci90_lower": pr["ci90_lower"], "ci90_upper": pr["ci90_upper"],
                "mde_share_of_baseline_brier": mde / bs_base,
                "mde_in_bss_units": mde / bs_clim,
                "origins_per_year_measured": per_year,
                "window_years": years,
            }
            if d > 0:
                ratio = (mde / d) ** 2
                cell["n_star_origins"] = y.size * ratio
                cell["n_star_multiple_of_current"] = ratio
                cell["n_star_extra_origins"] = y.size * (ratio - 1)
                cell["n_star_extra_years"] = y.size * (ratio - 1) / per_year
            else:
                cell["n_star_origins"] = None
                cell["n_star_note"] = "Δ̂ ≤ 0 — 표본을 늘려도 이 방향으로는 통과하지 않는다."
            out["by_cell"][f"h{h}|{name}"] = cell
    return out


# --------------------------------------------------------------------------- C G4 정량화

def section_c(per: dict[int, dict[str, Any]], draws: dict[int, list[np.ndarray]],
              contract: dict[str, Any]) -> dict[str, Any]:
    """G4 reliability 감소 요건의 정량화 — REL 의 부트스트랩 se 와 '무장 가능성'."""
    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "question": "S4-1 open_question 1 — G4 의 'reliability 가 V8 실측값보다 작을 것' 에 "
                    "최소 감소폭이 없었다. 여기서 MDE 로 정량화한다.",
        "method": {
            "rel_bootstrap": "각 복제표본에서 binning 을 다시 만들고 Murphy REL 을 재계산 "
                             "(분위 경계도 복제표본에서 재산출 — 고정하면 se 가 과소평가된다).",
            "convention": "정상 블록 부트스트랩 ℓ=13, B=2000, seed 20260902 — S1~S3 규약 동일.",
            "floor_rule": "설계 단계 최소 감소폭 ΔREL_min = z(0.95)·se_boot(REL_V8). "
                          "후보가 없으므로 쌍대 se 를 쓸 수 없고, 단일 추정량의 se 는 "
                          "쌍대 se 보다 크므로 이 문턱은 보수적(더 엄격)이다.",
            "ceiling_rule": "완전 재보정(REL→0)의 감소폭 = REL_V8. "
                            "ΔREL_min > REL_V8 이면 REL 다리는 구조적으로 무장 불가.",
        },
        "by_horizon": {},
    }
    for h in HS:
        b = per[h]
        p, y = b["p"], b["y"]
        obs = murphy_both(p, y)
        rows: dict[str, Any] = {}
        for binning in ("quantile_bins", "fixed_bins"):
            boot = []
            for idx in draws[h]:
                pb, yb = p[idx], y[idx]
                boot.append(murphy_both(pb, yb)[binning]["reliability"])
            arr = np.asarray(boot, dtype=float)
            se = float(np.std(arr, ddof=1))
            lo, hi = (float(v) for v in np.percentile(arr, [5, 95]))
            rel = obs[binning]["reliability"]
            floor = Z95 * se
            rows[binning] = {
                "reliability_v8": rel,
                "bootstrap_se": se,
                "ci90_lower": lo, "ci90_upper": hi,
                "bootstrap_mean": float(arr.mean()),
                "required_min_reduction_z95_unpaired": floor,
                "max_possible_reduction_perfect_recalibration": rel,
                "armable_under_unpaired_se": bool(floor < rel),
                "shortfall": floor - rel,
                "required_reduction_share_of_rel": floor / rel if rel > 0 else None,
                "interpretation": "비쌍대 se 는 쌍대 se 의 상한이다(양의 상관 가정). 따라서 "
                                  "'무장 불가' 는 비쌍대 규약 아래에서의 진술이며, 실제 쌍대 se 는 "
                                  "후보가 존재해야 잴 수 있다. 후보를 지금 만들면 등록부 "
                                  "no_post_hoc_hypotheses 위반이므로 여기서는 상한만 말한다.",
            }
        # gap 다리 — 계약이 요구하는 것은 '상위분위 gap CI90 하한이 0 이하로'
        gap_leg = {}
        for subject, key in (("v8", "v8_diagnostic"), ("reflection_2phi", "reflection_diagnostic")):
            g = b["refl"][key]
            ci = g["ci90"]["top_quintile_gap"]
            lower = ci["ci90_lower"]
            gap_leg[subject] = {
                "gap": g["top_quintile_gap"],
                "gap_ci90_lower": lower,
                "gap_bootstrap_se": ci["bootstrap_se"],
                "already_satisfies_gate": bool(lower <= 0),
                "required_reduction_of_lower_bound": max(0.0, lower),
                "required_reduction_share_of_gap": (max(0.0, lower) / g["top_quintile_gap"]
                                                    if g["top_quintile_gap"] else None),
                "note": "se 가 후보에서도 같다고 본 1차 근사 — 실제로는 후보의 se 를 다시 재야 한다.",
            }
        out["by_horizon"][f"h{h}"] = {"reliability": rows, "top_quintile_gap": gap_leg}
    out["elapsed_sec"] = time.perf_counter() - t0
    # 계약 등재값과 대사
    c4 = contract["gates"]["G4_reliability"]["current_v8_reliability"]
    resid = []
    for h in HS:
        for binning in ("quantile_bins", "fixed_bins"):
            resid.append(abs(out["by_horizon"][f"h{h}"]["reliability"][binning]["reliability_v8"]
                             - c4[f"h{h}"][binning]))
    out["contract_reconciliation"] = {"values_compared": len(resid),
                                      "max_abs_residual": max(resid),
                                      "tolerance": 1e-6,
                                      "all_within_tolerance": max(resid) < 1e-6}
    return out


# --------------------------------------------------------------------------- D G1 병기 표본

def section_d(per: dict[int, dict[str, Any]], draws: dict[int, list[np.ndarray]]) -> dict[str, Any]:
    """G1 병기 의무의 표본 불일치 분해 — eligible_n 차이가 skill 차이의 어디까지를 설명하는가."""
    out: dict[str, Any] = {
        "question": "S4-1 open_question 4 — expanding 기후는 eligible_n 이 달라(h21 392·h63 384) "
                    "in-sample 기후 대비 skill 과 직접 비교되지 않는다. 병기를 어떤 표본으로 맞출 것인가.",
        "decomposition_identity": "BSS_expanding(적격) − BSS_insample(전표본) = "
                                  "[표본 효과] + [기준선 효과]. "
                                  "표본 효과 = BSS_insample(적격) − BSS_insample(전표본), "
                                  "기준선 효과 = BSS_expanding(적격) − BSS_insample(적격).",
        "by_horizon": {},
    }
    for h in HS:
        b = per[h]
        p, y, dates = b["p"], b["y"], b["dates"]
        exp = ft.expanding_climatology(dates, y, h)
        elig = exp["eligible"]
        clim_exp = exp["climatology"]
        base_full = float(y.mean())

        bs_v8_full = ft.brier(p, y)
        bs_clim_full = ft.brier(np.full_like(p, base_full), y)
        bss_in_full = 1 - bs_v8_full / bs_clim_full

        pe, ye = p[elig], y[elig]
        bs_v8_elig = ft.brier(pe, ye)
        # 적격 부분표본에서의 in-sample 기후: 전표본 기저율을 상수로 쓴다(정보집합 동일 유지).
        # 대안(적격 부분표본 자체의 기저율)도 함께 내어 분해가 이 선택에 민감하지 않음을 보인다.
        bs_clim_in_on_elig = ft.brier(np.full_like(pe, base_full), ye)
        base_elig = float(ye.mean())
        bs_clim_in_own_base = ft.brier(np.full_like(pe, base_elig), ye)
        bs_clim_exp_on_elig = ft.brier(clim_exp[elig], ye)
        bss_in_elig = 1 - bs_v8_elig / bs_clim_in_on_elig
        bss_in_elig_own_base = 1 - bs_v8_elig / bs_clim_in_own_base
        bss_exp_elig = 1 - bs_v8_elig / bs_clim_exp_on_elig

        # 적격 부분표본 위의 쌍대 검정. 상류(S2-1)가 부분표본에 seed=SEED+1 을 쓰므로
        # 같은 규약을 그대로 따른다 — 그래야 재현이 대사가 된다.
        sub_draws = ft.block_index_draws(int(elig.sum()), seed=ft.SEED + 1)
        pr_exp = paired(pe, clim_exp[elig], ye, sub_draws)
        pr_in = paired(pe, np.full_like(pe, base_full), ye, sub_draws)

        out["by_horizon"][f"h{h}"] = {
            "n_full": int(y.size), "eligible_n": int(elig.sum()),
            "dropped_origins": int(y.size - elig.sum()),
            "maturity_days": exp["maturity_days"], "min_train": exp["min_train"],
            "base_rate_full": base_full,
            "base_rate_eligible": float(ye.mean()),
            "brier_v8_full": bs_v8_full, "brier_v8_eligible": bs_v8_elig,
            "brier_climatology_insample_full": bs_clim_full,
            "brier_climatology_insample_on_eligible": bs_clim_in_on_elig,
            "brier_climatology_expanding_on_eligible": bs_clim_exp_on_elig,
            "brier_climatology_insample_on_eligible_own_base": bs_clim_in_own_base,
            "bss_insample_full": bss_in_full,
            "bss_insample_on_eligible": bss_in_elig,
            "bss_insample_on_eligible_own_base": bss_in_elig_own_base,
            "sample_effect_own_base_variant": bss_in_elig_own_base - bss_in_full,
            "bss_expanding_on_eligible": bss_exp_elig,
            "total_difference": bss_exp_elig - bss_in_full,
            "sample_effect": bss_in_elig - bss_in_full,
            "baseline_effect": bss_exp_elig - bss_in_elig,
            "identity_residual": (bss_exp_elig - bss_in_full)
            - ((bss_in_elig - bss_in_full) + (bss_exp_elig - bss_in_elig)),
            "paired_v8_vs_expanding_on_eligible": pr_exp,
            "paired_v8_vs_insample_climatology_on_eligible": pr_in,
            "both_paired_ci90_lower_gt_0": bool(pr_exp["ci90_lower"] > 0
                                                and pr_in["ci90_lower"] > 0),
            "upstream_reconciliation": {
                "source": "first_touch_diagnostic.json per_horizon.h.ci90.loss_diff_expanding "
                          "· point_estimates.loss_diff_expanding (S2-1)",
                "seed_convention": "부분표본 draw 는 seed=SEED+1 (S2-1 규약) — 본 재현도 동일.",
                "loss_diff_residual": pr_exp["loss_diff"]
                - b["diag"]["point_estimates"]["loss_diff_expanding"],
                "ci90_lower_residual": pr_exp["ci90_lower"]
                - b["diag"]["ci90"]["loss_diff_expanding"]["ci90_lower"],
                "bootstrap_se_residual": pr_exp["bootstrap_se"]
                - b["diag"]["ci90"]["loss_diff_expanding"]["bootstrap_se"],
                "bss_expanding_residual": bss_exp_elig
                - b["diag"]["expanding_climatology"]["bss_vs_expanding"],
            },
        }
    return out


# --------------------------------------------------------------------------- E 예산

def section_e(sec_b: dict[str, Any], sec_c: dict[str, Any], s3v: dict[str, Any],
              prereg: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    dp = contract["development_protocol"]
    nr = contract["negative_result"]
    fam = int(nr["family_cells"])
    k_mean = float(nr["permutation_null"]["k_mean_under_null"])
    per_cell_null = k_mean / fam
    # 독립 근사 하의 family-wise 오통과 확률 (근사임을 명시)
    fw_any = 1 - (1 - per_cell_null) ** fam
    cell_rate = {k: float(v) for k, v in
                 s3v["null_liberality"]["cell_pass_rate"].items()}
    h21_rates = [v for k, v in cell_rate.items() if k.endswith("h21")]
    h63_rates = [v for k, v in cell_rate.items() if k.endswith("h63")]
    mean_h21 = sum(h21_rates) / len(h21_rates)
    mean_h63 = sum(h63_rates) / len(h63_rates)
    out: dict[str, Any] = {
        "unit_definition": {
            "cell": "(후보 맵, 지평) — 계약 gates.unit_of_judgement 원문.",
            "direction": "(셀, 전이 방향) — 셀 하나가 2 방향을 요구하므로 방향 = 2×셀.",
            "development_evaluation": "예산 단위. 한 후보 맵을 전 셀 격자에서 재는 1회 = "
                                      "지평 2 × 방향 2 = 4 방향검정.",
        },
        "contract_caps": {
            "maximum_development_evaluations": dp["maximum_development_evaluations"],
            "evaluations_spent_recorded": dp["evaluations_spent"],
            "holdout_maximum_finalists": dp["holdout_maximum_finalists"],
            "sealed_maximum_disclosures_per_model_version":
                contract["stopping_points"]["sealed"]["maximum_disclosures_per_model_version"],
            "track_open": dp["track_open"],
        },
        "s3_consumption": {
            "hypotheses_registered": len(prereg["hypotheses"]),
            "adoption_eligible_hypotheses": sum(1 for hh in prereg["hypotheses"]
                                                if hh.get("adoption_eligible")),
            "family_cells": fam,
            "directions_evaluated": int(nr["directions_evaluated"]),
            "development_evaluations_equivalent": fam / 2,
            "negative_control_runs": 1,
            "permutation_replicates": int(nr["permutation_null"]["replicates"]),
            "accounting_question": "S3 의 8 셀을 트랙 예산에 계상할 것인가 — 계약은 "
                                   "evaluations_spent=0 (트랙 미개시)으로 적었다. "
                                   "계상하면 잔여 예산은 24−4=20 development evaluation.",
            "recommended_accounting": "계상한다 (보수적). 같은 표본에서 이미 소모된 검정력을 "
                                      "0 으로 적으면 예산이 다중검정을 통제하지 못한다.",
            "remaining_if_counted": dp["maximum_development_evaluations"] - fam / 2,
        },
        "multiplicity_budget": {
            "family_cells": fam,
            "k_mean_under_permutation_null": k_mean,
            "implied_per_cell_null_pass_rate": per_cell_null,
            "nominal_per_cell_rate": 0.05,
            "inflation_factor": per_cell_null / 0.05,
            "per_cell_null_pass_rate_measured": cell_rate,
            "per_cell_mean_h21": mean_h21,
            "per_cell_mean_h63": mean_h63,
            "cells_above_nominal_h21": sum(1 for k, v in cell_rate.items()
                                           if k.endswith("h21") and v > 0.05),
            "cells_above_nominal_h63": sum(1 for k, v in cell_rate.items()
                                           if k.endswith("h63") and v > 0.05),
            "horizon_asymmetry": "h21 셀은 귀무 통과율이 명목 5% 를 크게 넘고(평균 "
                                 f"{mean_h21:.3f}) h63 셀은 명목 이하다(평균 {mean_h63:.3f}). "
                                 "같은 기계가 지평별로 반대 방향의 오차를 낸다.",
            "sum_check_vs_k_mean": sum(cell_rate.values()) - k_mean,
            "familywise_any_pass_independent_approx": fw_any,
            "independence_caveat": "셀은 지평·방향으로 겹치므로 독립이 아니다 — 위 근사는 "
                                   "상한도 하한도 아니고 규모 감각용이다.",
            "machine_repair_thresholds": {
                "negative_control_pooled_pass_rate_max": float(
                    nr["negative_control_T5"]["threshold"]),
                "observed_pooled_pass_rate": float(nr["negative_control_T5"]["pass_rate_pooled"]),
                "observed_pooled_pass_rate_source_check": float(
                    s3v["verdict"]["T5_pass_rate_pooled"]),
                "source_check_residual": float(s3v["verdict"]["T5_pass_rate_pooled"])
                - float(nr["negative_control_T5"]["pass_rate_pooled"]),
                "implied_gap": float(nr["negative_control_T5"]["pass_rate_pooled"])
                - float(nr["negative_control_T5"]["threshold"]),
                "per_cell_null_pass_rate_max_proposed": 0.05,
            },
            "budget_rule": "검정 기계가 수리되기 전에는 예산을 1 단위도 배정하지 않는다 — "
                           "현재 기계에서 얻는 통과는 P(귀무 통과)≈"
                           f"{per_cell_null:.3f}/셀 이라 증거가 아니다.",
        },
        "data_budget": {
            "definition": "현 점추정을 CI90 하한>0 으로 만드는 데 필요한 추가 원점·연수 (섹션 B n*).",
            "by_cell": {k: {"n_star_origins": v.get("n_star_origins"),
                            "extra_years": v.get("n_star_extra_years"),
                            "multiple": v.get("n_star_multiple_of_current"),
                            "defined": v.get("n_star_origins") is not None}
                        for k, v in sec_b["by_cell"].items()},
            "note": "정의되지 않은 셀(Δ̂ ≤ 0)은 표본 증설이 해법이 아님을 뜻한다.",
        },
        "compute_budget": {
            "rel_bootstrap_elapsed_sec_measured": sec_c["elapsed_sec"],
            "rel_bootstrap_scope": "2 지평 × 2 binning × B=2000 복제 (분위 경계 재산출 포함)",
            "note": "게이트 1회 평가의 비용은 이 규모 — 초 단위다. 예산의 제약은 계산이 아니라 "
                    "표본과 다중검정이다.",
            "api_cost_usd": 0.0,
            "api_cost_note": "이 층은 결정론 수치 계산이며 LLM 호출이 없다 (CLAUDE.md 비용 가드레일 무관).",
        },
    }
    return out


# --------------------------------------------------------------------------- F 배포 경계

def scan_surface() -> dict[str, Any]:
    """파생층이 지금 어디에 닿아 있는가 — 실측 스캔."""
    src = ROOT / "src"
    py = sorted(src.rglob("*.py"))
    js = sorted((src / "ai_fc/dashboard_parts").rglob("*.js"))
    files = py + js

    def hits(pattern: str, paths: list[Path]) -> list[str]:
        rx = re.compile(pattern)
        found = []
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    found.append(f"{path.relative_to(ROOT).as_posix()}:{i}")
        return found

    v12_refs = hits(r"timeseries_v12", files)
    ft_prob = hits(r"first_touch_probability", files)
    touch10 = hits(r"first_touch_minus_10", files)
    contracts_glob = hits(r"glob\(.*contracts|contracts.*\.glob\(", py)

    def role(site: str) -> str:
        path = site.rsplit(":", 1)[0]
        if path.startswith("src/tests/"):
            return "test"
        if path.endswith("dashboard.js"):
            return "display_dashboard"
        if path.endswith("artifact.py"):
            return "published_artifact_builder"
        if path.endswith("cli.py"):
            return "console_output"
        if path.endswith("audit.py"):
            return "audit"
        return "producer"

    by_role: dict[str, list[str]] = {}
    for site in touch10:
        by_role.setdefault(role(site), []).append(site)

    # 이미 배포된 산출물에 이 계열 확률이 실려 있는가 (읽기만).
    published: dict[str, Any] = {}
    fp = ROOT / "reports/future_paths.json"
    if fp.is_file():
        try:
            doc = json.loads(fp.read_text(encoding="utf-8"))
            found = json.dumps(doc, ensure_ascii=False).count("first_touch_minus_10")
            published["reports/future_paths.json"] = {
                "key_occurrences": found, "sha256": sha256(fp)}
        except (json.JSONDecodeError, OSError) as exc:            # noqa: PERF203
            published["reports/future_paths.json"] = {"error": repr(exc)}

    return {
        "files_scanned": len(files),
        "src_references_to_timeseries_v12": v12_refs,
        "src_references_to_timeseries_v12_count": len(v12_refs),
        "src_references_to_first_touch_probability": ft_prob,
        "src_references_to_first_touch_probability_count": len(ft_prob),
        "minus10_touch_probability_sites": touch10,
        "minus10_touch_probability_count": len(touch10),
        "minus10_sites_by_role": by_role,
        "minus10_sites_by_role_counts": {k: len(v) for k, v in sorted(by_role.items())},
        "published_artifacts_carrying_minus10": published,
        "code_paths_globbing_contracts": contracts_glob,
    }


def section_f(contract: dict[str, Any]) -> dict[str, Any]:
    scan = scan_surface()
    pc = contract["probability_contract"]
    return {
        "measured_surface": scan,
        "current_layer_state": {
            "publication_status": pc["publication_status"],
            "p3_gate_status": pc["p3_gate_status"],
            "combine_with_official_forecasts": pc["combine_with_official_forecasts"],
            "combine_with_scenario_v5_2": pc["combine_with_scenario_v5_2"],
            "combine_with_v8_surface": pc["combine_with_v8_surface"],
            "derived_layer_constraint": pc["derived_layer_constraint"],
        },
        "collision_risk": {
            "finding": "표시 계통에 이미 '−10% 접촉' 계열 확률이 있다 — 산출기(model/engine/paths), "
                       "배포 산출물 빌더(artifact.py), 대시보드(dashboard.js), 콘솔(cli.py).",
            "sites_by_role": scan["minus10_sites_by_role"],
            "published_artifacts": scan["published_artifacts_carrying_minus10"],
            "why_it_matters": "V12 파생층이 표시되면 같은 화면에 뜻이 다른 '−10% 접촉 확률' 이 "
                              "둘 이상 생긴다. 산출 모델·지평 규약·보정 상태가 모두 다르다.",
            "difference": {
                "timeseries_v1_artifact": "몬테카를로 경로 비율 (model.py: min ≤ 0.90·anchor) · "
                                          "future_paths 배포 산출물에 실림",
                "scenario_v5_2": "몬테카를로 경로 비율 · 달력 기한(10월 말) · 보정 안 됨(화면 명시)",
                "v12_derived": "V8 first_touch 확률의 파생 재보정 · 21/63 세션 지평 · "
                               "게이트 미통과(현재 armed=false)",
            },
            "required_before_any_display": "두 수의 라벨·지평·보정 상태를 화면에서 구분할 수 없다면 "
                                           "표시하지 않는다.",
        },
        "no_write_path_check": {
            "src_references_to_timeseries_v12": scan["src_references_to_timeseries_v12_count"],
            "meaning": "제품 코드가 V12 산출물을 읽지도 쓰지도 않는다 — 파생층은 현재 "
                       "표시면과 배선되어 있지 않다.",
        },
    }


# --------------------------------------------------------------------------- 봉인 대사

def seal_state() -> dict[str, Any]:
    """봉인 대사 — 규약은 tools/v12_seal_check.py (sunday_opus_loop.sh sealed_hash 재현)."""
    import subprocess

    import v12_seal_check as sc

    loop = ROOT / "outputs/timeseries_v12/loop"
    sealed = sc.sealed_hash()
    ledger = sc.ledger_hash()
    base = (loop / "sealed_baseline.hash").read_text(encoding="utf-8").strip()
    lbase = (loop / "ledger_baseline.hash").read_text(encoding="utf-8").strip()
    pin = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["predecessor_immutability"]
    out = {
        "sealed_source_hash": sealed,
        "sealed_baseline": base,
        "sealed_matches_baseline": sealed == base,
        "sealed_matches_contract_pin": sealed == pin["sealed_source_hash"],
        "v8_ledger_hash": ledger,
        "ledger_baseline": lbase,
        "ledger_matches_baseline": ledger == lbase,
        "ledger_matches_contract_pin": ledger == pin["v8_ledger_hash"],
        "v8_contract_sha256": sha256(V8_CONTRACT),
        "v8_contract_matches_pin": sha256(V8_CONTRACT) == pin["v8_contract_sha256"],
    }
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", "forecasts", "calibration", "src",
             "data/timeseries_v8", "data/timeseries_v2", "questions"],
            cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
        out["git_status_immutable_paths"] = proc.stdout.strip()
        out["immutable_paths_clean"] = proc.stdout.strip() == ""
    except Exception as exc:                                   # noqa: BLE001
        out["git_status_error"] = repr(exc)
    return out


# --------------------------------------------------------------------------- main

def main() -> int:
    out_path = OUT_DEFAULT
    argv = sys.argv[1:]
    if "--out" in argv:
        out_path = ROOT / argv[argv.index("--out") + 1]

    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    prereg = jload(PREREG)
    s3v = jload(S3V)

    bundle = load_all()
    per = bundle["per"]
    draws = {h: ft.block_index_draws(int(per[h]["y"].size)) for h in HS}

    sec_a = section_a(per, draws, contract)
    sec_b = section_b(per, draws, sec_a)
    sec_c = section_c(per, draws, contract)
    sec_d = section_d(per, draws)
    sec_e = section_e(sec_b, sec_c, s3v, prereg, contract)
    sec_f = section_f(contract)

    payload = {
        "generated_by": "tools/v12_s4_2_gate_design.py",
        "stage": "S4-2",
        "purpose": "V12 게이트 설계서(docs/design/v12_gate_design.md)의 수치 원천. "
                   "새 가설·새 후보·문턱 조정 0.",
        "read_only": True,
        "provenance": {
            "run_path": bundle["run"]["run_path"],
            "run_sha256": bundle["run"]["run_sha256"],
            "inputs_sha256": {
                p.relative_to(ROOT).as_posix(): sha256(p)
                for p in (DIAG, REFL, S2V, S3V, PREREG, CONTRACT, V8_CONTRACT)
            },
            "convention": {
                "bootstrap": "stationary block, block=13, replicates=2000, seed=20260902, "
                             "percentile[5,95]",
                "z_gate": Z95, "z_diagnostic": Z_DIAG,
                "loss_diff_sign": "양수 = V8 우수 (기준선 손실 − V8 손실)",
            },
        },
        "seal_state": seal_state(),
        "A_gate_arithmetic": sec_a,
        "B_mde_layer": sec_b,
        "C_g4_reliability_quantification": sec_c,
        "D_g1_companion_sample": sec_d,
        "E_budget": sec_e,
        "F_deployment_boundary": sec_f,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                        + "\n", encoding="utf-8")

    print(f"wrote {out_path.relative_to(ROOT).as_posix()}")
    print(f"  A 계약 대사: {sec_a['contract_reconciliation']}")
    for h in HS:
        c = sec_c["by_horizon"][f"h{h}"]["reliability"]
        print(f"  C h{h} REL quantile: rel={c['quantile_bins']['reliability_v8']:.6f} "
              f"se={c['quantile_bins']['bootstrap_se']:.6f} "
              f"floor={c['quantile_bins']['required_min_reduction_z95_unpaired']:.6f} "
              f"armable_unpaired={c['quantile_bins']['armable_under_unpaired_se']}")
        print(f"  C h{h} REL fixed   : rel={c['fixed_bins']['reliability_v8']:.6f} "
              f"se={c['fixed_bins']['bootstrap_se']:.6f} "
              f"floor={c['fixed_bins']['required_min_reduction_z95_unpaired']:.6f} "
              f"armable_unpaired={c['fixed_bins']['armable_under_unpaired_se']}")
        d = sec_d["by_horizon"][f"h{h}"]
        print(f"  D h{h}: BSS_in_full={d['bss_insample_full']:+.6f} "
              f"BSS_in_elig={d['bss_insample_on_eligible']:+.6f} "
              f"BSS_exp_elig={d['bss_expanding_on_eligible']:+.6f} "
              f"(표본 {d['sample_effect']:+.6f} · 기준선 {d['baseline_effect']:+.6f})")
    for key, cell in sec_b["by_cell"].items():
        print(f"  B {key}: Δ={cell['loss_diff_v8_minus_baseline']:+.6f} "
              f"MDE={cell['mde_z95']:.6f} n*="
              + (f"{cell['n_star_origins']:.0f}" if cell["n_star_origins"] else "정의없음"))
    print(f"  F 표시면: v12 참조 {sec_f['measured_surface']['src_references_to_timeseries_v12_count']} · "
          f"−10% 계열 {sec_f['measured_surface']['minus10_sites_by_role_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
