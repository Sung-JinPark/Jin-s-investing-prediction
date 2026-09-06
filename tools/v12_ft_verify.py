#!/usr/bin/env python
"""tools/v12_ft_verify.py — S2-1 헤드라인 수치의 독립 재계산 (읽기 전용, stdout 만).

v12_first_touch_diag.py 와 **코드 경로를 공유하지 않고** run JSON 에서 직접 다시 센다.
목적은 계산 버그 검출 하나 — 불일치가 있으면 즉시 드러난다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/timeseries_v8/runs/dev_tsv8-exp-61cee7b7fb7c41399534.json"
DIAG = ROOT / "data/timeseries_v12/diagnostics/first_touch_diagnostic.json"

GFC = ("2008-01-01", "2009-06-30")


def close(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol


def main() -> None:
    run = json.loads(RUN.read_text(encoding="utf-8"))
    diag = json.loads(DIAG.read_text(encoding="utf-8"))
    ok = True

    for h in (21, 63):
        rows = [s for s in run["scores"] if int(s["horizon"]) == h]
        rows.sort(key=lambda s: s["date"])
        p = [float(s["first_touch_probability"]) for s in rows]
        y = [1.0 if s["first_touch_actual"] else 0.0 for s in rows]
        n = len(rows)
        base = sum(y) / n
        bs = sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / n
        clim = base * (1 - base)
        bss = 1 - bs / clim

        # 상위 5분위 = p 내림차순 상위 20% (동점은 값 기준 — diag 의 분위 경계와 같은 집합이어야 한다)
        edge = diag["per_horizon"][str(h)]["quantile_bins"]["edges"][-2]
        top = [(pi, yi) for pi, yi in zip(p, y) if pi >= edge]
        gap = sum(t[0] for t in top) / len(top) - sum(t[1] for t in top) / len(top)

        gfc_rows = [(s, pi, yi) for s, pi, yi in zip(rows, p, y)
                    if GFC[0] <= s["date"] <= GFC[1]]
        gfc_base = sum(t[2] for t in gfc_rows) / len(gfc_rows)

        d = diag["per_horizon"][str(h)]
        checks = [
            ("n", n, d["n"]),
            ("touches", float(sum(y)), float(d["touches"])),
            ("base", base, d["base_rate"]),
            ("brier", bs, d["brier"]),
            ("clim", clim, d["climatology_brier_insample"]),
            ("bss", bss, d["brier_skill_vs_insample_climatology"]),
            ("top_gap", gap, d["top_quintile_gap"]),
            ("gfc_n", float(len(gfc_rows)),
             float([r for r in diag["regimes"][str(h)] if r["regime"] == "gfc"][0]["n"])),
            ("gfc_base", gfc_base,
             [r for r in diag["regimes"][str(h)] if r["regime"] == "gfc"][0]["base_rate"]),
        ]
        for name, mine, theirs in checks:
            match = close(float(mine), float(theirs))
            ok = ok and match
            print(f"h{h:>2} {name:<9} 독립={float(mine):.10f} 진단={float(theirs):.10f} "
                  f"{'OK' if match else '*** MISMATCH ***'}")

        # Murphy 항등식 재검산
        for key in ("murphy_quantile_bins", "murphy_fixed_bins"):
            m = d[key]
            lhs = m["reliability"] - m["resolution"] + m["uncertainty"] + m["binning_residual"]
            match = close(lhs, m["brier"], 1e-12)
            ok = ok and match
            print(f"h{h:>2} {key:<22} REL−RES+UNC+잔차={lhs:.12f} BS={m['brier']:.12f} "
                  f"{'OK' if match else '*** MISMATCH ***'}")

    print("\nALL OK" if ok else "\n*** 불일치 존재 ***")


if __name__ == "__main__":
    main()
