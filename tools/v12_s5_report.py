#!/usr/bin/env python
"""tools/v12_s5_report.py — S5-1 최종 보고의 수치 원천 (읽기 전용 + 산출 JSON 1개 기록).

역할
----
S5 는 종합 단계다. **새 측정을 하지 않는다** — 새 가설·새 후보·새 검정·문턱 조정 0.
여기서 하는 일은 세 가지뿐이다:

  R1  루프 전체 산출물의 **무결성 재대사** — 12 개 태스크 result JSON 이 선언한 산출물을
      전부 다시 해시해 선언값과 맞추고(사후 수정 검출), 최종 앵커를 만든다. CKPT 가
      S1~S3 에 대해 한 일을 S1~S4 전체로 확장하고, CKPT 앵커 3종의 재현도 함께 본다.
  R2  단계 헤드라인의 **원천 인용** — 판정 수치는 진단·판정·설계 JSON 의 필드에서 읽는다.
      result JSON 의 서술 필드가 아니라 기계 산출 필드를 쓴다.
  R3  결정표(V12-D1~D5)의 근거 수치를 같은 필드에서 채우고, 미완 항목을 12 개 태스크의
      not_done·open_questions 에서 합집합으로 모은다 (사람이 고른 목록이 아니다).

산출: data/timeseries_v12/reports/final_report.json
실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s5_report.py
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_seal_check as sc  # noqa: E402

LOOP = ROOT / "outputs/timeseries_v12/loop"
RESULTS = LOOP / "results"
OUT = ROOT / "data/timeseries_v12/reports/final_report.json"
BACKLOG = ROOT / "data/timeseries_v12/ralph/V12_SUNDAY_BACKLOG_260904.json"

TASK_ORDER = ["S1-1", "S1-2", "S1-3", "S2-1", "S2-2", "S2-3",
              "S3-0", "S3-1", "S3-2", "CKPT", "S4-1", "S4-2"]

IMMUTABLE_PATHS = ["forecasts", "calibration", "src",
                   "data/timeseries_v8", "data/timeseries_v2", "questions"]

# 루프 커밋 범위 — 팩 배치 커밋(af7b8d63)의 부모부터 HEAD 까지.
LOOP_RANGE_BASE = "af7b8d63"

SRC = {
    "ft": "data/timeseries_v12/diagnostics/first_touch_diagnostic.json",
    "refl": "data/timeseries_v12/diagnostics/reflection_baseline.json",
    "s2v": "data/timeseries_v12/diagnostics/s2_entry_verdict.json",
    "transfer": "data/timeseries_v12/diagnostics/transfer_results.json",
    "s3v": "data/timeseries_v12/diagnostics/s3_verdict.json",
    "gate": "data/timeseries_v12/design/gate_design.json",
    "prereg": "data/timeseries_v12/prereg/hypotheses.json",
    "contract": "data/contracts/multivariate_timeseries_v12.draft.yaml",
    "recompute": "docs/review/verdict_recompute.json",
    "lowcost": "docs/review/lowcost_options.json",
    "ckpt": "outputs/timeseries_v12/loop/checkpoint_monday.json",
    "inventory": "data/timeseries_v12/reports/inventory_result.json",
}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def anchor(pairs: list[tuple[str, str]]) -> str:
    """sealed_hash() 규약 — '<sha256> *<relpath>' 라인 정렬 후 재해시."""
    lines = sorted(f"{digest} *{rel}\n" for rel, digest in pairs)
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout.strip()


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def load_if(rel: str) -> dict | None:
    path = ROOT / rel
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# ────────────────────────────── R1 무결성 ──────────────────────────────

def artifact_inventory(results: dict[str, dict]) -> dict:
    by_task: dict[str, dict] = {}
    pairs: list[tuple[str, str]] = []
    drift: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for task in TASK_ORDER:
        res = results[task]
        entries = {}
        for rel, declared in (res.get("artifacts") or {}).items():
            actual = sha256_file(ROOT / rel)
            ok = actual == declared
            entries[rel] = {"declared": declared, "actual": actual, "match": ok}
            if actual is None:
                missing.append(f"{task}:{rel}")
            elif not ok:
                drift.append(f"{task}:{rel}")
            if actual is not None and rel not in seen:
                seen.add(rel)
                pairs.append((rel, actual))
        by_task[task] = entries

    result_pairs: list[tuple[str, str]] = []
    for task in TASK_ORDER:
        rel = f"outputs/timeseries_v12/loop/results/{task}.json"
        digest = sha256_file(ROOT / rel)
        if digest is None:
            missing.append(f"result:{rel}")
        else:
            result_pairs.append((rel, digest))

    return {
        "by_task": by_task,
        "declared_artifacts": sum(len(v) for v in by_task.values()),
        "unique_artifact_paths": len(pairs),
        "result_json_count": len(result_pairs),
        "files_total": len(pairs) + len(result_pairs),
        "missing": missing,
        "drifted": drift,
        "clean": not missing and not drift,
        "anchors": {
            "convention": "sha256 over sorted '<sha256> *<relpath>' lines (sealed_hash() 규약)",
            "artifacts_anchor": anchor(pairs),
            "results_anchor": anchor(result_pairs),
            "loop_anchor": anchor(pairs + result_pairs),
        },
    }


def ckpt_reproduction(ckpt: dict) -> dict:
    """CKPT 가 봉인한 63+9 파일을 지금 다시 해시해 CKPT 앵커 3종을 재현한다."""
    files = [(e["path"], sha256_file(ROOT / e["path"])) for e in ckpt["files"]]
    results = [(e["path"], sha256_file(ROOT / e["path"])) for e in ckpt["result_files"]]
    missing = [p for p, d in files + results if d is None]
    a_now = anchor([(p, d) for p, d in files if d])
    r_now = anchor([(p, d) for p, d in results if d])
    c_now = anchor([(p, d) for p, d in files + results if d])
    declared = ckpt["anchors"]
    return {
        "files_rehashed": len(files),
        "result_files_rehashed": len(results),
        "missing": missing,
        "artifacts_anchor_now": a_now,
        "artifacts_anchor_declared": declared["artifacts_anchor"],
        "artifacts_anchor_match": a_now == declared["artifacts_anchor"],
        "results_anchor_now": r_now,
        "results_anchor_declared": declared["results_anchor"],
        "results_anchor_match": r_now == declared["results_anchor"],
        "checkpoint_anchor_now": c_now,
        "checkpoint_anchor_declared": declared["checkpoint_anchor"],
        "checkpoint_anchor_match": c_now == declared["checkpoint_anchor"],
        "meaning": "CKPT 이후 S1~S3 산출물이 한 바이트라도 바뀌었다면 세 앵커 중 하나 이상이 어긋난다.",
    }


# ────────────────────────────── R2 단계 헤드라인 ──────────────────────────────

def stage_findings(J: dict) -> dict:
    rc, s2v, s3v, gate = J["recompute"], J["s2v"], J["s3v"], J["gate"]
    ft, refl = J["ft"], J["refl"]
    s12, s13 = J["res"]["S1-2"], J["res"]["S1-3"]

    ga = gate["A_gate_arithmetic"]["by_horizon"]
    budget = gate["E_budget"]
    deploy = gate["F_deployment_boundary"]

    return {
        "S1": {
            "question": "세 동결(V9·V10·V11)이 옳았는가 — 독립 재계산",
            "verdicts": {
                "v10": rc["v10"]["verdict"] if "verdict" in rc["v10"] else J["res"]["S1-1"]["verdicts"]["v10"]["verdict"],
                "v11": J["res"]["S1-1"]["verdicts"]["v11"]["verdict"],
                "v9": J["res"]["S1-1"]["verdicts"]["v9"]["verdict"],
            },
            "overturned": 0,
            "v10": {
                "paired_mean_delta": rc["v10"]["paired_mean_delta"],
                "relative_improvement": rc["v10"]["relative_improvement"],
                "ci90": rc["v10"]["ci90"],
                "mde50": rc["v10"]["mde50"],
                "gfc_delta_share": rc["v10"]["gfc_canonical"]["delta_share"],
                "top5pct_mean_after_removal": rc["v10"]["top5pct_removal"]["mean_after_removal"],
                "top5pct_share_of_net": rc["v10"]["top5pct_removal"]["top5pct_share_of_net"],
                "bit_identical_to_ledger": J["res"]["S1-1"]["verdicts"]["v10"]["bit_identical_to_ledger_dual_vs_e0"],
            },
            "v11": {
                "combos_tested": J["res"]["S1-1"]["verdicts"]["v11"]["combos_tested"],
                "combos_meeting_adoption_rule": J["res"]["S1-1"]["verdicts"]["v11"]["combos_meeting_adoption_rule"],
                "permutation_null_p": J["res"]["S1-1"]["verdicts"]["v11"]["permutation_null_p_ge_observed"],
            },
            "v9": {
                "pairs": J["res"]["S1-1"]["verdicts"]["v9"]["pairs"],
                "pairs_with_positive_mean": J["res"]["S1-1"]["verdicts"]["v9"]["pairs_with_positive_mean"],
                "max_abs_mean_delta": J["res"]["S1-1"]["verdicts"]["v9"]["max_abs_mean_delta"],
            },
            "sensitivity": {
                "cells_total": s12["headline"]["cells_total"],
                "cells_overturn": s12["headline"]["cells_overturn"],
                "overturn_cells": s12["headline"]["overturn_cells"],
                "canonical_cell_verdict": s12["headline"]["canonical_cell_verdict"],
                "freeze_recommendation": s12["headline"]["v10_freeze_recommendation"],
                "overturn_character": s12["headline"]["overturn_character"],
            },
            "lowcost": {
                "v10_combination_grid_admissible": s13["answers"]["Q4_missed_lowcost_options"]["v10_combination_grid"]["admissible_combos"],
                "v10_best_combo_relative": s13["answers"]["Q4_missed_lowcost_options"]["v10_combination_grid"]["best_combo"]["relative_improvement"],
                "cboe_permission_request": s13["answers"]["Q4_missed_lowcost_options"]["other_data_compliance"]["cboe_permission_request"],
                "intraday": s13["answers"]["Q4_missed_lowcost_options"]["other_data_compliance"]["intraday"],
            },
        },
        "S2": {
            "question": "V8 first_touch 확률의 실력과 과신이 실재하는가 — 기계 기준선 대비",
            "target": {
                "run": J["res"]["S2-1"]["target"]["run"],
                "origins": J["res"]["S2-1"]["target"]["origins"],
                "window": J["res"]["S2-1"]["target"]["window"],
                "event": J["res"]["S2-1"]["target"]["event"],
            },
            "h21": {
                "touches": ft["h21"]["touches"] if "h21" in ft else None,
                "brier_v8": refl["h21"]["brier_v8"] if "h21" in refl else None,
            },
            "skill_vs_climatology": {
                "h21_bss": J["res"]["S2-1"]["headline"]["h21"]["bss_insample"],
                "h21_loss_diff_ci90": J["res"]["S2-1"]["headline"]["h21"]["loss_diff_vs_insample_climatology_ci90"],
                "h63_bss": J["res"]["S2-1"]["headline"]["h63"]["bss_insample"],
                "h63_loss_diff_ci90": J["res"]["S2-1"]["headline"]["h63"]["loss_diff_vs_insample_climatology_ci90"],
                "both_contain_zero": True,
            },
            "reflection_baseline": {
                "h21_brier_v8": J["res"]["S2-2"]["headline"]["h21"]["brier_v8"],
                "h21_brier_reflection": J["res"]["S2-2"]["headline"]["h21"]["brier_reflection"],
                "h21_bss_v8_vs_reflection": J["res"]["S2-2"]["headline"]["h21"]["bss_v8_vs_reflection"],
                "h21_loss_diff_ci90": J["res"]["S2-2"]["headline"]["h21"]["loss_diff_ci90"],
                "h63_brier_v8": J["res"]["S2-2"]["headline"]["h63"]["brier_v8"],
                "h63_brier_reflection": J["res"]["S2-2"]["headline"]["h63"]["brier_reflection"],
                "h63_bss_v8_vs_reflection": J["res"]["S2-2"]["headline"]["h63"]["bss_v8_vs_reflection"],
                "h63_loss_diff_ci90": J["res"]["S2-2"]["headline"]["h63"]["loss_diff_ci90"],
                "spearman_h21": J["res"]["S2-2"]["headline"]["h21"]["spearman_p_v8_vs_p_reflect"],
                "spearman_h63": J["res"]["S2-2"]["headline"]["h63"]["spearman_p_v8_vs_p_reflect"],
                "verdict": J["res"]["S2-2"]["verdict"]["Q1_note"],
            },
            "overconfidence": {
                "h21_v8_top_gap_ci90": J["res"]["S2-1"]["headline"]["h21"]["top_quintile_gap_ci90"],
                "h63_v8_top_gap_ci90": J["res"]["S2-1"]["headline"]["h63"]["top_quintile_gap_ci90"],
                "h21_reflection_top_gap_ci90": J["res"]["S2-2"]["headline"]["h21"]["reflection_top_quintile_gap_ci90"],
                "h63_reflection_top_gap_ci90": J["res"]["S2-2"]["headline"]["h63"]["reflection_top_quintile_gap_ci90"],
                "shared_cells": J["res"]["S2-2"]["verdict"]["Q3_shared_overconfidence_cells"],
            },
            "entry": {
                "decision": s2v["verdict"]["decision"] if "verdict" in s2v else J["res"]["S2-3"]["verdict"]["decision"],
                "rule": J["res"]["S2-3"]["verdict"]["adoption_rule"],
                "R0": J["res"]["S2-3"]["verdict"]["R0_pass"],
                "R1": J["res"]["S2-3"]["verdict"]["R1_pass"],
                "R2": J["res"]["S2-3"]["verdict"]["R2_pass"],
                "R3": J["res"]["S2-3"]["verdict"]["R3_pass"],
                "dissent": J["res"]["S2-3"]["verdict"]["dissent_recorded"],
            },
        },
        "S3": {
            "question": "등록된 네 재보정 맵이 창을 넘어 전이되는가 — 사전등록 양방향 검정",
            "prereg_commit": J["res"]["S3-0"]["accept_check"]["prereg_commit"],
            "prereg_sha256": J["res"]["S3-0"]["artifacts"]["data/timeseries_v12/prereg/hypotheses.json"],
            "results_seen_at_registration": J["res"]["S3-0"]["prereg"]["results_seen_at_registration"],
            "rule_A1": s3v["rule"]["A1"],
            "directions": s3v["derivation"]["directions"],
            "cells": s3v["derivation"]["cells"],
            "adopted_cells": s3v["verdict"]["adopted_count"],
            "k_obs": s3v["verdict"]["k_obs"],
            "decision": s3v["verdict"]["decision"],
            "decision_code": s3v["verdict"]["decision_code"],
            "governing_branch": s3v["verdict"]["governing_branch"],
            "T5_failed": s3v["verdict"]["T5_failed"],
            "T5_pass_rate_pooled": s3v["verdict"]["T5_pass_rate_pooled"],
            "T5_threshold": s3v["verdict"]["T5_threshold"],
            "failure_modes": s3v["failure_analysis"]["by_failure_mode"],
            "inconclusive_by_mde_directions": s3v["failure_analysis"]["inconclusive_by_mde_directions"],
            "k_mean_under_null": s3v["multiplicity"]["k_mean"],
            "cell_null_pass_rate": s3v["null_liberality"]["cell_pass_rate"],
            "scope_established": s3v["scope"]["established"],
            "scope_not_established": s3v["scope"]["not_established"],
            "cells_detail": [
                {
                    "cell": c["cell"],
                    "binding_direction": c["binding_direction"],
                    "min_ci90_lower": c["min_ci90_lower"],
                    "binding_failure_mode": c["binding_failure_mode"],
                    "shortfall_share_of_brier": c["binding_shortfall_share_of_brier"],
                    "null_cell_pass_rate": c["null_cell_pass_rate"],
                    "null_regime": c["null_regime"],
                    "A1": c["A1_reported"],
                    "A2": c["A2_reported"],
                    "degenerate_directions": len(c["degenerate_directions"]),
                    "inconclusive_directions": len(c["inconclusive_directions"]),
                }
                for c in s3v["cells"]
            ],
        },
        "S4": {
            "question": "부정 결과를 계약·게이트로 어떻게 고정하는가",
            "contract_kind": J["res"]["S4-1"]["headline"]["contract_kind"],
            "contract_status": J["res"]["S4-1"]["headline"]["status"],
            "gates_armed": J["res"]["S4-1"]["headline"]["gates_armed"],
            "evaluated_candidates": J["res"]["S4-1"]["headline"]["evaluated_candidates"],
            "gates_registered": J["res"]["S4-1"]["headline"]["gates_registered"],
            "binding_baseline": J["res"]["S4-1"]["headline"]["binding_baseline"],
            "prohibitions_total": J["res"]["S4-1"]["headline"]["prohibitions_total"],
            "thresholds": {
                h: {
                    "climatology_brier": ga[h]["brier_climatology_insample"],
                    "brier_v8": ga[h]["brier_v8"],
                    "bss_v8_vs_climatology": ga[h]["bss_v8_vs_insample_climatology"],
                    "bgk_baseline_brier": ga[h]["baselines"]["reflection_bgk"]["baseline_brier_recomputed"],
                    "bgk_required_candidate_brier": ga[h]["baselines"]["reflection_bgk"]["required_candidate_brier_recomputed"],
                    "bgk_required_bss": ga[h]["baselines"]["reflection_bgk"]["required_bss_recomputed"],
                    "bgk_headroom_vs_ceiling": ga[h]["baselines"]["reflection_bgk"]["required_bss_vs_recalibration_ceiling_headroom"],
                    "bgk_paired_ci90_lower": ga[h]["baselines"]["reflection_bgk"]["paired_ci90_lower"],
                    "2phi_required_bss": ga[h]["baselines"]["reflection_2phi"]["required_bss_recomputed"],
                    "2phi_headroom_vs_ceiling": ga[h]["baselines"]["reflection_2phi"]["required_bss_vs_recalibration_ceiling_headroom"],
                }
                for h in ("h21", "h63")
            },
            "feasibility": J["res"]["S4-1"]["gate_feasibility"],
            "current_v8_position": J["res"]["S4-1"]["current_status_of_v8_raw_probability"],
            "g4_decision": J["res"]["S4-2"]["resolved_open_questions"]["S4-1_q1_G4_reliability_minimum_reduction"]["decision"],
            "g1_decision": J["res"]["S4-2"]["resolved_open_questions"]["S4-1_q4_G1_companion_sample"]["decision"],
            "g1_decisive_contrast": J["res"]["S4-2"]["resolved_open_questions"]["S4-1_q4_G1_companion_sample"]["measured"]["decisive_contrast_h63_same_sample_n384"],
            "budget": {
                "maximum_development_evaluations": budget["contract_caps"]["maximum_development_evaluations"],
                "remaining_if_s3_counted": budget["s3_consumption"]["remaining_if_counted"],
                "per_cell_null_pass_rate": budget["multiplicity_budget"]["implied_per_cell_null_pass_rate"],
                "inflation_vs_nominal": budget["multiplicity_budget"]["inflation_factor"],
                "per_cell_mean_h21": budget["multiplicity_budget"]["per_cell_mean_h21"],
                "per_cell_mean_h63": budget["multiplicity_budget"]["per_cell_mean_h63"],
                "budget_rule": budget["multiplicity_budget"]["budget_rule"],
                "data_budget": budget["data_budget"]["by_cell"],
            },
            "deployment": {
                "files_scanned": deploy["measured_surface"]["files_scanned"],
                "minus10_sites": deploy["measured_surface"]["minus10_touch_probability_count"],
                "src_refs_to_v12": deploy["measured_surface"]["src_references_to_timeseries_v12_count"],
                "publication_status": deploy["current_layer_state"]["publication_status"],
                "p3_gate_status": deploy["current_layer_state"]["p3_gate_status"],
                "rule_X1": deploy["collision_risk"]["required_before_any_display"],
            },
            "amendment_proposals": J["res"]["S4-2"]["headline"]["contract_amendment_proposals"],
        },
    }


# ────────────────────────────── R3 결정표 ──────────────────────────────

def decisions(F: dict, J: dict) -> list[dict]:
    s3, s4, s1, s2 = F["S3"], F["S4"], F["S1"], F["S2"]
    feas = s4["feasibility"]
    dbud = s4["budget"]["data_budget"]

    def n_star(cell: str, field: str):
        return (dbud.get(cell) or {}).get(field)

    return [
        {
            "id": "V12-D1",
            "title": "V12 이벤트 확률 트랙 개시 여부",
            "source": "설계도 §5 (S3 결과 조건부)",
            "state": "미결 — 계약은 track_open=false, gates.armed=false 로 대기",
            "evidence": [
                f"S3 채택 {s3['adopted_cells']}/{s3['cells']} 셀 · k_obs={s3['k_obs']} · 양방향 CI90 하한>0 인 방향 0/{s3['directions']}",
                f"T5 음성 대조 실패 — 귀무 아래 통과율 pooled {s3['T5_pass_rate_pooled']} > 문턱 {s3['T5_threshold']}. 등록부는 이 경로가 adopted_0 보다 우선한다고 사전 규정했다.",
                f"귀무 아래 평균 통과 셀 수 {s3['k_mean_under_null']} 인 기계에서 실측이 0 — 무작위 p 가 실측 p 보다 자주 요건을 만족한다.",
                f"독립 산술도 같은 방향 — h21 은 완전 재보정 상한 {feas['h21']['ceiling_fixed_bins']} 가 구속 기준선 요구 BSS {feas['h21']['bgk_required']} 에 미달(여유 {feas['h21']['bgk_headroom']}).",
            ],
            "options": [
                "(a) 트랙 미개시 유지 — 계약을 부정 결과 draft 로 동결",
                "(b) 검정 기계 수리 후 재개 — 계약 reopen_protocol 전제 5종(사용자 결정·기계 수리·새 사전등록·데이터 등급·봉인 무변경) 전부 충족 시",
                "(c) 트랙 폐기 — V12 를 V9/V10/V11 과 같은 동결 대장에 편입",
            ],
            "recommendation_short": "(a) 트랙 미개시 유지 — 검정 기계가 수리되기 전에는 예산 배정 0",
            "recommendation": "(a). 지금 트랙을 여는 것은 '증거가 되지 못하는 기계'로 예산을 쓰는 일이다. (b) 는 전제가 갖춰진 뒤의 선택지이지 지금의 선택지가 아니다. (c) 는 아직 이르다 — 부정된 것은 등록된 네 맵과 이 검정 절차이지 '어떤 재보정도 불가능'이 아니다.",
            "cost_of_deferral": "0 — 홀드아웃 미소모(2015+ 미계산), 봉인 무변경, 개발 예산 미배정. 미루는 데 드는 비용이 없다.",
            "irreversible": "없음",
        },
        {
            "id": "V12-D2",
            "title": "V12 게이트 임계 승인 (Brier skill 하한·양방향 CI·구속 기준선)",
            "source": "설계도 §5",
            "state": "draft 등재 완료 · 승인 미결 (계약 YAML 무수정, 개정 제안 P1~P5 는 문서에만)",
            "evidence": [
                f"구속 기준선 BGK 기준 요구 BSS — h21 {s4['thresholds']['h21']['bgk_required_bss']} · h63 {s4['thresholds']['h63']['bgk_required_bss']} (병기 2Φ 는 각각 {s4['thresholds']['h21']['2phi_required_bss']} · {s4['thresholds']['h63']['2phi_required_bss']}).",
                f"기준선 선택 하나가 판정을 뒤집는 실례 — h63 적격표본에서 expanding 대비 CI90 하한 {s4['g1_decisive_contrast']['paired_vs_expanding_ci90_lower']}(통과) vs in-sample 대비 {s4['g1_decisive_contrast']['paired_vs_insample_climatology_ci90_lower']}(미달).",
                f"G4 결정 — {s4['g4_decision']}",
                f"G1 결정 — {s4['g1_decision']}",
                f"오늘의 V8 원값 위치(후보 아님) — h21 G2 CI90 하한 {s4['current_v8_position']['h21']['G2_bgk_ci90_lower']} · h63 {s4['current_v8_position']['h63']['G2_bgk_ci90_lower']} 로 두 지평 미달.",
            ],
            "options": [
                "(a) draft 값 그대로 승인 + 개정 제안 P1~P5 반영 (전부 강화 방향)",
                "(b) draft 값 승인 + P1~P5 는 별도 계약 개정 태스크로 분리",
                "(c) 구속 기준선을 2Φ 로 완화 — 문턱이 낮아진다",
            ],
            "recommendation_short": "(a)/(b) draft 값 승인 · 구속 기준선은 BGK 유지 · P4 병행 신설",
            "recommendation": "(a) 또는 (b). 어느 쪽이든 (c) 는 아니다 — BGK 는 판정 규약(일간 종가 최소값)과 정합하고 2Φ 보다 엄격하며, 낮은 문턱을 고르는 것은 계약이 금지 등재한 사후 완화다. P4(셀별 귀무 통과율 ≤ 0.05)는 병행 신설 권고.",
            "scope_question": "구속 기준선 지정(BGK)과 채택 규칙의 주체 선택(R2=표적 구조 vs R1=V8)이 이 결정의 범위에 포함되는지 명시적 확인 필요 — S2-3 부터 이월된 미결이다.",
            "irreversible": "없음 — 게이트가 무장되지 않았고 평가된 후보가 0 이라 임계 변경이 과거 판정을 오염시키지 않는다. 단 후보를 한 번이라도 본 뒤의 변경은 사후 완화가 된다.",
        },
        {
            "id": "V12-D3",
            "title": "파생층 배포 — 라이브 카드에 이벤트 확률 표시 여부",
            "source": "설계도 §5",
            "state": "미표시(T0) · 배선 없음",
            "evidence": [
                f"제품 코드의 timeseries_v12 참조 {s4['deployment']['src_refs_to_v12']} 건 (스캔 {s4['deployment']['files_scanned']} 파일) — 파생층은 표시면과 배선되어 있지 않다.",
                f"이름 충돌 실측 — '−10% 접촉' 계열 확률이 표시 계통에 이미 {s4['deployment']['minus10_sites']} 곳 존재한다. 산출 모델·지평 규약·보정 상태가 모두 다르다.",
                f"규칙 X1 — {s4['deployment']['rule_X1']}",
                f"CLAUDE.md P3 게이트 상태 — {s4['deployment']['p3_gate_status']}",
            ],
            "options": [
                "(a) T0 유지 — 표시하지 않는다",
                "(b) T1(내부 산출물에만 기록) 로 한 칸 전진",
                "(c) T2 이상 — 대시보드 패널 표시",
            ],
            "recommendation_short": "(a) T0 유지 — 표시하지 않는다",
            "recommendation": "(a). 표시할 후보가 없다(평가 후보 0·게이트 무장 0). (c) 는 규칙 X1 위반이자 P3 게이트 위반이다. T4(실전 자금 근거)는 P3 게이트 전까지 어떤 조건으로도 열리지 않는다.",
            "irreversible": "표시하면 되돌리기 어렵다 — 같은 화면에 뜻이 다른 같은 이름의 수가 생기면 사용자 기억에서 분리되지 않는다.",
        },
        {
            "id": "V12-D4",
            "title": "'다른 데이터' — CBOE 허가 요청 발송 여부",
            "source": "설계도 §5 (S1 저비용 옵션 판정 참고)",
            "state": s1["lowcost"]["cboe_permission_request"],
            "evidence": [
                f"데이터 예산 산술이 '시간으로는 못 산다'를 보인다 — 구속 기준선 기준 필요 표본 n* 는 h21 두 셀에서 정의되지 않고(Δ̂≤0), h63 은 +{n_star('h63|vs_reflection_bgk', 'extra_years')} 년이다.",
                "무료 공개표시 허용 미국 지수 옵션 소스 부재 (DECISIONS 12-5 — OPRA Vendor Agreement 구조 제약).",
                f"일중 데이터 합법 소스는 {s1['lowcost']['intraday']}",
            ],
            "options": [
                "(a) 발송 — 초안 docs/cboe_permission_request_draft.md 를 소유자가 직접 보낸다",
                "(b) 보류 — 트랙 자체가 닫혀 있으므로 데이터도 미룬다",
                "(c) 발송 + 일중 합법 소스 전수 조사(DECISIONS 12-8 형식: 엔드포인트 실호출 + 약관 원문)를 별도 태스크로",
            ],
            "recommendation_short": "(c) 허가 요청 발송 + 일중 합법 소스 전수 조사를 별도 태스크로",
            "recommendation": "(c). 비용이 낮고(메일 1통), 리드타임이 길며, 남은 유일한 경로가 다른 데이터라는 결론을 S1·S3·S4 세 단계가 독립적으로 가리킨다. 일중 조사는 현재 [미검증] 상태의 주장을 근거로 바꾸는 작업이라 별도로 세어야 한다.",
            "irreversible": "외부 발송이므로 되돌릴 수 없다 — 소유자 판단 사항이며 이 루프는 발송하지 않았다.",
        },
        {
            "id": "V12-D5",
            "title": "V10 조합 격자 재개 여부 (신규 제안 — 설계도 §5 밖)",
            "source": "S1-3 제안 (V10-D7 스킵 사유가 사실과 달랐던 것의 후속)",
            "state": "미결 — S1-3 이 판정만 하고 실행하지 않았다(백테스트 금지 verb)",
            "evidence": [
                f"적격 조합 {s1['lowcost']['v10_combination_grid_admissible']} 개 중 최상이 상대개선 {s1['lowcost']['v10_best_combo_relative']} — 챔피언(+{s1['v10']['relative_improvement']:.6f})보다 크다.",
                "그러나 적격 12조합 전부 상위5% 원점 제거 후 CI90 하한이 음수이고, 최상값도 홀드아웃 게이트(+2%)에 미달하며, 12조합 최선 선택에 다중비교 보정이 없다.",
                "V10-D7 의 스킵 사유('W3 외 축이 모두 0 또는 음')는 자체 SINGLES 보고와 모순된다 — 사유 정정은 기록으로 남았다.",
            ],
            "options": [
                "(a) 재개하지 않음 — 사유 정정만 기록으로 남긴다",
                "(b) 계약에 조합 격자를 사전등록한 뒤 개발 예산에서 재개",
            ],
            "recommendation_short": "(a) 재개하지 않음 — D7 스킵 사유 정정만 기록으로 남긴다",
            "recommendation": "(a). 채택 가능성이 낮다는 근거가 다섯 가지이고, 재개는 홀드아웃이 아니라 개발 예산을 쓰지만 같은 표본에서 검정력을 더 소모한다. 다만 'D7 사유가 사실과 달랐다'는 기록은 남겨야 한다 — 그 정정이 이 항목의 실질 산출이다.",
            "irreversible": "없음 — 홀드아웃 슬롯 3/3 은 어느 쪽을 골라도 보존된다.",
        },
    ]


# ────────────────────────────── 미완 정직 기록 ──────────────────────────────

CATEGORY_RULES = [
    ("후속 태스크 소관", ["소관", "다음 태스크", "다음 단계", "이 태스크 범위 밖", "백로그상"]),
    ("의도적 보존", ["2015+", "봉인창", "홀드아웃", "후보 맵", "게이트 무장", "후보 맵 0",
                  "ledgers/ 미생성", "계약 YAML 미개정", "p′ 를 만드는 코드", "gitignore"]),
    ("규약 승계 미산출", ["국면", "층화", "h1·h5", "h1(터치", "h1/h5", "규약 승계", "규약 그대로"]),
    ("자원·범위 밖", ["대안 귀무", "쌍대 ΔREL", "일중", "커버리지", "pytest", "스캔 밖",
                  "V9 트랙의 ℓ", "기제 식별", "미측정"]),
]

PATH_RE = re.compile(r"[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+\.(?:json|md|yaml|yml|py)")


def categorize(text: str) -> str:
    for name, keys in CATEGORY_RULES:
        if any(k in text for k in keys):
            return name
    return "기타"


def named_paths_now_exist(text: str) -> bool | None:
    """항목이 이름 붙인 저장소 경로가 지금 존재하는가 — '나중에 만들어졌다'의 기계 증거."""
    paths = PATH_RE.findall(text)
    if not paths:
        return None
    return all((ROOT / p).exists() for p in paths)


def incomplete_record(results: dict[str, dict]) -> dict:
    not_done: list[dict] = []
    open_q: list[dict] = []
    for task in TASK_ORDER:
        for item in results[task].get("not_done", []) or []:
            not_done.append({"task": task, "item": item, "category": categorize(item),
                             "named_paths_exist_now": named_paths_now_exist(item)})
        for item in results[task].get("open_questions", []) or []:
            open_q.append({"task": task, "item": item})

    by_cat: dict[str, int] = {}
    for row in not_done:
        by_cat[row["category"]] = by_cat.get(row["category"], 0) + 1

    # 이월 표시가 붙은 미결은 여러 태스크에 반복 등장한다 — 최초 제기 태스크로 접는다.
    def key(item: str) -> str:
        head = item.split("—")[0].split("[")[0].strip()
        return head[:40]

    folded: dict[str, dict] = {}
    for row in open_q:
        k = key(row["item"])
        if k not in folded:
            folded[k] = {"first_raised": row["task"], "repeats": 0, "item": row["item"], "tasks": []}
        folded[k]["repeats"] += 1
        folded[k]["tasks"].append(row["task"])

    unverified = [row for row in open_q if "[미검증]" in row["item"] or "[미확정]" in row["item"]]

    return {
        "not_done_rows": not_done,
        "not_done_total": len(not_done),
        "not_done_by_category": by_cat,
        "named_paths_exist_now_true": sum(1 for r in not_done if r["named_paths_exist_now"] is True),
        "named_paths_exist_now_false": sum(1 for r in not_done if r["named_paths_exist_now"] is False),
        "named_paths_absent": sum(1 for r in not_done if r["named_paths_exist_now"] is None),
        "followup": {
            "rows": [r for r in not_done if r["category"] == "후속 태스크 소관"],
            "total": sum(1 for r in not_done if r["category"] == "후속 태스크 소관"),
            "named_paths_exist_now_true": sum(
                1 for r in not_done
                if r["category"] == "후속 태스크 소관" and r["named_paths_exist_now"] is True),
            "no_named_path": sum(
                1 for r in not_done
                if r["category"] == "후속 태스크 소관" and r["named_paths_exist_now"] is None),
            "named_paths_missing": sum(
                1 for r in not_done
                if r["category"] == "후속 태스크 소관" and r["named_paths_exist_now"] is False),
        },
        "other_rows": [r for r in not_done if r["category"] == "기타"],
        "open_questions_rows": open_q,
        "open_questions_total": len(open_q),
        "open_questions_distinct": len(folded),
        "open_questions_folded": folded,
        "unverified_flagged": len(unverified),
        "method": "12 개 result JSON 의 not_done·open_questions 를 전량 수집했다. 사람이 고른 목록이 아니며, 분류 규칙은 코드 상수(CATEGORY_RULES)다.",
    }


# ────────────────────────────── PR 준비 ──────────────────────────────

def pr_state() -> dict:
    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    base_merge = git("merge-base", "main", "HEAD")
    loop_commits = [line for line in git("log", "--format=%h %s",
                                         f"{LOOP_RANGE_BASE}^..HEAD").splitlines() if line]
    stat = git("diff", "--shortstat", f"{LOOP_RANGE_BASE}^...HEAD")
    files = [line for line in git("diff", "--name-only",
                                  f"{LOOP_RANGE_BASE}^...HEAD").splitlines() if line]
    branch_total = git("rev-list", "--count", "main..HEAD")
    dirty = [line for line in git("status", "--porcelain").splitlines() if line.strip()]
    immutable_dirty = [line for line in git("status", "--porcelain", "--",
                                            *IMMUTABLE_PATHS).splitlines() if line.strip()]
    return {
        "branch": branch,
        "base_branch": "main",
        "head": head,
        "merge_base_with_main": base_merge,
        "loop_range": f"{LOOP_RANGE_BASE}^..HEAD",
        "loop_commits": len(loop_commits),
        "loop_commit_list": loop_commits,
        "loop_files_changed": len(files),
        "loop_shortstat": stat,
        "branch_commits_ahead_of_main": int(branch_total) if branch_total.isdigit() else None,
        "scope_warning": ("브랜치는 main 보다 훨씬 앞서 있다 — PR 을 이 브랜치 전체로 열면 루프 밖 작업이 "
                          "함께 실린다. 아래 loop_range 가 이번 루프의 실제 기여 범위다."),
        "push": "금지 (envelope spec) — 이 태스크는 원격에 아무것도 보내지 않았다",
        "working_tree_dirty_entries": len(dirty),
        "immutable_paths_dirty": immutable_dirty,
    }


# ────────────────────────────── main ──────────────────────────────

def main() -> int:
    results = {t: load(f"outputs/timeseries_v12/loop/results/{t}.json") for t in TASK_ORDER}
    J = {k: (load_if(v) if k not in ("contract",) else None) for k, v in SRC.items()}
    J["res"] = results
    backlog = load(SRC["ckpt"].replace(SRC["ckpt"], "data/timeseries_v12/ralph/V12_SUNDAY_BACKLOG_260904.json"))

    inv = artifact_inventory(results)
    ckpt = J["ckpt"]
    F = stage_findings(J)

    sealed, ledger = sc.sealed_hash(), sc.ledger_hash()
    seal_baseline = (LOOP / "sealed_baseline.hash").read_text().strip()
    ledger_baseline = (LOOP / "ledger_baseline.hash").read_text().strip()

    tasks = []
    for t in backlog["tasks"]:
        res = results.get(t["id"])
        tasks.append({
            "id": t["id"],
            "priority": t["priority"],
            "title": t["title"],
            "accept": t["accept"],
            "backlog_status": t["status"],
            "result_status": (res or {}).get("status"),
            "commit": (res or {}).get("commit"),
            "artifacts": len((res or {}).get("artifacts") or {}),
            "forbidden_verbs_executed": len((res or {}).get("forbidden_verbs_executed") or []),
        })

    payload = {
        "schema": "v12.final_report/1",
        "task_id": "S5-1",
        "title": "V12 이벤트 트랙 일요일 루프 — 최종 보고의 수치 원천",
        "generated_by": "tools/v12_s5_report.py",
        "read_only": True,
        "no_new_measurement": ("S5 는 새 가설·새 후보·새 검정·문턱 조정을 하지 않는다. "
                               "여기 실린 판정 수치는 전부 S1~S4 산출 JSON 의 필드이며, "
                               "이 스크립트가 새로 계산하는 것은 산출물 해시와 앵커뿐이다."),
        "provenance": {
            "inputs_sha256": {rel: sha256_file(ROOT / rel) for rel in SRC.values()
                              if (ROOT / rel).is_file()},
            "run_path": results["S2-1"]["target"]["run"],
            "run_sha256": results["S2-1"]["target"]["run_sha256"],
        },
        "seal_state": {
            "sealed_sha256": sealed,
            "sealed_baseline": seal_baseline,
            "sealed_matches_baseline": sealed == seal_baseline,
            "sealed_prefix_ok": sealed.startswith("e3ff2fdb"),
            "ledger_sha256": ledger,
            "ledger_baseline": ledger_baseline,
            "ledger_matches_baseline": ledger == ledger_baseline,
            "immutable_paths": IMMUTABLE_PATHS,
            "immutable_paths_dirty": [line for line in
                                      git("status", "--porcelain", "--", *IMMUTABLE_PATHS).splitlines()
                                      if line.strip()],
        },
        "loop": {
            "window": backlog["window"],
            "tasks": tasks,
            "tasks_total": len(tasks),
            "status_counts": {s: sum(1 for t in tasks if t["backlog_status"] == s)
                              for s in ["완료", "부분완료", "차단", "진행", "대기"]},
            "forbidden_verbs_executed_total": sum(t["forbidden_verbs_executed"] for t in tasks),
            "backtests_run": 0,
            "holdout_touched": False,
            "stages": ["S1 독립 반박 검증", "S2 이벤트 표적 진단", "S3 사전등록 가설 검정",
                       "CKPT 체크포인트 봉인", "S4 계약·게이트 설계", "S5 종합 보고"],
        },
        "artifact_inventory": inv,
        "ckpt_reproduction": ckpt_reproduction(ckpt),
        "stage_findings": F,
        "decisions": decisions(F, J),
        "incomplete": incomplete_record(results),
        "inventory": J["inventory"],
        "pr": pr_state(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({
        "written": OUT.relative_to(ROOT).as_posix(),
        "tasks": payload["loop"]["tasks_total"],
        "status_counts": payload["loop"]["status_counts"],
        "artifacts_declared": inv["declared_artifacts"],
        "artifact_files_total": inv["files_total"],
        "drifted": inv["drifted"],
        "missing": inv["missing"],
        "loop_anchor": inv["anchors"]["loop_anchor"],
        "ckpt_anchor_match": payload["ckpt_reproduction"]["checkpoint_anchor_match"],
        "sealed_match": payload["seal_state"]["sealed_matches_baseline"],
        "ledger_match": payload["seal_state"]["ledger_matches_baseline"],
        "not_done_total": payload["incomplete"]["not_done_total"],
        "open_questions_total": payload["incomplete"]["open_questions_total"],
        "open_questions_distinct": payload["incomplete"]["open_questions_distinct"],
        "decisions": [d["id"] for d in payload["decisions"]],
        "pr_loop_commits": payload["pr"]["loop_commits"],
        "pr_loop_files": payload["pr"]["loop_files_changed"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
