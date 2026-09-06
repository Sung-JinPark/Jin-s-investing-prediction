#!/usr/bin/env python
"""tools/v12_sensitivity_v11.py — S1-2 부속: V11 전이 판정의 ℓ·calm 민감도 (읽기 전용).

S1-1(``verdict_recompute.json``)은 V11 전이를 **ℓ=13·calm p80 고정**으로만 돌렸고,
"블록길이·calm 백분위 민감도는 S1-2 로 이월"을 open_question 에 남겼다. 이 스크립트가 그 이월분이다.
창 경계 ±1y 축은 S1-1 이 이미 3 split(2009/2010/2011-12-31)으로 수행했으므로 같은 3개를 쓴다.

격자 = calm ∈ {60, 80, 90} × ℓ ∈ {5, 13, 26} × (지평 2 × 경계 3 × 변형 2) 양방향.
판정 규칙은 S1-1 승계: **번복 = 양방향 CI90 하한 > 0 인 조합 ≥1 AND 순열 귀무 p ≤ 0.05**.
AND 이므로 채택 조합이 0이면 p 와 무관하게 유지 — 그래서 순열 귀무(1000회)는
**채택 조합 ≥1 인 (calm, ℓ) 셀에서만** 돌린다(계산 낭비 방지, 판정 논리는 동일).

쓰기는 ``--out`` 한 파일뿐(기본 ``docs/review/v11_sensitivity_grid.json``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

# 래퍼(tools/v12_run.py)는 runpy.run_path 로 실행하므로 tools/ 가 sys.path 에 없다 — 직접 넣는다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v12_recompute_verdict import (  # noqa: E402 — sys.path 주입 뒤에 와야 한다
    DUAL_SEED,
    _cell_improvements,
    _v11_calm_rows,
    _v11_null_pass_count,
    dual_ci90,
)

ROOT = Path(__file__).resolve().parents[1]

BLOCK_LENGTHS = (5, 13, 26)
CANONICAL_BLOCK = 13
CALM_PCTS = (60.0, 80.0, 90.0)
CANONICAL_CALM = 80.0
HORIZONS = (21, 63)
BOUNDARIES = ("2009-12-31", "2010-12-31", "2011-12-31")
VARIANTS = ("p1_linear", "low_mom_tertile")
PERM_REPLICATES = 1000
PERM_SEED = 20260904
MIN_SUBWINDOW = 30


def _arrays(horizon: int, calm_pct: float) -> dict[str, Any]:
    rows = _v11_calm_rows(horizon, calm_pct=calm_pct)
    return {
        "date": [str(r["date"]) for r in rows],
        "sigma": np.array([r["sigma"] for r in rows], dtype=float),
        "raw_err": np.array([r["raw_err"] for r in rows], dtype=float),
        "crps": np.array([r["crps"] for r in rows], dtype=float),
        "p1": np.array([r["p1"] for r in rows], dtype=float),
    }


def _split(dates: Sequence[str], boundary: str) -> tuple[np.ndarray, np.ndarray]:
    first = np.array([i for i, d in enumerate(dates) if d <= boundary])
    second = np.array([i for i, d in enumerate(dates) if d > boundary])
    return first, second


def cells_for(calm_pct: float, blocks: Sequence[int]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """한 calm 백분위에서 모든 (지평·경계·변형·방향) 셀을 계산. CI 는 ℓ 별로 병기."""
    arrays_by_h = {h: _arrays(h, calm_pct) for h in HORIZONS}
    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        arrays = arrays_by_h[horizon]
        for boundary in BOUNDARIES:
            first, second = _split(arrays["date"], boundary)
            if min(first.size, second.size) < MIN_SUBWINDOW:
                rows.append({"horizon": horizon, "boundary": boundary, "calm_pct": calm_pct,
                             "skipped": f"sub-window < {MIN_SUBWINDOW} origins",
                             "train_n": int(first.size), "test_n": int(second.size)})
                continue
            for variant in VARIANTS:
                for direction, (train, test) in (("forward", (first, second)),
                                                 ("reverse", (second, first))):
                    d, a, b = _cell_improvements(arrays, train, test, variant)
                    base = float(arrays["crps"][test].mean())
                    row = {
                        "calm_pct": calm_pct, "horizon": horizon, "boundary": boundary,
                        "variant": variant, "direction": direction,
                        "train_n": int(train.size), "test_n": int(test.size),
                        "fit_intercept": a, "fit_slope": b,
                        "crps_base": base,
                        "improvement_mean": float(d.mean()),
                        "improved": bool(d.mean() > 0),
                        "crps_relative_change": -float(d.mean()) / base if base else None,
                        "ci90_by_block": {}, "ci90_lower_positive_by_block": {},
                    }
                    for block in blocks:
                        ci = dual_ci90(d, block=block, seed=DUAL_SEED)
                        row["ci90_by_block"][str(block)] = [ci["ci90_lower"], ci["ci90_upper"]]
                        row["ci90_lower_positive_by_block"][str(block)] = bool(ci["ci90_lower"] > 0)
                    rows.append(row)
    return rows, arrays_by_h


def combo_verdicts(rows: Sequence[dict[str, Any]], calm_pct: float,
                   block: int) -> dict[str, Any]:
    """(calm, ℓ) 한 셀의 조합 판정 — 양방향 부호개선 / 양방향 CI90 하한>0."""
    live = [r for r in rows if not r.get("skipped")]
    combos = [(h, bd, v) for h in HORIZONS for bd in BOUNDARIES for v in VARIANTS]
    both_sign, both_ci = [], []
    for h, bd, v in combos:
        cells = [r for r in live if r["horizon"] == h and r["boundary"] == bd and r["variant"] == v]
        if len(cells) != 2:
            continue
        if all(c["improved"] for c in cells):
            both_sign.append({"horizon": h, "boundary": bd, "variant": v})
        if all(c["ci90_lower_positive_by_block"][str(block)] for c in cells):
            both_ci.append({"horizon": h, "boundary": bd, "variant": v,
                            "ci90_lowers": [c["ci90_by_block"][str(block)][0] for c in cells]})
    return {
        "calm_pct": calm_pct, "block_length": block,
        "is_canonical_cell": calm_pct == CANONICAL_CALM and block == CANONICAL_BLOCK,
        "cells_live": len(live),
        "cells_improved_by_sign": sum(1 for r in live if r["improved"]),
        "combos_tested": len(combos),
        "both_directions_improved_by_sign": len(both_sign),
        "combos_meeting_adoption_rule": len(both_ci),
        "adopted": both_ci,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="S1-2 부속: V11 ℓ·calm 민감도 (읽기 전용)")
    ap.add_argument("--out", default="docs/review/v11_sensitivity_grid.json")
    args = ap.parse_args()

    per_calm: dict[str, Any] = {}
    verdict_cells: list[dict[str, Any]] = []
    arrays_cache: dict[float, dict[int, dict[str, Any]]] = {}

    for calm_pct in CALM_PCTS:
        rows, arrays_by_h = cells_for(calm_pct, BLOCK_LENGTHS)
        arrays_cache[calm_pct] = arrays_by_h
        per_calm[f"p{int(calm_pct)}"] = {
            "calm_pct": calm_pct,
            "origins_by_horizon": {str(h): len(arrays_by_h[h]["date"]) for h in HORIZONS},
            "rows": rows,
        }
        for block in BLOCK_LENGTHS:
            verdict_cells.append(combo_verdicts(rows, calm_pct, block))

    # 순열 귀무는 채택 조합 ≥1 인 (calm, ℓ) 에서만 (AND 규칙이므로 그 외는 p 무관하게 유지).
    for cell in verdict_cells:
        if cell["combos_meeting_adoption_rule"] == 0:
            cell["permutation_null"] = None
            cell["verdict"] = "유지"
            cell["verdict_reason"] = "채택 조합 0 (AND 규칙 첫 다리 탈락 — 순열 귀무 불필요)"
            continue
        rng = np.random.default_rng(PERM_SEED)
        arrays_by_h = arrays_cache[cell["calm_pct"]]
        observed = cell["both_directions_improved_by_sign"]
        null_counts = [
            _v11_null_pass_count(arrays_by_h, BOUNDARIES, VARIANTS,
                                 {h: rng.permutation(arrays_by_h[h]["p1"]) for h in HORIZONS})
            for _ in range(PERM_REPLICATES)
        ]
        null_arr = np.array(null_counts)
        p = float((null_arr >= observed).mean())
        cell["permutation_null"] = {"replicates": PERM_REPLICATES, "seed": PERM_SEED,
                                    "statistic": "양방향 부호 개선 조합 수",
                                    "observed": observed, "null_mean": float(null_arr.mean()),
                                    "null_p_ge_observed": p}
        cell["verdict"] = "번복" if p <= 0.05 else "유지"
        cell["verdict_reason"] = f"채택 조합 {cell['combos_meeting_adoption_rule']}, 순열 p={p:.3f}"

    verdicts = sorted({c["verdict"] for c in verdict_cells})
    payload = {
        "schema": "v12_v11_sensitivity_v1",
        "task": "S1-2 (부속 — S1-1 이월분)",
        "read_only": True,
        "axes": {"calm_pcts": list(CALM_PCTS), "block_lengths": list(BLOCK_LENGTHS),
                 "boundaries": list(BOUNDARIES), "variants": list(VARIANTS),
                 "canonical": {"calm_pct": CANONICAL_CALM, "block_length": CANONICAL_BLOCK}},
        "verdict_rule": "번복 = 양방향 CI90 하한 > 0 조합 ≥1 AND 순열 귀무 p ≤ 0.05 (S1-1 승계)",
        "per_calm": per_calm,
        "verdict_grid": verdict_cells,
        "summary": {
            "cells": len(verdict_cells),
            "distinct_verdicts": verdicts,
            "conclusion_changes": bool(len(verdicts) > 1),
            "max_combos_meeting_adoption_rule": max(
                c["combos_meeting_adoption_rule"] for c in verdict_cells),
            "max_both_directions_by_sign": max(
                c["both_directions_improved_by_sign"] for c in verdict_cells),
            "canonical_cell_verdict": next(
                (c["verdict"] for c in verdict_cells if c["is_canonical_cell"]), None),
        },
    }

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    s = payload["summary"]
    print(f"  cells={s['cells']} verdicts={s['distinct_verdicts']} "
          f"conclusion_changes={s['conclusion_changes']}")
    print(f"  max_adoption={s['max_combos_meeting_adoption_rule']} "
          f"max_both_sign={s['max_both_directions_by_sign']}")
    for c in verdict_cells:
        print(f"  calm p{int(c['calm_pct'])} ℓ={c['block_length']}: {c['verdict']} "
              f"(부호양방향 {c['both_directions_improved_by_sign']}/12, "
              f"채택 {c['combos_meeting_adoption_rule']}/12)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
