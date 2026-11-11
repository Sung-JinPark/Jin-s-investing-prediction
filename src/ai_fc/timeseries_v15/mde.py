"""V15 MDE — 설계창 결정론 재생(`design_replay`)과 요약(`summarize_mde`). mde_code_hash 대상.

수치모델 예외(CLAUDE.md 5대 원칙 5 명문화 예외): 산출은 MDE·base rate 참조다 — 채택 근거도
캘리브레이션 표본도 아니다. 블록 길이·창 선택·n_min 이 사후 지식을 간접 내포할 수 있다. 설계창은
GFC 를 포함해 절대 단위 MDE 는 과대, 상대 단위는 근사다. A4 는 산출 불가(설계 비대표) — proxy 는
참고값. LLM 무관. 요약에는 효과 추정치(`design_delta_rel`·`power_at_design_estimate`)를 두지 않는다.
판정과 같은 내부 함수(verdict._bootstrap_means·_episode_stats·_pvalue)를 쓴다. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ai_fc.timeseries_v8.contracts import canonical_hash

from .arms import ARM_INDEX, ARMS, SEED_MODEL_ID, SEED_MODEL_VERSION, VERDICT_HORIZONS, arm_spec
from .contracts import (
    MDE_SUMMARY_RELATIVE,
    NOTICE,
    PREREG_RELATIVE,
    TimeSeriesV15ContractError,
    kernel_code_hash,
    load_contract_v15,
    mde_code_hash,
)
from .verdict import (
    BLOCK_LENGTH,
    BOOTSTRAP_SEED,
    NI_MARGIN,
    REPLICATES,
    _bootstrap_means,
    _episode_stats,
    _ratio_resamples,
    blocks_drawn,
    bootstrap_indices,
    data_condition,
)

DESIGN_TRUNCATION = "2014-12-31"
DESIGN_OUTER_START = "2007-01-01"
TRIALS = 2000
POWER = 0.90
SUPERIORITY_M = 12
NONINFERIORITY_M = 3
ALPHA = 0.05
N_MIN = {5: 26, 21: 26, 63: 39}
N_EXP = {h: 39 + (63 - h) // 5 for h in VERDICT_HORIZONS}  # {5: 50, 21: 47, 63: 39}
REPRESENTATIVE_MIN_ROWS = 5
FRAME_AXIS_ARMS = ("A3", "A4")  # 단일 변경 축이 입력 프레임인 팔만 대표성 판정 대상
MDE_ARMS = ("A0", "A1", "A2", "A3", "A4", "A5")
SUMMARY_EXCLUDES = ("design_delta_rel", "power_at_design_estimate")


def replay_relative(arm: str) -> Path:
    return PREREG_RELATIVE / f"mde_replay_{arm}.json"


def _iso_week(day: str) -> str:
    iso = date.fromisoformat(day).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# ── 재생 ────────────────────────────────────────────────────────────────────


def _frame_difference(base, other) -> int:
    """설계창 입력 행 차이 수 = 날짜 대칭차 + 공통 날짜 중 내생 값이 다른 행."""
    left = {day: index for index, day in enumerate(base.dates)}
    right = {day: index for index, day in enumerate(other.dates)}
    count = len(set(left) ^ set(right))
    for day in set(left) & set(right):
        if not np.array_equal(base.endogenous[left[day]], other.endogenous[right[day]]):
            count += 1
    return count


def design_replay(
    root: Path, *, arm: str, data_snapshot_sha: str, data_root: Path | None = None,
    path_count: int | None = None,
) -> dict[str, Any]:
    from ai_fc.timeseries_v2.contracts import require_dfm_runtime, runtime_manifest
    from ai_fc.timeseries_v2.market_archive import read_market_observations
    from ai_fc.timeseries_v8.contracts import load_contract_v8
    from ai_fc.timeseries_v8.pipeline import build_config_from_grids

    from .backtest import walk_forward_v15
    from .bundle import bundle_at
    from .calendar import exchange_calendars_version
    from .labels import xnas_label_fn

    contract = load_contract_v15(root)
    if (contract.get("mde") or {}).get("status") != "not_computed":
        raise TimeSeriesV15ContractError("MDE 는 write-once — 계약 mde.status 가 not_computed 가 아니다")
    if (root / MDE_SUMMARY_RELATIVE).exists():
        raise TimeSeriesV15ContractError("mde_v1.json 이 이미 있다 — MDE 재생은 write-once")
    spec = arm_spec(arm)
    source = data_root or root
    require_dfm_runtime()
    cutoff = str(contract["mde"]["replay_knowledge_cutoff"])
    bundle, provenance = bundle_at(source, knowledge_cutoff=cutoff, frame_mode=spec.frame_mode,
                                   truncate_at=DESIGN_TRUNCATION)
    if max(bundle.dates) > DESIGN_TRUNCATION:
        raise TimeSeriesV15ContractError("설계창 절단 위반")
    contract_v8 = load_contract_v8(root)
    config = build_config_from_grids(
        contract_v8, json.loads(json.dumps(contract_v8["frozen_winner"]["config_overrides"])),
    )
    observations = read_market_observations(source, knowledge_cutoff=cutoff)
    label = xnas_label_fn(observations, cap=DESIGN_TRUNCATION)
    _, summary = walk_forward_v15(
        dates=bundle.dates, endog=bundle.endogenous, exog=bundle.exogenous,
        endog_names=bundle.endogenous_names, exog_names=bundle.exogenous_names,
        model_id=SEED_MODEL_ID, model_version=SEED_MODEL_VERSION, config=config,
        outer_start=DESIGN_OUTER_START, outer_end=DESIGN_TRUNCATION,
        path_count=int(path_count or contract["mde"]["path_count"]),
        pit_min_matured=int(contract_v8["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]),
        collect_cramer_audit=False, arm=spec, verdict_label=label,
    )
    rows = [
        {"date": row["date"], "iso_week": _iso_week(row["date"]), "horizon": int(row["horizon"]),
         "seed": int(row["seed"]), "crps_verdict": row["crps_verdict"], "y_verdict": row["y_verdict"]}
        for row in summary["origin_rows"]
    ]
    differing: int | None = None
    if arm in FRAME_AXIS_ARMS:
        base, _ = bundle_at(source, knowledge_cutoff=cutoff, frame_mode="v8", truncate_at=DESIGN_TRUNCATION)
        differing = _frame_difference(base, bundle)
    payload = {
        "schema_version": 1, "kind": "v15_mde_design_replay", "arm": arm,
        "arm_spec": spec.as_manifest(),
        "replay_knowledge_cutoff": cutoff, "design_truncation": DESIGN_TRUNCATION,
        "outer_start": DESIGN_OUTER_START, "data_snapshot_sha": str(data_snapshot_sha),
        "origin_count": len({row["date"] for row in rows}),
        "difference_axis": ("frame" if arm in FRAME_AXIS_ARMS else
                            "control" if arm == "A0" else "vol_or_issuance"),
        "input_rows_differing_from_a0": differing,
        "frame_provenance_summary": {key: (value if not isinstance(value, list) else value[-10:])
                                     for key, value in provenance.items()
                                     if key in ("frame_mode", "dates", "non_xnas_rows_ignored", "dropped_sessions")},
        "runtime_manifest": runtime_manifest(),
        "exchange_calendars_version": exchange_calendars_version(),
        "kernel_code_hash": kernel_code_hash(root),
        "rows": rows,
        "notice": NOTICE,
    }
    payload["content_hash"] = canonical_hash(payload)
    return payload


# ── 요약 ────────────────────────────────────────────────────────────────────


def _pairs(replays: Mapping[str, Mapping[str, Any]], arm: str, h: int) -> dict[str, Any]:
    """같은 ISO 주·같은 원점 날짜·같은 seed 인 (X, A0) 쌍. 라벨 없는 원점은 뺀다."""
    def by_week(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {row["iso_week"]: row for row in payload["rows"]
                if int(row["horizon"]) == h and row["crps_verdict"] is not None}

    control = by_week(replays["A0"])
    target = by_week(replays[arm])
    d: list[float] = []
    c: list[float] = []
    mismatched = 0
    for week in sorted(set(control) & set(target)):
        left, right = control[week], target[week]
        if left["date"] != right["date"] or int(left["seed"]) != int(right["seed"]):
            mismatched += 1
            continue
        d.append(float(right["crps_verdict"]) - float(left["crps_verdict"]))
        c.append(float(left["crps_verdict"]))
    unmatched = len(set(control) ^ set(target))
    return {"d": np.asarray(d, dtype=float), "c": np.asarray(c, dtype=float),
            "mismatched_weeks": mismatched, "unpaired_weeks": unmatched}


def _trial_index(rng: np.random.Generator, length: int, n_trial: int, h: int, trials: int) -> np.ndarray:
    """설계 계열 위 이동블록(ℓ_h) 재표본 색인 (trials, n_trial)."""
    ell = BLOCK_LENGTH[h]
    if length < ell:
        raise TimeSeriesV15ContractError(f"설계 쌍 {length} < ℓ={ell}")
    b = blocks_drawn(n_trial, h)
    starts = rng.integers(0, length - ell + 1, size=(trials, b))
    index = starts[:, :, None] + np.arange(ell)[None, None, :]
    return index.reshape(trials, b * ell)[:, :n_trial]


def critical_effects(trial_d: np.ndarray, h: int, *, alpha: float) -> np.ndarray:
    """각 시행의 임계 효과 δ_t* — δ > δ_t* 이면 우월성 pass(CI·p·에피소드 모두 δ 에 단조).

    CIup(δ) = CIup(0) − δ < 0, p(δ) = (1+#{d̄*_b(0) ≥ δ})/(B+1) < α,
    블록평균(δ) = 블록평균(0) − δ, 최유리 블록 제거 평균(δ) = 그것(0) − δ.
    """
    trial_d = np.atleast_2d(np.asarray(trial_d, dtype=float))
    n = trial_d.shape[1]
    if data_condition(n, h) is not None:
        return np.full(trial_d.shape[0], np.inf)
    index = bootstrap_indices(n, h)
    allowed = math.ceil(alpha * (REPLICATES + 1) - 1) - 1  # #{x ≥ δ} ≤ allowed
    out = np.empty(trial_d.shape[0], dtype=float)
    chunk = 25
    for start in range(0, trial_d.shape[0], chunk):
        block = trial_d[start:start + chunk]
        means = _bootstrap_means(block, index)
        ci_up = np.quantile(means, 0.95, axis=-1, method="linear")
        ordered = np.sort(means, axis=-1)
        p_edge = ordered[:, REPLICATES - 1 - allowed] if allowed >= 0 else np.full(len(block), np.inf)
        for offset, series in enumerate(block):
            episodes = _episode_stats(series, h)
            if episodes["blocks"] < 1 or episodes["required"] > episodes["blocks"]:
                out[start + offset] = np.inf
                continue
            block_means = np.sort(np.asarray(episodes["block_means"], dtype=float))
            out[start + offset] = max(float(ci_up[offset]), float(p_edge[offset]),
                                      float(block_means[episodes["required"] - 1]),
                                      float(episodes["mean_without_best_block"]))
    return out


def ni_pass_flags(trial_d: np.ndarray, trial_c: np.ndarray, h: int, *, alpha: float) -> np.ndarray:
    trial_d = np.atleast_2d(np.asarray(trial_d, dtype=float))
    trial_c = np.atleast_2d(np.asarray(trial_c, dtype=float))
    n = trial_d.shape[1]
    if data_condition(n, h) is not None:
        return np.zeros(trial_d.shape[0], dtype=bool)
    index = bootstrap_indices(n, h)
    flags = np.zeros(trial_d.shape[0], dtype=bool)
    for row in range(trial_d.shape[0]):
        ratios = _ratio_resamples(trial_d[row], trial_c[row], index)
        upper = float(np.quantile(ratios, 0.95, method="linear"))
        p_ni = float((1 + int(np.sum(ratios >= NI_MARGIN))) / (REPLICATES + 1))
        flags[row] = upper < NI_MARGIN and p_ni < alpha
    return flags


def summarize_mde(replays: Mapping[str, Mapping[str, Any]], *, trials: int = TRIALS) -> dict[str, Any]:
    missing = [arm for arm in MDE_ARMS if arm not in replays]
    if missing:
        raise TimeSeriesV15ContractError(f"MDE 재생 파일 누락: {missing}")
    per_arm: dict[str, Any] = {}
    for arm in ("A1", "A2", "A3", "A4", "A5"):
        per_arm[arm] = {}
        differing = replays[arm].get("input_rows_differing_from_a0")
        representative = not (arm in FRAME_AXIS_ARMS and differing is not None
                              and int(differing) < REPRESENTATIVE_MIN_ROWS)
        for h in VERDICT_HORIZONS:
            pairs = _pairs(replays, arm, h)
            d, c = pairs["d"], pairs["c"]
            entry: dict[str, Any] = {"n_design_pairs": int(len(d)),
                                     "mismatched_weeks": pairs["mismatched_weeks"],
                                     "unpaired_weeks": pairs["unpaired_weeks"],
                                     "mean_crps_a0": float(np.mean(c)) if len(c) else None,
                                     "flags": []}
            rng = np.random.default_rng([BOOTSTRAP_SEED, h, ARM_INDEX[arm], 7])
            if len(d) < BLOCK_LENGTH[h]:
                entry.update({"status": "not_computable", "flags": ["insufficient_design_pairs"]})
                per_arm[arm][str(h)] = entry
                continue
            e = d - float(np.mean(d))  # 중심화 — 효과를 뺀 잡음 구조만
            if arm == "A5":
                power = {}
                for label, n_trial in (("n_min", N_MIN[h]), ("n_exp", N_EXP[h])):
                    index = _trial_index(rng, len(e), n_trial, h, trials)
                    flags = ni_pass_flags(e[index], c[index], h, alpha=ALPHA / NONINFERIORITY_M)
                    power[label] = float(np.mean(flags))
                entry.update({"status": "computed", "power_at_true_zero": power})
                per_arm[arm][str(h)] = entry
                continue
            values = {}
            for label, n_trial in (("n_min", N_MIN[h]), ("n_exp", N_EXP[h])):
                index = _trial_index(rng, len(e), n_trial, h, trials)
                critical = critical_effects(e[index], h, alpha=ALPHA / SUPERIORITY_M)
                values[label] = float(np.quantile(critical, POWER))
            mean_c = float(np.mean(c))
            entry.update({
                "mde_abs_at_nmin": values["n_min"],
                "mde_rel_at_nmin": values["n_min"] / mean_c,
                "mde_rel_at_nexp": values["n_exp"] / mean_c,
                "status": "computed",
            })
            if not representative:
                entry.update({"status": "not_computable", "mde_rel_at_nmin": None, "mde_rel_at_nexp": None,
                              "mde_abs_at_nmin": None, "flags": ["design_non_representative"],
                              "input_rows_differing_from_a0": int(differing)})
            per_arm[arm][str(h)] = entry
    headline: dict[str, float | None] = {}
    for h in VERDICT_HORIZONS:
        values = [per_arm[arm][str(h)]["mde_rel_at_nmin"] for arm in ("A1", "A2", "A3")
                  if per_arm[arm][str(h)].get("status") == "computed"]
        headline[str(h)] = max(values) if values else None
        for arm in ("A1", "A2", "A3", "A4"):
            if per_arm[arm][str(h)].get("status") == "not_computable" and headline[str(h)] is not None:
                per_arm[arm][str(h)]["proxy_reference"] = headline[str(h)]
    return {
        "schema_version": 1, "kind": "v15_mde_summary",
        "method": {"trials": trials, "power": POWER, "alpha_assumed": f"{ALPHA}/{SUPERIORITY_M}",
                   "ni_alpha_assumed": f"{ALPHA}/{NONINFERIORITY_M}", "n_min": N_MIN, "n_exp": N_EXP,
                   "outer_rng": "default_rng([20261111, h, ARM_INDEX[X], 7]) — n_min 시행 뒤 n_exp 시행",
                   "inner_rng": "verdict.bootstrap_indices (default_rng([20261111, h]), B=5000)",
                   "representativeness_rule": "단일 변경 축이 입력 프레임(A3·A4)인 팔의 설계창 입력 행 차이 < 5 → not_computable"},
        "values_by_horizon": headline,
        "per_arm": per_arm,
        "excludes": list(SUMMARY_EXCLUDES),
        "notice": NOTICE,
        "numeric_model_exception": [
            "MDE·base rate 참조 — 채택 근거·캘리브레이션 표본 아님",
            "블록 길이·창 선택·n_min 이 사후 지식을 간접 내포할 수 있다",
            "설계창은 GFC 포함 — 절대 MDE 과대, 상대 MDE 근사",
            "A4 는 산출 불가(설계 비대표), proxy 는 참고",
            "LLM 무관",
        ],
    }


def write_mde_prereg(root: Path, *, staging: Path, trials: int = TRIALS) -> dict[str, Any]:
    """7파일(replay 6 + mde_v1) 원자 쓰기 — 전부 또는 없음. 하나라도 이미 있으면 거부."""
    targets = [root / replay_relative(arm) for arm in MDE_ARMS] + [root / MDE_SUMMARY_RELATIVE]
    existing = [path.relative_to(root).as_posix() for path in targets if path.exists()]
    if existing:
        raise TimeSeriesV15ContractError(f"MDE prereg 파일이 이미 있다(write-once): {existing}")
    replays: dict[str, dict[str, Any]] = {}
    for arm in MDE_ARMS:
        path = Path(staging) / f"mde_{arm}.json"
        if not path.is_file():
            raise TimeSeriesV15ContractError(f"MDE staging 누락: {path.name} — 아무것도 쓰지 않는다")
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = {key: value for key, value in payload.items() if key != "content_hash"}
        if payload.get("arm") != arm or payload.get("content_hash") != canonical_hash(body):
            raise TimeSeriesV15ContractError(f"MDE staging 무결성 실패: {path.name}")
        replays[arm] = payload
    kernels = {payload["kernel_code_hash"] for payload in replays.values()}
    snapshots = {payload["data_snapshot_sha"] for payload in replays.values()}
    if len(kernels) != 1 or len(snapshots) != 1:
        raise TimeSeriesV15ContractError("MDE 재생 6팔의 kernel_code_hash·data_snapshot_sha 가 같아야 한다")
    summary = summarize_mde(replays, trials=trials)
    encoded = {arm: (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
               for arm, payload in replays.items()}
    summary["replay_sha256"] = {arm: hashlib.sha256(body).hexdigest() for arm, body in encoded.items()}
    summary["kernel_code_hash"] = kernels.pop()
    summary["data_snapshot_sha"] = snapshots.pop()
    summary["mde_code_hash"] = mde_code_hash(root)
    summary["canonical_hash"] = canonical_hash(summary)
    summary_body = (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (root / PREREG_RELATIVE).mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".mde_tmp_", dir=root / PREREG_RELATIVE))
    try:
        for arm, body in encoded.items():
            (temporary / replay_relative(arm).name).write_bytes(body)
        (temporary / MDE_SUMMARY_RELATIVE.name).write_bytes(summary_body)
        for path in targets:
            os.replace(temporary / path.name, path)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {"written": [path.relative_to(root).as_posix() for path in targets],
            "summary_sha256": hashlib.sha256(summary_body).hexdigest(),
            "values_by_horizon": summary["values_by_horizon"]}
