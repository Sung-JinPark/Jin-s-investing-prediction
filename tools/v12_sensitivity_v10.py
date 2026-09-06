#!/usr/bin/env python
"""tools/v12_sensitivity_v10.py — S1-2 공통 방법론 민감도 (읽기 전용).

백테스트·홀드아웃·봉인 실행 0. 커밋된 run/ledger/diagnostic 아티팩트만 읽는다.
쓰기는 ``--out`` 한 파일뿐(기본 ``docs/review/v10_sensitivity_grid.json``).

목적 (envelope S1-2 spec)
-------------------------
V10 챔피언(``V10_W3_gamma_m010`` vs ``V10_E0_identity``) 의 쌍대 CI·동결 판정이
**공통 방법론 손잡이 3개**에 얼마나 민감한지 표로 만든다.

  축 A. 블록 부트스트랩 평균 블록길이 ℓ ∈ {5, 13, 26}      (정본 ℓ=13)
  축 B. 위기창 경계 각각 ±1y (3×3 격자 중 start<end 인 8칸) (정본 [2008-01-01, 2009-06-30])
  축 C. calm 백분위 ∈ {60, 80, 90} — calm = V10 primary(EWMA97 분산비) ≤ pXX
        (정본 = V11 렌즈 규약 p80. 위기 = 상위 (100−pXX)%)

축 B와 축 C는 "무엇을 위기로 볼 것인가"의 **두 가지 정의 계열**이다(날짜창 vs 상태분위).
축 A는 그 위에 곱해진다 → 판정 셀 = 3 × (8 + 3) = 33.

판정 규칙 (S1-1 에서 쓴 규칙을 그대로 승계 — 사후 신설 없음)
------------------------------------------------------------
    유지 = (상위 5% 원점 제거 시 쌍대 평균 부호 반전) AND (위기 제외 평균 Δ < mde50)
    번복 = 그 외
mde50 = 1.645 · se_bootstrap 이므로 ℓ에 의존하고, "위기 제외 평균"은 축 B/C에 의존한다.
즉 세 손잡이 전부가 판정식에 실제로 들어간다.

방법 정본 (S1-1 과 동일 구현 재사용 — tools/v12_recompute_verdict.py 에서 import)
--------------------------------------------------------------------------------
* 쌍대 통계 d_i = mean_{h∈{21,63}}( crps_E0(i,h) − crps_champ(i,h) ), 양수 = 개선
  (``src/ai_fc/timeseries_v10/pipeline.py::_dual_vs_e0``).
* CI90 = 정상 블록 부트스트랩(기하분포 평균길이 ℓ, B=2000, seed 20260902), percentile[5,95].
* primary = ``data/timeseries_v11/diagnostics/aligned_origin_frame.json`` 의 origin별 값.
  V11 동결문서 §정의: "위기 상태 프록시 = V10 primary(EWMA97 분산비)".

caveat: 부분표본(calm·trimmed) 부트스트랩은 시간축이 비연속이 된 표본에 블록을 적용한다
(S1-1 상위5% 제거와 동일 취급). 블록 구조가 원계열보다 약해지므로 se 는 과소추정 쪽 편향
가능 — 이 문서의 모든 부분표본 CI 에 동일하게 해당한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import numpy as np

# 래퍼(tools/v12_run.py)는 runpy.run_path 로 실행하므로 tools/ 가 sys.path 에 없다 — 직접 넣는다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v12_recompute_verdict import (  # noqa: E402 — sys.path 주입 뒤에 와야 한다
    DUAL_SEED,
    GFC_CANONICAL,
    _experiment_id,
    _ledger,
    _load_run,
    dual_ci90,
    mean_long_crps,
    per_origin_delta,
)

ROOT = Path(__file__).resolve().parents[1]

BLOCK_LENGTHS = (5, 13, 26)
CANONICAL_BLOCK = 13
CALM_PCTS = (60.0, 80.0, 90.0)
CANONICAL_CALM = 80.0
BOUNDARY_OFFSETS_YEARS = (-1, 0, 1)
TOP_TAIL_FRACTION = 0.05

CHAMPION = "V10_W3_gamma_m010"
BASELINE = "V10_E0_identity"


# --------------------------------------------------------------------------- 입력

def _shift_year(iso: str, years: int) -> str:
    d = date.fromisoformat(iso)
    return d.replace(year=d.year + years).isoformat()


def _primary_by_date() -> dict[str, Any]:
    """origin date → V10 primary. h21·h63 계열을 합치고 불일치를 계측해 함께 보고한다."""
    frame = json.loads(
        (ROOT / "data/timeseries_v11/diagnostics/aligned_origin_frame.json").read_text(encoding="utf-8")
    )
    merged: dict[str, float] = {}
    per_h: dict[str, dict[str, float]] = {}
    for horizon, payload in frame["horizons"].items():
        per_h[horizon] = {d: float(v) for d, v in zip(payload["date"], payload["primary"])}
    for horizon in sorted(per_h, key=int):
        for d, v in per_h[horizon].items():
            merged.setdefault(d, v)
    horizons = sorted(per_h, key=int)
    diffs = []
    if len(horizons) >= 2:
        a, b = per_h[horizons[0]], per_h[horizons[-1]]
        diffs = [abs(a[d] - b[d]) for d in set(a) & set(b)]
    return {
        "map": merged,
        "frame_design_window": frame.get("design"),
        "frame_calm_pct": frame.get("calm_pct"),
        "per_horizon_counts": {h: len(per_h[h]) for h in horizons},
        "cross_horizon_common_dates": len(diffs),
        "cross_horizon_max_abs_diff": (max(diffs) if diffs else None),
    }


# --------------------------------------------------------------------------- 축 A

def _tail_trim(deltas: np.ndarray) -> tuple[np.ndarray, int, float]:
    """상위 5% 원점 제거 표본 + 제거된 원점 수 + 제거분 Δ 합 (S1-1 과 동일 절차)."""
    n = len(deltas)
    drop = int(np.ceil(TOP_TAIL_FRACTION * n))
    order = np.argsort(deltas)
    keep = np.sort(order[: n - drop])
    top_sum = float(deltas[order[n - drop:]].sum())
    return deltas[keep], drop, top_sum


def block_axis(deltas: np.ndarray, denom: float) -> dict[str, dict[str, Any]]:
    """ℓ 별 전표본 CI90·se·mde50 과 상위5% 제거 표본 CI90."""
    trimmed, drop, top_sum = _tail_trim(deltas)
    out: dict[str, dict[str, Any]] = {}
    for block in BLOCK_LENGTHS:
        full = dual_ci90(deltas, block=block, seed=DUAL_SEED)
        trim = dual_ci90(trimmed, block=block, seed=DUAL_SEED)
        out[str(block)] = {
            "block_length": block,
            "is_canonical": block == CANONICAL_BLOCK,
            "mean_delta": float(deltas.mean()),
            "relative_improvement": float(deltas.mean()) / denom,
            "ci90": [full["ci90_lower"], full["ci90_upper"]],
            "ci90_lower_positive": full["ci90_lower"] > 0,
            "bootstrap_se": full["bootstrap_se"],
            "mde50": full["mde50"],
            "trimmed": {
                "origins_dropped": drop,
                "top5pct_delta_sum": top_sum,
                "mean_after_removal": float(trimmed.mean()),
                "sign_after_removal": "negative" if trimmed.mean() < 0 else "positive",
                "sign_flips": bool(trimmed.mean() < 0),
                "ci90": [trim["ci90_lower"], trim["ci90_upper"]],
                "ci90_upper_negative": trim["ci90_upper"] < 0,
            },
        }
    return out


# --------------------------------------------------------------------------- 축 B·C

def _regime_stats(origins: Sequence[str], deltas: np.ndarray, crisis_mask: np.ndarray,
                  denom: float) -> dict[str, Any]:
    """위기/평온 분할의 원점 수·Δ 견인 비중·평온 평균과 그 ℓ별 CI90."""
    total = float(deltas.sum())
    calm = deltas[~crisis_mask]
    crisis = deltas[crisis_mask]
    calm_ci = {
        str(block): dual_ci90(calm, block=block, seed=DUAL_SEED) if calm.size > 1 else None
        for block in BLOCK_LENGTHS
    }
    return {
        "crisis_origins": int(crisis_mask.sum()),
        "calm_origins": int((~crisis_mask).sum()),
        "crisis_origin_share": float(crisis_mask.mean()),
        "crisis_delta_sum": float(crisis.sum()),
        "crisis_delta_share": (float(crisis.sum()) / total) if total else None,
        "calm_mean_delta": float(calm.mean()) if calm.size else None,
        "calm_relative_improvement": (float(calm.mean()) / denom) if calm.size else None,
        "crisis_mean_delta": float(crisis.mean()) if crisis.size else None,
        "calm_ci90_by_block": {
            b: ([v["ci90_lower"], v["ci90_upper"]] if v else None) for b, v in calm_ci.items()
        },
        "calm_ci90_lower_positive_by_block": {
            b: (bool(v["ci90_lower"] > 0) if v else None) for b, v in calm_ci.items()
        },
    }


def window_axis(origins: Sequence[str], deltas: np.ndarray, denom: float) -> list[dict[str, Any]]:
    """축 B — 위기창 경계 각각 ±1y (start<end 인 조합만)."""
    rows: list[dict[str, Any]] = []
    for s_off in BOUNDARY_OFFSETS_YEARS:
        for e_off in BOUNDARY_OFFSETS_YEARS:
            start = _shift_year(GFC_CANONICAL[0], s_off)
            end = _shift_year(GFC_CANONICAL[1], e_off)
            if start >= end:
                rows.append({"definition": "date_window", "start": start, "end": end,
                             "start_offset_years": s_off, "end_offset_years": e_off,
                             "skipped": "start >= end"})
                continue
            mask = np.array([start <= o <= end for o in origins])
            row = {
                "definition": "date_window",
                "cell_id": f"win[{s_off:+d}y,{e_off:+d}y]",
                "start": start, "end": end,
                "start_offset_years": s_off, "end_offset_years": e_off,
                "is_canonical": (s_off == 0 and e_off == 0),
            }
            row.update(_regime_stats(origins, deltas, mask, denom))
            rows.append(row)
    return rows


def localization(origins: Sequence[str], deltas: np.ndarray) -> dict[str, Any]:
    """축 B 격자가 함의하는 분해 — 정본창을 ±1y 경계가 만드는 3조각으로 쪼갠 Δ 견인 비중.

    [start, start+6m] ∪ (start+6m, end−6m] ∪ (end−6m, end] = 정본창 (서로소·완비)이므로
    새 가설이 아니라 격자의 항등식이다. 손계산(83.8 − 0.2 − 2.7)을 대신한다.
    """
    total = float(deltas.sum())
    pieces = [
        ("2008H1", "2008-01-01", "2008-06-30"),
        ("2008H2", "2008-07-01", "2008-12-31"),
        ("2009H1", "2009-01-01", "2009-06-30"),
    ]
    rows = []
    for name, start, end in pieces:
        mask = np.array([start <= o <= end for o in origins])
        rows.append({
            "piece": name, "start": start, "end": end,
            "origins": int(mask.sum()),
            "origin_share": float(mask.mean()),
            "delta_sum": float(deltas[mask].sum()),
            "delta_share": (float(deltas[mask].sum()) / total) if total else None,
            "mean_delta": float(deltas[mask].mean()) if mask.any() else None,
        })
    outside = np.array([not (GFC_CANONICAL[0] <= o <= GFC_CANONICAL[1]) for o in origins])
    return {
        "pieces": rows,
        "outside_canonical": {
            "origins": int(outside.sum()),
            "origin_share": float(outside.mean()),
            "delta_share": (float(deltas[outside].sum()) / total) if total else None,
        },
        "max_piece": max(rows, key=lambda r: r["delta_share"] or 0.0)["piece"],
    }


def calm_axis(origins: Sequence[str], deltas: np.ndarray, denom: float,
              primary: dict[str, Any]) -> dict[str, Any]:
    """축 C — calm = primary ≤ pXX. primary 결측 원점은 제외하고 결측률을 보고한다."""
    pmap = primary["map"]
    matched = np.array([o in pmap for o in origins])
    values = np.array([pmap[o] for o in origins if o in pmap], dtype=float)
    sub_deltas = deltas[matched]
    sub_origins = [o for o in origins if o in pmap]

    rows: list[dict[str, Any]] = []
    for pct in CALM_PCTS:
        threshold = float(np.percentile(values, pct))
        crisis_mask = values > threshold
        row = {
            "definition": "state_percentile",
            "cell_id": f"calm p{int(pct)}",
            "calm_pct": pct,
            "is_canonical": pct == CANONICAL_CALM,
            "primary_threshold": threshold,
            # primary 에 질량점이 있으면 '≤ 임계' 가 목표 백분위보다 많은 origin 을 남긴다.
            "ties_at_threshold": int((values == threshold).sum()),
            "nominal_calm_share": pct / 100.0,
            "effective_calm_share": float((values <= threshold).mean()),
        }
        row.update(_regime_stats(sub_origins, sub_deltas, crisis_mask, denom))
        rows.append(row)

    unique, counts = np.unique(values, return_counts=True)
    mass_i = int(np.argmax(counts))
    return {
        "coverage": {
            "v10_origins": len(origins),
            "primary_min": float(values.min()),
            "primary_max": float(values.max()),
            "primary_largest_mass_point": {"value": float(unique[mass_i]),
                                           "count": int(counts[mass_i]),
                                           "share": float(counts[mass_i] / values.size)},
            "primary_matched": int(matched.sum()),
            "primary_missing": int((~matched).sum()),
            "matched_share": float(matched.mean()),
            "matched_mean_delta": float(sub_deltas.mean()) if sub_deltas.size else None,
            "unmatched_dates_sample": [o for o in origins if o not in pmap][:10],
            "frame_design_window": primary["frame_design_window"],
            "frame_calm_pct": primary["frame_calm_pct"],
            "per_horizon_counts": primary["per_horizon_counts"],
            "cross_horizon_max_abs_diff": primary["cross_horizon_max_abs_diff"],
        },
        "rows": rows,
    }


# --------------------------------------------------------------------------- 판정 격자

def verdict_grid(blocks: dict[str, dict[str, Any]],
                 regime_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """유지/번복 = (부호반전) AND (위기 제외 평균 < mde50). S1-1 규칙 그대로."""
    cells: list[dict[str, Any]] = []
    for block in BLOCK_LENGTHS:
        b = blocks[str(block)]
        flips = bool(b["trimmed"]["sign_flips"])
        mde50 = b["mde50"]
        for row in regime_rows:
            if row.get("skipped") or row.get("calm_mean_delta") is None:
                continue
            calm_mean = row["calm_mean_delta"]
            below = bool(calm_mean < mde50)
            cells.append({
                "block_length": block,
                "regime_definition": row["definition"],
                "cell_id": row["cell_id"],
                "is_canonical_cell": bool(b["is_canonical"] and row.get("is_canonical")),
                "calm_mean_delta": calm_mean,
                "mde50": mde50,
                "calm_mean_over_mde50": calm_mean / mde50 if mde50 else None,
                "calm_mean_below_mde50": below,
                "sign_flips_on_top5pct_removal": flips,
                "full_ci90_lower_positive": bool(b["ci90_lower_positive"]),
                "crisis_delta_share": row["crisis_delta_share"],
                "calm_ci90_lower_positive": row["calm_ci90_lower_positive_by_block"][str(block)],
                "verdict": "유지" if (flips and below) else "번복",
            })
    return cells


# --------------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description="S1-2 공통 방법론 민감도 (읽기 전용)")
    parser.add_argument("--out", default="docs/review/v10_sensitivity_grid.json")
    args = parser.parse_args()

    e0 = _load_run("v10", _experiment_id("v10", BASELINE))
    champ = _load_run("v10", _experiment_id("v10", CHAMPION))
    origins, deltas = per_origin_delta(e0, champ)
    denom = mean_long_crps(e0)

    primary = _primary_by_date()
    blocks = block_axis(deltas, denom)
    windows = window_axis(origins, deltas, denom)
    calm = calm_axis(origins, deltas, denom, primary)

    regime_rows = [r for r in windows if not r.get("skipped")] + calm["rows"]
    grid = verdict_grid(blocks, regime_rows)

    verdicts = sorted({c["verdict"] for c in grid})
    overturn_cells = [c for c in grid if c["verdict"] == "번복"]
    canonical = next((c for c in grid if c["is_canonical_cell"]), None)

    payload: dict[str, Any] = {
        "schema": "v12_v10_sensitivity_v1",
        "task": "S1-2",
        "read_only": True,
        "champion": CHAMPION,
        "baseline": BASELINE,
        "origin_count": len(origins),
        "origin_range": [origins[0], origins[-1]],
        "paired_mean_delta": float(deltas.mean()),
        "e0_mean_long_crps": denom,
        "relative_improvement": float(deltas.mean()) / denom,
        "ledger_recorded_dual_vs_e0": next(
            (r.get("dual_vs_e0") for r in _ledger("v10") if r.get("experiment_label") == CHAMPION), None),
        "axes": {
            "block_lengths": list(BLOCK_LENGTHS),
            "boundary_offsets_years": list(BOUNDARY_OFFSETS_YEARS),
            "calm_pcts": list(CALM_PCTS),
            "canonical": {"block_length": CANONICAL_BLOCK,
                          "window": list(GFC_CANONICAL), "calm_pct": CANONICAL_CALM},
        },
        "verdict_rule": "유지 = 상위5% 원점 제거 시 부호반전 AND 위기 제외 평균 Δ < mde50 (S1-1 승계)",
        "axis_a_block_length": blocks,
        "axis_b_date_window": windows,
        "axis_b_localization": localization(origins, deltas),
        "axis_c_calm_percentile": calm,
        "verdict_grid": grid,
        "summary": {
            "cells": len(grid),
            "distinct_verdicts": verdicts,
            "conclusion_changes": bool(len(verdicts) > 1),
            "overturn_cells": [c["cell_id"] + f" | ℓ={c['block_length']}" for c in overturn_cells],
            "canonical_cell_verdict": canonical["verdict"] if canonical else None,
            "sign_flip_all_blocks": all(blocks[str(b)]["trimmed"]["sign_flips"] for b in BLOCK_LENGTHS),
            "full_ci90_lower_positive_all_blocks": all(
                blocks[str(b)]["ci90_lower_positive"] for b in BLOCK_LENGTHS),
            "calm_ci90_lower_positive_cells": [
                f"{c['cell_id']} | ℓ={c['block_length']}" for c in grid
                if c["calm_ci90_lower_positive"]],
            "calm_mean_over_mde50_max": max(
                (c["calm_mean_over_mde50"] for c in grid
                 if c["calm_mean_over_mde50"] is not None), default=None),
            "crisis_delta_share_range": [
                min(r["crisis_delta_share"] for r in regime_rows),
                max(r["crisis_delta_share"] for r in regime_rows),
            ],
        },
    }

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    s = payload["summary"]
    print(f"  cells={s['cells']} verdicts={s['distinct_verdicts']} "
          f"conclusion_changes={s['conclusion_changes']}")
    print(f"  sign_flip_all_blocks={s['sign_flip_all_blocks']} "
          f"full_ci90_lower_positive_all_blocks={s['full_ci90_lower_positive_all_blocks']}")
    print(f"  calm_mean/mde50 max={s['calm_mean_over_mde50_max']:.4f} "
          f"crisis_delta_share={s['crisis_delta_share_range']}")
    print(f"  primary coverage={calm['coverage']['primary_matched']}/{calm['coverage']['v10_origins']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
