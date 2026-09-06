#!/usr/bin/env python
"""S4-1 요약표 렌더 — 계약 draft 의 핵심 표를 마크다운으로 낸다 (수기 전사 방지).

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_tables.py \
        --out outputs/timeseries_v12/loop/_s4_1_tables.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml"
C = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
HS = ["h21", "h63"]


def f(x, nd=6):
    return "—" if x is None else f"{x:.{nd}f}"


def table_a() -> list[str]:
    out = ["### 표 A — 계약 성격 (S3 판정 승계)", "",
           "| 항목 | 값 |", "|---|---|"]
    nr = C["negative_result"]
    rows = [
        ("status", C["status"]),
        ("판정", nr["decision"]),
        ("decision_code", nr["decision_code"]),
        ("채택 셀", f"{nr['adopted_count']}/{nr['family_cells']}"),
        ("k_obs", nr["k_obs"]),
        ("CI90 하한 > 0 인 방향", f"{nr['directions_with_ci90_lower_gt_0']}/"
                              f"{nr['directions_evaluated']}"),
        ("T5 음성 대조", f"실패 (pooled {nr['negative_control_T5']['pass_rate_pooled']} > "
                     f"문턱 {nr['negative_control_T5']['threshold']})"),
        ("지배 분기", nr["governing_branch"]),
        ("게이트 무장", C["gates"]["armed"]),
        ("평가된 후보", C["gates"]["evaluated_candidates"]),
        ("트랙 개시", C["development_protocol"]["track_open"]),
    ]
    out += [f"| {k} | {v} |" for k, v in rows]
    return out + [""]


def table_b() -> list[str]:
    out = ["### 표 B — 게이트 문턱 (구속 기준선 = reflection_bgk)", "",
           "| 지평 | 기준선 | 기준선 BS | MDE | 요구 후보 BS ≤ | 요구 BSS ≥ |", "|---|---|---|---|---|---|"]
    th = C["gates"]["G2_skill_vs_reflection"]["thresholds"]
    for h in HS:
        for name, label in (("vs_reflection_bgk", "BGK (구속)"), ("vs_reflection_2phi", "2Φ (병기)")):
            r = th[h][name]
            out.append(f"| {h} | {label} | {f(r['baseline_brier'])} | {f(r['mde_1645se'])} | "
                       f"{f(r['required_candidate_brier_max'])} | "
                       f"{f(r['required_brier_skill_vs_climatology_min'])} |")
    return out + [""]


def table_c() -> list[str]:
    out = ["### 표 C — 게이트 도달 가능성 (재보정 상한 vs 요구 BSS)", "",
           "| 지평 | 기준선 | 요구 BSS | 상한(fixed) | 상한(quantile) | 여유 | 도달 |",
           "|---|---|---|---|---|---|---|"]
    fb = C["gate_feasibility_arithmetic"]["by_horizon"]
    for h in HS:
        ceil = fb[h]["recalibration_ceiling_bss"]
        for name in ("reflection_bgk", "reflection_2phi"):
            v = fb[h]["verdict_by_baseline"][name]
            out.append(
                f"| {h} | {name} | {f(v['required_brier_skill_vs_climatology_min'])} | "
                f"{f(ceil['fixed_bins'])} | {f(ceil['quantile_bins'])} | "
                f"{f(v['headroom_vs_max_ceiling'])} | "
                f"{'가능' if v['reachable_under_any_binning'] else '불가'} |")
    return out + [""]


def table_d() -> list[str]:
    out = ["### 표 D — 오늘의 V8 원값이 게이트 앞에 선 위치 (후보 평가 아님)", "",
           "| 지평 | G1 기후 | G1 하한 | G2 BGK | G2 하한 | G4 과신 유의 | G4 gap 하한 |",
           "|---|---|---|---|---|---|---|"]
    st = C["gates"]["current_status_of_v8_raw_probability"]
    for h in HS:
        s = st[h]
        out.append(f"| {h} | {s['G1_vs_climatology']} | {f(s['G1_ci90_lower'])} | "
                   f"{s['G2_vs_reflection_bgk']} | {f(s['G2_bgk_ci90_lower'])} | "
                   f"{'예' if s['G4_overconfidence_still_significant'] else '아니오'} | "
                   f"{f(s['G4_top_quintile_gap_ci90_lower'])} |")
    return out + [""]


def table_e() -> list[str]:
    out = ["### 표 E — 헌법 승계 대사", "", "| 항목 | 계약 값 | 출처 |", "|---|---|---|"]
    sp = C["stopping_points"]
    pr = C["prohibitions"]
    rows = [
        ("정지점 수", sp["count"], "V9·V10 헌법"),
        ("홀드아웃 승인", sp["holdout"]["requires_explicit_user_approval"], "V8 계약"),
        ("홀드아웃 상태", sp["holdout"]["current_state"], "이 루프"),
        ("봉인 사인오프", sp["sealed"]["requires_explicit_user_signoff"], "V8 계약"),
        ("봉인 공개 상한", sp["sealed"]["maximum_disclosures_per_model_version"], "V8 계약"),
        ("retune_after_failure", sp["sealed"]["retune_after_failure"], "V8 계약"),
        ("봉인 실행", sp["loop_execution_record"]["sealed_runs"], "이 루프"),
        ("백테스트 실행", sp["loop_execution_record"]["backtest_runs"], "이 루프"),
        ("승계 금지 키 수", len(pr["inherited_from_v8_and_v10"]), "V8 ∪ V10"),
        ("V12 고유 금지 키 수", len(pr["v12_specific"]), "이 계약"),
        ("CRPS proxy 조건 수", len(C["crps_gate_intact"]["dev_gate_proxy"]), "V8 값 무변경 복제"),
    ]
    out += [f"| {k} | {v} | {s} |" for k, v, s in rows]
    return out + [""]


def main() -> int:
    lines = ["# S4-1 요약표 — V12 부정 결과 계약 draft", "",
             f"> 원천 `{CONTRACT.relative_to(ROOT).as_posix()}` · 렌더 `tools/v12_s4_tables.py`",
             "> 이 문서의 수치는 계약 YAML 을 읽은 값이며 수기 전사가 없다.", ""]
    for fn in (table_a, table_b, table_c, table_d, table_e):
        lines += fn()
    text = "\n".join(lines).rstrip("\n") + "\n"
    if "--out" in sys.argv:
        dest = ROOT / sys.argv[sys.argv.index("--out") + 1]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
        print(f"written: {dest.relative_to(ROOT).as_posix()}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
