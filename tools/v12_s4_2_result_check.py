#!/usr/bin/env python
"""S4-2 result JSON 자기주장 대사 (읽기 전용).

result JSON 이 적은 수치·주장을 산출 JSON·계약·문서·git·봉인·검사기 재실행과 맞춘다.
result 가 스스로를 과장하거나 오기하면 여기서 걸린다.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_2_result_check.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

RESULT = ROOT / "outputs/timeseries_v12/loop/results/S4-2.json"
GD = ROOT / "data/timeseries_v12/design/gate_design.json"
DOC = ROOT / "docs/design/v12_gate_design.md"
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml"
S3V = ROOT / "data/timeseries_v12/diagnostics/s3_verdict.json"

R: list[tuple[str, bool, str]] = []


def check(cid: str, ok: bool, detail: str = "") -> None:
    R.append((cid, bool(ok), detail))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8").stdout


J = json.loads(RESULT.read_text(encoding="utf-8"))
G = json.loads(GD.read_text(encoding="utf-8"))
C = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
S3 = json.loads(S3V.read_text(encoding="utf-8"))
DOCTEXT = DOC.read_text(encoding="utf-8")


def close(a: float, b: float, tol: float = 1e-12) -> bool:
    return abs(float(a) - float(b)) <= tol


# --------------------------------------------------------------------- R1 산출물
def r1_artifacts() -> None:
    for rel, digest in J["artifacts"].items():
        p = ROOT / rel
        check(f"R1 존재 · {rel}", p.is_file())
        if p.is_file():
            actual = sha256_file(p)
            check(f"R1 sha256 · {rel}", actual == digest, actual[:12])
    check("R1-n 산출물 7종", len(J["artifacts"]) == 7, str(len(J["artifacts"])))


# --------------------------------------------------------------------- R2 커밋
def r2_commit() -> None:
    short = J["commit"].split()[0]
    log = git("log", "--oneline", "-30")
    check("R2-a 커밋 존재", short in log, short)
    files = git("show", "--name-only", "--format=", short).split()
    for rel in J["artifacts"]:
        if rel != "outputs/timeseries_v12/loop/results/S4-2.json":
            check(f"R2-b 커밋 포함 · {rel}", rel in files)
    subject = git("log", "-1", "--format=%s", short).strip()
    check("R2-c 커밋 제목 규약", subject.startswith("loop(v12): S4-2"), subject)


# --------------------------------------------------------------------- R3 입력 무변경
def r3_inputs() -> None:
    for rel, digest in J["inputs"].items():
        if rel == "note":
            continue
        p = ROOT / rel
        check(f"R3 · {rel}", p.is_file() and sha256_file(p) == digest)
    prov = G["provenance"]["inputs_sha256"]
    for rel, digest in prov.items():
        if rel in J["inputs"]:
            check(f"R3-x 산출측 교차 · {rel}", J["inputs"][rel] == digest)
    check("R3-run run 해시 = 산출측",
          J["inputs"]["data/timeseries_v8/runs/dev_tsv8-exp-61cee7b7fb7c41399534.json"]
          == G["provenance"]["run_sha256"])


# --------------------------------------------------------------------- R4 봉인
def r4_seal() -> None:
    s = J["seal_reconciliation"]
    gs = G["seal_state"]
    check("R4-a 봉인 해시 = 산출측", s["sealed_sha256"] == gs["sealed_source_hash"])
    check("R4-b 봉인 = BOOT 기준선", gs["sealed_matches_baseline"] is True)
    check("R4-c 봉인 = 계약 핀", gs["sealed_matches_contract_pin"] is True)
    check("R4-d 원장 해시 = 산출측", s["ledger_sha256"] == gs["v8_ledger_hash"])
    check("R4-e 원장 = BOOT 기준선", gs["ledger_matches_baseline"] is True)
    check("R4-f 원장 = 계약 핀", gs["ledger_matches_contract_pin"] is True)
    porcelain = git("status", "--porcelain", "--", "forecasts", "calibration", "src",
                    "data/timeseries_v8", "data/timeseries_v2", "questions").strip()
    check("R4-g 불변 경로 청결", porcelain == "", porcelain[:80])
    check("R4-h 계약 무수정",
          sha256_file(CONTRACT)
          == J["inputs"]["data/contracts/multivariate_timeseries_v12.draft.yaml"])


# --------------------------------------------------------------------- R5 headline
def r5_headline() -> None:
    h = J["headline"]
    recon = G["A_gate_arithmetic"]["contract_reconciliation"]
    check("R5-a 계약 대사 값 수", h["contract_values_reconciled"] == recon["values_compared"],
          str(recon["values_compared"]))
    check("R5-b 최대 잔차", close(h["max_abs_residual_vs_contract"],
                              recon["max_abs_residual"]),
          f"{recon['max_abs_residual']:.3e}")
    tbl = ROOT / "outputs/timeseries_v12/loop/_s4_2_tables.md"
    n_tbl = sum(1 for ln in tbl.read_text(encoding="utf-8").splitlines()
                if ln.startswith("### 표 "))
    check("R5-c 표 개수", h["tables_rendered"] == n_tbl, str(n_tbl))
    n_sec = sum(1 for ln in DOCTEXT.splitlines() if re.match(r"^## \d+\.", ln))
    check("R5-d 문서 절 수", h["document_sections"] == n_sec, str(n_sec))
    check("R5-e 게이트 무장", h["gates_armed"] is False and C["gates"]["armed"] is False)
    check("R5-f 후보 0", h["candidates_created"] == 0
          and int(C["gates"]["evaluated_candidates"]) == 0)
    check("R5-g 개정 제안 5종", h["contract_amendment_proposals"] == ["P1", "P2", "P3", "P4", "P5"]
          and all(f"**{p}**" in DOCTEXT for p in h["contract_amendment_proposals"]))


# --------------------------------------------------------------------- R6 G4 수치
def r6_g4() -> None:
    m = J["resolved_open_questions"]["S4-1_q1_G4_reliability_minimum_reduction"]["measured"]
    src = G["C_g4_reliability_quantification"]["by_horizon"]
    pairs = {"h21_quantile": ("h21", "quantile_bins"), "h21_fixed": ("h21", "fixed_bins"),
             "h63_quantile": ("h63", "quantile_bins"), "h63_fixed": ("h63", "fixed_bins")}
    for key, (h, binning) in pairs.items():
        row = src[h]["reliability"][binning]
        claim = m[key]
        check(f"R6 rel · {key}", close(claim["rel"], row["reliability_v8"]))
        check(f"R6 se · {key}", close(claim["se"], row["bootstrap_se"]))
        check(f"R6 floor · {key}",
              close(claim["floor_z95"], row["required_min_reduction_z95_unpaired"]))
        check(f"R6 armable · {key}",
              claim["armable_under_unpaired_se"] == row["armable_under_unpaired_se"])
        check(f"R6 floor>rel · {key}",
              row["required_min_reduction_z95_unpaired"] > row["reliability_v8"],
              "무장 불가 주장의 근거 부등식")
    # 요구 하락폭이 문서·산출과 일치
    for h, val in (("h21", 0.007792), ("h63", 0.065441)):
        gap = src[h]["top_quintile_gap"]["reflection_2phi"]["required_reduction_of_lower_bound"]
        check(f"R6 gap 요구 하락폭 · {h}", close(gap, val, 5e-7), f"{gap:.6f}")


# --------------------------------------------------------------------- R7 G1 수치
def r7_g1() -> None:
    m = J["resolved_open_questions"]["S4-1_q4_G1_companion_sample"]["measured"]
    src = G["D_g1_companion_sample"]["by_horizon"]
    for h in ("h21", "h63"):
        check(f"R7 표본효과 · {h}", close(m[h]["sample_effect"], src[h]["sample_effect"]))
        check(f"R7 기준선효과 · {h}", close(m[h]["baseline_effect"], src[h]["baseline_effect"]))
        check(f"R7 자체기저 변형 · {h}",
              close(m[h]["own_base_variant_sample_effect"],
                    src[h]["sample_effect_own_base_variant"]))
        check(f"R7 항등식 잔차 0 · {h}", close(src[h]["identity_residual"], 0.0))
        check(f"R7 상류 재현 잔차 0 · {h}",
              all(close(v, 0.0) for k, v in src[h]["upstream_reconciliation"].items()
                  if k.endswith("_residual")))
        check(f"R7 기준선효과 우세 · {h}",
              abs(src[h]["baseline_effect"]) > 10 * abs(src[h]["sample_effect"]),
              "'표본이 아니라 기준선' 주장의 근거")
    dc = m["decisive_contrast_h63_same_sample_n384"]
    d63 = src["h63"]
    check("R7-x expanding 하한",
          close(dc["paired_vs_expanding_ci90_lower"],
                d63["paired_v8_vs_expanding_on_eligible"]["ci90_lower"]))
    check("R7-y insample 하한",
          close(dc["paired_vs_insample_climatology_ci90_lower"],
                d63["paired_v8_vs_insample_climatology_on_eligible"]["ci90_lower"]))
    check("R7-z 판정 뒤집힘",
          d63["paired_v8_vs_expanding_on_eligible"]["ci90_lower"] > 0
          > d63["paired_v8_vs_insample_climatology_on_eligible"]["ci90_lower"],
          "같은 표본·같은 후보에서 기준선만 다름")
    check("R7-n 표본 동일",
          d63["paired_v8_vs_expanding_on_eligible"]["n"]
          == d63["paired_v8_vs_insample_climatology_on_eligible"]["n"] == 384)


# --------------------------------------------------------------------- R8 예산 수치
def r8_budget() -> None:
    mb = G["E_budget"]["multiplicity_budget"]
    bh = J["budget_headline"]
    check("R8-a 셀 평균 통과율",
          close(bh["per_cell_null_pass_rate_mean"], mb["implied_per_cell_null_pass_rate"]),
          f"{mb['implied_per_cell_null_pass_rate']}")
    check("R8-b 지평 평균 원값",
          close(bh["per_cell_mean_h21"], mb["per_cell_mean_h21"])
          and close(bh["per_cell_mean_h63"], mb["per_cell_mean_h63"]),
          f"h21={mb['per_cell_mean_h21']} h63={mb['per_cell_mean_h63']}")
    check("R8-b2 렌더 반올림 표기",
          bh["rendered_h21"] == f"{mb['per_cell_mean_h21']:.3f}"
          and bh["rendered_h63"] == f"{mb['per_cell_mean_h63']:.3f}"
          and bh["rendered_h21"] in DOCTEXT and bh["rendered_h63"] in DOCTEXT,
          "result 의 반올림 표기가 문서와 일치")
    check("R8-c 팽창 배수", close(bh["inflation_vs_nominal_5pct"], mb["inflation_factor"]),
          f"{mb['inflation_factor']:.3f}")
    check("R8-c2 잔여 예산", close(bh["remaining_development_budget_if_s3_counted"],
                               G["E_budget"]["s3_consumption"]["remaining_if_counted"]))
    check("R8-c3 계산 시간", close(bh["rel_bootstrap_elapsed_sec_measured"],
                              G["E_budget"]["compute_budget"]
                              ["rel_bootstrap_elapsed_sec_measured"]))
    check("R8-d k̄ 합 일치", close(mb["sum_check_vs_k_mean"], 0.0, 1e-9))
    check("R8-e 셀별 통과율 = S3 원천",
          mb["per_cell_null_pass_rate_measured"] == {
              k: float(v) for k, v in S3["null_liberality"]["cell_pass_rate"].items()})
    db = G["E_budget"]["data_budget"]["by_cell"]
    check("R8-f h21 반사 셀 n* 미정의",
          db["h21|vs_reflection_bgk"]["defined"] is False
          and db["h21|vs_reflection_2phi"]["defined"] is False)
    yrs = db["h63|vs_reflection_bgk"]["extra_years"]
    check("R8-g h63 BGK +943년", round(yrs) == 943
          and close(bh["n_star_h63_bgk_extra_years"], yrs)
          and bh["n_star_h21_reflection_cells_defined"] is False, f"{yrs:.1f}")
    check("R8-h 계약 캡 인용",
          G["E_budget"]["contract_caps"]["maximum_development_evaluations"]
          == C["development_protocol"]["maximum_development_evaluations"] == 24)


# --------------------------------------------------------------------- R9 배포 경계
def r9_boundary() -> None:
    scan = G["F_deployment_boundary"]["measured_surface"]
    counts = scan["minus10_sites_by_role_counts"]
    text = json.dumps(J, ensure_ascii=False)
    check("R9-a v12 배선 0", scan["src_references_to_timeseries_v12_count"] == 0)
    check("R9-b 스캔 파일 수", scan["files_scanned"] == 435 and "435" in text,
          str(scan["files_scanned"]))
    for role, n in (("display_dashboard", 1), ("published_artifact_builder", 1),
                    ("console_output", 1), ("producer", 7)):
        check(f"R9-c 역할 수 · {role}", counts.get(role) == n, str(counts.get(role)))
    fp = scan["published_artifacts_carrying_minus10"].get("reports/future_paths.json", {})
    check("R9-d future_paths 키 11회", fp.get("key_occurrences") == 11 and "11회" in text,
          str(fp.get("key_occurrences")))
    check("R9-e 미공개 유지", C["probability_contract"]["publication_status"] == "not_published")
    for tier in ("T0", "T1", "T2", "T3", "T4"):
        check(f"R9-f 사다리 · {tier}", f"**{tier}**" in DOCTEXT)


# --------------------------------------------------------------------- R10 검사기 재실행
def r10_rerun() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools/v12_run.py"), "tools/v12_s4_2_doc_check.py"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    out = proc.stdout
    n_pass = out.count("[PASS]")
    n_fail = out.count("[FAIL]")
    check("R10-a doc_check 재실행 종료코드 0", proc.returncode == 0, str(proc.returncode))
    check("R10-b doc_check 항목 수", J["verification"]["total"].startswith(str(n_pass + n_fail)),
          f"{n_pass}P/{n_fail}F")
    check("R10-c doc_check 전부 PASS", n_fail == 0 and n_pass == J["headline"]["doc_check_pass"],
          f"{n_pass}")
    # verification 그룹별 항목 수가 실제 검사 ID 접두사와 맞는지
    ids = re.findall(r"\[(?:PASS|FAIL)\] (D\d+)-", out)
    from collections import Counter
    got = Counter(ids)
    for gid, desc in J["verification"].items():
        if not gid.startswith("D"):
            continue
        m = re.match(r"[^\d]*(\d+)\s*항목", desc)
        if m:
            check(f"R10-d 그룹 수 · {gid}", got[gid] == int(m.group(1)),
                  f"주장 {m.group(1)} vs 실측 {got[gid]}")


# --------------------------------------------------------------------- R11 문서 주장
def r11_doc_claims() -> None:
    check("R11-a accept 경로 = spec", J["accept_check"]["artifact_path"]
          == "docs/design/v12_gate_design.md")
    for topic in ("게이트 산술", "MDE", "예산", "파생층 배포 경계"):
        check(f"R11-b spec 주제 · {topic}", topic in J["accept_check"]["spec_topics_delivered"])
    check("R11-c 문턱 미조정 주장",
          J["headline"]["thresholds_lowered"] == 0
          and J["prereg_compliance"]["thresholds_relaxed"] == 0
          and J["prereg_compliance"]["candidate_maps_created"] == 0)
    # 계약이 실제로 수정되지 않았는지 git 으로 확인
    diff = git("diff", "HEAD", "--name-only", "--",
               "data/contracts/multivariate_timeseries_v12.draft.yaml").strip()
    check("R11-d 계약 파일 워킹트리 무변경", diff == "", diff)
    check("R11-e not_done 에 계약 미개정 명시",
          any("계약 YAML 미개정" in s for s in J["not_done"]))
    check("R11-f 정정 기록", "−0.0046" not in DOCTEXT and "-0.0046" not in DOCTEXT,
          "문서에서 오기 제거 확인")
    check("R11-g 오기 정정을 result 가 기록",
          any("−0.0046" in s or "-0.0046" in s for s in J["key_findings"]))


def main() -> int:
    for fn in (r1_artifacts, r2_commit, r3_inputs, r4_seal, r5_headline, r6_g4,
               r7_g1, r8_budget, r9_boundary, r10_rerun, r11_doc_claims):
        fn()
    failed = [c for c in R if not c[1]]
    for cid, ok, detail in R:
        print(f"[{'PASS' if ok else 'FAIL'}] {cid}" + (f" — {detail}" if detail else ""))
    print(f"\n{len(R) - len(failed)}/{len(R)} PASS")
    if failed:
        print("실패: " + ", ".join(c[0] for c in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
