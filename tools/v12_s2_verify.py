#!/usr/bin/env python
"""tools/v12_s2_verify.py — S2-3 판정의 독립 재검 (읽기 전용).

v12_s2_verdict.py 의 산출을 **다른 경로**로 다시 만들어 대사한다. 하나라도 어긋나면 종료코드 1.

V1  R0/R1/R2/R3 부울을 두 원본 JSON 에서 직접 재구성 (판정 스크립트 자료구조 미경유)
V2  분할창 쌍대 손실차 점추정을 부트스트랩 없이 직접 계산해 대사
V3  분해 항등식 — n_early·Δ_early + n_late·Δ_late = n·Δ_full (S2-2 풀표본 값과 대사)
V4  집중도 재계산 (상위5% 제거 후 평균·부호반전) 대사
V5  reflection JSON 의 p_reflect 배열이 보고된 반사 Brier 를 재현하는지
V6  국면 8 셀 부호 카운트를 두 regimes 블록에서 다시 세기
V7  판정 = R0 ∧ R2 가 실제로 산출 JSON 의 entry 와 같은지 (채택 규칙 무결성)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_first_touch_diag as ft   # noqa: E402

V = "data/timeseries_v12/diagnostics/s2_entry_verdict.json"
S21 = "data/timeseries_v12/diagnostics/first_touch_diagnostic.json"
S22 = "data/timeseries_v12/diagnostics/reflection_baseline.json"
SPLIT = "2010-12-31"
TOL = 1e-12


def load(rel: str) -> dict[str, Any]:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def main() -> int:
    v, s21, s22 = load(V), load(S21), load(S22)
    fails: list[str] = []

    def check(name: str, ok: bool, detail: str) -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
        if not ok:
            fails.append(name)

    # ---- V1 네 조작화 재구성
    r0_sign, r1, r2, r3 = True, True, True, True
    for h in (21, 63):
        a = s21["per_horizon"][str(h)]
        b = s22["per_horizon"][str(h)]["reflection_diagnostic"]
        r0_sign &= (a["top_quintile_gap"] > 0) and (b["top_quintile_gap"] > 0)
        r1 &= a["ci90"]["top_quintile_gap"]["ci90_lower"] > 0
        r2 &= b["ci90"]["top_quintile_gap"]["ci90_lower"] > 0
        r3 &= (a["ci90"]["logistic_slope"]["ci90_upper"] < 1.0
               and b["ci90"]["logistic_slope"]["ci90_upper"] < 1.0)
    cells_ok = all(
        c["v8_top_gap"] > 0 and c["reflection_top_gap"] > 0 for c in v["rules"]["regime_cells"])
    got = v["rules"]
    check("V1 R0", bool(r0_sign and cells_ok) == got["R0"]["pass"],
          f"재구성={r0_sign and cells_ok} 산출={got['R0']['pass']}")
    check("V1 R1", r1 == got["R1"]["pass"], f"재구성={r1} 산출={got['R1']['pass']}")
    check("V1 R2", r2 == got["R2"]["pass"], f"재구성={r2} 산출={got['R2']['pass']}")
    check("V1 R3", r3 == got["R3"]["pass"], f"재구성={r3} 산출={got['R3']['pass']}")

    # ---- V2/V3/V4 분할창
    ftd = ft.load_first_touch()
    for h in (21, 63):
        rows = ftd["per_horizon"][h]
        dates = np.array(rows["dates"])
        p_v8, y = rows["p"], rows["y"]
        pr = np.asarray(s22["per_horizon"][str(h)]["p_reflect"], dtype=float)
        d_all = (pr - y) ** 2 - (p_v8 - y) ** 2
        early = dates <= SPLIT
        parts = {"early_2007_2010": early, "late_2011_2014": ~early}
        for name, mask in parts.items():
            got_w = v["split_power"][f"h{h}"][name]
            direct = float(d_all[mask].mean())
            check(f"V2 h{h}/{name} 점추정",
                  abs(direct - got_w["paired_v8_minus_reflection"]) < TOL,
                  f"직접={direct:+.10f} 산출={got_w['paired_v8_minus_reflection']:+.10f}")
            d = d_all[mask]
            order = np.argsort(-np.abs(d))
            k5 = max(1, int(round(0.05 * int(mask.sum()))))
            drop_mean = float(np.delete(d, order[:k5]).mean())
            con = got_w["concentration"]
            check(f"V4 h{h}/{name} 집중도",
                  abs(drop_mean - con["mean_after_dropping_top5pct_by_abs"]) < TOL
                  and con["top5pct_origins"] == k5,
                  f"제거후평균={drop_mean:+.10f} k5={k5}")
        # V3 분해 항등식 + S2-2 풀표본 대사
        ne, nl = int(early.sum()), int((~early).sum())
        de = v["split_power"][f"h{h}"]["early_2007_2010"]["paired_v8_minus_reflection"]
        dl = v["split_power"][f"h{h}"]["late_2011_2014"]["paired_v8_minus_reflection"]
        recomposed = (ne * de + nl * dl) / (ne + nl)
        full = s22["per_horizon"][str(h)]["paired"]["v8_vs_reflection"]["loss_diff"]
        check(f"V3 h{h} 분해 항등식", abs(recomposed - full) < 1e-12,
              f"재조립={recomposed:+.12f} S2-2 풀표본={full:+.12f}")
        # V5 p_reflect → 반사 Brier
        bs = float(np.mean((pr - y) ** 2))
        rep = s22["per_horizon"][str(h)]["brier"]["reflection"]
        check(f"V5 h{h} 반사 Brier", abs(bs - rep) < 1e-12, f"재계산={bs:.12f} 보고={rep:.12f}")

    # ---- V6 국면 셀 카운트
    n_pos = 0
    for h in (21, 63):
        v8_rows = {r["regime"]: r for r in s21["regimes"][str(h)] if "regime" in r}
        rf_rows = {r["regime"]: r for r in s22["regimes"][str(h)] if "regime" in r}
        for reg in ("gfc", "non_gfc", "calm_p80", "storm_p80"):
            if reg in v8_rows and reg in rf_rows:
                n_pos += int(v8_rows[reg]["top_quintile_gap"] > 0
                             and rf_rows[reg]["top_quintile_gap"]["reflection"] > 0)
    summary = v["rules"]["regime_cell_summary"]
    check("V6 셀 카운트", n_pos == summary["both_top_gap_positive"],
          f"재계수={n_pos} 산출={summary['both_top_gap_positive']}/{summary['cells']}")

    # ---- V7 채택 규칙 무결성
    expect = bool(got["R0"]["pass"] and got["R2"]["pass"])
    check("V7 채택 규칙", expect == v["verdict"]["entry"],
          f"R0∧R2={expect} entry={v['verdict']['entry']} 판정={v['verdict']['decision']}")

    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
