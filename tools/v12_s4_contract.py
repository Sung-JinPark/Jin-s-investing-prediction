#!/usr/bin/env python
"""S4-1 — V12 계약 draft 생성기 (읽기 전용 재분석 + 계약 파일 1개 쓰기).

`data/contracts/multivariate_timeseries_v12.draft.yaml` 를 만든다. 계약에 실리는 모든 수치는
S2/S3 산출 JSON 과 V8 계약 원문에서 **읽어서** 채운다 — 사람이 옮겨 적는 수치는 0 이다
(등록부 reporting_contract.numbers_from_scripts_only 승계).

S3-2 판정이 NEGATIVE_RESULT 이므로 이 계약은 **부정 결과 계약**이다. 게이트는 산술까지
사전등록하되 `armed: false` 로 두며, 어떤 후보도 평가되지 않았다. 판정을 '조건부 통과' 로
되살리는 서술은 S3-2 이월 조항 C-S4-contract 위반이라 이 스크립트가 스스로 금지어를 검사한다.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_contract.py [--print]
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml"

SRC = {
    "ft": "data/timeseries_v12/diagnostics/first_touch_diagnostic.json",
    "rb": "data/timeseries_v12/diagnostics/reflection_baseline.json",
    "s2": "data/timeseries_v12/diagnostics/s2_entry_verdict.json",
    "s3": "data/timeseries_v12/diagnostics/s3_verdict.json",
    "pre": "data/timeseries_v12/prereg/hypotheses.json",
    "prelog": "data/timeseries_v12/prereg/prereg_commit_log.json",
    "ckpt": "outputs/timeseries_v12/loop/checkpoint_monday.json",
    "v8": "data/contracts/multivariate_timeseries_v8.yaml",
    "v10": "data/contracts/multivariate_timeseries_v10.yaml",
}

# 계약 본문에서 **긍정형으로** 쓰이면 안 되는 서술 (C-S4-contract — 부정 결과를 되살리는 어휘).
# 부정·금지문 안의 인용(예: "조건부 통과가 아니다")은 조항 자체라 허용하되, 허용한 줄을
# 출력에 공시한다. 공시 없이 통째로 면제하면 검사가 무의미해지기 때문이다.
BANNED_PHRASES = ["조건부 통과", "조건부통과", "사실상 통과", "잠정 채택", "유망하다", "잠정 통과"]
NEGATION_MARKERS = ["아니다", "금지", "위반", "무효"]


def scan_banned(text: str) -> tuple[list, list]:
    """(위반, 공시된 면제) — 금지 어휘가 부정문 밖에서 쓰였는지 줄 단위로 본다."""
    violations, exempted = [], []
    for lineno, line in enumerate(text.split("\n"), 1):
        for phrase in BANNED_PHRASES:
            if phrase not in line:
                continue
            if any(m in line for m in NEGATION_MARKERS):
                exempted.append({"line": lineno, "phrase": phrase, "text": line.strip()[:120]})
            else:
                violations.append({"line": lineno, "phrase": phrase, "text": line.strip()[:120]})
    return violations, exempted


def loop_kst(epoch: int) -> str:
    """epoch → KST 문자열. 고정 오프셋 +09:00 이라 실행 시각에 의존하지 않는다."""
    from datetime import datetime, timedelta, timezone

    return datetime.fromtimestamp(epoch, timezone(timedelta(hours=9))).strftime(
        "%Y-%m-%d %H:%M KST")


def sha256_file(rel: str) -> str:
    h = hashlib.sha256()
    with (ROOT / rel).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def r(x, nd=6):
    """계약에 싣는 소수 자리 통일 — 원값 재포맷일 뿐 재계산이 아니다."""
    return None if x is None else round(float(x), nd)


# ── 입력 ────────────────────────────────────────────────────────────────────
FT = load_json(SRC["ft"])
RB = load_json(SRC["rb"])
S2 = load_json(SRC["s2"])
S3 = load_json(SRC["s3"])
PRE = load_json(SRC["pre"])
PRELOG = load_json(SRC["prelog"])
CKPT = load_json(SRC["ckpt"])
V8 = yaml.safe_load((ROOT / SRC["v8"]).read_text(encoding="utf-8"))
V10 = yaml.safe_load((ROOT / SRC["v10"]).read_text(encoding="utf-8"))

HORIZONS = ["21", "63"]


def ci(node: dict) -> dict:
    """paired 블록에서 계약이 쓰는 필드만 추린다 (원값 재포맷 — 재계산 없음).

    mde50 은 S2-1/S2-2 진단이 저장한 값(승수 리터럴 1.645)을 그대로 옮긴다. S2-3
    gate_arithmetic 의 mde_1645se 는 정규분위 정확값 1.6448536… 을 썼으므로 두 값은
    소수 6째 자리에서 갈린다 — mde_convention 이 그 사실을 계약 본문에 남긴다.
    """
    c = node["ci90"]
    return {
        "loss_diff": r(node["loss_diff"]),
        "ci90_lower": r(c["ci90_lower"]),
        "ci90_upper": r(c["ci90_upper"]),
        "bootstrap_se": r(c["bootstrap_se"]),
        "mde50": r(c["mde50"]),
        "n": node["n"],
    }


def mde_convention() -> dict:
    """두 상류 규약의 차이를 계량해 공시한다 (은폐 금지 — 판정은 바꾸지 않는다)."""
    se = RB["per_horizon"]["21"]["paired"]["v8_vs_reflection"]["ci90"]["bootstrap_se"]
    diag = RB["per_horizon"]["21"]["paired"]["v8_vs_reflection"]["ci90"]["mde50"]
    gate = S2["gate_arithmetic"]["h21"]["reflection_2phi"]["mde_1645se"]
    return {
        "diagnostic_multiplier": "리터럴 1.645 (S2-1·S2-2 진단의 mde50)",
        "gate_multiplier": "정규분위 정확값 z(0.95) (S2-3 gate_arithmetic 의 mde_1645se)",
        "worked_example_h21_reflection_2phi": {
            "bootstrap_se": r(se, 9),
            "diagnostic_mde50": r(diag, 9),
            "gate_mde_1645se": r(gate, 9),
            "absolute_difference": r(abs(diag - gate), 9),
            "implied_gate_multiplier": r(gate / se, 7),
        },
        "effect_on_verdicts": "차이는 소수 6째 자리이며 이 계약의 어떤 판정도 바꾸지 않는다. "
                              "게이트 문턱은 gate_arithmetic 규약을 따르고, 진단 표는 mde50 을 "
                              "그대로 싣는다 — 두 규약을 섞어 유리한 쪽을 고르는 것은 금지.",
    }


def measured_state() -> dict:
    out = {}
    for h in HORIZONS:
        ph = FT["per_horizon"][h]
        rh = RB["per_horizon"][h]
        ga = S2["gate_arithmetic"][f"h{h}"]
        mq = ph["murphy_quantile_bins"]
        mf = ph["murphy_fixed_bins"]
        out[f"h{h}"] = {
            "n": ph["n"],
            "touches": ph["touches"],
            "base_rate": r(ph["base_rate"]),
            "brier_v8_first_touch": r(ph["brier"]),
            "climatology_brier_insample": r(ph["climatology_brier_insample"]),
            "brier_skill_vs_insample_climatology": r(ph["brier_skill_vs_insample_climatology"]),
            "expanding_climatology": {
                "eligible_n": ph["expanding_climatology"]["eligible_n"],
                "climatology_brier": r(ph["expanding_climatology"]["expanding_climatology_brier"]),
                "model_brier_on_eligible": r(ph["expanding_climatology"]["model_brier_on_eligible"]),
                "brier_skill": r(ph["expanding_climatology"]["bss_vs_expanding"]),
            },
            "murphy_decomposition": {
                "quantile_bins": {
                    "reliability": r(mq["reliability"]),
                    "resolution": r(mq["resolution"]),
                    "uncertainty": r(mq["uncertainty"]),
                    "binning_residual": r(mq["binning_residual"]),
                },
                "fixed_bins": {
                    "reliability": r(mf["reliability"]),
                    "resolution": r(mf["resolution"]),
                    "uncertainty": r(mf["uncertainty"]),
                    "binning_residual": r(mf["binning_residual"]),
                },
            },
            "top_quintile_overconfidence": {
                "v8_gap": r(S2["rules"]["horizons"][f"h{h}"]["v8_top_gap"]),
                "v8_gap_ci90_lower": r(S2["rules"]["R1"]["ci90_lower"][f"h{h}"]),
                "reflection_gap": r(S2["rules"]["horizons"][f"h{h}"]["reflection_top_gap"]),
                "reflection_gap_ci90_lower": r(S2["rules"]["R2"]["ci90_lower"][f"h{h}"]),
            },
            "paired_v8_vs_climatology": ci(rh["paired"]["v8_vs_climatology"]),
            "paired_v8_vs_reflection_2phi": ci(rh["paired"]["v8_vs_reflection"]),
            "paired_v8_vs_reflection_bgk": ci(
                rh["variants"]["discrete_monitoring_bgk"]["paired_v8_vs_variant"]),
            "auc": r(ph["auc"]),
            "gate_reference_brier": {
                "reflection_2phi_baseline_brier": r(ga["reflection_2phi"]["baseline_brier"]),
                "reflection_bgk_baseline_brier": r(ga["reflection_bgk"]["baseline_brier"]),
            },
        }
    return out


def gate_thresholds() -> dict:
    """게이트 문턱 — 전부 S2 gate_arithmetic 의 실측 파생값. 임의 상수 0."""
    out = {}
    for h in HORIZONS:
        ga = S2["gate_arithmetic"][f"h{h}"]
        out[f"h{h}"] = {
            "climatology_brier": r(ga["climatology_brier"]),
            "vs_reflection_2phi": {
                "baseline_brier": r(ga["reflection_2phi"]["baseline_brier"]),
                "mde_1645se": r(ga["reflection_2phi"]["mde_1645se"]),
                "required_candidate_brier_max": r(ga["reflection_2phi"]["required_candidate_brier"]),
                "required_brier_skill_vs_climatology_min": r(
                    ga["reflection_2phi"]["required_bss_vs_climatology"]),
            },
            "vs_reflection_bgk": {
                "baseline_brier": r(ga["reflection_bgk"]["baseline_brier"]),
                "mde_1645se": r(ga["reflection_bgk"]["mde_1645se"]),
                "required_candidate_brier_max": r(ga["reflection_bgk"]["required_candidate_brier"]),
                "required_brier_skill_vs_climatology_min": r(
                    ga["reflection_bgk"]["required_bss_vs_climatology"]),
            },
        }
    return out


def feasibility() -> dict:
    """게이트 도달 가능성 산술 — 완전 재보정 상한 vs 요구 BSS.

    상한 = 1 − (BS − REL)/BS_기후 (Murphy REL 을 0 으로 만든 가상 후보). REL 이 binning 에
    의존하므로 두 binning 을 모두 싣는다. 이 산술은 문턱을 낮추지 않는다 — 낮추기 금지는
    prohibitions.gate_threshold_relaxation.
    """
    out = {}
    for h in HORIZONS:
        ga = S2["gate_arithmetic"][f"h{h}"]
        prc = ga["perfect_recalibration_ceiling"]
        ceil_fixed = prc["murphy_fixed_bins"]["bss_if_rel_zero"]
        ceil_quant = prc["murphy_quantile_bins"]["bss_if_rel_zero"]
        row = {
            "recalibration_ceiling_bss": {
                "fixed_bins": r(ceil_fixed),
                "quantile_bins": r(ceil_quant),
                "max": r(ga["ceiling_max_bss"]),
            },
            "verdict_by_baseline": {},
        }
        for name in ("reflection_2phi", "reflection_bgk"):
            req = ga[name]["required_bss_vs_climatology"]
            row["verdict_by_baseline"][name] = {
                "required_brier_skill_vs_climatology_min": r(req),
                "reachable_under_fixed_bin_ceiling": bool(req <= ceil_fixed),
                "reachable_under_quantile_bin_ceiling": bool(req <= ceil_quant),
                "reachable_under_any_binning": bool(req <= max(ceil_fixed, ceil_quant)),
                "headroom_vs_max_ceiling": r(max(ceil_fixed, ceil_quant) - req),
            }
        out[f"h{h}"] = row
    return out


def gate_current_status() -> dict:
    """오늘의 V8 원값이 각 게이트에 어떻게 서 있는지 — 후보 평가가 아니라 현상 기록."""
    out = {}
    for h in HORIZONS:
        rh = RB["per_horizon"][h]
        g1 = rh["paired"]["v8_vs_climatology"]["ci90"]["ci90_lower"]
        g2a = rh["paired"]["v8_vs_reflection"]["ci90"]["ci90_lower"]
        g2b = rh["variants"]["discrete_monitoring_bgk"]["paired_v8_vs_variant"]["ci90"]["ci90_lower"]
        g4 = S2["rules"]["R2"]["ci90_lower"][f"h{h}"]
        out[f"h{h}"] = {
            "G1_vs_climatology": "미달" if g1 <= 0 else "충족",
            "G1_ci90_lower": r(g1),
            "G2_vs_reflection_2phi": "미달" if g2a <= 0 else "충족",
            "G2_2phi_ci90_lower": r(g2a),
            "G2_vs_reflection_bgk": "미달" if g2b <= 0 else "충족",
            "G2_bgk_ci90_lower": r(g2b),
            "G4_overconfidence_still_significant": bool(g4 > 0),
            "G4_top_quintile_gap_ci90_lower": r(g4),
        }
    return out


def build() -> list:
    """(주석, 키, 값) 순서 목록 — 계약 본문."""
    inputs = {rel: sha256_file(rel) for rel in
              (SRC["ft"], SRC["rb"], SRC["s2"], SRC["s3"], SRC["pre"], SRC["v8"], SRC["v10"])}
    v = S3["verdict"]
    der = S3["derivation"]
    fa = S3["failure_analysis"]
    mult = S3["multiplicity"]
    tgt = PRE["target"]

    sections = []

    sections.append((
        None,
        "schema_version", 1))
    sections.append((None, "contract_id", "multivariate_timeseries_v12"))
    sections.append((None, "model_id", "derived.first_touch_event_probability_v12"))
    sections.append((None, "model_version", 12))
    sections.append((
        "status = negative_result_draft — '개발 중' 이 아니다. 트랙이 개시되지 않았고\n"
        "게이트는 한 번도 무장되지 않았다. S3-2 판정(NEGATIVE_RESULT)이 이 상태의 근거다.",
        "status", "negative_result_draft"))
    sections.append((None, "track", "event_probability_first_touch"))
    sections.append((
        None, "supersedes",
        "none — V9·V10·V11 은 각각 동결됐고 이 계약은 그것들을 대체하지 않는다."))
    sections.append((None, "drafted_by", "tools/v12_s4_contract.py (S4-1, V12 일요일 Opus 루프)"))
    sections.append((None, "drafted_during", {
        "loop_window_start_kst": loop_kst(CKPT["window"]["start_epoch"]),
        "loop_deadline_kst": loop_kst(CKPT["window"]["deadline_epoch"]),
        "stage": "S4-1",
    }))

    sections.append((
        "이 계약이 무엇인가 — 성격을 본문 맨 앞에 못박는다. S3-2 이월 조항 C-S4-contract:\n"
        "'계약 draft 를 조건부 통과로 되살리는 서술은 등록부 위반'.",
        "contract_character", {
            "kind": "negative_result_contract",
            "meaning": "표적·기준선·게이트 산술을 사전등록하되, 이 표본에서 채택 가능한 후보가 "
                       "없음을 계약 본문에 확정한다. 게이트는 armed=false 이며 어떤 후보도 평가되지 않았다.",
            "is_not": [
                "개시 승인이 아니다 — 트랙 개시는 사용자 결정 V12-D1.",
                "조건부 통과가 아니다 — 통과·잠정통과·유예 어느 것도 아니다.",
                "V8 분포 계약의 개정이 아니다 — V8 계약의 어떤 좌표도 건드리지 않는다.",
                "실전 자금 결정 근거가 아니다 — CLAUDE.md P3 게이트 미통과. 게이트 수치의 정본은 "
                "CLAUDE.md 이며 여기에 옮겨 적지 않는다.",
            ],
            "authority_order": [
                "docs/design/V12_EVENT_TRACK_SUNDAY_OPUS_LOOP_DESIGN_260904.md §1·§2 (설계 정본)",
                "data/timeseries_v12/prereg/hypotheses.json (S3 등록부 — 규칙 정본)",
                "data/timeseries_v12/diagnostics/s3_verdict.json (S3-2 판정 — 결과 정본)",
                "이 계약은 위 셋을 완화하지 않는다. 충돌 시 위가 이긴다.",
            ],
        }))

    sections.append((
        "출처 — 이 계약의 모든 수치는 아래 파일에서 읽었다. 파일이 바뀌면 해시로 걸린다.",
        "provenance", {
            "design_doc": "docs/design/V12_EVENT_TRACK_SUNDAY_OPUS_LOOP_DESIGN_260904.md",
            "prereg_commit": PRELOG["prereg_commit"]["commit"],
            "prereg_blob_sha1": PRELOG["registered_artifacts"][SRC["pre"]]["git_blob_sha1"],
            "prereg_committed_kst": PRELOG["prereg_commit"]["author_date"],
            "prereg_immutability_rule": PRELOG["immutability_rule"],
            "checkpoint_anchor": CKPT["anchors"]["checkpoint_anchor"],
            "loop_head_commit_at_checkpoint": CKPT["head_commit"],
            "inputs_sha256": inputs,
            "numbers_from_scripts_only": True,
        }))

    sections.append((
        "S3-2 판정의 전재 — 요약이 아니라 판정 JSON 의 필드 그대로다.",
        "negative_result", {
            "decision": v["decision"],
            "decision_code": v["decision_code"],
            "adopted_cells": v["adopted_cells"],
            "adopted_count": v["adopted_count"],
            "k_obs": v["k_obs"],
            "family_cells": PRE["multiplicity"]["family_size"],
            "directions_evaluated": der["directions"],
            "directions_with_ci90_lower_gt_0": fa["by_failure_mode"]["하한>0"],
            "failure_modes": {
                "ci90_lower_below_zero": fa["by_failure_mode"]["하한<0"],
                "ci90_lower_equal_zero_map_inert": fa["by_failure_mode"]["하한=0"],
            },
            "negative_control_T5": {
                "failed": v["T5_failed"],
                "pass_rate_pooled": r(v["T5_pass_rate_pooled"], 4),
                "threshold": v["T5_threshold"],
                "meaning": f"귀무로 섞은 p 로도 채택 요건이 pooled "
                           f"{v['T5_pass_rate_pooled'] * 100:.1f}% 확률로 충족된다 — "
                           f"이 검정 기계가 낸 '통과' 는 증거로 쓸 수 없었다.",
                "interpretation_limit": S3["rule"]["T5_interpretation_limit"],
            },
            "permutation_null": {
                "replicates": PRE["multiplicity"]["null"]["replicates"],
                "k_mean_under_null": r(mult["k_mean"], 3),
                "p_k_ge_kobs": r(v["p_k_ge_kobs"], 4),
                "family_claim_supported": v["family_claim_supported"],
            },
            "governing_branch": v["governing_branch"],
            "branches_fired": v["branches_fired"],
            "branch_precedence": v["branch_precedence"],
            "s4_contract_mandate": v["s4_contract"],
            "s4_contract_source": v["s4_contract_source"],
            "established": [
                "이 표본·이 창·이 분할에서 사전등록된 네 파생층 맵(T1~T4) 중 어느 것도 "
                "두 방향 모두에서 Brier 개선의 CI90 하한을 0 위로 올리지 못했다.",
                "T3(반사 앵커 혼합)은 전→후 두 지평에서 CI90 상한이 0 미만 — 미달을 넘어 악화다.",
                "T4(지평 단조 제약)는 이 표본에서 위반 0 건이라 무비용이자 무효과다.",
                "음성 대조 T5 가 실패했다 — 검정 기계 결함의 증거다.",
            ],
            "not_established": [
                "'V8 first_touch 가 잘 보정돼 있다' 가 아니다 — S2-1 과신 구조는 그대로다.",
                "'어떤 재보정도 불가능하다' 가 아니다 — 부정된 것은 등록된 네 맵과 이 검정 절차다.",
                "'V8 이 반사원리 기준선을 이긴다/진다' 를 새로 말하지 않는다 — 풀표본 판정(S2-2)이 정본.",
                "2015+ 봉인창에 대한 어떤 주장도 아니다 — 홀드아웃 미계산.",
            ],
            "carryover_clauses_from_s3": {
                "C-S4-contract": "이 계약을 '조건부 통과' 로 되살리는 서술 금지.",
                "C-null-redesign": "결과를 본 뒤 귀무를 갈아끼워 판정을 되살리는 것 금지.",
                "C-gate-arith": "기준선을 바꿔 문턱을 낮추는 것은 근거 명문화 없이 금지.",
                "C-split-contrast": "S2-3 분할창 대비를 S3/S4 근거로 인용 금지.",
                "C-holdout": "2015+ 봉인창 미계산 유지 — 부정 결과가 홀드아웃을 여는 근거가 되지 않는다.",
            },
        }))

    sections.append((
        "표적 — 설계도 §1·등록부 target 승계. 판정기준은 첫 예측 이후 변경 금지(CLAUDE.md).",
        "target", {
            "event": "first_touch — 지평 내 지수 경로 최소값 ≤ 0.90 × S0 (원점 대비 −10% first-passage)",
            "resolution_source": "일간 종가 최소값 (연속 모니터링 아님 — 기준선 선택의 근거)",
            "y": tgt["y"],
            "p": tgt["p"],
            "asset": V8["target"]["asset"],
            "series_id": V8["target"]["series_id"],
            "horizons_sessions": tgt["horizons"],
            "horizons_excluded": {
                "values": tgt["horizons_excluded"]["values"],
                "reason": tgt["horizons_excluded"]["reason"],
            },
            "origin_frequency": V8["evaluation"]["origin_frequency"],
            "sample": {
                "run_path": tgt["run_path"],
                "run_sha256": tgt["run_sha256"],
                "experiment_label": tgt["experiment_label"],
                "n_origins": tgt["n_origins"],
                "window": tgt["window"],
            },
            "split": {
                "boundary": PRE["split"]["boundary"],
                "early_n": PRE["split"]["early"]["n_expected"],
                "late_n": PRE["split"]["late"]["n_expected"],
                "frozen": PRE["split"]["frozen"],
            },
        }))

    sections.append((
        "확률 계약 — 파생층 전용. V8 분포를 만들지도 바꾸지도 않는다.",
        "probability_contract", {
            "space": "derived_event_probability_v12",
            "stored_unit": "fraction",
            "bounds": [0.0, 1.0],
            "layer": "derived_from_v8_first_touch_probability",
            "derived_layer_constraint": tgt["derived_layer_constraint"],
            "combine_with_official_forecasts": False,
            "combine_with_scenario_v5_2": False,
            "combine_with_v8_surface": False,
            "publication_status": "not_published",
            "p3_gate_status": "미통과 — 모든 출력은 '참고 의견' 지위 (CLAUDE.md 하드 게이트)",
        }))

    sections.append((
        "선행자 불변 — V8/V2 봉인 0바이트. 루프 전 구간 대사된 해시를 계약에 핀으로 박는다.",
        "predecessor_immutability", {
            "v8_contract": "data/contracts/multivariate_timeseries_v8.yaml",
            "v8_contract_sha256": inputs[SRC["v8"]],
            "v8_status": V8["status"],
            "v8_frozen_on": str(V8["freeze_note"]["frozen_on"]),
            "sealed_source_hash": CKPT["seal_reconciliation"]["sealed_sha256"],
            "sealed_hash_convention": CKPT["seal_reconciliation"]["source"],
            "v8_ledger_hash": CKPT["seal_reconciliation"]["ledger_sha256"],
            "immutable": True,
            "retune_prohibited": True,
            "v2_benchmark_retune_prohibited": V8["v2_benchmark"]["retune_prohibited"],
            "immutable_paths": CKPT["immutable_paths_checked"],
            "fail_closed": "위 해시 중 하나라도 달라지면 이 계약 아래의 어떤 평가도 무효다.",
        }))

    dev_gate = {k: val for k, val in V8["dev_gate_proxy"].items() if k != "revision_history"}
    sections.append((
        "CRPS 게이트 무손상 제약 — V8 계약의 분포 게이트를 값 그대로 복제해 싣는다.\n"
        "V12 는 이 값을 바꾸지 않고, 이 게이트의 판정을 다시 열지도 않는다. V8 은 이미 PASS 상태이며\n"
        "파생층은 분포를 건드리지 않으므로 CRPS 판정에 영향이 없어야 한다 — 그 '없음' 이 제약이다.",
        "crps_gate_intact", {
            "principle": "V12 이벤트 확률 트랙은 V8 분포 계층의 CRPS/coverage 게이트를 무손상으로 둔다.",
            "v8_gate_is_settled": "V8 은 design·holdout proxy 를 이미 통과했고, 이 계약은 그 판정을 "
                                  "재개하지도 번복하지도 않는다.",
            "no_damage_requirements": [
                "V8 run·분포 산출물·봉인 원장에 쓰기 0 (data_policy.v8_store_write=prohibited).",
                "파생층 p′ 는 새 배열로만 존재하며 CRPS·coverage 계산 입력에 들어가지 않는다.",
                "CRPS 게이트 수치의 완화·재산정 금지 — 아래 복제값은 참조 사본이지 개정 대상이 아니다.",
                "파생층 도입이 V8 게이트 여유(margin)를 바꿀 수 없음을 배포 전 대사한다.",
            ],
            "copied_from": "data/contracts/multivariate_timeseries_v8.yaml (값 무변경 복제)",
            "dev_gate_proxy": dev_gate,
            "publication_gate": V8["publication_gate"],
            "operational_gate": V8["operational_gate"],
        }))

    sections.append((
        "기준선 — 게이트가 이길 것을 요구하는 상대. 기후는 하한, 반사원리는 실질 상대다.\n"
        "판정이 일간 종가 기준이므로 이산 모니터링 보정판(BGK)이 정합 기준선이고, 연속식 2Φ 는\n"
        "구조적으로 터치를 과대추정한다 — 그래서 BGK 가 더 엄격한 쪽이며 구속 기준선으로 등록한다.",
        "baselines", {
            "climatology_insample": {
                "definition": "표본 기저율 상수 예측 (in-sample)",
                "role": "하한 기준선 — 이기지 못하면 skill 주장 불가",
                "caveat": "in-sample 이라 낙관 편의. 병기 기준선은 expanding_climatology.",
            },
            "climatology_expanding": {
                "definition": FT["method"]["expanding_climatology"],
                "role": "표본외 기후 — 병기 의무",
            },
            "reflection_2phi": {
                "formula": RB["baseline"]["formula"],
                "sigma": RB["baseline"]["sigma"],
                "barrier_k_over_s": RB["baseline"]["barrier_k_over_s"],
                "free_parameters": 0,
                "assumptions": RB["baseline"]["assumptions"],
                "known_biases": RB["baseline"]["known_biases"],
                "role": "보조 기준선 (연속 모니터링 가정)",
            },
            "reflection_bgk": {
                "definition": RB["per_horizon"]["21"]["variants"]["discrete_monitoring_bgk"]["note"],
                "beta": r(RB["per_horizon"]["21"]["variants"]["discrete_monitoring_bgk"]["beta"]),
                "beta_note": "β 는 지평에 의존하지 않는 보정 상수다 — h21·h63 이 같은 값인 것은 "
                             "복제 오류가 아니라 정의상 그렇다.",
                "beta_identical_across_horizons": bool(
                    RB["per_horizon"]["21"]["variants"]["discrete_monitoring_bgk"]["beta"]
                    == RB["per_horizon"]["63"]["variants"]["discrete_monitoring_bgk"]["beta"]),
                "free_parameters": 0,
                "role": "구속 기준선 — 판정 규약(일간 종가)과 정합하며 2Φ 보다 엄격하다",
                "binding": True,
            },
            "baseline_swap_prohibited": "결과를 본 뒤 구속 기준선을 2Φ 로 바꿔 문턱을 낮추는 것은 "
                                        "C-gate-arith 위반이다.",
        }))

    sections.append((
        "실측 현황 — S2 가 계측한 V8 first_touch 의 상태. 후보 평가가 아니라 출발점 기록이다.",
        "measured_state_v8_first_touch", measured_state()))

    sections.append((
        "MDE 규약 차 — 상류 두 산출물이 서로 다른 승수를 쓴다. 계량해 공시하고, 유리한 쪽을\n"
        "골라 쓰는 것을 금지한다.",
        "mde_convention", mde_convention()))

    sections.append((
        "게이트 — 산술까지 사전등록하되 armed=false. 어떤 후보도 이 게이트로 평가된 적이 없다.\n"
        "문턱은 전부 S2 실측에서 유도된 값이며 임의 상수는 없다.",
        "gates", {
            "armed": False,
            "armed_reason": "S3-2 부정 결과 — 채택 후보 0. 무장 조건은 reopen_protocol 참조.",
            "evaluated_candidates": 0,
            "unit_of_judgement": "셀 = (후보, 지평). 지평·후보 간 합산 채택 금지 (등록부 no_pooling).",
            "G0_crps_no_damage": {
                "rule": "V8 봉인 해시·원장 해시가 baseline 과 일치하고 V8 store 쓰기 0.",
                "hard": True,
                "failure_action": "계약 아래 모든 평가 무효",
            },
            "G1_skill_vs_climatology": {
                "rule": "두 지평 모두 후보 vs 기후 쌍대 손실차의 CI90 하한 > 0.",
                "strict_inequality": True,
                "both_horizons_required": True,
                "companion_obligation": "expanding climatology 대비 값을 병기한다 (eligible_n 차이 공시).",
            },
            "G2_skill_vs_reflection": {
                "rule": "두 지평 모두 후보 vs 구속 기준선(reflection_bgk) 쌍대 손실차의 CI90 하한 > 0.",
                "binding_baseline": "reflection_bgk",
                "companion_baseline": "reflection_2phi (병기 의무 — 판정에는 쓰지 않는다)",
                "point_estimate_form": "BS_후보 ≤ BS_기준선 − 1.645·se (S2-2 규약)",
                "rationale": PRE["adoption"]["secondary"]["rationale"],
                "thresholds": gate_thresholds(),
            },
            "G3_bidirectional_transfer": {
                "rule": PRE["adoption"]["primary"]["rule"],
                "source": PRE["adoption"]["primary"]["source"],
                "frozen": PRE["adoption"]["primary"]["frozen"],
                "directions": [d["id"] for d in PRE["estimation_protocol"]["directions"]],
                "fit_objective": PRE["estimation_protocol"]["fit_objective"],
                "frozen_nuisance": PRE["estimation_protocol"]["frozen_nuisance"],
                "test_statistic": PRE["estimation_protocol"]["test_statistic"],
                "uncertainty": {
                    "bootstrap": PRE["uncertainty"]["bootstrap"]["type"],
                    "block_length": PRE["uncertainty"]["bootstrap"]["block_length"],
                    "replicates": PRE["uncertainty"]["bootstrap"]["replicates"],
                    "seed": PRE["uncertainty"]["bootstrap"]["seed"],
                    "interval": PRE["uncertainty"]["bootstrap"]["interval"],
                },
            },
            "G4_reliability": {
                "rule": "후보의 Murphy reliability 가 두 binning 모두에서 V8 실측값보다 작고, "
                        "상위분위 과신 gap(예측 − 관측)의 CI90 하한이 두 지평 모두 0 이하로 내려간다.",
                "subject_of_gap": "표적 구조 — 반사 기준선 기준(S2-3 R2). 주체 선택은 사용자 결정 V12-D2.",
                "current_v8_reliability": {
                    f"h{h}": {
                        "quantile_bins": r(FT["per_horizon"][h]["murphy_quantile_bins"]["reliability"]),
                        "fixed_bins": r(FT["per_horizon"][h]["murphy_fixed_bins"]["reliability"]),
                    } for h in HORIZONS},
                "current_gap_ci90_lower_must_fall_below_zero": {
                    f"h{h}": r(S2["rules"]["R2"]["ci90_lower"][f"h{h}"]) for h in HORIZONS},
                "note": "reliability 는 binning 의존량이다. 한 binning 만 인용해 통과를 주장하는 것 금지.",
            },
            "G5_reporting_obligations": {
                "mde": PRE["uncertainty"]["mde_obligation"]["rule"],
                "concentration": PRE["uncertainty"]["concentration_obligation"]["rule"],
                "no_cell_dropping": "모든 셀·방향을 미달·퇴화 포함 전수 보고한다.",
                "negative_control_required": "T5 류 음성 대조를 동반하지 않은 채택 주장은 무효.",
                "multiplicity": PRE["multiplicity"]["family_claim_threshold"],
            },
            "current_status_of_v8_raw_probability": gate_current_status(),
            "current_status_note": "이 줄은 '오늘의 V8 원값이 게이트 앞에 어떻게 서 있는가' 의 기록이지 "
                                   "후보 평가가 아니다. 게이트는 armed=false 다.",
        }))

    sections.append((
        "게이트 도달 가능성 산술 — 재보정만으로 구속 기준선을 넘을 수 있는가.\n"
        "상한 = 완전 재보정(REL=0) 가상 후보의 BSS. 상한 < 요구치면 '재보정 경로로는 도달 불가' 다.",
        "gate_feasibility_arithmetic", {
            "definition": S2["gate_arithmetic"]["definition"],
            "by_horizon": feasibility(),
            "reading": "h21 은 구속 기준선(BGK) 요구치가 재보정 상한을 넘어선다 — 상단 수축류 재보정만으로는 "
                       "도달할 수 없다는 뜻이며, S3 의 부정 결과와 같은 방향을 가리킨다. h63 은 상한 안에 "
                       "들어오지만 여유가 좁다.",
            "caveat": "상한은 REL 이 in-sample 추정이라 그 자체로 낙관 편의를 안는다. 따라서 "
                      "'도달 가능' 은 가능성 진술이지 예측이 아니다.",
            "does_not_lower_thresholds": "이 산술은 문턱을 조정하는 근거가 아니다 (C-gate-arith).",
        }))

    sections.append((
        "정지점 2 — V9/V10 헌법 승계. 자동 소모 경로는 코드에 존재하지 않는다.",
        "stopping_points", {
            "count": 2,
            "holdout": {
                "window": [str(x) for x in V8["model"]["windows"]["holdout"]],
                "requires_explicit_user_approval": True,
                "consumption": "finalist 당 1회, 자동 소모 금지",
                "execution_path": "absent_by_construction — 이 단계의 CLI·하네스에 해당 verb 부재",
                "current_state": "미소모 — V12 는 홀드아웃을 열지 않았다 (C-holdout)",
            },
            "sealed": {
                "window": [str(x) for x in V8["model"]["windows"]["sealed"]],
                "maximum_disclosures_per_model_version":
                    V8["model"]["sealed_evaluation"]["maximum_disclosures_per_model_version"],
                "requires_explicit_user_signoff": True,
                "separate_session_required": True,
                "retune_after_failure":
                    V8["model"]["sealed_evaluation"]["retune_after_failure"],
                "current_state": "미실행 — V12 루프의 봉인 실행 0회",
            },
            "loop_execution_record": {
                "backtest_runs": 0,
                "holdout_runs": 0,
                "sealed_runs": 0,
                "refresh_runs": 0,
                "push": 0,
            },
        }))

    sections.append((
        "개발 규율 — 트랙이 열리지 않았으므로 예산은 0 이다. 열릴 때 적용될 규약만 등록한다.",
        "development_protocol", {
            "track_open": False,
            "evaluations_spent": 0,
            "maximum_development_evaluations": V8["development_protocol"][
                "maximum_development_evaluations"],
            "design_window_only_for_iteration": True,
            "holdout_maximum_finalists": V8["development_protocol"]["holdout_maximum_finalists"],
            "experiment_ledger": "data/timeseries_v12/ledgers/development_experiments.jsonl",
            "ledger_append_only": True,
            "ledger_exists": (ROOT / "data/timeseries_v12/ledgers").exists(),
            "preregistered_hypotheses_exhausted": [h["id"] for h in PRE["hypotheses"]],
            "exhausted_meaning": "T1~T4 는 이 표본에서 소진됐다. 같은 표본에 다섯 번째 맵을 사후에 "
                                 "만들어 다시 재는 것은 등록부 no_post_hoc_hypotheses 위반이다.",
        }))

    sections.append((
        "재개 프로토콜 — 이 부정 결과를 뒤집는 유일한 경로. 되살리기가 아니라 새 검정이다.",
        "reopen_protocol", {
            "only_path": "다른 데이터 (사용자 결정 V12-D4)",
            "why": "부정된 것은 이 표본·이 창·이 분할에서의 네 맵과 이 검정 기계다. 같은 표본에서 "
                   "다섯 번째 맵을 만드는 것도, 귀무를 갈아끼우는 것도 금지돼 있다.",
            "preconditions_all_required": [
                "P1 사용자 결정 V12-D1(트랙 개시) 및 V12-D4(다른 데이터) 승인.",
                f"P2 검정 기계 수리 — T5 실패(pooled {v['T5_pass_rate_pooled']})의 원인을 "
                f"규명하고, 수리된 기계가 새 음성 대조를 통과함을 결과 보기 전에 보인다.",
                "P3 새 사전등록 — 가설·문턱·귀무·분할을 결과 보기 전 커밋. 기존 등록부의 재사용이 "
                "아니라 새 등록이다.",
                "P4 새 데이터의 PIT·영수증 등급이 data_policy 를 만족한다.",
                "P5 V8/V2 봉인 해시 무변경.",
            ],
            "prohibited_shortcuts": [
                "같은 표본에서 T5 이후 가설 추가 (no_post_hoc_hypotheses).",
                "결과를 본 뒤 귀무 교체로 판정 되살리기 (C-null-redesign).",
                "구속 기준선을 완화해 문턱 낮추기 (C-gate-arith).",
                "S2-3 분할창 대비를 채택 근거로 인용 (C-split-contrast).",
                "홀드아웃 조기 개봉으로 표본 늘리기 (C-holdout).",
            ],
            "compliance_wall": "설계도 §0 — 옵션 표면·일중 데이터는 CBOE 허가 미발송·합법 일중 소스 "
                               "부재로 현재 루프 밖이다. V12-D4 는 그 벽을 여는 결정이기도 하다.",
        }))

    # 승계는 선언이 아니라 집합 연산이다 — V8·V10 금지 키의 합집합을 통째로 싣고,
    # 그 위에 V12 고유 조항을 얹는다. 누락은 v12_s4_contract_check.py 가 기계로 잡는다.
    inherited = {k: True for k in sorted(set(V8["prohibitions"]) | set(V10["prohibitions"]))}
    v12_specific = {
        "crps_gate_threshold_relaxation": True,
        "gate_threshold_relaxation": True,
        "binding_baseline_swap_after_results": True,
        "post_hoc_hypotheses_on_same_sample": True,
        "null_redesign_after_results": True,
        "revive_negative_result_as_conditional_pass": True,
        "split_contrast_as_adoption_evidence": True,
        "backtest_of_llm_questions": True,
        "forecasts_directory_write": True,
        "publication_without_p3_gate": True,
    }
    sections.append((
        "금지 — V8·V10 계약 금지 키의 합집합을 전부 승계하고 V12 고유 조항을 얹는다.\n"
        "true = 금지된 행위. 승계 누락은 검증기가 잡는다.",
        "prohibitions", {
            "inherited_from_v8_and_v10": inherited,
            "v12_specific": v12_specific,
            "inheritance_rule": "V8·V10 금지 키는 하나도 빠지지 않는다. 파생층이 구조적으로 "
                                "저촉될 수 없는 항목(예: 분포 학습 관련)도 완화하지 않고 그대로 싣는다.",
        }))

    sections.append((
        "한계 — 이 계약이 안고 있는 미검증. 숨기지 않고 계약 본문에 싣는다.",
        "known_limits", [
            "N1 귀무가 T1 류 상단 수축 맵의 적법한 귀무인지 [미검증] — 대안 귀무 미계산.",
            f"귀무 통과율의 지평 간 격차(T1 h21 {S3['null_liberality']['cell_pass_rate']['T1_h21']} "
            f"vs h63 {S3['null_liberality']['cell_pass_rate']['T1_h63']}) 기전 [미검증].",
            "T4 두 셀의 비독립성을 family 8셀 산술이 무시한다 [미검증].",
            "국면(GFC/calm) 층화 CI 미산출 — S2 규약 승계.",
            "h1·h5 지평 미평가 — 터치 기저율이 판정 불가 수준.",
            "2015+ 봉인창 미계산 — 의도적 홀드아웃 보존.",
            "공통 창(2007–14) 전반부가 GFC 로 지배돼 '전반→후반 전이' 가 곧 '위기→평온 전이' 다 "
            "(설계도 §0 인정 사항).",
            "재보정 상한의 REL 이 in-sample 추정이라 상한 자체가 낙관 편의를 안는다.",
            "G4 의 gap 주체 선택(R2 = 표적 구조)이 옳은 독해인지는 사용자 판단 V12-D2.",
            "상류 두 산출물의 MDE 승수 규약이 다르다 (mde_convention) — 판정 무영향이나 미정리.",
            "measured_state 의 h21 v8_gap_ci90_lower 는 0 을 포함한다 — 과신 구조의 주체를 V8 로 "
            "잡으면(S2-3 R1) 두 지평 재현이 성립하지 않는다. 이 계약은 R2 를 쓰며 그 선택은 V12-D2.",
        ]))

    sections.append((
        "사용자 결정 대기 — 이 계약은 어느 것도 대신 결정하지 않는다.",
        "decisions_pending", {
            "V12-D1": "트랙 개시 여부 — S3 부정 결과를 받고도 열 것인가.",
            "V12-D2": "게이트 임계와 gap 주체(R2 vs R1) 선택.",
            "V12-D3": "파생층 배포 — 라이브 카드에 이벤트 확률 표시 여부 (현 계약은 not_published).",
            "V12-D4": "다른 데이터 — CBOE 허가 요청 발송 여부. reopen_protocol 의 유일 경로.",
            "V12-D5": "V10 조합 격자 재개 여부 (S1-3 제안 — 이 계약 밖).",
        }))

    return sections


def render(sections: list) -> str:
    head = (
        "# V12 이벤트 확률 트랙 — 부정 결과 계약 (draft)\n"
        "#\n"
        "# 성격: S3-2 판정이 NEGATIVE_RESULT(채택 0/8, T5 음성 대조 실패)이므로 이 계약은\n"
        "# 설계도 §1 각주가 정한 '부정 결과 계약' 이다. 표적·기준선·게이트 산술은 사전등록하되\n"
        "# 게이트는 armed=false 이며 어떤 후보도 평가된 적이 없다.\n"
        "#\n"
        "# 생성: tools/v12_s4_contract.py — 본문의 모든 수치는 S2/S3 산출 JSON 과 V8 계약에서\n"
        "# 읽은 값이다. 사람이 옮겨 적은 수치는 0 이며 tools/v12_s4_contract_check.py 가 대사한다.\n"
        "#\n"
        "# 이 파일은 draft 다. 동결·개시는 사용자 결정(V12-D1)이며 계약 자체가 승인이 아니다.\n"
    )
    blocks = [head.rstrip("\n")]
    for comment, key, value in sections:
        body = yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True,
                              default_flow_style=False, width=10 ** 6).rstrip("\n")
        if comment:
            body = "\n".join("# " + ln for ln in comment.split("\n")) + "\n" + body
        blocks.append(body)
    return "\n\n".join(blocks) + "\n"


def main() -> int:
    sections = build()
    text = render(sections)

    violations, exempted = scan_banned(text)
    if violations:
        print(f"REFUSED: 금지 서술이 부정문 밖에서 발견 (C-S4-contract): {violations}",
              file=sys.stderr)
        return 5

    parsed = yaml.safe_load(text)
    if parsed["status"] != "negative_result_draft" or parsed["gates"]["armed"] is not False:
        print("REFUSED: 계약 상태가 부정 결과 계약이 아니다", file=sys.stderr)
        return 6

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    summary = {
        "written": OUT.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "bytes": len(text.encode("utf-8")),
        "top_level_keys": list(parsed.keys()),
        "status": parsed["status"],
        "gates_armed": parsed["gates"]["armed"],
        "adopted_count": parsed["negative_result"]["adopted_count"],
        "banned_phrase_violations": violations,
        "banned_phrase_exempted_in_negation": exempted,
        "gate_current_status": parsed["gates"]["current_status_of_v8_raw_probability"],
        "feasibility": {h: {b: c["reachable_under_any_binning"]
                            for b, c in row["verdict_by_baseline"].items()}
                        for h, row in parsed["gate_feasibility_arithmetic"]["by_horizon"].items()},
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if "--print" in sys.argv:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
