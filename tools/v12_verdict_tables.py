#!/usr/bin/env python
"""tools/v12_verdict_tables.py — verdict_recompute.json → 마크다운 표 (읽기 전용).

S1-1 판정 문서에 붙일 수치를 손으로 옮기지 않기 위한 포맷터. 계산은 하지 않는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100.0 * x:+.3f}%"


def _sci(x: float | None) -> str:
    return "—" if x is None else f"{x:+.3e}"


def v10_table(v10: dict[str, Any]) -> str:
    t = v10["top5pct_removal"]
    g, gw = v10["gfc_canonical"], v10["gfc_wide_sensitivity"]
    lo, hi = v10["ci90"]
    tlo, thi = t["ci90_after_removal"]
    lines = [
        "| 항목 | 재계산값 | 동결문서 주장 |",
        "|---|---|---|",
        f"| 쌍대 평균 Δ (origin {v10['origin_count']}) | {_sci(v10['paired_mean_delta'])} | — |",
        f"| 상대개선 | {_pct(v10['relative_improvement'])} | +0.64% |",
        f"| CI90 | [{_sci(lo)}, {_sci(hi)}] | — |",
        f"| mde50 | {_sci(v10['mde50'])} | — |",
        f"| GFC 견인 비중 (정본창 {g['window'][0]}~{g['window'][1]}, n={g['origins_in_window']}) "
        f"| {100 * g['delta_share']:.1f}% | 83.8% |",
        f"| GFC 견인 비중 (넓은창 {gw['window'][0]}~{gw['window'][1]}, n={gw['origins_in_window']}) "
        f"| {100 * gw['delta_share']:.1f}% | (설계 §0 87.0%) |",
        f"| GFC 제외 평균 Δ | {_sci(g['mean_excluding_window'])} | — |",
        f"| 상위5% 제거({t['origins_dropped']}개) 후 평균 Δ | {_sci(t['mean_after_removal'])} "
        f"| 부호반전(−0.0000115) |",
        f"| 상위5% 제거 후 CI90 | [{_sci(tlo)}, {_sci(thi)}] | — |",
        f"| 상위5%가 차지한 순이득 비중 | {100 * t['top5pct_share_of_net']:.1f}% | — |",
    ]
    led = v10.get("ledger_recorded_dual_vs_e0") or {}
    if led:
        same = (abs(led.get("mean", 0) - v10["paired_mean_delta"]) < 1e-15
                and abs(led.get("ci90", [0, 0])[0] - lo) < 1e-15)
        lines.append(f"| 원장 기록값과 비트 동일 | {'예' if same else '아니오'} | — |")
    return "\n".join(lines)


def v11_table(v11: dict[str, Any], variant_filter: tuple[str, ...] = ("p1_linear", "low_mom_tertile")) -> str:
    rows = [r for r in v11["results"] if r.get("variant") in variant_filter]
    out = ["| h | 경계 | 변형 | 방향 | CRPS 변화 | 개선 평균 | 개선 CI90 | 하한>0 |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lo, hi = r["improvement_ci90"]
        out.append(
            f"| {r['horizon']} | {r['boundary']} | {r['variant']} | {r['direction']} "
            f"| {_pct(r['crps_relative_change'])} | {_sci(r['improvement_mean'])} "
            f"| [{_sci(lo)}, {_sci(hi)}] | {'예' if r['improvement_ci90_lower_positive'] else '아니오'} |")
    return "\n".join(out)


def v11_placebo_table(v11: dict[str, Any]) -> str:
    return v11_table(v11, variant_filter=("constant_placebo",))


def v9_table(v9: dict[str, Any]) -> str:
    out = ["| 실험 | 기준선 | n | 쌍대 평균 Δ | 상대 | CI90 | 0 배제 |",
           "|---|---|---|---|---|---|---|"]
    for r in v9["pairs"]:
        lo, hi = r["ci90"]
        out.append(
            f"| {r['experiment']} | {r['baseline']} | {r['origin_count']} "
            f"| {_sci(r['paired_mean_delta'])} | {_pct(r['relative_improvement'])} "
            f"| [{_sci(lo)}, {_sci(hi)}] | {'예' if r['ci90_excludes_zero'] else '아니오'} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="docs/review/verdict_recompute.json")
    args = ap.parse_args()
    payload = json.loads((ROOT / args.src).read_text(encoding="utf-8"))
    if "v10" in payload:
        print("### V10\n" + v10_table(payload["v10"]) + "\n")
    if "v11" in payload:
        print("### V11 (정본 변형)\n" + v11_table(payload["v11"]) + "\n")
        print("### V11 (플라시보 = 상수 recenter)\n" + v11_placebo_table(payload["v11"]) + "\n")
        print("### V11 summary\n```json\n"
              + json.dumps(payload["v11"]["summary"], indent=2, ensure_ascii=False) + "\n```\n")
    if "v9" in payload:
        print("### V9\n" + v9_table(payload["v9"]) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
