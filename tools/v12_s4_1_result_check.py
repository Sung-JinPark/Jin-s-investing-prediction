#!/usr/bin/env python
"""S4-1 result JSON 자기주장 대사 (읽기 전용).

result JSON 이 적은 모든 수치·주장을 계약 YAML·원천 JSON·git·봉인·검증기 재실행과 맞춘다.
result 가 스스로를 과장하거나 오기하면 여기서 걸린다.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_1_result_check.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "outputs/timeseries_v12/loop/results/S4-1.json"
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml"

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
C = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
TEXT = RESULT.read_text(encoding="utf-8")


def r1_artifacts() -> None:
    for rel, digest in J["artifacts"].items():
        p = ROOT / rel
        check(f"R1 존재 · {rel}", p.is_file())
        if p.is_file():
            check(f"R1 sha256 · {rel}", sha256_file(p) == digest, sha256_file(p)[:12])


def r2_commit() -> None:
    short = J["commit"].split()[0]
    subj = git("log", "-1", "--format=%s", short).strip()
    check("R2-a 커밋 존재", bool(subj), subj)
    check("R2-b 커밋 제목 규약", subj.startswith("loop(v12): S4-1"), subj)
    files = set(git("show", "--name-only", "--format=", short).split())
    for rel in J["artifacts"]:
        check(f"R2-c 커밋에 포함 · {rel}", rel in files)
    check("R2-d accept_check.commit 일치", J["accept_check"]["commit"] == short)
    check("R2-e accept_check.committed", J["accept_check"]["committed"] is True)


def r3_seal() -> None:
    spec = importlib.util.spec_from_file_location(
        "seal_mod", ROOT / "tools/v12_seal_check.py")
    seal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seal)
    sr = J["seal_reconciliation"]
    check("R3-a 봉인 해시", seal.sealed_hash() == sr["sealed_sha256"])
    check("R3-b 원장 해시", seal.ledger_hash() == sr["ledger_sha256"])
    loop = ROOT / "outputs/timeseries_v12/loop"
    check("R3-c baseline 일치 주장", sr["sealed_matches_boot_baseline"] is True
          and sr["sealed_sha256"] == (loop / "sealed_baseline.hash").read_text().strip())
    check("R3-d 원장 baseline 주장", sr["ledger_matches_baseline"] is True
          and sr["ledger_sha256"] == (loop / "ledger_baseline.hash").read_text().strip())
    protected = ["forecasts", "calibration", "src", "data/timeseries_v8",
                 "data/timeseries_v2", "questions"]
    dirty = git("status", "--porcelain", *protected).strip()
    check("R3-e 보호 경로 무변경", dirty == "", dirty[:120])
    contracts = [ln for ln in git("status", "--porcelain", "data/contracts").splitlines()
                 if ln.strip()]
    check("R3-f data/contracts 잔여 변경 0 (커밋 완료)", contracts == [], f"{contracts}")


def r4_accept() -> None:
    ac = J["accept_check"]
    check("R4-a 산출물 경로 = spec 파일명",
          ac["artifact_path"].endswith("multivariate_timeseries_v12.draft.yaml"))
    check("R4-b 파일 존재 주장", ac["artifact_named_in_spec_exists"] is True and CONTRACT.is_file())
    # spec 조항 매핑이 실제 계약 절을 가리키는지 — 조항 문자열이 언급한 최상위 키가 존재해야 한다
    top = set(C)
    referenced = {
        "표적 first_touch h21/h63": "target",
        "게이트 Brier skill vs 기후": "gates",
        "게이트 Brier skill vs 반사원리 기준선": "gates",
        "게이트 양방향 전이": "gates",
        "게이트 reliability": "gates",
        "CRPS 게이트 무손상 제약": "crps_gate_intact",
        "정지점2 승계": "stopping_points",
        "봉인0 승계": "stopping_points",
        "retune 금지 승계": "prohibitions",
        "S3 부정이면 부정결과 계약": "negative_result",
    }
    check("R4-c spec 조항 10개 전부 기재",
          set(ac["spec_clauses_delivered"]) == set(referenced),
          f"{sorted(set(ac['spec_clauses_delivered']) ^ set(referenced))}")
    for clause, key in referenced.items():
        check(f"R4-d 조항이 실제 절을 가리킴 · {clause}", key in top)


def r5_headline() -> None:
    h = J["headline"]
    check("R5-a status", h["status"] == C["status"])
    check("R5-b armed", h["gates_armed"] == C["gates"]["armed"])
    check("R5-c 후보 0", h["evaluated_candidates"] == C["gates"]["evaluated_candidates"])
    check("R5-d 최상위 절 수", h["top_level_sections"] == len(C), f"실제 {len(C)}")
    gate_ids = sorted(k for k in C["gates"] if re.match(r"^G\d_", k))
    check("R5-e 게이트 목록", sorted(h["gates_registered"]) == gate_ids, f"{gate_ids}")
    check("R5-f 구속 기준선",
          h["binding_baseline"] == C["gates"]["G2_skill_vs_reflection"]["binding_baseline"])
    inh = len(C["prohibitions"]["inherited_from_v8_and_v10"])
    spc = len(C["prohibitions"]["v12_specific"])
    check("R5-g 승계 금지 수", h["prohibitions_inherited"] == inh, f"실제 {inh}")
    check("R5-h 고유 금지 수", h["prohibitions_v12_specific"] == spc, f"실제 {spc}")
    check("R5-i 금지 합계", h["prohibitions_total"] == inh + spc)
    check("R5-j 한계 수", h["known_limits"] == len(C["known_limits"]),
          f"실제 {len(C['known_limits'])}")
    check("R5-k 결정 목록", sorted(h["decisions_pending"]) == sorted(C["decisions_pending"]))
    check("R5-l contract_kind", h["contract_kind"] == C["contract_character"]["kind"])


def r6_thresholds() -> None:
    th = C["gates"]["G2_skill_vs_reflection"]["thresholds"]
    for h in ("h21", "h63"):
        g, t = J["gate_thresholds"][h], th[h]
        check(f"R6 기후 Brier {h}", g["climatology_brier"] == t["climatology_brier"])
        check(f"R6 BGK 기준선 {h}", g["bgk_baseline_brier"] == t["vs_reflection_bgk"]["baseline_brier"])
        check(f"R6 BGK 요구 Brier {h}", g["bgk_required_candidate_brier_max"]
              == t["vs_reflection_bgk"]["required_candidate_brier_max"])
        check(f"R6 BGK 요구 BSS {h}", g["bgk_required_bss_min"]
              == t["vs_reflection_bgk"]["required_brier_skill_vs_climatology_min"])
        check(f"R6 2Φ 요구 Brier {h}", g["2phi_required_candidate_brier_max"]
              == t["vs_reflection_2phi"]["required_candidate_brier_max"])
        check(f"R6 2Φ 요구 BSS {h}", g["2phi_required_bss_min"]
              == t["vs_reflection_2phi"]["required_brier_skill_vs_climatology_min"])


def r7_feasibility() -> None:
    fb = C["gate_feasibility_arithmetic"]["by_horizon"]
    for h in ("h21", "h63"):
        g, f = J["gate_feasibility"][h], fb[h]
        check(f"R7 상한 fixed {h}", g["ceiling_fixed_bins"]
              == f["recalibration_ceiling_bss"]["fixed_bins"])
        check(f"R7 상한 quantile {h}", g["ceiling_quantile_bins"]
              == f["recalibration_ceiling_bss"]["quantile_bins"])
        bgk = f["verdict_by_baseline"]["reflection_bgk"]
        check(f"R7 BGK 요구 {h}", g["bgk_required"]
              == bgk["required_brier_skill_vs_climatology_min"])
        check(f"R7 BGK 도달 {h}", g["bgk_reachable"] == bgk["reachable_under_any_binning"])
        check(f"R7 BGK 여유 {h}", g["bgk_headroom"] == bgk["headroom_vs_max_ceiling"])
        two = f["verdict_by_baseline"]["reflection_2phi"]
        check(f"R7 2Φ 요구 {h}", g["2phi_required"]
              == two["required_brier_skill_vs_climatology_min"])
        check(f"R7 2Φ 도달 {h}", g["2phi_reachable_under_any_binning"]
              == two["reachable_under_any_binning"])
    check("R7-b h21 2Φ quantile 도달 주장",
          J["gate_feasibility"]["h21"]["2phi_reachable_under_quantile_binning"]
          == fb["h21"]["verdict_by_baseline"]["reflection_2phi"][
              "reachable_under_quantile_bin_ceiling"])


def r8_current_status() -> None:
    st = C["gates"]["current_status_of_v8_raw_probability"]
    for h in ("h21", "h63"):
        g, s = J["current_status_of_v8_raw_probability"][h], st[h]
        check(f"R8 G1 판정 {h}", g["G1_vs_climatology"] == s["G1_vs_climatology"])
        check(f"R8 G1 하한 {h}", g["G1_ci90_lower"] == s["G1_ci90_lower"])
        check(f"R8 G2 판정 {h}", g["G2_vs_bgk"] == s["G2_vs_reflection_bgk"])
        check(f"R8 G2 하한 {h}", g["G2_bgk_ci90_lower"] == s["G2_bgk_ci90_lower"])
        check(f"R8 G4 유의 {h}", g["G4_overconfidence_significant"]
              == s["G4_overconfidence_still_significant"])


def r9_checker() -> None:
    """검증기를 다시 돌려 result 가 주장한 항목 수·실패 수를 대사한다."""
    spec = importlib.util.spec_from_file_location(
        "s4_check_mod", ROOT / "tools/v12_s4_contract_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in (mod.v1_seal, mod.v2_inputs, mod.v3_character, mod.v4_verdict, mod.v5_thresholds,
               mod.v6_feasibility, mod.v7_crps, mod.v8_measured, mod.v9_prereg_quotes,
               mod.v10_banned, mod.v11_stops, mod.v12_holdout, mod.v13_deterministic,
               mod.v14_mde, mod.v15_accept):
        fn()
    total = len(mod.RESULTS)
    failed = [c for c, ok, _ in mod.RESULTS if not ok]
    claimed = int(re.search(r"(\d+)항목", J["verification"]["total"]).group(1))
    check("R9-a 검증기 실패 0", not failed, f"{failed[:3]}")
    check("R9-b 항목 수 주장 일치", claimed == total, f"주장 {claimed} · 실제 {total}")
    # 그룹별 항목 수 — result 의 V<n> 문자열이 숫자를 적었다면 실제와 맞아야 한다
    groups = Counter(re.match(r"(V\d+)", cid).group(1) for cid, _, _ in mod.RESULTS)
    for key, text in J["verification"].items():
        if not re.match(r"^V\d+$", key):
            continue
        m = re.search(r"(\d+)\s*항목", text)
        if not m:
            check(f"R9-c {key} 항목 수 미기재", True, f"실제 {groups.get(key, 0)}")
            continue
        check(f"R9-c {key} 항목 수", int(m.group(1)) == groups.get(key, 0),
              f"주장 {m.group(1)} · 실제 {groups.get(key, 0)}")
    print("  [group counts] " + json.dumps(dict(sorted(groups.items(),
          key=lambda kv: int(kv[0][1:]))), ensure_ascii=False))


def r10_prose_numbers() -> None:
    """산문이 인용한 수치가 계약·원천과 일치하는지."""
    fb = C["gate_feasibility_arithmetic"]["by_horizon"]
    th = C["gates"]["G2_skill_vs_reflection"]["thresholds"]
    pairs = [
        ("h21 BGK 요구 BSS", f"{th['h21']['vs_reflection_bgk']['required_brier_skill_vs_climatology_min']:.6f}"),
        ("h21 상한", f"{fb['h21']['recalibration_ceiling_bss']['fixed_bins']:.6f}"),
        ("h21 여유", f"{fb['h21']['verdict_by_baseline']['reflection_bgk']['headroom_vs_max_ceiling']:.6f}"),
        ("h63 여유", f"{fb['h63']['verdict_by_baseline']['reflection_bgk']['headroom_vs_max_ceiling']:.6f}"),
    ]
    prose = " ".join(J["key_findings"])
    for name, token in pairs:
        check(f"R10 산문 수치 · {name}", token in prose, token)
    # MDE 차이 주장
    rb = json.loads((ROOT / "data/timeseries_v12/diagnostics/reflection_baseline.json")
                    .read_text(encoding="utf-8"))
    s2 = json.loads((ROOT / "data/timeseries_v12/diagnostics/s2_entry_verdict.json")
                    .read_text(encoding="utf-8"))
    diff = abs(rb["per_horizon"]["21"]["paired"]["v8_vs_reflection"]["ci90"]["mde50"]
               - s2["gate_arithmetic"]["h21"]["reflection_2phi"]["mde_1645se"])
    check("R10-b MDE 차이 주장", f"{diff:.2e}".replace("e-0", "e-0") in prose,
          f"실제 {diff:.2e}")
    check("R10-c 금지 수 주장", "21종" in prose and "31" in json.dumps(J["headline"]))


def r11_not_done() -> None:
    nd = " ".join(J["not_done"])
    check("R11-a gate_design.md 부재 주장",
          not (ROOT / "docs/design/v12_gate_design.md").exists()
          and "v12_gate_design.md 미작성" in nd)
    check("R11-b ledgers 디렉터리 부재",
          not (ROOT / "data/timeseries_v12/ledgers").exists()
          and C["development_protocol"]["ledger_exists"] is False)
    check("R11-c 홀드아웃 산출물 0",
          not list((ROOT / "data/timeseries_v12").rglob("*holdout*")))
    check("R11-d 금지 verb 실행 0 주장", J["forbidden_verbs_executed"] == []
          and all(v == 0 for v in C["stopping_points"]["loop_execution_record"].values()))
    check("R11-e next_task", J["next_task"] == "S4-2")
    check("R11-f status", J["status"] == "완료")


def r12_prereg_compliance() -> None:
    pc = J["prereg_compliance"]
    s3 = json.loads((ROOT / "data/timeseries_v12/diagnostics/s3_verdict.json")
                    .read_text(encoding="utf-8"))
    check("R12-a 분기 주장", pc["branch_used"].startswith(s3["verdict"]["governing_branch"]))
    check("R12-b 분기 원문 인용", C["negative_result"]["s4_contract_mandate"]
          == s3["verdict"]["s4_contract"])
    check("R12-c 기준선 교체 없음 주장", pc["baseline_swapped_to_easier"] is False)
    # 실제로 BGK 가 더 엄격한지 재확인 (주장과 사실 일치)
    s2 = json.loads((ROOT / "data/timeseries_v12/diagnostics/s2_entry_verdict.json")
                    .read_text(encoding="utf-8"))
    stricter = all(s2["gate_arithmetic"][h]["reflection_bgk"]["required_candidate_brier"]
                   < s2["gate_arithmetic"][h]["reflection_2phi"]["required_candidate_brier"]
                   for h in ("h21", "h63"))
    check("R12-d BGK 가 실제로 더 엄격", stricter)
    check("R12-e K 조항 5종 전부 기재",
          set(pc["K_constraints_honored"]) == set(C["negative_result"]["carryover_clauses_from_s3"]))
    check("R12-f 사후 추가 공시 존재", len(pc["post_hoc_additions_declared"]) >= 3)


def main() -> int:
    for fn in (r1_artifacts, r2_commit, r3_seal, r4_accept, r5_headline, r6_thresholds,
               r7_feasibility, r8_current_status, r9_checker, r10_prose_numbers,
               r11_not_done, r12_prereg_compliance):
        fn()
    failed = [(c, d) for c, ok, d in R if not ok]
    for c, ok, d in R:
        if not ok:
            print(f"FAIL  {c}  {d}")
    print(json.dumps({"checks_total": len(R), "checks_failed": len(failed),
                      "failed_ids": [c for c, _ in failed]}, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
