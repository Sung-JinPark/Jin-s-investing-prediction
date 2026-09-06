#!/usr/bin/env python
"""tools/v12_s3_1_result_check.py — S3-1 result JSON 의 주장 재대사 (읽기 전용).

result JSON 은 사람이 읽는 요약이므로 수기 전사 오류가 들어갈 수 있다(S2-3 에서 실제로 2건 발생).
이 스크립트는 ``outputs/timeseries_v12/loop/results/S3-1.json`` 이 적어 둔 **모든 수치**를
``transfer_results.json``·git·봉인 해시와 대사한다. 반올림 주장은 round(원값, 6) 과 비교한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

RESULT = "outputs/timeseries_v12/loop/results/S3-1.json"
TRANSFER = "data/timeseries_v12/diagnostics/transfer_results.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def r6(v: float) -> float:
    return round(float(v), 6)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", default=RESULT)
    args = ap.parse_args()

    res = json.loads((ROOT / args.result).read_text(encoding="utf-8"))
    tr = json.loads((ROOT / TRANSFER).read_text(encoding="utf-8"))
    recs = {(r["hypothesis_id"], r["horizon"], r["direction"]): r for r in tr["records"]}
    cells = {(c["hypothesis_id"], c["horizon"]): c for c in tr["cells"]}

    checks: list[dict[str, Any]] = []

    def add(cid: str, name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"id": cid, "name": name, "pass": bool(ok), "detail": detail})

    # ---------------------------------------------------------------- R1 아티팩트
    art_fail = []
    for path, claimed in res["artifacts"].items():
        actual = _sha256(ROOT / path)
        if actual != claimed:
            art_fail.append(f"{path}: {actual} != {claimed}")
    add("R1-a", "artifacts sha256 5종 일치", not art_fail, art_fail or list(res["artifacts"]))
    add("R1-b", "transfer_results.json 이 spec 이 요구한 산출물 경로",
        res["accept_check"]["artifact_path"] == TRANSFER
        and (ROOT / TRANSFER).is_file(), TRANSFER)

    # ---------------------------------------------------------------- R2 봉인
    seal = json.loads(subprocess.run(
        [sys.executable, str(ROOT / "tools/v12_seal_check.py")],
        capture_output=True, text=True, cwd=str(ROOT)).stdout)
    sr = res["seal_reconciliation"]
    add("R2-a", "봉인 해시 주장 = 실측 = baseline",
        sr["sealed_sha256"] == seal["sealed"] == seal["sealed_baseline"], seal["sealed"])
    add("R2-b", "원장 해시 주장 = 실측 = baseline",
        sr["ledger_sha256"] == seal["ledger"] == seal["ledger_baseline"], seal["ledger"])
    dirty = subprocess.run(["git", "status", "--porcelain", "--",
                            "forecasts", "calibration", "src", "data/timeseries_v8",
                            "data/timeseries_v2", "questions"],
                           capture_output=True, text=True, cwd=str(ROOT)).stdout.strip()
    add("R2-c", "봉인 대상 경로 git 무변경", dirty == "", dirty or "clean")
    add("R2-d", "V8 run sha256 이 등록부 값과 동일",
        tr["target"]["run_sha256"] == "38dde7a8d029f2f02000d6174f995da52cdc2428e072926f0d8b08067e0a6727",
        tr["target"]["run_sha256"])

    # ---------------------------------------------------------------- R3 커밋
    log = subprocess.run(["git", "log", "--oneline", "-6"],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout
    add("R3", "산출물 커밋 2020047f 이 이력에 존재", "2020047f" in log,
        log.splitlines()[:3])

    # ---------------------------------------------------------------- R4 headline
    hl = res["headline"]
    t5 = tr["t5_negative_control"]
    add("R4-a", "채택 셀 0 · k_obs 0",
        hl["adopted_cells"] == len(tr["verdict"]["adopted_cells_final"]) == 0
        and hl["k_obs"] == tr["adoption"]["k_obs"] == 0, tr["adoption"]["adopted_cells"])
    add("R4-b", "T5 실패 여부·통과율·문턱 일치",
        hl["T5_failed"] == t5["failed"] is True
        and r6(hl["T5_pass_rate_pooled"]) == r6(t5["pass_rate_pooled"])
        and {k: r6(v) for k, v in hl["T5_pass_rate_by_cell"].items()}
        == {k: r6(v) for k, v in t5["pass_rate_by_cell"].items()}
        and hl["T5_threshold"] == t5["threshold"],
        {"pooled": t5["pass_rate_pooled"], "by_cell": t5["pass_rate_by_cell"]})
    add("R4-c", "S4 계약 문자열이 산출물 verdict 와 동일",
        hl["s4_contract"] == tr["verdict"]["s4_contract"], tr["verdict"]["s4_contract"])

    # ---------------------------------------------------------------- R5 multiplicity
    ml = res["multiplicity"]
    n = tr["multiplicity_null"]
    ok = (ml["replicates"] == n["replicates"] == 1000
          and ml["k_distribution"] == n["k_distribution"]
          and r6(ml["k_mean"]) == r6(n["k_mean"])
          and ml["k_max"] == n["k_max"]
          and {k: r6(v) for k, v in ml["cell_pass_rate_under_null"].items()}
          == {k: r6(v) for k, v in n["cell_pass_rate"].items()}
          and ml["family_claim_supported"] == n["family_claim_supported"]
          and ml["computational_fallback_used"]
          == tr["method"]["permutation_null"]["computational_fallback_used"] is False
          and ml["inner_bootstrap_replicates"]
          == tr["method"]["permutation_null"]["inner_bootstrap_replicates"] == 2000)
    add("R5-a", "귀무 분포·평균·최대·셀별 통과율·fallback 미사용 일치", ok, n["k_distribution"])
    add("R5-b", "실측 소요 주장이 산출물 timing 과 ±0.5s 이내",
        abs(ml["measured_runtime_sec"] - tr["timing"]["null_sec"]) <= 0.5,
        tr["timing"]["null_sec"])
    pge = res["accept_check"]["p_ge_k_reported"]
    add("R5-c", "P(k≥j) 표 j=1..8 일치",
        all(r6(pge["P(k>=j)"][str(j)]) == r6(n["p_k_ge"][str(j)]) for j in range(1, 9)),
        n["p_k_ge"])
    add("R5-d", "P(k≥k_obs) = 1.0 (k_obs=0 이라 자명)",
        pge["P(k>=k_obs)"] == n["p_k_ge_kobs"] == 1.0, n["p_k_ge_kobs"])

    # ---------------------------------------------------------------- R6 16 결과 발췌
    r16 = res["results_16"]
    bad: list[str] = []

    def cmp_dir(key: str, hyp: str, h: int, direction: str, claim: dict[str, Any]) -> None:
        rec = recs[(hyp, h, direction)]
        if "delta" in claim and r6(rec["delta"]) != r6(claim["delta"]):
            bad.append(f"{key}/{direction}.delta {rec['delta']} vs {claim['delta']}")
        if "ci90" in claim:
            if [r6(rec["ci90_lower"]), r6(rec["ci90_upper"])] != [r6(v) for v in claim["ci90"]]:
                bad.append(f"{key}/{direction}.ci90 "
                           f"[{rec['ci90_lower']},{rec['ci90_upper']}] vs {claim['ci90']}")
        for pkey in ("lambda", "w"):
            if pkey in claim and r6(rec["fitted_parameter"]) != r6(claim[pkey]):
                bad.append(f"{key}/{direction}.{pkey} {rec['fitted_parameter']} vs {claim[pkey]}")
        if "A1" in claim and rec["A1_pass"] != claim["A1"]:
            bad.append(f"{key}/{direction}.A1")
        if "degenerate" in claim and rec["degenerate"] != claim["degenerate"]:
            bad.append(f"{key}/{direction}.degenerate {rec['degenerate']!r}")

    for key, block in r16.items():
        if key in ("convention", "note", "rounding"):
            continue
        hyp, hs = key.split("_h")
        h = int(hs)
        for direction, claim in block.items():
            if direction in ("early_to_late", "late_to_early", "early_window", "late_window"):
                cmp_dir(key, hyp, h, direction, claim)
            elif direction == "lambda_star":
                for d in ("early_to_late", "late_to_early"):
                    if r6(recs[(hyp, h, d)]["fitted_parameter"]) != r6(claim):
                        bad.append(f"{key}.lambda_star {recs[(hyp, h, d)]['fitted_parameter']}")
            elif direction == "monotonicity_violations":
                for d in ("early_window", "late_window"):
                    if recs[(hyp, h, d)]["monotonicity_violations"] != claim:
                        bad.append(f"{key}.violations")
    add("R6-a", "results_16 발췌가 records 원값(6자리 반올림)과 일치", not bad, bad or "일치")
    add("R6-b", "발췌가 8 셀 전부를 덮음",
        {k for k in r16 if k not in ("convention", "note", "rounding")}
        == {f"{h}_h{hz}" for h in ("T1", "T2", "T3", "T4") for hz in (21, 63)},
        sorted(k for k in r16 if k not in ("convention", "note", "rounding")))

    # ---------------------------------------------------------------- R7 표본 사실
    sf = res["sample_facts_verified"]
    m = tr["method"]["split"]
    touch = {"h21_early": recs[("T1", 21, "late_to_early")]["touches_eval"],
             "h21_late": recs[("T1", 21, "early_to_late")]["touches_eval"],
             "h63_early": recs[("T1", 63, "late_to_early")]["touches_eval"],
             "h63_late": recs[("T1", 63, "early_to_late")]["touches_eval"]}
    brier = {"h21_early": recs[("T1", 21, "late_to_early")]["brier_p"],
             "h21_late": recs[("T1", 21, "early_to_late")]["brier_p"],
             "h63_early": recs[("T1", 63, "late_to_early")]["brier_p"],
             "h63_late": recs[("T1", 63, "early_to_late")]["brier_p"]}
    tau = {"h21_early": recs[("T1", 21, "early_to_late")]["tau"],
           "h21_late": recs[("T1", 21, "late_to_early")]["tau"],
           "h63_early": recs[("T1", 63, "early_to_late")]["tau"],
           "h63_late": recs[("T1", 63, "late_to_early")]["tau"]}
    ok = (sf["split"]["early"] == m["n"]["early"] == 209
          and sf["split"]["late"] == m["n"]["late"] == 208
          and sf["split"]["boundary"] == m["boundary"]
          and sf["touches"] == touch
          and {k: r6(v) for k, v in sf["brier_p_by_window"].items()} == {k: r6(v) for k, v in brier.items()}
          and {k: r6(v) for k, v in sf["tau_by_window"].items()} == {k: r6(v) for k, v in tau.items()}
          and sf["monotonicity_violations_full_sample"]
          == tr["t4_full_sample"]["h21"]["monotonicity_violations"] == 0
          and sf["p_reflect_identical_to_S2_2"]
          == all(v["identical"] for v in tr["target"]["p_reflect_reconciliation"].values()))
    add("R7", "표본 사실(분할·터치·창별 Brier·τ·단조·p_reflect) 일치", ok,
        {"touches": touch, "tau": tau})

    # ---------------------------------------------------------------- R8 산문 수치
    prose_fail: list[str] = []
    # (1) 결정적 증거 없음 — 셀 5개 / 방향 9개
    inc_cells = sum(1 for c in tr["cells"] if c["inconclusive_by_mde"])
    inc_dirs = sum(1 for r in tr["records"] if r["inconclusive_by_mde"])
    if not (inc_cells == 5 and inc_dirs == 9):
        prose_fail.append(f"inconclusive cells={inc_cells} dirs={inc_dirs} (주장 5/9)")
    # (2) 상단집합 구조 14·9·156·151
    us = tr["upper_set_transfer_structure"]
    want = {"h21_early_to_late": 14, "h21_late_to_early": 156,
            "h63_early_to_late": 9, "h63_late_to_early": 151}
    for k, v in want.items():
        if us[k]["eval_upper_set_n"] != v:
            prose_fail.append(f"{k} upper={us[k]['eval_upper_set_n']} (주장 {v})")
    # (3) h63 전→후 상위5% 제거 시 Δ=0
    r63 = recs[("T1", 63, "early_to_late")]
    if not (r63["delta_after_top5pct_drop"] == 0.0 and r63["concentration_sign_vanishes"]
            and r6(r63["mde_1645se"]) == 0.002988):
        prose_fail.append("h63 e2l 소멸/MDE 주장 불일치")
    # (4) T1 h63 후→전 MDE/BS = 37.0%
    if round(recs[("T1", 63, "late_to_early")]["mde_share_of_brier"], 3) != 0.37:
        prose_fail.append("h63 l2e MDE/BS 주장 불일치")
    # (5) T3 전→후 CI90 상한 < 0 (두 지평)
    for h, up in ((21, -1.0e-05), (63, -0.000123)):
        rec = recs[("T3", h, "early_to_late")]
        if not (rec["ci90_upper"] < 0 and r6(rec["ci90_upper"]) == r6(up)):
            prose_fail.append(f"T3 h{h} e2l CI 상한 {rec['ci90_upper']}")
    # (6) T3 후→전 w*=0 두 지평
    if not all(recs[("T3", h, "late_to_early")]["fitted_parameter"] == 0.0 for h in (21, 63)):
        prose_fail.append("T3 l2e w*=0 주장 불일치")
    # (7) T2 정보누출 방향 = 후→전 두 지평만
    leak = {(r["horizon"], r["direction"]) for r in tr["records"]
            if r["hypothesis_id"] == "T2" and r.get("uses_eval_window_information")}
    if leak != {(21, "late_to_early"), (63, "late_to_early")}:
        prose_fail.append(f"T2 누출 방향 {sorted(leak)}")
    # (8) A2 통과 방향 5개, 그 중 T4 두 개
    a2 = [(r["hypothesis_id"], r["horizon"], r["direction"]) for r in tr["records"] if r["A2_pass"]]
    if not (len(a2) == 5 and sum(1 for x in a2 if x[0] == "T4") == 2):
        prose_fail.append(f"A2 통과 {a2}")
    # (9) T4 네 레코드 Δ=0 · 위반 0
    if not all(recs[("T4", h, f"{w}_window")]["delta"] == 0.0
               for h in (21, 63) for w in ("early", "late")):
        prose_fail.append("T4 Δ=0 주장 불일치")
    add("R8", "key_findings 산문 수치 9종 재대사", not prose_fail, prose_fail or "9/9 일치")

    # ---------------------------------------------------------------- R9 사전등록 준수
    pc = res["prereg_compliance"]
    add("R9-a", "레코드 16·셀 8 (생략 0 주장과 일치)",
        len(tr["records"]) == 16 and len(tr["cells"]) == 8 and pc["cells_dropped"] == 0,
        len(tr["records"]))
    add("R9-b", "채택 규칙 문자열이 산출물 adoption.rule_A1 과 같은 뜻",
        tr["adoption"]["rule_A1"].startswith("양방향"), tr["adoption"]["rule_A1"])
    add("R9-c", "등록부 sha256 이 S3-0 result 기록과 동일",
        tr["prereg"]["sha256"] == json.loads(
            (ROOT / "outputs/timeseries_v12/loop/results/S3-0.json").read_text(encoding="utf-8")
        )["artifacts"]["data/timeseries_v12/prereg/hypotheses.json"], tr["prereg"]["sha256"])
    add("R9-d", "사후 추가 항목이 선언돼 있고 채택 요건이 아님",
        len(pc["post_hoc_additions_declared"]) == 2
        and pc["hypotheses_added_after_results"] == 0 and pc["knobs_changed_after_results"] == 0,
        pc["post_hoc_additions_declared"])

    # ---------------------------------------------------------------- R10 미완 주장
    add("R10-a", "S3-2 판정문서 미작성 주장이 사실",
        not (ROOT / "docs/design/v12_s3_verdict.md").exists(), "docs/design/v12_s3_verdict.md")
    add("R10-b", "홀드아웃 미접촉 — 평가 원점이 2015 이전",
        tr["target"]["holdout_policy"].startswith("2015+"), tr["target"]["holdout_policy"])
    add("R10-c", "status='완료' 이고 accept 산출물이 존재",
        res["status"] == "완료" and (ROOT / TRANSFER).is_file(), res["status"])

    failed = [c for c in checks if not c["pass"]]
    print(json.dumps({"checks": len(checks), "failed": len(failed), "items": checks},
                     ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
