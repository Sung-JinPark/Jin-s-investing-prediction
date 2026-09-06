#!/usr/bin/env python
"""S4-2 표 렌더 — 게이트 설계서의 모든 표를 gate_design.json 에서 직접 낸다 (수기 전사 방지).

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_2_tables.py \
        [--out outputs/timeseries_v12/loop/_s4_2_tables.md]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/timeseries_v12/design/gate_design.json"
OUT_DEFAULT = ROOT / "outputs/timeseries_v12/loop/_s4_2_tables.md"

G = json.loads(SRC.read_text(encoding="utf-8"))
HS = ["h21", "h63"]
BASE_LABEL = {"reflection_bgk": "BGK (구속)", "reflection_2phi": "2Φ (병기)",
              "vs_climatology_insample": "기후(in-sample)",
              "vs_reflection_2phi": "반사 2Φ", "vs_reflection_bgk": "반사 BGK (구속)"}


def f(x, nd=6):
    return "—" if x is None else f"{x:.{nd}f}"


def s(x, nd=6):
    return "—" if x is None else f"{x:+.{nd}f}"


def table_a() -> list[str]:
    out = ["### 표 A — 게이트 산술 재유도 (원배열 → 문턱, 계약 대사)", "",
           "| 지평 | 기준선 | 기준선 BS | 쌍대 se | MDE=z·se | 요구 후보 BS ≤ | 요구 BSS ≥ "
           "| V8 대비 필요 감소 | 계약 잔차(최대) |",
           "|---|---|---|---|---|---|---|---|---|"]
    for h in HS:
        row = G["A_gate_arithmetic"]["by_horizon"][h]
        for name in ("reflection_bgk", "reflection_2phi"):
            b = row["baselines"][name]
            resid = max(abs(b["baseline_brier_residual"]), abs(b["mde_residual"]),
                        abs(b["required_candidate_brier_residual"]),
                        abs(b["required_bss_residual"]))
            out.append(
                f"| {h} | {BASE_LABEL[name]} | {f(b['baseline_brier_recomputed'])} | "
                f"{f(b['paired_bootstrap_se'])} | {f(b['mde_z95_recomputed'])} | "
                f"{f(b['required_candidate_brier_recomputed'])} | "
                f"{f(b['required_bss_recomputed'])} | "
                f"{f(b['required_brier_reduction_from_v8'])} "
                f"({b['required_brier_reduction_share_of_v8'] * 100:.1f}%) | {resid:.2e} |")
    return out + [""]


def table_a2() -> list[str]:
    out = ["### 표 A2 — 요구 BSS vs 재보정 상한 (독립 재유도, 계약 대사)", "",
           "| 지평 | 재보정 상한(fixed) | 재보정 상한(quantile) | 기준선 | 요구 BSS | 여유 "
           "| 점추정 도달 |",
           "|---|---|---|---|---|---|---|"]
    for h in HS:
        row = G["A_gate_arithmetic"]["by_horizon"][h]
        c = row["recalibration_ceiling_bss"]
        for name in ("reflection_bgk", "reflection_2phi"):
            b = row["baselines"][name]
            out.append(
                f"| {h} | {f(c['fixed_bins'])} | {f(c['quantile_bins'])} | "
                f"{BASE_LABEL[name]} | {f(b['required_bss_recomputed'])} | "
                f"{s(b['required_bss_vs_recalibration_ceiling_headroom'])} | "
                f"{'예' if b['reachable_by_recalibration_point_estimate'] else '**아니오**'} |")
    return out + [""]


def table_b() -> list[str]:
    out = ["### 표 B — MDE 층 (셀별 분해능과 필요 표본)", "",
           "| 셀 | Δ̂ (V8−기준선) | se | MDE | \\|Δ̂\\|/MDE | MDE/기준선BS | MDE(BSS 단위) "
           "| n* | 추가 연수 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for key, c in G["B_mde_layer"]["by_cell"].items():
        h, name = key.split("|")
        nstar = c.get("n_star_origins")
        yrs = c.get("n_star_extra_years")
        out.append(
            f"| {h} · {BASE_LABEL[name]} | {s(c['loss_diff_v8_minus_baseline'])} | "
            f"{f(c['bootstrap_se'])} | {f(c['mde_z95'])} | "
            f"{c['abs_effect_over_mde']:.3f} | {c['mde_share_of_baseline_brier'] * 100:.1f}% | "
            f"{f(c['mde_in_bss_units'], 4)} | "
            + (f"{nstar:,.0f} | {yrs:,.0f} |" if nstar else "정의없음 | — |"))
    return out + [""]


def table_c() -> list[str]:
    out = ["### 표 C — G4 reliability 다리의 정량화 (최소 감소폭 vs 도달 가능 감소폭)", "",
           "| 지평 | binning | REL(V8) | se_boot(REL) | 최소 감소폭 z·se (비쌍대) "
           "| 완전재보정 감소폭 | 비쌍대 규약 무장 | 부족분 |",
           "|---|---|---|---|---|---|---|---|"]
    for h in HS:
        for binning in ("quantile_bins", "fixed_bins"):
            r = G["C_g4_reliability_quantification"]["by_horizon"][h]["reliability"][binning]
            out.append(
                f"| {h} | {binning} | {f(r['reliability_v8'])} | {f(r['bootstrap_se'])} | "
                f"{f(r['required_min_reduction_z95_unpaired'])} | "
                f"{f(r['max_possible_reduction_perfect_recalibration'])} | "
                f"{'가능' if r['armable_under_unpaired_se'] else '**불가**'} | "
                f"{s(r['shortfall'])} |")
    return out + [""]


def table_c2() -> list[str]:
    out = ["### 표 C2 — G4 상위분위 gap 다리 (계약이 요구하는 것: CI90 하한 ≤ 0)", "",
           "| 지평 | gap 주체 | gap | gap CI90 하한 | se | 이미 충족 | 하한을 0 으로 만들 "
           "필요 하락폭 |",
           "|---|---|---|---|---|---|---|"]
    label = {"v8": "V8 (S2-3 R1)", "reflection_2phi": "반사 기준선 (S2-3 R2 · 계약 채택)"}
    for h in HS:
        leg = G["C_g4_reliability_quantification"]["by_horizon"][h]["top_quintile_gap"]
        for subject, row in leg.items():
            out.append(
                f"| {h} | {label[subject]} | {f(row['gap'])} | {s(row['gap_ci90_lower'])} | "
                f"{f(row['gap_bootstrap_se'])} | "
                f"{'예' if row['already_satisfies_gate'] else '아니오'} | "
                f"{f(row['required_reduction_of_lower_bound'])} |")
    return out + [""]


def table_d() -> list[str]:
    out = ["### 표 D — G1 병기 의무의 표본 분해 (expanding 기후는 왜 더 후한가)", "",
           "| 지평 | n | 적격 n | BSS(기후 in-sample, 전표본) | BSS(기후 in-sample, 적격) "
           "| BSS(기후 expanding, 적격) | 표본 효과 | 기준선 효과 | 쌍대 Δ vs expanding "
           "| CI90 하한 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for h in HS:
        d = G["D_g1_companion_sample"]["by_horizon"][h]
        pe = d["paired_v8_vs_expanding_on_eligible"]
        out.append(
            f"| {h} | {d['n_full']} | {d['eligible_n']} | {s(d['bss_insample_full'])} | "
            f"{s(d['bss_insample_on_eligible'])} | {s(d['bss_expanding_on_eligible'])} | "
            f"{s(d['sample_effect'])} | {s(d['baseline_effect'])} | "
            f"{s(pe['loss_diff'])} | {s(pe['ci90_lower'])} |")
    return out + [""]


def table_e1() -> list[str]:
    e = G["E_budget"]
    out = ["### 표 E1 — 예산 캡과 소모 (계약 등재값 + S3 실사용)", "",
           "| 항목 | 값 |", "|---|---|"]
    caps = e["contract_caps"]
    s3 = e["s3_consumption"]
    rows = [
        ("트랙 개시", caps["track_open"]),
        ("개발 평가 상한", caps["maximum_development_evaluations"]),
        ("계약 기록 소모", caps["evaluations_spent_recorded"]),
        ("홀드아웃 finalist 상한", caps["holdout_maximum_finalists"]),
        ("봉인 공개 상한(모델 버전당)", caps["sealed_maximum_disclosures_per_model_version"]),
        ("S3 등록 가설", s3["hypotheses_registered"]),
        ("S3 채택 대상 가설", s3["adoption_eligible_hypotheses"]),
        ("S3 셀 / 방향", f"{s3['family_cells']} / {s3['directions_evaluated']}"),
        ("S3 = 개발 평가 환산", s3["development_evaluations_equivalent"]),
        ("계상 시 잔여 예산", s3["remaining_if_counted"]),
        ("순열 복제", s3["permutation_replicates"]),
    ]
    out += [f"| {k} | {v} |" for k, v in rows]
    return out + [""]


def table_e2() -> list[str]:
    m = G["E_budget"]["multiplicity_budget"]
    out = ["### 표 E2 — 다중검정 예산 (S3 순열 귀무의 셀별 통과율)", "",
           "| 셀 | 귀무 통과율 | 명목 5% 대비 |", "|---|---|---|"]
    for cell, rate in m["per_cell_null_pass_rate_measured"].items():
        out.append(f"| {cell} | {rate:.3f} | ×{rate / 0.05:.1f} |")
    out += [f"| **h21 평균** | **{m['per_cell_mean_h21']:.3f}** | "
            f"×{m['per_cell_mean_h21'] / 0.05:.1f} |",
            f"| **h63 평균** | **{m['per_cell_mean_h63']:.3f}** | "
            f"×{m['per_cell_mean_h63'] / 0.05:.1f} |",
            f"| 전체 평균 (k̄/{m['family_cells']}) | {m['implied_per_cell_null_pass_rate']:.4f} | "
            f"×{m['inflation_factor']:.2f} |"]
    return out + [""]


def table_e3() -> list[str]:
    out = ["### 표 E3 — 데이터 예산 (현 점추정을 유의하게 만들 표본)", "",
           "| 셀 | 정의 | n* (원점) | 현재 대비 배수 | 추가 연수 |", "|---|---|---|---|---|"]
    for key, c in G["E_budget"]["data_budget"]["by_cell"].items():
        h, name = key.split("|")
        if c["defined"]:
            out.append(f"| {h} · {BASE_LABEL[name]} | 정의됨 | {c['n_star_origins']:,.0f} | "
                       f"×{c['multiple']:.1f} | {c['extra_years']:,.0f} |")
        else:
            out.append(f"| {h} · {BASE_LABEL[name]} | **정의 안 됨 (Δ̂ ≤ 0)** | — | — | — |")
    return out + [""]


def table_f() -> list[str]:
    scan = G["F_deployment_boundary"]["measured_surface"]
    out = ["### 표 F — 표시 계통 실측 스캔 ('−10% 접촉' 계열 확률)", "",
           "| 역할 | 사이트 수 | 예 |", "|---|---|---|"]
    role_ko = {"producer": "산출기", "published_artifact_builder": "배포 산출물 빌더",
               "display_dashboard": "대시보드 표시", "console_output": "콘솔 출력",
               "audit": "감사", "test": "테스트"}
    for role, sites in sorted(scan["minus10_sites_by_role"].items()):
        out.append(f"| {role_ko.get(role, role)} | {len(sites)} | `{sites[0]}` |")
    out += ["", f"- src 전체에서 `timeseries_v12` 참조: "
                f"**{scan['src_references_to_timeseries_v12_count']}건** "
                f"(파생층은 제품 코드와 배선되어 있지 않다)",
            f"- src 에서 `first_touch_probability` 참조: "
            f"{scan['src_references_to_first_touch_probability_count']}건 (V8 계열 산출·검증 경로)",
            f"- 스캔 파일 수: {scan['files_scanned']}"]
    return out + [""]


def main() -> int:
    out_path = OUT_DEFAULT
    argv = sys.argv[1:]
    if "--out" in argv:
        out_path = ROOT / argv[argv.index("--out") + 1]
    lines: list[str] = ["<!-- 생성: tools/v12_s4_2_tables.py — 수기 편집 금지 -->", ""]
    for fn in (table_a, table_a2, table_b, table_c, table_c2, table_d,
               table_e1, table_e2, table_e3, table_f):
        lines += fn()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out_path.relative_to(ROOT).as_posix()} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
