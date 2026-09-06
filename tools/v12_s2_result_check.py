#!/usr/bin/env python
"""tools/v12_s2_result_check.py — S2-3 result JSON 을 산출물과 자동 대사 (읽기 전용).

result JSON 의 headline·verdict·artifacts·inputs 를 s2_entry_verdict.json 과 실제 파일
해시에 대사한다. 수기로 옮겨 적은 값이 하나라도 어긋나면 종료코드 1.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULT = "outputs/timeseries_v12/loop/results/S2-3.json"
V = "data/timeseries_v12/diagnostics/s2_entry_verdict.json"
TOL = 1e-12


def sha256(rel: str) -> str:
    h = hashlib.sha256()
    with (ROOT / rel).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    res = json.loads((ROOT / RESULT).read_text(encoding="utf-8"))
    v = json.loads((ROOT / V).read_text(encoding="utf-8"))
    fails: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
        if not ok:
            fails.append(name)

    def num(name: str, got: Any, want: Any, tol: float = TOL) -> None:
        check(name, abs(float(got) - float(want)) < tol, f"{got} vs {want}")

    # ---- artifacts 해시 (result JSON 자신은 제외 — 순환)
    for rel, want in res["artifacts"].items():
        check(f"artifact {rel}", sha256(rel) == want, want[:12] + "…")
    for rel, want in res["inputs"].items():
        if rel == "note":
            continue
        check(f"input {rel}", sha256(rel) == want, want[:12] + "…")

    # ---- verdict / headline
    hl, rules, power, gate = res["headline"], v["rules"], v["split_power"], v["gate_arithmetic"]
    check("decision", res["verdict"]["decision"] == v["verdict"]["decision"],
          res["verdict"]["decision"])
    check("accept decision", res["accept_check"]["decision"] == v["verdict"]["decision"], "")
    for key, rid in (("R0_pass", "R0"), ("R1_pass", "R1"), ("R2_pass", "R2"), ("R3_pass", "R3")):
        check(f"verdict {key}", res["verdict"][key] == rules[rid]["pass"],
              str(rules[rid]["pass"]))
    check("headline R0", hl["R0_design_literal_prereg"]["pass"] == rules["R0"]["pass"], "")
    check("headline R0 cells",
          hl["R0_design_literal_prereg"]["regime_cells_both_positive"]
          == rules["R0"]["cells_both_positive"], rules["R0"]["cells_both_positive"])
    for rid, hkey in (("R1", "R1_strict_subject_v8"), ("R2", "R2_strict_subject_target_structure")):
        for h in ("h21", "h63"):
            num(f"headline {rid} {h}", hl[hkey]["ci90_lower"][h], rules[rid]["ci90_lower"][h])
    for h in ("h21", "h63"):
        r3 = rules["R3"]["by_horizon"][h]
        num(f"headline R3 {h} v8", hl["R3_slope_supporting_only"][f"ci90_upper_{h}"]["v8"],
            r3["v8_slope_ci90_upper"])
        num(f"headline R3 {h} reflection",
            hl["R3_slope_supporting_only"][f"ci90_upper_{h}"]["reflection"],
            r3["reflection_slope_ci90_upper"])
    for k, want in rules["regime_cell_summary"].items():
        if k == "note":
            continue
        check(f"headline cells {k}", hl["regime_cell_summary"][k] == want, str(want))

    # ---- split power
    pairs = {"h21_early": ("h21", "early_2007_2010"), "h21_late": ("h21", "late_2011_2014"),
             "h63_early": ("h63", "early_2007_2010"), "h63_late": ("h63", "late_2011_2014")}
    for hk, (h, w) in pairs.items():
        src, got = power[h][w], hl["split_power"][hk]
        check(f"power {hk} n/touches", got["n"] == src["n"] and got["touches"] == src["touches"],
              f"{src['n']}/{src['touches']}")
        num(f"power {hk} Δ", got["paired_v8_minus_reflection"], src["paired_v8_minus_reflection"])
        num(f"power {hk} mde", got["mde_1645se"], src["mde_1645se"])
        num(f"power {hk} mde/BS", got["mde_share_of_brier"], src["mde_as_share_of_window_brier"],
            5e-6)
        num(f"power {hk} top5", got["top5_abs_share"], src["concentration"]["top5_abs_share_of_sum"],
            5e-4)
        check(f"power {hk} flip",
              got["sign_flips_after_top5pct_drop"] == src["concentration"]["sign_flips_after_drop"],
              str(src["concentration"]["sign_flips_after_drop"]))
        if "ci90_lower" in got:
            num(f"power {hk} ci90_lower", got["ci90_lower"], src["paired_ci90"]["ci90_lower"])

    # ---- gate arithmetic
    ga = hl["gate_arithmetic"]
    for h in ("h21", "h63"):
        num(f"gate {h} 2phi", ga[f"required_bss_{h}_2phi"],
            gate[h]["reflection_2phi"]["required_bss_vs_climatology"])
        num(f"gate {h} bgk", ga[f"required_bss_{h}_bgk"],
            gate[h]["reflection_bgk"]["required_bss_vs_climatology"])
        num(f"gate {h} ceiling", ga[f"perfect_recalibration_ceiling_{h}"], gate[h]["ceiling_max_bss"])

    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
