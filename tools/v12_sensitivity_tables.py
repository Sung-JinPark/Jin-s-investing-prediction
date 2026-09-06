#!/usr/bin/env python
"""tools/v12_sensitivity_tables.py — v10_sensitivity_grid.json → 마크다운 표 (읽기 전용).

S1-2 민감도 문서에 붙일 수치를 손으로 옮기지 않기 위한 포맷터. 계산은 하지 않는다
(비율·백분율 환산만 한다). 정의·판정은 전부 v12_sensitivity_v10.py 산출값 그대로.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100.0 * x:+.3f}%"


def _share(x: float | None) -> str:
    return "—" if x is None else f"{100.0 * x:.1f}%"


def _sci(x: float | None) -> str:
    return "—" if x is None else f"{x:+.3e}"


def _yn(x: bool | None) -> str:
    return "—" if x is None else ("예" if x else "아니오")


def block_table(payload: dict[str, Any]) -> str:
    out = ["| ℓ | 평균 Δ | 상대개선 | CI90 | 하한>0 | 부트 se | mde50 | 상위5%제거 평균 Δ | 부호반전 | 제거후 CI90 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for key, b in payload["axis_a_block_length"].items():
        lo, hi = b["ci90"]
        t = b["trimmed"]
        tlo, thi = t["ci90"]
        mark = " (정본)" if b["is_canonical"] else ""
        out.append(
            f"| {key}{mark} | {_sci(b['mean_delta'])} | {_pct(b['relative_improvement'])} "
            f"| [{_sci(lo)}, {_sci(hi)}] | {_yn(b['ci90_lower_positive'])} "
            f"| {_sci(b['bootstrap_se'])} | {_sci(b['mde50'])} "
            f"| {_sci(t['mean_after_removal'])} | {_yn(t['sign_flips'])} "
            f"| [{_sci(tlo)}, {_sci(thi)}] |")
    return "\n".join(out)


def _regime_row(r: dict[str, Any], label: str, block: str) -> str:
    ci = r["calm_ci90_by_block"][block]
    ci_txt = "—" if ci is None else f"[{_sci(ci[0])}, {_sci(ci[1])}]"
    return (f"| {label} | {r['crisis_origins']} | {_share(r['crisis_origin_share'])} "
            f"| {_share(r['crisis_delta_share'])} | {_sci(r['crisis_mean_delta'])} "
            f"| {_sci(r['calm_mean_delta'])} | {_pct(r['calm_relative_improvement'])} "
            f"| {ci_txt} | {_yn(r['calm_ci90_lower_positive_by_block'][block])} |")


_REGIME_HEAD = ["| 위기 정의 | 위기 n | 위기 원점비 | 위기 Δ견인 | 위기 평균 Δ | calm 평균 Δ | calm 상대 | calm CI90 (ℓ=13) | 하한>0 |",
                "|---|---|---|---|---|---|---|---|---|"]


def window_table(payload: dict[str, Any], block: str = "13") -> str:
    out = list(_REGIME_HEAD)
    for r in payload["axis_b_date_window"]:
        if r.get("skipped"):
            out.append(f"| ~~{r['start']}~{r['end']}~~ (start≥end, 제외) | — | — | — | — | — | — | — | — |")
            continue
        mark = " **(정본)**" if r.get("is_canonical") else ""
        out.append(_regime_row(r, f"{r['cell_id']} {r['start']}~{r['end']}{mark}", block))
    return "\n".join(out)


def calm_table(payload: dict[str, Any], block: str = "13") -> str:
    out = list(_REGIME_HEAD)
    for r in payload["axis_c_calm_percentile"]["rows"]:
        mark = " **(정본)**" if r.get("is_canonical") else ""
        label = (f"{r['cell_id']} (primary ≤ {r['primary_threshold']:.4f}, "
                 f"실효 calm {_share(r['effective_calm_share'])}){mark}")
        out.append(_regime_row(r, label, block))
    return "\n".join(out)


def localization_table(payload: dict[str, Any]) -> str:
    loc = payload["axis_b_localization"]
    out = ["| 조각 | 기간 | origin n | 원점비 | Δ 합 | Δ 견인 비중 | 평균 Δ |", "|---|---|---|---|---|---|---|"]
    for r in loc["pieces"]:
        out.append(f"| {r['piece']} | {r['start']}~{r['end']} | {r['origins']} "
                   f"| {_share(r['origin_share'])} | {_sci(r['delta_sum'])} "
                   f"| {_share(r['delta_share'])} | {_sci(r['mean_delta'])} |")
    o = loc["outside_canonical"]
    out.append(f"| 정본창 밖 | — | {o['origins']} | {_share(o['origin_share'])} | — "
               f"| {_share(o['delta_share'])} | — |")
    return "\n".join(out)


def verdict_table(payload: dict[str, Any]) -> str:
    blocks = [str(b) for b in payload["axes"]["block_lengths"]]
    cells = payload["verdict_grid"]
    labels: list[str] = []
    for c in cells:
        if c["cell_id"] not in labels:
            labels.append(c["cell_id"])
    out = ["| 위기 정의 \\ ℓ | " + " | ".join(f"ℓ={b}" for b in blocks) + " |",
           "|---" * (len(blocks) + 1) + "|"]
    for label in labels:
        row = [label]
        for b in blocks:
            c = next(x for x in cells if x["cell_id"] == label and str(x["block_length"]) == b)
            star = "★" if c["is_canonical_cell"] else ""
            row.append(f"{c['verdict']}{star} ({c['calm_mean_over_mde50']:.2f})")
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def v11_verdict_table(payload: dict[str, Any]) -> str:
    out = ["| calm | ℓ | 셀 n | 부호개선 셀 | 양방향 부호개선 | 채택(양방향 CI90 하한>0) | 순열 p | 판정 |",
           "|---|---|---|---|---|---|---|---|"]
    for c in payload["verdict_grid"]:
        perm = c.get("permutation_null")
        p_txt = "—(불필요)" if perm is None else f"{perm['null_p_ge_observed']:.3f}"
        star = "★" if c["is_canonical_cell"] else ""
        out.append(f"| p{int(c['calm_pct'])}{star} | {c['block_length']} | {c['cells_live']} "
                   f"| {c['cells_improved_by_sign']} | {c['both_directions_improved_by_sign']}/{c['combos_tested']} "
                   f"| {c['combos_meeting_adoption_rule']}/{c['combos_tested']} | {p_txt} | {c['verdict']} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="docs/review/v10_sensitivity_grid.json")
    ap.add_argument("--block", default="13")
    ap.add_argument("--v11", action="store_true", help="V11 부속 격자(v11_sensitivity_grid.json) 렌더")
    args = ap.parse_args()
    payload = json.loads((ROOT / args.src).read_text(encoding="utf-8"))

    if args.v11:
        print("### V11 부속 — calm × ℓ 판정 격자\n" + v11_verdict_table(payload) + "\n")
        print("### origins\n```json\n" + json.dumps(
            {k: v["origins_by_horizon"] for k, v in payload["per_calm"].items()},
            indent=2, ensure_ascii=False) + "\n```\n")
        print("### summary\n```json\n"
              + json.dumps(payload["summary"], indent=2, ensure_ascii=False) + "\n```")
        return 0

    print("### 축 A — 블록길이 ℓ\n" + block_table(payload) + "\n")
    print(f"### 축 B — 위기창 경계 ±1y (calm CI 는 ℓ={args.block})\n"
          + window_table(payload, args.block) + "\n")
    print("### 축 B 부속 — 정본창 3분할 Δ 견인 (격자 항등식)\n"
          + localization_table(payload) + "\n")
    print(f"### 축 C — calm 백분위 (calm CI 는 ℓ={args.block})\n"
          + calm_table(payload, args.block) + "\n")
    print("### 판정 격자 (괄호 = calm 평균 Δ / mde50, ★ = 정본 셀)\n" + verdict_table(payload) + "\n")
    print("### summary\n```json\n"
          + json.dumps(payload["summary"], indent=2, ensure_ascii=False) + "\n```\n")
    print("### axis_c coverage\n```json\n"
          + json.dumps(payload["axis_c_calm_percentile"]["coverage"], indent=2, ensure_ascii=False)
          + "\n```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
