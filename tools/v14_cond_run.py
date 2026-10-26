"""tools/v14_cond_run.py — V14 조건부 전이 rung 러너 (설계창 한정). `tools/v13_vol_rung_public.py` 미러.

정본 계약 `data/contracts/multivariate_timeseries_v14_conditional.yaml`(yaml.safe_load — V14 전용 모듈·패키지는 V14-D10 전 금지).
실행 단위 1 = 사전등록된 블록 집합 1벌을 6셀 전수로 1회 검정(예산 4). 결과 전 커밋(prereg_commit) 없이는 돌지 않는다.

계약 키 `rung{N}_conditional_blocks` — P0(`tools/v14_cond_diagnostics.py`) 뒤 orchestrator 가 결과 전 커밋으로 추가한다. 스키마:
    registered: 'YYYY-MM-DD'
    prereg_commit: <8+ hex> | null          # null 이면 실행 거부(exit 2)
    experiment_label: V14COND_rung1_conditional   # 원장에 이미 있으면 거부 — 예산은 1회용
    rung_name: conditional_blocks_vs_conditional_pb
    results_path: data/timeseries_v14/vol/ladder_rung1_conditional.json
    evaluation_index: 1                     # == max(evaluations_spent, 원장 행 수) + 1 이어야 한다 — 아니면 거부
    uncertainty: {block_length, replicates, seed, interval}   # gate.uncertainty 와 같아야 한다 — 아니면 거부
    planned_tests: 6                        # 사전등록 분모 — 런타임 tests_run 과 다르면 아무것도 쓰지 않는다
    blocks: [{id, class, definition, lag_sessions?, pit_grade?}]      # P0 registration 이 고른 블록만
    excluded_cells: [{cell, block, reason}]                           # R3 퇴화 · guard untestable (사전등록)
    family: {representative: binomial}
    hypothesis_active_cells?: {block: [cells]}                        # 부분 family 진단 병기용(판정 다리 아님)

거부 규칙(데이터 읽기 전 — refuse_reason):
  track_open · rung 키 · prereg_commit · experiment_label 원장 중복 · 예산 spent = max(evaluations_spent, 원장 행 수)
  (spent+1 > maximum 거부 · evaluation_index != spent+1 거부) · rung 키 uncertainty == gate.uncertainty · 공유 구현 좌표
  (v13_vol_run.BLOCK/B == contracts.BLOCK_LENGTH/BOOTSTRAP_REPLICATES) · interval [5, 95].
거부 규칙(셀 루프 뒤 · 쓰기 전 — denominator_mismatch):
  tests_run != planned_tests 또는 런타임 untestable 셀 집합 != excluded_cells 의 셀 집합이면 exit 2, 아무것도 쓰지 않는다.
  (한계: 판정 자격 셀의 R3 단독 제외는 이 규칙에서 '셀 집합 불일치' 로 거부된다 — 그런 경우는 사전등록을 다시 써야 한다. 페일클로즈.)

셀별 절차(조건 충족 원점만, 압축 부분열 — 시간순):
  guard(반창 degeneracy_report 20/5 + marginal band) → untestable 셀은 family 분모 제외(기록)
  G0: conditional_pb 대 conditional_climatology (R.eval_cell + R.neg_control) — **6셀 전수** 계산(untestable 셀은 informational_only)
  블록별: [level, x] 대 PB (PB3.paired_model_ci 양방향 CI90) — **6셀 × 등록 블록 전수** 계산(MDE 표가 전 셀·블록·방향을 싣도록)
      family 셀: 통과 시 PB3.neg_control_increment(120) → adopted / measured_zero / null_leak
      excluded_cells 쌍: verdict excluded_preregistered + 계약 사유 + 런타임 guard 판정(둘 다 보이게) · informational_only
      untestable 셀: verdict untestable_by_construction · informational_only
  reliability(Murphy rel/res/unc + 곡선)·log_score(평균 로그우도, p clip [1e-6, 1−1e-6]) 를 셀·방향별로 병기 — 보고 의무, 판정 다리 아님.
MDE 표(셀·블록·방향 전수 + G0 방향)는 판정 표보다 **먼저** 인쇄한다(계약 gate.mde.printed_before_results).
family 대표값 S.family_p_binomial(k_obs, tested). champion_rule(a/b/c)은 셀별 기록만 — 승격·표시 없음(V14-D10 사용자 결정).
부트스트랩·적합·귀무는 공유 구현 import 만(신규 구현 0) — 본 CI 는 tools/v13_vol_run.block_boot_ci(기하 길이·순환) 를
tools/v13_vol_rung3_pb.paired_model_ci 로, 귀무 채택 판정은 V13 rung-3~8 과 같은 고속 근사 tools/v13_vol_run._boot_lower_fast
(고정 길이 순환 블록 ℓ=13 · b=400) 로 돈다. seed 는 계약 gate.uncertainty.seed(20261021) — V13 seed 가 아니다.

    PYTHONUTF8=1 python tools/v14_cond_run.py --rung 1 [--root PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from ai_fc.timeseries_v13 import contracts as C  # noqa: E402  (DESIGN_WINDOW · canonical_hash · BLOCK_LENGTH · BOOTSTRAP_REPLICATES)
from ai_fc.timeseries_v13 import scoring as S  # noqa: E402  (degeneracy_report · family_p_binomial · murphy_reliability)
from ai_fc.timeseries_v2.market_archive import read_market_observations  # noqa: E402
import v13_vol_run as R  # noqa: E402  (eval_cell · neg_control · BLOCK · B · block_boot_ci · _boot_lower_fast)
import v13_vol_rung3_pb as PB3  # noqa: E402  (pb_features · paired_model_ci · neg_control_increment · _dir_preds · content_hash)
import v14_cond_diagnostics as P0  # noqa: E402  (조건부 부분집합 · 라벨 · 블록 · 가드 판정 — P0 와 같은 코드)

MODEL_ID = P0.MODEL_ID
LEDGER_RELATIVE = Path("data/timeseries_v14/ledgers/v14_experiments.jsonl")
NULL_DRAWS = 120
NULL_THRESHOLD = 0.10
SPLIT = P0.SPLIT
CI_INTERVAL = [5, 95]
PROB_CLIP = 1e-6
UNCERTAINTY_KEYS = ("block_length", "replicates", "seed", "interval")
NON_FAMILY_VERDICTS = ("excluded_preregistered", "untestable_by_construction")
DIRECTIONS = ("early_to_late", "late_to_early")
G0_LABEL = "G0:conditional_pb_vs_climatology"
GATE_TEXT = "셀별 쌍대 Brier(conditional_pb−후보) 양방향 CI90 하한>0 ∧ 증분 y-block(ℓ13) ≤0.10 · 조건 충족 원점만 · family binomial"
CONDITIONING_NOTE = ("조건 충족 원점(vix 셀 VIX_t<20 엄격 · rv 셀 raw RV21_t 유한 ∧ <=θ)만 표본. 라벨은 전체 패널 미래창에서 계산한 뒤 "
                     "부분집합으로 제한. rv NaN 원점(패널 첫 21세션)은 부분집합 밖. 기후 = fit 반창의 조건부 기저율.")
BOOTSTRAP_NOTE = ("블록 부트스트랩·y-block 순열은 조건 충족 원점의 **압축 부분열**(시간순) 위에서 돈다 — 블록(ℓ=13)이 달력상 끊긴 구간을 "
                  "가로지를 수 있다. 본 CI 는 tools/v13_vol_run.block_boot_ci(기하 길이·순환 정지 블록)를 tools/v13_vol_rung3_pb.paired_model_ci "
                  "경유로, 귀무(y-block) 채택 판정은 V13 rung-3~8 과 동일한 고속 근사 tools/v13_vol_run._boot_lower_fast(고정 길이 순환 블록 "
                  "ℓ=13 · b=400 · CI90 하한만)로 돈다. 공유 구현을 그대로 import 했고 새 bootstrap 은 없다.")
SCORING_NOTE = ("reliability = Murphy 분해(rel/res/unc + 10구간 곡선, S.murphy_reliability) · log_score = 평균 로그우도(높을수록 좋음, "
                "p clip [1e-6, 1−1e-6]). 계약 gate.reliability · gate.scoring 보고 의무 — 판정 다리가 아니다.")
INFORMATIONAL_NOTE = ("informational_only=true 인 셀·블록 통계(G0 · 쌍대 CI · MDE · 귀무)는 계약 G0_baseline_check(6셀 전수 보고)와 "
                      "gate.mde(모든 셀·방향 인쇄)를 위한 것이며 family 분모·k_obs·채택 목록에 들어가지 않는다.")


# ── 원장·계약 ────────────────────────────────────────────────────────────────
def ledger_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ledger_labels(path: Path) -> set[str]:
    return {row.get("experiment_label") for row in ledger_rows(path)}


def _norm(value: Any) -> Any:
    return list(value) if isinstance(value, (list, tuple)) else value


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def refuse_reason(contract: dict[str, Any], key: str, ledger_path: Path) -> str | None:
    """실행 거부 사유(없으면 None). 전부 데이터 읽기 전에 판정한다."""
    dp = contract.get("development_protocol") or {}
    if dp.get("track_open") is not True:
        return "development_protocol.track_open 이 true 가 아니다 — 트랙 개시 승인 전에는 돌지 않는다."
    spec = contract.get(key)
    if not isinstance(spec, dict):
        return f"계약에 {key} 가 없다 — P0 뒤 사전등록(결과 전 커밋)으로 추가해야 한다."
    if not spec.get("prereg_commit"):
        return f"{key}.prereg_commit 이 null 이다 — 사전등록 커밋 뒤에만 실행한다."
    label = spec.get("experiment_label")
    if not label:
        return f"{key}.experiment_label 이 없다."
    rows = ledger_rows(ledger_path)
    if label in {row.get("experiment_label") for row in rows}:
        return f"{label} already in ledger — 평가 예산은 1회용이다. 재실행 거부."
    # 예산 — 손으로 적은 카운터가 아니라 실험 원장(ledger) 행 수와의 max 가 '쓴 예산' 이다 (F2/F11/F20).
    counter = int(dp.get("evaluations_spent", 0))
    spent = max(counter, len(rows))
    maximum = int(dp.get("maximum_development_evaluations", 0))
    if spent + 1 > maximum:
        return (f"개발 평가 예산 소진 — spent {spent}/{maximum} (evaluations_spent 카운터 {counter} · 실험 원장(ledger) 행 {len(rows)} 중 "
                f"큰 값). 새 rung 은 사용자 결정 없이는 없다.")
    idx = spec.get("evaluation_index")
    if not _is_int(idx) or idx != spent + 1:
        return (f"{key}.evaluation_index={idx!r} 가 spent+1={spent + 1} 과 다르다 (evaluations_spent 카운터 {counter} · 실험 원장(ledger) 행 "
                f"{len(rows)}). 사전등록 인덱스와 실제 소모가 어긋난다.")
    # uncertainty — rung 키의 좌표가 gate.uncertainty 와 같고, 공유 구현 상수와도 같아야 한다 (F14/F16).
    unc = (contract.get("gate") or {}).get("uncertainty") or {}
    spec_unc = spec.get("uncertainty")
    if not isinstance(spec_unc, dict):
        return f"{key}.uncertainty 가 없다 — gate.uncertainty 와 같은 좌표(block_length·replicates·seed·interval)를 rung 키에 명시해야 한다."
    for k in UNCERTAINTY_KEYS:
        if _norm(spec_unc.get(k)) != _norm(unc.get(k)):
            return f"{key}.uncertainty.{k}={spec_unc.get(k)!r} 가 gate.uncertainty.{k}={unc.get(k)!r} 과 다르다 — 러너는 불일치 시 거부한다."
    if not _is_int(unc.get("seed")):
        return "gate.uncertainty.seed 가 정수가 아니다."
    if _norm(unc.get("interval")) != CI_INTERVAL:
        return f"gate.uncertainty.interval={unc.get('interval')!r} 가 CI90 [5, 95] 가 아니다."
    if int(unc.get("block_length", -1)) != R.BLOCK or int(unc.get("replicates", -1)) != R.B:
        return f"계약 bootstrap 좌표(ℓ={unc.get('block_length')}, B={unc.get('replicates')})가 공유 구현(ℓ={R.BLOCK}, B={R.B})과 다르다."
    if (R.BLOCK, R.B) != (C.BLOCK_LENGTH, C.BOOTSTRAP_REPLICATES):
        return (f"공유 구현 좌표 불일치 — tools/v13_vol_run (ℓ={R.BLOCK}, B={R.B}) 와 src/ai_fc/timeseries_v13/contracts.py "
                f"(BLOCK_LENGTH={C.BLOCK_LENGTH}, BOOTSTRAP_REPLICATES={C.BOOTSTRAP_REPLICATES}) 가 다르다.")
    return None


# ── 압축 부분열 ───────────────────────────────────────────────────────────────
def compact_cell(spec: dict[str, Any], ctx: dict[str, Any], blocks: dict[str, np.ndarray]) -> dict[str, Any]:
    """조건 충족 ∧ 설계창 ∧ 유한 라벨 ∧ 유한 피처 원점을 시간순으로 압축. 마스크 me/ml 도 압축 좌표."""
    y_full = P0.full_labels(spec, ctx["vix"], ctx["rv_raw"])
    level = P0.champion_feature(spec, ctx["vix"], ctx["rv_raw"])
    cond = P0.conditional_subset(spec, ctx["vix"], ctx["rv_raw"])
    sub = ctx["design"] & cond & np.isfinite(y_full) & np.isfinite(level)
    idx = np.flatnonzero(sub)
    dates = [ctx["dates"][i] for i in idx]
    me = np.array([d < SPLIT for d in dates], bool)
    return {"idx": idx, "dates": dates, "y": y_full[idx], "level": level[idx], "me": me, "ml": ~me,
            "blocks": {b: np.asarray(x, float)[idx] for b, x in blocks.items()}}


# ── 보고 의무: 신뢰도 · 로그 점수 (판정 다리 아님) ───────────────────────────
def log_score(p: np.ndarray, y: np.ndarray) -> float:
    """평균 로그우도(높을수록 좋음). p 는 [1e-6, 1−1e-6] 로 클립."""
    p = np.clip(np.asarray(p, float), PROB_CLIP, 1 - PROB_CLIP)
    y = np.asarray(y, float)
    if y.size == 0:
        return float("nan")
    return float(np.mean(y * np.log(p) + (1 - y) * np.log1p(-p)))


def direction_scores(preds: dict[str, np.ndarray], y_eval: np.ndarray) -> tuple[dict[str, Any], dict[str, float]]:
    reliability = {k: S.murphy_reliability(p, y_eval) for k, p in preds.items()}
    scores = {k: log_score(p, y_eval) for k, p in preds.items()}
    return reliability, scores


def _directions(me: np.ndarray, ml: np.ndarray):
    return (("early_to_late", me, ml), ("late_to_early", ml, me))


# ── 셀 평가 ──────────────────────────────────────────────────────────────────
def evaluate_cell(spec: dict[str, Any], cc: dict[str, Any], registered: list[dict[str, Any]],
                  excluded: dict[tuple[str, str], str], guard_cfg: dict[str, Any], *,
                  seed: int, b: int = R.B, null_draws: int = NULL_DRAWS) -> dict[str, Any]:
    """한 셀: guard → G0(전수) → 블록별 쌍대 CI(전수) → family 자격 셀만 채택 판정. untestable·excluded 는 informational_only."""
    name = spec["name"]
    y, level, me, ml = cc["y"], cc["level"], cc["me"], cc["ml"]
    entry: dict[str, Any] = {"target": spec["target"], "h": spec["h"],
                             "n_subset_early": int(me.sum()), "n_subset_late": int(ml.sum()), "blocks": {}}
    guard: dict[str, Any] = {}
    for half, mask in (("early", me), ("late", ml)):
        rep = S.degeneracy_report(y[mask], min_events=int(guard_cfg["min_events_per_half_per_class"]),
                                  min_episodes=int(guard_cfg["min_episodes"]))
        v = P0.v14_guard_verdict(rep, guard_cfg)
        guard[half] = {"n": rep["n"], "events": rep["events"], "non_events": rep["non_events"], "base_rate": rep["base_rate"],
                       "event_runs": rep["event_runs"], "non_event_runs": rep["non_event_runs"], "min_episodes": rep["min_episodes"],
                       "episode_band": v["episode_band"], "verdict": v["verdict"], "reason": v["reason"]}
    guard["min_episodes"] = min(guard["early"]["min_episodes"], guard["late"]["min_episodes"])
    entry["guard"] = guard
    untestable = "untestable_by_construction" in (guard["early"]["verdict"], guard["late"]["verdict"])
    if untestable:
        cell_verdict = "untestable_by_construction"
    elif "episode_thin" in (guard["early"]["verdict"], guard["late"]["verdict"]):
        cell_verdict = "episode_thin"
    else:
        cell_verdict = "testable"
    entry["verdict"] = cell_verdict

    # G0 — 6셀 전수(계약 G0_baseline_check). untestable 셀은 정보용.
    pb_feat = PB3.pb_features(level)
    g0 = R.eval_cell(pb_feat, y, me, ml, seed, b)
    g0_null = R.neg_control(pb_feat, y, me, ml, seed, draws=null_draws) if g0["adopted"] else None
    g0_pass = bool(g0["adopted"] and g0_null is not None and g0_null <= NULL_THRESHOLD)
    for d, fit_m, ev_m in _directions(me, ml):
        ye = y[ev_m]
        preds = {"conditional_pb": PB3._dir_preds(pb_feat, y, fit_m, ev_m),
                 "conditional_climatology": np.full(ye.shape, float(g0[d]["clim_base_rate"]))}
        g0[d]["reliability"], g0[d]["log_score"] = direction_scores(preds, ye)
    entry["conditional_pb_vs_climatology"] = {
        "early_to_late": g0["early_to_late"], "late_to_early": g0["late_to_early"],
        "adopted_ci_both": bool(g0["adopted"]), "neg_control_pass_rate": g0_null,
        "pb_beats_climatology": g0_pass,
        "informational_only": untestable,
        "note": "climatology = fit 반창의 조건부 기저율. 귀무는 양방향 CI 통과 셀에만 계산(V13 rung-3 규약). "
                "informational_only 셀은 guard untestable — family·champion_rule 에 쓰지 않는다.",
    }

    # 블록 — 6셀 × 등록 블록 전수 계산(MDE 표 전수 인쇄). family 자격은 untestable 아님 ∧ excluded_cells 아님.
    adopted_blocks: list[str] = []
    for blk in registered:
        bname, klass = blk["id"], blk["class"]
        bentry: dict[str, Any] = {"class": klass}
        x = cc["blocks"][bname]
        usable = np.isfinite(x)
        me_b, ml_b = me & usable, ml & usable
        cand = np.column_stack([level, np.where(usable, x, 0.0)])
        bentry.update({"n_early": int(me_b.sum()), "n_late": int(ml_b.sum())})
        paired = PB3.paired_model_ci(pb_feat, cand, y, me_b, ml_b, seed, b)
        for d, fit_m, ev_m in _directions(me_b, ml_b):
            ye = y[ev_m]
            preds = {"conditional_pb": PB3._dir_preds(pb_feat, y, fit_m, ev_m),
                     "candidate": PB3._dir_preds(cand, y, fit_m, ev_m)}
            paired[d]["reliability"], paired[d]["log_score"] = direction_scores(preds, ye)
        bentry["paired"] = paired
        bentry["paired_naming_note"] = "공유 구현 키 명칭: a=pb=conditional_pb · b='ewma'=후보 [level, x]"
        ci_pass = bool(paired["ewma_beats_pb_both"])
        bentry["bidirectional_ci_pass"] = ci_pass
        rate = PB3.neg_control_increment(pb_feat, cand, y, me_b, ml_b, seed, draws=null_draws) if ci_pass else None
        bentry["neg_control_pass_rate"] = rate
        gate_pass = bool(ci_pass and rate is not None and rate <= NULL_THRESHOLD)
        if (name, bname) in excluded:
            bentry.update({"verdict": "excluded_preregistered", "reason": excluded[(name, bname)],
                           "runtime_guard_verdict": cell_verdict, "informational_only": True, "would_pass_gate": gate_pass})
        elif untestable:
            bentry.update({"verdict": "untestable_by_construction", "runtime_guard_verdict": cell_verdict,
                           "informational_only": True, "would_pass_gate": gate_pass})
        else:
            bentry["adopted"] = gate_pass
            if gate_pass:
                bentry["verdict"] = "adopted_episode_thin" if guard["min_episodes"] < int(guard_cfg["min_episodes"]) else "adopted"
                adopted_blocks.append(bname)
            elif not ci_pass:
                bentry["verdict"] = "measured_zero"
            else:
                bentry["verdict"] = "null_leak"
        entry["blocks"][bname] = bentry

    if untestable:
        entry["champion_rule_outcome"] = {"rule": "c", "champion": "hold",
                                          "note": "untestable_by_construction — 판정 자격 없음(G0·블록 통계는 정보용)"}
    elif adopted_blocks:
        entry["champion_rule_outcome"] = {"rule": "a", "champion": adopted_blocks[0], "adopted_blocks": adopted_blocks,
                                          "note": "후보가 conditional_pb 를 양방향 CI90 ∧ 증분 귀무로 이김 — 기록만, 승격 없음(V14-D10)"}
    elif g0_pass:
        entry["champion_rule_outcome"] = {"rule": "b", "champion": "conditional_persistence_pb",
                                          "note": "후보 전부 미채택 · conditional_pb 가 conditional_climatology 를 같은 형으로 이김 — 기록만"}
    else:
        entry["champion_rule_outcome"] = {"rule": "c", "champion": "hold",
                                          "note": "조건부 부분집합에서도 정보가 '자명'을 넘지 못함 — HOLD 셀은 표시 불가"}
    return entry


# ── rung 실행 ────────────────────────────────────────────────────────────────
def run_rung(contract: dict[str, Any], spec: dict[str, Any], ctx: dict[str, Any], *, rung: int,
             blocks_by_cell: dict[str, dict[str, np.ndarray]] | None = None,
             b: int = R.B, null_draws: int = NULL_DRAWS) -> dict[str, Any]:
    """전 셀 계산(인쇄 없음). 반환 payload 는 content_hash 전 상태(쓰기 직전에 붙인다)."""
    seed = int(contract["gate"]["uncertainty"]["seed"])
    guard_cfg = contract["episode_guard"]
    specs = P0.v14_cell_specs(contract)
    registered = list(spec["blocks"])
    excluded = {(e["cell"], e["block"]): e["reason"] for e in spec.get("excluded_cells", []) or []}
    results: dict[str, Any] = {}
    tested = k_obs = 0
    k_by_class: dict[str, int] = {}
    n_by_class: dict[str, int] = {}
    for cell in specs:
        blocks = (blocks_by_cell or {}).get(cell["name"]) or P0.cell_blocks(cell, ctx)
        cc = compact_cell(cell, ctx, blocks)
        entry = evaluate_cell(cell, cc, registered, excluded, guard_cfg, seed=seed, b=b, null_draws=null_draws)
        for bname, bentry in entry["blocks"].items():
            if bentry.get("verdict") in NON_FAMILY_VERDICTS:
                continue
            tested += 1
            n_by_class[bentry["class"]] = n_by_class.get(bentry["class"], 0) + 1
            if bentry.get("adopted"):
                k_obs += 1
                k_by_class[bentry["class"]] = k_by_class.get(bentry["class"], 0) + 1
        results[cell["name"]] = entry
    family_p = S.family_p_binomial(k_obs, max(tested, 1))
    active = spec.get("hypothesis_active_cells") or {}
    active_summary = {}
    for blk in registered:
        cells = active.get(blk["id"])
        if not cells:
            continue
        sub = [results.get(c, {}).get("blocks", {}).get(blk["id"], {}) for c in cells]
        n_sub = sum(1 for e in sub if e.get("verdict") not in (None,) + NON_FAMILY_VERDICTS)
        k_sub = sum(1 for e in sub if e.get("adopted"))
        active_summary[blk["id"]] = {"cells": cells, "n": n_sub, "k": k_sub,
                                     "family_p_binomial_diagnostic": S.family_p_binomial(k_sub, max(n_sub, 1))}
    adopted = sorted(f"{c}|{bn}" for c, e in results.items() for bn, be in e["blocks"].items() if be.get("adopted"))
    planned = spec.get("planned_tests")
    payload = {
        "schema": f"v14_cond_rung{rung}_conditional",
        "contract_id": contract["contract_id"],
        "model_id": MODEL_ID,
        "prereg_commit": spec.get("prereg_commit"),
        "experiment_label": spec["experiment_label"],
        "evaluation_index": int(spec["evaluation_index"]),
        "window": list(C.DESIGN_WINDOW),
        "split": SPLIT,
        "lookback_start": P0.D.LOOKBACK_START,
        "n_panel_design": int(ctx["design"].sum()),
        "bootstrap": {"method": "stationary_block", "block_length": R.BLOCK, "replicates": b, "seed": seed, "interval": list(CI_INTERVAL),
                      "null_draws": null_draws, "null_threshold": NULL_THRESHOLD,
                      "ci_implementation": "tools/v13_vol_run.block_boot_ci via tools/v13_vol_rung3_pb.paired_model_ci",
                      "null_implementation": "tools/v13_vol_run._boot_lower_fast (fixed-length circular blocks, b=400) via "
                                             "v13_vol_run.neg_control / v13_vol_rung3_pb.neg_control_increment"},
        "conditioning": {"vix_cells": "VIX_close_t < 20 (strict)", "rv_cells": "RV21_ann_t <= theta (raw, finite)",
                         "theta": float(contract["targets"]["rv_conditional_transition"]["theta"]),
                         "conditioning_note": CONDITIONING_NOTE},
        "bootstrap_note": BOOTSTRAP_NOTE,
        "scoring_note": SCORING_NOTE,
        "informational_note": INFORMATIONAL_NOTE,
        "blocks": {blk["id"]: {"class": blk["class"], "definition": blk.get("definition"), "lag_sessions": blk.get("lag_sessions"),
                               "pit_grade": blk.get("pit_grade")} for blk in registered},
        "excluded_cells": list(spec.get("excluded_cells", []) or []),
        "cells_untestable": [c for c, e in results.items() if e["verdict"] == "untestable_by_construction"],
        "cells_episode_thin": [c for c, e in results.items() if e["verdict"] == "episode_thin"],
        "planned_tests": int(planned) if _is_int(planned) else None,
        "tests_run": tested,
        "k_obs_adopted": k_obs,
        "family_p_binomial": family_p,
        "family_representative": (spec.get("family") or {}).get("representative", "binomial"),
        "family_dependence_caveat": "셀 종속(지평 중첩) — 대표값은 이항, 종속조정은 진단 병기만. 프로그램 전역 누적(lineage.campaign_prior_tests)과 함께 읽는다(M6).",
        "campaign_prior_tests": (contract.get("lineage") or {}).get("campaign_prior_tests"),
        "by_class": {k: {"n": n_by_class.get(k, 0), "k": k_by_class.get(k, 0)} for k in sorted(n_by_class)},
        "hypothesis_active_diagnostic": active_summary,
        "adopted": adopted,
        "champion_rule_outcomes": {c: e["champion_rule_outcome"] for c, e in results.items()},
        "promotion": "none — champion_rule 은 기록만. 라이브 포인터·verb 는 V14-D10 사용자 결정",
        "cells": results,
        "holdout_read": False,
        "sealed_read": False,
        "new_data_ingested": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return P0._clean(payload)


def denominator_mismatch(spec: dict[str, Any], payload: dict[str, Any]) -> str | None:
    """사전등록 분모 강제(F15) — 셀 루프 뒤·쓰기 전. 어긋나면 사유를 돌려주고 호출자는 아무것도 쓰지 않는다."""
    planned = spec.get("planned_tests")
    if not _is_int(planned):
        return f"planned_tests 가 정수가 아니다: {planned!r} — 사전등록 분모 없이는 쓰지 않는다."
    if int(payload["tests_run"]) != planned:
        return (f"tests_run {payload['tests_run']} != planned_tests {planned} — 런타임 분모가 사전등록 분모와 다르다. "
                "아무것도 쓰지 않는다(exit 2).")
    runtime = set(payload["cells_untestable"])
    registered = {e["cell"] for e in spec.get("excluded_cells", []) or []}
    if runtime != registered:
        return (f"런타임 untestable 셀 {sorted(runtime)} != 사전등록 excluded_cells 셀 {sorted(registered)} — "
                "guard 실측과 사전등록이 어긋난다. 아무것도 쓰지 않는다(exit 2).")
    return None


# ── 인쇄: MDE 표 → 판정 표 (순서 고정) ──────────────────────────────────────
def mde_rows(payload: dict[str, Any]) -> list[tuple[str, str, str, float | None, bool]]:
    """모든 셀 × (G0 방향 + 등록 블록 × 방향). 다섯째 원소 = informational_only(family 밖)."""
    rows: list[tuple[str, str, str, float | None, bool]] = []
    for cell, e in payload["cells"].items():
        g0 = e["conditional_pb_vs_climatology"]
        for d in DIRECTIONS:
            rows.append((cell, G0_LABEL, d, g0[d]["mde"], bool(g0.get("informational_only"))))
        for bname, be in e["blocks"].items():
            for d in DIRECTIONS:
                rows.append((cell, bname, d, be["paired"][d]["mde"], bool(be.get("informational_only"))))
    return rows


def _fmt_ci(mean: float | None, ci: list[float | None]) -> str:
    vals = [v if v is not None else float("nan") for v in (mean, ci[0], ci[1])]
    return "{:+.5f}[{:+.5f},{:+.5f}]".format(*vals)


def render(payload: dict[str, Any]) -> None:
    print("=== MDE (결과 전 인쇄 — 계약 gate.mde.printed_before_results) · |Δ| < MDE 는 '측정된 영' · 셀·블록·방향 전수 ===")
    print("{:11s} {:34s} {:14s} {:>9s}  {}".format("셀", "블록", "방향", "MDE", "비고"))
    rows = mde_rows(payload)
    for cell, block, d, mde, informational in rows:
        print("{:11s} {:34s} {:14s} {:9.5f}  {}".format(cell, block, d, mde if mde is not None else float("nan"),
                                                       "정보용(family 밖)" if informational else "family"))
    if not rows:
        print("(셀 없음 — MDE 없음)")
    print()
    print("=== 판정 ===")
    print("{:11s} {:34s} {:>28s} {:>28s} {:>6s} 판정".format("셀", "블록", "e2l 쌍대[CI90]", "l2e 쌍대[CI90]", "귀무"))
    for cell, e in payload["cells"].items():
        g0 = e["conditional_pb_vs_climatology"]
        e2l, l2e = g0["early_to_late"], g0["late_to_early"]
        nc = g0["neg_control_pass_rate"]
        g0_verdict = "pb_beats_climatology" if g0["pb_beats_climatology"] else ("ci_pass_null_leak" if g0["adopted_ci_both"] else "measured_zero")
        if g0.get("informational_only"):
            g0_verdict += f" (정보용 — {e['verdict']})"
        print("{:11s} {:34s} {:>28s} {:>28s} {:6.3f} {}".format(
            cell, G0_LABEL, _fmt_ci(e2l["paired_mean"], e2l["ci90"]), _fmt_ci(l2e["paired_mean"], l2e["ci90"]),
            nc if nc is not None else float("nan"), g0_verdict))
        for bname, be in e["blocks"].items():
            pe, pl = be["paired"]["early_to_late"], be["paired"]["late_to_early"]
            nc = be["neg_control_pass_rate"]
            verdict = be["verdict"]
            if be.get("informational_only"):
                verdict += f" (정보용 · guard {be['runtime_guard_verdict']})"
            print("{:11s} {:34s} {:>28s} {:>28s} {:6.3f} {}".format(
                cell, bname, _fmt_ci(pe["paired_mean_pb_minus_ewma"], pe["ci90"]), _fmt_ci(pl["paired_mean_pb_minus_ewma"], pl["ci90"]),
                nc if nc is not None else float("nan"), verdict))
    print("\n검정 {}건(사전등록 {}) · 채택 {}건 · family P(k>={}|n={}) = {:.4f} · 클래스별 {} · untestable {} · episode_thin {}".format(
        payload["tests_run"], payload.get("planned_tests"), payload["k_obs_adopted"], payload["k_obs_adopted"], payload["tests_run"],
        payload["family_p_binomial"], payload["by_class"], payload["cells_untestable"] or "-", payload["cells_episode_thin"] or "-"))
    print("채택: " + (", ".join(payload["adopted"]) if payload["adopted"] else "none"))
    print("champion_rule(기록만): " + " · ".join(f"{c}={o['champion']}({o['rule']})" for c, o in payload["champion_rule_outcomes"].items()))


# ── 쓰기 ─────────────────────────────────────────────────────────────────────
def ledger_row(spec: dict[str, Any], payload: dict[str, Any], results_sha256: str) -> dict[str, Any]:
    row = {
        "schema_version": 1,
        "experiment_label": spec["experiment_label"],
        "model": MODEL_ID,
        "rung": spec["rung_name"],
        "window_role": "design",
        "window": list(C.DESIGN_WINDOW),
        "prereg_commit": spec.get("prereg_commit"),
        "evaluation_index": int(spec["evaluation_index"]),
        "backtest_windows_opened": 0,
        "holdout_slot_consumed": 0,
        "gate": GATE_TEXT,
        "blocks": [blk["id"] for blk in spec["blocks"]],
        "planned_tests": payload.get("planned_tests"),
        "tests_run": payload["tests_run"],
        "k_obs_adopted": payload["k_obs_adopted"],
        "family_p_binomial": payload["family_p_binomial"],
        "adopted": payload["adopted"],
        "cells_untestable": payload["cells_untestable"],
        "results_sha256": results_sha256,
        "conditioning": {"vix_cells": "VIX_close_t < 20 (strict)", "rv_cells": "RV21_ann_t <= theta (raw, finite)",
                         "theta": payload["conditioning"]["theta"]},
        "caveat": "설계창 한정·홀드아웃(2015-2018) 재사용 불허·봉인 미열람. 조건부 부분집합 압축 부분열 위 bootstrap. champion_rule 은 기록만 — 승격·표시 없음. 참고 의견이지 매매 신호가 아니다.",
        "knowledge_cutoff": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    row["content_hash"] = PB3.content_hash(row)
    return row


def write_outputs(root: Path, spec: dict[str, Any], payload: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    payload = dict(payload)
    payload.pop("content_hash", None)
    payload["content_hash"] = C.canonical_hash(payload)
    out = root / spec["results_path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + "\n",
                   encoding="utf-8", newline="\n")
    row = ledger_row(spec, payload, hashlib.sha256(out.read_bytes()).hexdigest())
    ledger = root / LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    return out, row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rung", type=int, required=True)
    ap.add_argument("--root", type=Path, default=ROOT, help="저장소 루트(테스트용 임시 복사본 지정 가능)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    key = f"rung{args.rung}_conditional_blocks"
    contract = P0.load_contract_v14(root)
    reason = refuse_reason(contract, key, root / LEDGER_RELATIVE)
    if reason:
        print(reason)
        return 2
    spec = contract[key]
    theta = float(contract["targets"]["rv_conditional_transition"]["theta"])
    ctx = P0.panel_context(read_market_observations(root), theta=theta)
    payload = run_rung(contract, spec, ctx, rung=args.rung)
    mismatch = denominator_mismatch(spec, payload)
    if mismatch:
        print(mismatch)
        return 2
    render(payload)
    out, row = write_outputs(root, spec, payload)
    print("wrote {} · 원장 행 {}…".format(out.relative_to(root).as_posix(), row["content_hash"][:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
