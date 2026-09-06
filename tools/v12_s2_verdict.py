#!/usr/bin/env python
"""tools/v12_s2_verdict.py — S2-3 진입/중단 판정 (읽기 전용).

무엇을 하는가
-------------
S2-1(`first_touch_diagnostic.json`) 과 S2-2(`reflection_baseline.json`) 의 **커밋된 산출물만**
읽어서 설계도 §1 의 S2→S3 통과 조건

    "과신 구조가 두 지평·국면 초월로 재현되면 S3 진입"

을 네 가지 조작화(R0~R3) 전부에서 기계적으로 평가하고, 그중 **어느 것을 채택하는지의 근거를
결과와 무관하게 미리 고정**한 뒤 진입/중단을 1건 판정한다. 채택 규칙은 아래 ADOPTION 상수에
문자열로 박혀 있고, 스크립트는 네 조작화의 결과를 **전부** 출력한다 — 통과한 것만 고르지 않는다.

채택 근거(사후 선택 방지)
------------------------
설계도 §1 문장의 주어는 "V8 의 과신" 이 아니라 **"과신 구조"** 다. S2-2 는 그 구조의 담지자를
식별했다 — 자유 파라미터 0 개인 반사원리 기준선도 두 지평에서 같은 방향으로 과신하며(8/8 셀),
V8 과의 순위상관은 0.95/0.91 이다. 즉 과신은 V8 의 성질이 아니라 −10% first-passage 를
변동성으로 확률화할 때 생기는 **표적의 성질**이다. 따라서 "구조가 재현되는가" 를 엄격
조작화(CI90 하한>0)로 물을 때 주체는 기준선이어야 한다(R2). R1(V8 주체 엄격)은 더 좁은 질문
— "V8 의 과신이 통계적으로 확립되는가" — 이며 h21 에서 미달한다. 둘 다 공표한다.

이 근거는 S2-2 가 결과를 공표한 뒤에 쓰였다. 그래서 R0(2026-09-04 설계도 문자 기준, 유일한
사전등록 조작화)도 함께 판정하고, R0·R2 가 **동시에** 통과할 때만 진입으로 본다 — 사후에
느슨한 쪽으로 갈아타 통과시키는 경로를 차단한다.

부수 산출: S3-0 사전등록에 넘길 검정력 사실(분할창 쌍대 손실차의 블록부트 se·MDE).
이것은 T1~T5 어느 가설도 평가하지 않는다 — 후보 맵을 만들지 않고 분산 규모만 잰다.

쓰기는 ``--out`` 한 파일뿐. 백테스트·홀드아웃·봉인 실행 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_first_touch_diag as ft        # noqa: E402  — S2-1 통계 헬퍼 재사용
import v12_reflect_baseline as rb        # noqa: E402  — S2-2 쌍대 부트스트랩 재사용

S2_1_JSON = "data/timeseries_v12/diagnostics/first_touch_diagnostic.json"
S2_2_JSON = "data/timeseries_v12/diagnostics/reflection_baseline.json"

FOCUS = [21, 63]
REGIMES = ["gfc", "non_gfc", "calm_p80", "storm_p80"]
SPLIT = "2010-12-31"          # 설계도 §2 전반(2007–10) / 후반(2011–14)
Z90 = 1.6448536269514722

ADOPTION = (
    "채택 = R0(설계도 문자·사전등록) AND R2(엄격·주체=표적 구조). "
    "R1(엄격·주체=V8) 은 더 좁은 질문이며 결과와 무관하게 함께 공표한다. "
    "R3(로짓 기울기 CI90 상한<1) 은 보강 증거로만 쓰고 판정에 넣지 않는다(S2-1 gate_definition 승계)."
)


# --------------------------------------------------------------------------- 로딩

def load_json(rel: str) -> dict[str, Any]:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def lower(ci: dict[str, Any] | None) -> float | None:
    if not ci:
        return None
    v = ci.get("ci90_lower")
    return None if v is None else float(v)


def upper(ci: dict[str, Any] | None) -> float | None:
    if not ci:
        return None
    v = ci.get("ci90_upper")
    return None if v is None else float(v)


# --------------------------------------------------------------------------- R0~R3

def evaluate_rules(s21: dict[str, Any], s22: dict[str, Any]) -> dict[str, Any]:
    """네 조작화를 전부 평가한다. 통과한 것만 남기지 않는다."""
    out: dict[str, Any] = {}

    # ---- 지평 수준 수치 (두 진단서에서 그대로)
    horizons: dict[str, Any] = {}
    for h in FOCUS:
        v8 = s21["per_horizon"][str(h)]
        ref = s22["per_horizon"][str(h)]["reflection_diagnostic"]
        v8r = s22["per_horizon"][str(h)]["v8_diagnostic"]
        # S2-1 과 S2-2 의 V8 수치는 같은 표본이므로 반드시 일치해야 한다 — 대사한다.
        assert abs(float(v8["top_quintile_gap"]) - float(v8r["top_quintile_gap"])) < 1e-12, h
        horizons[f"h{h}"] = {
            "n": int(v8["n"]),
            "touches": int(v8["touches"]),
            "base_rate": float(v8["base_rate"]),
            "v8_top_gap": float(v8["top_quintile_gap"]),
            "v8_top_gap_ci90": v8["ci90"]["top_quintile_gap"],
            "v8_slope": float(v8["logistic_recalibration"]["slope"]),
            "v8_slope_ci90": v8["ci90"]["logistic_slope"],
            "reflection_top_gap": float(ref["top_quintile_gap"]),
            "reflection_top_gap_ci90": ref["ci90"]["top_quintile_gap"],
            "reflection_slope": float(ref["logistic_slope"]),
            "reflection_slope_ci90": ref["ci90"]["logistic_slope"],
        }
    out["horizons"] = horizons

    # ---- 국면 셀 (8 = 2 지평 × 4 국면). 부호 기준은 두 모델 모두 양수일 때만 인정.
    cells: list[dict[str, Any]] = []
    for h in FOCUS:
        v8_rows = {r["regime"]: r for r in s21["regimes"][str(h)] if "regime" in r}
        rf_rows = {r["regime"]: r for r in s22["regimes"][str(h)] if "regime" in r}
        for reg in REGIMES:
            a, b = v8_rows.get(reg), rf_rows.get(reg)
            if a is None or b is None:
                continue
            v8_gap = float(a["top_quintile_gap"])
            rf_gap = float(b["top_quintile_gap"]["reflection"])
            rf_ci = b["ci90_reflection"].get("top_quintile_gap")
            v8_ci = (a.get("ci90") or {}).get("top_quintile_gap")
            cells.append({
                "horizon": h,
                "regime": reg,
                "n": int(a["n"]),
                "touches": int(a["touches"]),
                "v8_top_gap": v8_gap,
                "v8_top_gap_ci90": v8_ci,
                "v8_top_gap_ci90_lower_positive": bool((lower(v8_ci) or -1.0) > 0),
                "reflection_top_gap": rf_gap,
                "reflection_top_gap_ci90": rf_ci,
                "reflection_top_gap_ci90_lower_positive": bool((lower(rf_ci) or -1.0) > 0),
                "v8_mean_gap": float(a["mean_calibration_gap"]),
                "reflection_mean_gap": float(b["mean_calibration_gap"]["reflection"]),
                "both_top_gap_positive": bool(v8_gap > 0 and rf_gap > 0),
                "both_mean_gap_positive": bool(float(a["mean_calibration_gap"]) > 0
                                               and float(b["mean_calibration_gap"]["reflection"]) > 0),
            })
    out["regime_cells"] = cells
    out["regime_cell_summary"] = {
        "cells": len(cells),
        "both_top_gap_positive": sum(1 for c in cells if c["both_top_gap_positive"]),
        "both_mean_gap_positive": sum(1 for c in cells if c["both_mean_gap_positive"]),
        "reflection_ci90_lower_positive": sum(
            1 for c in cells if c["reflection_top_gap_ci90_lower_positive"]),
        "v8_ci90_lower_positive": sum(1 for c in cells if c["v8_top_gap_ci90_lower_positive"]),
        "note": ("부호는 8/8 이지만 셀 수준 CI90 하한>0 은 그보다 적다 — 국면 부분표본은 "
                 "S2-1 과 동일한 비층화 블록부트 근사이며 storm_p80 은 전역 상위분위 경계가 "
                 "부분표본을 거의 덮어 독립 정보가 아니다(S2-2 이월)."),
    }

    # ---- R0: 설계도 문자 (사전등록) — 두 지평 부호 재현 + 국면 초월 부호 재현
    r0_h = {f"h{h}": bool(horizons[f"h{h}"]["v8_top_gap"] > 0
                          and horizons[f"h{h}"]["reflection_top_gap"] > 0) for h in FOCUS}
    r0_cells = sum(1 for c in cells if c["both_top_gap_positive"])
    out["R0"] = {
        "name": "설계도 §1 문자 기준 (2026-09-04 사전등록) — 두 지평·국면 초월 부호 재현",
        "by_horizon": r0_h,
        "cells_both_positive": f"{r0_cells}/{len(cells)}",
        "cells_all_positive": bool(r0_cells == len(cells)),
        "pass": bool(all(r0_h.values()) and r0_cells == len(cells)),
    }

    # ---- R1: 엄격 · 주체 = V8 (S2-1 이 데이터 본 뒤 도입)
    r1_h = {f"h{h}": (lower(horizons[f"h{h}"]["v8_top_gap_ci90"]) or -1.0) > 0 for h in FOCUS}
    out["R1"] = {
        "name": "엄격 · 주체=V8 — 두 지평 top-quintile gap CI90 하한 > 0",
        "by_horizon": r1_h,
        "ci90_lower": {f"h{h}": lower(horizons[f"h{h}"]["v8_top_gap_ci90"]) for h in FOCUS},
        "pass": bool(all(r1_h.values())),
    }

    # ---- R2: 엄격 · 주체 = 표적 구조(반사 기준선) (S2-2 가 담지자 식별)
    r2_h = {f"h{h}": (lower(horizons[f"h{h}"]["reflection_top_gap_ci90"]) or -1.0) > 0
            for h in FOCUS}
    out["R2"] = {
        "name": "엄격 · 주체=표적 구조(반사 기준선) — 두 지평 top-quintile gap CI90 하한 > 0",
        "by_horizon": r2_h,
        "ci90_lower": {f"h{h}": lower(horizons[f"h{h}"]["reflection_top_gap_ci90"]) for h in FOCUS},
        "pass": bool(all(r2_h.values())),
    }

    # ---- R3: 보강 — 로짓 기울기 CI90 상한 < 1 (판정 미포함)
    r3 = {}
    for h in FOCUS:
        hh = horizons[f"h{h}"]
        r3[f"h{h}"] = {
            "v8_slope": hh["v8_slope"],
            "v8_slope_ci90_upper": upper(hh["v8_slope_ci90"]),
            "v8_upper_below_1": bool((upper(hh["v8_slope_ci90"]) or 9.0) < 1.0),
            "reflection_slope": hh["reflection_slope"],
            "reflection_slope_ci90_upper": upper(hh["reflection_slope_ci90"]),
            "reflection_upper_below_1": bool((upper(hh["reflection_slope_ci90"]) or 9.0) < 1.0),
        }
    out["R3"] = {
        "name": "보강(판정 미포함) · 로짓 기울기 CI90 상한 < 1",
        "by_horizon": r3,
        "pass": bool(all(v["v8_upper_below_1"] and v["reflection_upper_below_1"]
                         for v in r3.values())),
    }
    return out


# --------------------------------------------------------------------------- 검정력 사실

def split_power(s22: dict[str, Any]) -> dict[str, Any]:
    """S3-0 에 넘길 분할창 검정력 사실 — 후보 맵을 만들지 않고 분산 규모만 잰다.

    쌍대 대비는 V8 vs 반사 기준선(둘 다 이미 공표된 고정 확률열)이며 T1~T5 어느 가설도 아니다.
    MDE = 1.645·se — S2-2 가 쓴 것과 같은 근사(후보 맵의 se 를 이 대비와 같다고 봄).
    """
    ftd = ft.load_first_touch()
    out: dict[str, Any] = {"split": SPLIT, "convention": "1.645·se, 블록부트 ℓ=13 B=2000 seed 20260902",
                           "note": "후보 맵 미생성 — 분산 규모만. T1~T5 어느 가설도 평가하지 않음."}
    for h in FOCUS:
        rows = ftd["per_horizon"][h]
        dates = np.array(rows["dates"])
        p_v8 = rows["p"]
        y = rows["y"]
        pr = np.asarray(s22["per_horizon"][str(h)]["p_reflect"], dtype=float)
        assert pr.size == y.size, (h, pr.size, y.size)
        early = dates <= SPLIT
        per_window: dict[str, Any] = {}
        for name, mask in (("early_2007_2010", early), ("late_2011_2014", ~early)):
            n = int(mask.sum())
            draws = ft.block_index_draws(n)
            paired = rb.paired_block(p_v8[mask], pr[mask], y[mask], draws)
            boot = np.asarray([float(np.mean((pr[mask][i] - y[mask][i]) ** 2
                                             - (p_v8[mask][i] - y[mask][i]) ** 2))
                               for i in draws])
            se = float(boot.std(ddof=1))
            # 집중도 — 쌍대 차이의 몇 개 원점이 합을 지배하는가 (V10 검토의 상위5% 제거 선례).
            d = (pr[mask] - y[mask]) ** 2 - (p_v8[mask] - y[mask]) ** 2   # 양수 = V8 우수
            order = np.argsort(-np.abs(d))
            k5 = max(1, int(round(0.05 * n)))
            total = float(d.sum())
            brier_v8_w = float(np.mean((p_v8[mask] - y[mask]) ** 2))
            per_window[name] = {
                "n": n,
                "touches": int(y[mask].sum()),
                "base_rate": float(y[mask].mean()),
                "brier_v8": brier_v8_w,
                "paired_v8_minus_reflection": paired["loss_diff"],
                "paired_ci90": paired["ci90"],
                "paired_se": se,
                "mde_1645se": Z90 * se,
                "mde_as_share_of_window_brier": (Z90 * se / brier_v8_w) if brier_v8_w > 0 else None,
                "concentration": {
                    "top5_abs_share_of_sum": (float(np.abs(d[order[:5]]).sum() / np.abs(d).sum())
                                              if np.abs(d).sum() > 0 else None),
                    "top5pct_origins": k5,
                    "mean_after_dropping_top5pct_by_abs": float(np.delete(d, order[:k5]).mean()),
                    "sign_flips_after_drop": bool(
                        np.sign(total) != np.sign(float(np.delete(d, order[:k5]).sum()))),
                },
            }
        out[f"h{h}"] = per_window
    return out


# --------------------------------------------------------------------------- 게이트 산술

def gate_arithmetic(s21: dict[str, Any], s22: dict[str, Any]) -> dict[str, Any]:
    """S2-2 가 산문으로 낸 게이트 문턱을 기계 필드로 재산출한다 (수기 이월 제거).

    문턱 = 기준선을 CI90 하한>0 으로 이기려면 필요한 '기후 대비 BSS'.
      후보 BS < BS_기준선 − 1.645·se(쌍대)  ⇒  BSS_필요 = 1 − 그 값 / BS_기후
    상한 = REL→0 완전보정 시 도달 가능한 BSS (두 binning 모두 산출 — in-sample 추정이라 낙관 편의).
    """
    out: dict[str, Any] = {
        "definition": ("문턱 BSS = 1 − (BS_기준선 − 1.645·se)/BS_기후 — se 를 후보 모델에서도 "
                       "같다고 본 근사(S2-2 규약). 상한 BSS = 1 − (BS_V8 − REL)/BS_기후, "
                       "REL 은 in-sample 추정이라 상한 자체가 낙관 편의."),
    }
    for h in FOCUS:
        ph22 = s22["per_horizon"][str(h)]
        ph21 = s21["per_horizon"][str(h)]
        clim = float(ph22["brier"]["climatology_insample"])
        bs_v8 = float(ph22["brier"]["v8_first_touch"])
        row: dict[str, Any] = {"climatology_brier": clim, "brier_v8": bs_v8,
                               "bss_v8_vs_climatology": float(ph22["skill"]["bss_v8_vs_climatology"])}
        pairs = {
            "reflection_2phi": (ph22["paired"]["v8_vs_reflection"],
                                float(ph22["brier"]["reflection"])),
            "reflection_bgk": (ph22["variants"]["discrete_monitoring_bgk"]["paired_v8_vs_variant"],
                               float(ph22["variants"]["discrete_monitoring_bgk"]["brier"])),
        }
        for label, (pa, bs_base) in pairs.items():
            se = float(pa["ci90"]["bootstrap_se"])
            need_bs = bs_base - Z90 * se
            row[label] = {
                "baseline_brier": bs_base,
                "baseline_bss_vs_climatology": 1.0 - bs_base / clim,
                "paired_se": se,
                "mde_1645se": Z90 * se,
                "required_candidate_brier": need_bs,
                "required_bss_vs_climatology": 1.0 - need_bs / clim,
            }
        ceilings = {}
        for binning in ("murphy_fixed_bins", "murphy_quantile_bins"):
            rel = float(ph21[binning]["reliability"])
            ceilings[binning] = {"reliability": rel,
                                 "bss_if_rel_zero": 1.0 - (bs_v8 - rel) / clim}
        row["perfect_recalibration_ceiling"] = ceilings
        row["ceiling_max_bss"] = max(c["bss_if_rel_zero"] for c in ceilings.values())
        out[f"h{h}"] = row
    return out


# --------------------------------------------------------------------------- 판정

def decide(rules: dict[str, Any], power: dict[str, Any],
           s22: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    entry = bool(rules["R0"]["pass"] and rules["R2"]["pass"])
    # S3-0 으로 넘기는 사전 제약. 결과가 아니라 이미 확정된 사실에서만 유도한다.
    constraints = []
    for h in FOCUS:
        late = power[f"h{h}"]["late_2011_2014"]
        early = power[f"h{h}"]["early_2007_2010"]
        constraints.append({
            "id": f"K-power-h{h}",
            "fact": (f"전반창 터치 {early['touches']}/{early['n']} · 후반창 터치 "
                     f"{late['touches']}/{late['n']}. 쌍대 손실차 MDE(1.645·se) = "
                     f"전반 {early['mde_1645se']:.6f}({early['mde_as_share_of_window_brier']:.1%} of BS) · "
                     f"후반 {late['mde_1645se']:.6f}({late['mde_as_share_of_window_brier']:.1%} of BS). "
                     f"후반창 손실차 절대합의 상위 5 원점 비중 "
                     f"{late['concentration']['top5_abs_share_of_sum']:.1%}."),
            "prescription": ("S3 보고 시 지평별로 이 MDE 를 병기한다. MDE 미만의 개선은 방향과 "
                             "무관하게 '결정적 증거 없음'. 후반창 결과는 집중도(상위5% 제거 후 부호)를 "
                             "반드시 함께 낸다 — 소수 원점이 부호를 만드는지 확인 없이 채택 금지."),
        })
    constraints.append({
        "id": "K-split-contrast",
        "fact": ("본 태스크가 새로 낸 분할창 대비(V8 vs 반사 기준선)는 후반창에서 두 지평 모두 "
                 f"CI90 하한>0 이다 — h21 {power['h21']['late_2011_2014']['paired_v8_minus_reflection']:+.6f} "
                 f"CI90 하한 {power['h21']['late_2011_2014']['paired_ci90']['ci90_lower']:+.2e}, "
                 f"h63 {power['h63']['late_2011_2014']['paired_v8_minus_reflection']:+.6f} "
                 f"CI90 하한 {power['h63']['late_2011_2014']['paired_ci90']['ci90_lower']:+.6f}. "
                 "전반창은 두 지평 모두 0 을 걸친다."),
        "prescription": ("이것은 사전등록 검정이 아니라 S2-2 공표 뒤의 부분표본 분할이며 "
                         "다중검정 보정도 없다. 'V8 이 기준선을 이긴다' 는 주장의 근거로 인용 금지 — "
                         "풀표본 판정(두 지평 모두 0 포함)이 정본이다. S3-0 은 이 대비를 가설로 "
                         "승격시키지 않는다."),
    })
    # T3 사전 통지 — S2-2 가 이미 시점을 못박아 공개한 사실
    t3_cells = []
    for h in FOCUS:
        rows = {r["regime"]: r for r in s22["regimes"][str(h)] if "regime" in r}
        for reg in ("non_gfc", "calm_p80"):
            r = rows.get(reg)
            if r is None:
                continue
            rf = float(r["top_quintile_gap"]["reflection"])
            v8 = float(r["top_quintile_gap"]["v8"])
            if rf > v8:
                t3_cells.append({"horizon": h, "regime": reg,
                                 "reflection_top_gap": rf, "v8_top_gap": v8})
    constraints.append({
        "id": "K-T3",
        "fact": (f"반사 앵커가 V8 보다 더 과신한 국면 셀 {len(t3_cells)}개 "
                 + ", ".join(f"h{c['horizon']}/{c['regime']}(+{c['reflection_top_gap']:.4f} vs "
                             f"+{c['v8_top_gap']:.4f})" for c in t3_cells)),
        "prescription": ("T3 는 설계도 §2 원문 그대로 등록하되 '사전 기대' 를 "
                         "'비GFC·calm 에서 w>0 은 악화 방향' 으로 정정 기록한다. 가설 삭제 금지 — "
                         "실패도 원장에 남긴다."),
    })
    constraints.append({
        "id": "K-baseline",
        "fact": ("S3 채택 기준(설계도 §2)은 'p′ 가 p 를 양방향으로 개선' 이며 기준선 대비가 아니다. "
                 "S2-2 는 V8 이 자유 파라미터 0 개 기준선을 두 지평 어디서도 엄밀히 이기지 못함을 확정했다."),
        "prescription": ("1차 채택 기준은 §2 원문 불변. 그 위에 2차 기준 "
                         "'p′ vs p_reflect 쌍대 CI90 하한 > 0' 을 S3-0 에 **추가** 등록한다 — "
                         "강화 방향이므로 사후 완화가 아니다. S3 통과·2차 미달은 그대로 공표."),
    })
    constraints.append({
        "id": "K-gate-arith",
        "fact": ("게이트 산술(본 태스크 재산출): 현 표본에서 기준선을 CI90 하한>0 으로 이기려면 "
                 "기후 대비 BSS 가 "
                 f"h21 ≥ {gate['h21']['reflection_2phi']['required_bss_vs_climatology']:+.2%}"
                 f"(BGK 판 ≥ {gate['h21']['reflection_bgk']['required_bss_vs_climatology']:+.2%}), "
                 f"h63 ≥ {gate['h63']['reflection_2phi']['required_bss_vs_climatology']:+.2%}"
                 f"(BGK 판 ≥ {gate['h63']['reflection_bgk']['required_bss_vs_climatology']:+.2%}). "
                 f"완전보정 상한은 h21 {gate['h21']['ceiling_max_bss']:+.2%}·"
                 f"h63 {gate['h63']['ceiling_max_bss']:+.2%} — h21 은 BGK 문턱 미달, h63 은 간발 통과."),
        "prescription": ("S3 가 통과해도 S4 게이트 미달일 수 있음을 지금 못박는다. "
                         "S4-2 에서 이 문턱을 낮추는 방향의 기준선 선택(원식·λ=0.99)은 "
                         "사후 완화이며 근거 명문화 없이는 금지."),
    })

    return {
        "adoption_rule": ADOPTION,
        "entry": entry,
        "decision": "진입" if entry else "중단",
        "R0_pass": rules["R0"]["pass"],
        "R1_pass": rules["R1"]["pass"],
        "R2_pass": rules["R2"]["pass"],
        "R3_pass": rules["R3"]["pass"],
        "published_readings": {
            "R0": rules["R0"]["name"], "R1": rules["R1"]["name"],
            "R2": rules["R2"]["name"], "R3": rules["R3"]["name"],
        },
        "dissent": ("R1(주체=V8) 은 h21 에서 미달한다 — CI90 하한 "
                    f"{rules['R1']['ci90_lower']['h21']:+.6f}. 진입은 '표적의 과신 구조가 확립됐다' 는 "
                    "뜻이지 'V8 의 과신이 확립됐다' 는 뜻이 아니다."),
        "prereg_constraints": constraints,
        "next": "S3-0",
    }


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/timeseries_v12/diagnostics/s2_entry_verdict.json")
    args = ap.parse_args()

    s21, s22 = load_json(S2_1_JSON), load_json(S2_2_JSON)
    rules = evaluate_rules(s21, s22)
    power = split_power(s22)
    gate = gate_arithmetic(s21, s22)
    verdict = decide(rules, power, s22, gate)

    payload = {
        "schema": "v12_s2_entry_verdict_v1",
        "task_id": "S2-3",
        "generated_by": "tools/v12_s2_verdict.py",
        "inputs": {
            S2_1_JSON: ft._sha256(ROOT / S2_1_JSON),
            S2_2_JSON: ft._sha256(ROOT / S2_2_JSON),
        },
        "design_condition": "설계도 §1 S2 통과 조건 — '과신 구조가 두 지평·국면 초월로 재현되면 S3 진입'",
        "rules": rules,
        "split_power": power,
        "gate_arithmetic": gate,
        "verdict": verdict,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  R0 {rules['R0']['pass']}  R1 {rules['R1']['pass']}  "
          f"R2 {rules['R2']['pass']}  R3 {rules['R3']['pass']}")
    print(f"  DECISION = {verdict['decision']}")


if __name__ == "__main__":
    main()
