"""V15-VOL 판정 산술 — 읽기 전용(쓰기 0). 승격·표시·배선 적용 없음, 사람이 수동으로 인쇄만 한다.

규칙(계약 verdict_rule, 결과 전 고정):
- 셀마다 결정론적 '첫 적격 접두' 1회: n≥60 ∧ floor(n/ℓ_h)≥5 ∧ min(사건,비사건)≥20 ∧ 국면(run) ≥5/5,
  접두 안 pending 원점 없음(scored=false 보류행은 처리 완료로 센다), 접두 마지막 원점 ≤ V13 최신 as_of − 20 XNAS 세션.
  늦게 파생된 V15 행(derived_at UTC 날짜 ≥ 원점 + 20 XNAS 세션 — V13 late_capture 백필이 오래된 원점을 나중에 끼우는
  경로)은 접두에서 제외한다(차단 아님·기술통계에는 포함). 이미 확정된 접두가 소급으로 바뀌는 경로를 닫는다(리뷰 N3).
- 쌍대 d_B = BS_PB − BS_arm (양수=팔 우세), d_L = LS_arm − LS_PB. 정지 블록 부트스트랩(기하 평균 ℓ_h=max(13,h), 순환)
  B=5000, rng default_rng([20261111, cell_index]) 셀당 1회 — 모든 팔·두 점수 공유(CRN). CI90 = 5·95 백분위(linear).
  단측 p = (1 + #{d̄*≤0})/(B+1).
- 음성 대조 = 블록 부호반전(교환) 귀무: K=floor(n/ℓ_h) 연속 블록(나머지는 마지막 블록), 120회, 내부 B=300 CI90 하한>0 비율 ≤0.10.
- 단일 에피소드 가드: 팔에 가장 유리한 블록 1개를 뺀 d̄>0 (K<2 이면 불통과). 로그 비열화: d_L CI90 상한 ≥ 0.
- 고정 가족 m=20 Holm(α 0.05, 미적격 p=1, 동률은 family_pairs 순서). 비기각은 가족 완결 전 not_rejected_provisional.
rv 셀 기계확정 비율은 닫힌형 하한(원점에서 알려진 수익만으로 rv21[t+k] 의 최솟값)을 이 파일 안에서 계산한다(보고 전용).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..timeseries_v13 import contracts as V13C
from ..timeseries_v13 import scoring as S
from . import contracts as C
from .resolve import _xnas_session_offset

SCHEMA = "v15_vol_shadow_verdict_dry_run"
RV_WINDOW = 21
RV_ANNUALIZATION = 252.0
PROB_COLUMNS = ("pb", "r1", "r2", "r3", "clim", "cond")
ARM_COLUMN = {"R1_platt": "r1", "R2_calm_jump": "r2", "R3_regime_mix": "r3"}
DISCLAIMER = "참고 의견 — 승격·표시·배선은 사용자 결정, 이 출력은 산술이며 매매 신호가 아니다."


# ── 부트스트랩 ────────────────────────────────────────────────────────────────
def stationary_indices(rng: np.random.Generator, n: int, block: int, replicates: int) -> np.ndarray:
    """정지 블록(기하 길이 평균 block, 순환) 재표본 인덱스 행렬 (replicates, n) — V13 block_boot_ci 규칙."""
    out = np.empty((replicates, n), dtype=np.int64)
    p = 1.0 / block
    for b in range(replicates):
        parts: list[np.ndarray] = []
        total = 0
        while total < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(p))
            parts.append((start + np.arange(length)) % n)
            total += length
        out[b] = np.concatenate(parts)[:n]
    return out


def boot_summary(d: np.ndarray, idx: np.ndarray) -> dict[str, Any]:
    means = np.asarray(d, float)[idx].mean(axis=1)
    lo, hi = np.quantile(means, [0.05, 0.95], method="linear")
    b = len(means)
    p = (1 + int((means <= 0).sum())) / (b + 1)
    return {"mean": float(np.mean(d)), "ci90": [float(lo), float(hi)], "p_one_sided": float(p), "B": b}


def block_ids(n: int, ell: int) -> tuple[np.ndarray, int]:
    """앞에서부터 ℓ 씩 K=floor(n/ℓ) 블록 — 나머지는 마지막 블록에 병합."""
    k = n // ell
    if k < 1:
        return np.zeros(n, dtype=np.int64), 0
    ids = np.minimum(np.arange(n) // ell, k - 1)
    return ids, k


def sign_flip_null_pass_rate(d: np.ndarray, ell: int, *, cell_index: int, arm_index: int,
                             draws: int = C.NULL_DRAWS, inner_b: int = C.NULL_BOOT_B) -> float:
    """블록 부호반전(교환) 귀무 아래 'CI90 하한 > 0' 통과율 — 샤프니스와 무관한 크기(size) 대조."""
    d = np.asarray(d, float)
    n = len(d)
    ids, k = block_ids(n, ell)
    if k < 1 or draws <= 0:
        return float("nan")
    rng = np.random.default_rng([C.BOOTSTRAP_SEED, cell_index, arm_index, 1])
    passes = 0
    for r in range(draws):
        signs = rng.integers(0, 2, size=k) * 2 - 1
        flipped = signs[ids] * d
        inner = np.random.default_rng([C.BOOTSTRAP_SEED, cell_index, arm_index, 2, r])
        idx = stationary_indices(inner, n, ell, inner_b)
        lo = float(np.quantile(flipped[idx].mean(axis=1), 0.05, method="linear"))
        passes += int(lo > 0)
    return passes / draws


def single_episode_guard(d: np.ndarray, ell: int) -> dict[str, Any]:
    d = np.asarray(d, float)
    ids, k = block_ids(len(d), ell)
    if k < 2:
        return {"pass": False, "K": k, "reason": "K<2"}
    means = np.array([d[ids == j].mean() for j in range(k)])
    drop = int(np.argmax(means))
    rest = d[ids != drop]
    value = float(rest.mean())
    return {"pass": bool(value > 0), "K": k, "dropped_block": drop, "mean_without_best_block": value}


def holm(pvalues: list[float], alpha: float = C.ALPHA) -> list[bool]:
    """Holm step-down — 동률은 입력 순서(family_pairs) 로 정렬(안정 정렬)."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: (pvalues[i], i))
    reject = [False] * m
    for rank, i in enumerate(order, start=1):
        if pvalues[i] <= alpha / (m - rank + 1):
            reject[i] = True
        else:
            break
    return reject


# ── rv 기계확정 (닫힌형 하한, 보고 전용) ─────────────────────────────────────
def rv_floor(known_sum: float, known_sumsq: float, n_known: int, k: int) -> float:
    if k >= RV_WINDOW or n_known == 0:
        return 0.0
    f1 = known_sum * k / (RV_WINDOW - k)
    f2 = f1 * f1 / k
    total = known_sum + f1
    variance = (known_sumsq + f2 - total * total / RV_WINDOW) / (RV_WINDOW - 1)
    return math.sqrt(max(variance, 0.0) * RV_ANNUALIZATION)


def mechanical_positive(returns: np.ndarray, t: int, h: int, theta: float) -> dict[str, Any]:
    """원점 t 에서 h 지평 안 rv 사건이 원점 정보만으로 확정됐는가 — k<21 만 가능."""
    returns = np.asarray(returns, float)
    best_k, best_floor = None, 0.0
    for k in range(1, min(h, RV_WINDOW - 1) + 1):
        start = t + k - RV_WINDOW + 1
        if start <= 0:
            raise C.TimeSeriesV15VolError("rv window before archive start")
        known = returns[start:t + 1]
        if not np.isfinite(known).all():
            raise C.TimeSeriesV15VolError("rv known window has NaN")
        floor = rv_floor(float(known.sum()), float((known ** 2).sum()), len(known), k)
        if floor > best_floor:
            best_floor, best_k = floor, k
    return {"max_floor": best_floor, "argmax_k": best_k, "mechanically_determined": bool(best_floor > theta)}


def _rv_mechanics(root: Path, cell: str, h: int, scored: list[dict[str, Any]], knowledge_cutoff: str) -> dict[str, Any]:
    from ..timeseries_v13 import features as F
    from ..timeseries_v2.market_archive import read_market_observations

    panel = F.build_panel(read_market_observations(root, knowledge_cutoff=knowledge_cutoff), start="2007-01-01")
    dates = [str(d) for d in panel["dates"]]
    index = {d: i for i, d in enumerate(dates)}
    returns = np.concatenate([[np.nan], np.diff(np.log(np.asarray(panel["ndx"], float)))])
    flags: list[bool] = []
    unknown = 0
    for row in scored:
        t = index.get(str(row["origin"]))
        if t is None:
            unknown += 1
            flags.append(False)
            continue
        try:
            flags.append(mechanical_positive(returns, t, h, C.THETA_RV)["mechanically_determined"])
        except C.TimeSeriesV15VolError:
            unknown += 1
            flags.append(False)
    mech = np.asarray(flags, bool)
    known = len(flags) - unknown
    out: dict[str, Any] = {"n": len(flags), "mechanical": int(mech.sum()), "unknown": unknown,
                           "ratio": float(mech.sum()) / known if known else None, "bridge": False}
    for label, mask in (("mechanical", mech), ("non_mechanical", ~mech)):
        sub = [row for row, keep in zip(scored, mask) if keep]
        out[f"brier_{label}"] = {col: float(np.mean([r["brier"][col] for r in sub]))
                                 for col in PROB_COLUMNS if sub and col in sub[0]["brier"]}
    return out


# ── 셀 상태·접두 ──────────────────────────────────────────────────────────────
def _late_derived(row: dict[str, Any]) -> bool:
    """derived_at(UTC 날짜) ≥ 원점 + PREFIX_SETTLE_SESSIONS XNAS 세션이면 True. 해석 불가도 True(보수 — 접두 제외)."""
    try:
        derived = datetime.fromisoformat(str(row.get("derived_at")))
        if derived.tzinfo is None:
            return True
        settle = _xnas_session_offset(date.fromisoformat(str(row["as_of"])), C.PREFIX_SETTLE_SESSIONS)
        return derived.astimezone(timezone.utc).date() >= settle
    except (KeyError, TypeError, ValueError, C.TimeSeriesV15VolError):
        return True


def _cell_origins(shadow_rows: list[dict[str, Any]], resolutions: dict[tuple[str, str], dict[str, Any]],
                  cell: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in sorted(shadow_rows, key=lambda r: str(r.get("as_of"))):
        if cell not in (row.get("cells") or {}):
            continue
        origin = str(row["as_of"])
        if origin in seen:
            raise C.TimeSeriesV15VolError(f"duplicate (cell, origin): {cell} {origin}")
        seen.add(origin)
        res = resolutions.get((str(row["run_id"]), cell))
        state = "pending" if res is None else ("scored" if res.get("scored") is True else "held")
        out.append({"origin": origin, "state": state, "resolution": res, "late_derived": _late_derived(row)})
    return out


def first_eligible_prefix(origins: list[dict[str, Any]], h: int, settle_limit: str | None) -> dict[str, Any]:
    """원점 순서 최단 적격 접두 — 결정론(언제 계산해도 같다). 반환 {eligible, end_index, n, ...}."""
    ell = C.block_length(h)
    n = events = ev_runs = ne_runs = 0
    prev: float | None = None
    for i, item in enumerate(origins):
        if settle_limit is None or item["origin"] > settle_limit:
            break
        if item.get("late_derived"):
            continue
        if item["state"] == "pending":
            return {"eligible": False, "reason": "pending_in_prefix", "blocked_at": item["origin"]}
        if item["state"] != "scored":
            continue
        y = float(item["resolution"]["label"])
        n += 1
        events += int(y == 1.0)
        if prev is None or y != prev:
            if y == 1.0:
                ev_runs += 1
            else:
                ne_runs += 1
        prev = y
        if (n >= C.MIN_ORIGINS and n // ell >= C.MIN_BLOCKS
                and min(events, n - events) >= C.MIN_EVENTS_EACH
                and min(ev_runs, ne_runs) >= C.MIN_EPISODES_EACH):
            return {"eligible": True, "end_index": i, "end_origin": item["origin"], "n": n, "events": events,
                    "event_runs": ev_runs, "non_event_runs": ne_runs}
    return {"eligible": False, "reason": "not_reached", "n_scored_within_settle": n, "events": events,
            "event_runs": ev_runs, "non_event_runs": ne_runs}


def _describe(rows: list[dict[str, Any]], h: int) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    ell = C.block_length(h)
    y = np.array([float(r["label"]) for r in rows])
    cols = [c for c in PROB_COLUMNS if c in rows[0]["probabilities"]]
    probs = {c: np.array([float(r["probabilities"][c]) for r in rows]) for c in cols}
    brier = {c: float(np.mean([r["brier"][c] for r in rows])) for c in cols}
    logs = {c: float(np.mean([r["log_score"][c] for r in rows])) for c in cols}
    bss: dict[str, Any] = {}
    for c in cols:
        if c in ("clim", "cond"):
            continue
        bss[c] = {f"vs_{base}": (1.0 - brier[c] / brier[base]) if brier.get(base) else None
                  for base in ("clim", "cond", "pb") if base != c}
    return {
        "n": len(rows), "events": int(y.sum()), "brier_mean": brier, "log_score_mean": logs, "bss": bss,
        "murphy_reliability": {c: S.murphy_reliability(probs[c], y) for c in cols},
        "calibration_in_the_large": {c: {"sum_p": float(probs[c].sum()), "events": int(y.sum())} for c in cols},
        "blocks_K": len(rows) // ell, "effective_blocks": len(rows) / ell,
        "episodes": S.episode_runs(y),
    }


def _load(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]], str | None]:
    contract = C.load_contract_v15_vol(root)
    mismatched = C.check_code_pins(root, contract)
    if mismatched:
        raise C.TimeSeriesV15VolError(f"code_pin_mismatch:{','.join(mismatched)} — verdict arithmetic refused")
    shadow_rows = C.read_rows(root / C.SHADOW_LEDGER_RELATIVE)
    resolutions = {(str(r["run_id"]), str(r["cell"])): r for r in C.read_rows(root / C.RESOLUTION_LEDGER_RELATIVE)}
    v13_rows = C.read_rows(root / V13C.LIVE_LEDGER_RELATIVE)
    latest = max((str(r.get("as_of")) for r in v13_rows if r.get("as_of")), default=None)
    return contract, shadow_rows, resolutions, latest


def shadow_verdict(root: Path, *, now: datetime | None = None, draws: int = C.NULL_DRAWS,
                   rv_mechanics: bool = True,
                   index_hook: Callable[[str, np.ndarray], None] | None = None) -> dict[str, Any]:
    """읽기 전용 판정 산술. 코드 핀 불일치면 raise(산술 인쇄 거부)."""
    current = now or datetime.now(timezone.utc)
    current = current if current.tzinfo else current.replace(tzinfo=timezone.utc)
    knowledge_cutoff = current.isoformat(timespec="seconds")
    contract, shadow_rows, resolutions, latest = _load(root)
    settle_limit = (_xnas_session_offset(date.fromisoformat(latest), -C.PREFIX_SETTLE_SESSIONS).isoformat()
                    if latest else None)
    specs = {s["name"]: s for s in C.cell_specs()}
    pairs = C.family_pairs()
    pair_out: dict[tuple[str, str], dict[str, Any]] = {}
    cells_out: dict[str, Any] = {}
    for cell_index, cell in enumerate(C.CELL_ORDER):
        h = int(specs[cell]["h"])
        ell = C.block_length(h)
        origins = _cell_origins(shadow_rows, resolutions, cell)
        prefix = first_eligible_prefix(origins, h, settle_limit)
        scored_all = [o["resolution"] for o in origins if o["state"] == "scored"]
        held: dict[str, int] = {}
        for o in origins:
            if o["state"] == "held":
                reason = str(o["resolution"].get("hold_reason"))
                held[reason] = held.get(reason, 0) + 1
        cell_report: dict[str, Any] = {
            "h": h, "block_length": ell, "origins": len(origins), "scored": len(scored_all),
            "held_by_reason": held, "pending": sum(1 for o in origins if o["state"] == "pending"),
            "late_derived_excluded_from_prefix": sum(1 for o in origins if o.get("late_derived")),
            "settle_limit": settle_limit, "prefix": prefix, "all_scored": _describe(scored_all, h),
        }
        arms_here = [arm for arm, c in pairs if c == cell]
        if prefix["eligible"]:
            pre_rows = [o["resolution"] for o in origins[:prefix["end_index"] + 1]
                        if o["state"] == "scored" and not o.get("late_derived")]
            cell_report["prefix_stats"] = _describe(pre_rows, h)
            n = len(pre_rows)
            idx = stationary_indices(np.random.default_rng([C.BOOTSTRAP_SEED, cell_index]), n, ell,
                                     C.BOOTSTRAP_REPLICATES)
            if index_hook is not None:
                index_hook(cell, idx)
            for arm in arms_here:
                col = ARM_COLUMN[arm]
                arm_index = C.ARMS.index(arm)
                d_b = np.array([r["brier"]["pb"] - r["brier"][col] for r in pre_rows])
                d_l = np.array([r["log_score"][col] - r["log_score"]["pb"] for r in pre_rows])
                brier_boot = boot_summary(d_b, idx)
                log_boot = boot_summary(d_l, idx)
                null_rate = sign_flip_null_pass_rate(d_b, ell, cell_index=cell_index, arm_index=arm_index,
                                                     draws=draws)
                guard = single_episode_guard(d_b, ell)
                pair_out[(arm, cell)] = {
                    "arm": arm, "cell": cell, "eligible": True, "n": n, "p": brier_boot["p_one_sided"],
                    "d_brier": brier_boot, "d_log": log_boot, "sign_flip_null_pass_rate": null_rate,
                    "single_episode_guard": guard,
                    "ci90_lower_gt_zero": brier_boot["ci90"][0] > 0,
                    "log_non_inferior": log_boot["ci90"][1] >= 0,
                    "void": bool(null_rate > C.NULL_PASS_RATE_MAX),
                }
        else:
            for arm in arms_here:
                pair_out[(arm, cell)] = {"arm": arm, "cell": cell, "eligible": False, "p": 1.0,
                                         "status": "insufficient"}
        if rv_mechanics and specs[cell]["target"] == "rv_exceedance" and scored_all:
            try:
                cell_report["rv_mechanics"] = _rv_mechanics(root, cell, h, scored_all, knowledge_cutoff)
            except Exception as exc:  # noqa: BLE001 — 보고 전용 진단, 판정 다리 아님
                cell_report["rv_mechanics"] = {"status": "unavailable", "reason": str(exc)}
        cells_out[cell] = cell_report

    pvalues = [float(pair_out[pair]["p"]) for pair in pairs]
    rejected = holm(pvalues)
    family_complete = all(pair_out[pair]["eligible"] for pair in pairs)
    holm_out = []
    for pair, p, rej in zip(pairs, pvalues, rejected):
        item = pair_out[pair]
        item["holm_reject"] = bool(rej)
        holm_out.append({"arm": pair[0], "cell": pair[1], "p": p, "reject": bool(rej)})
        if not item["eligible"]:
            item["status"] = "insufficient"
            continue
        others = bool(item["ci90_lower_gt_zero"] and not item["void"] and item["single_episode_guard"]["pass"]
                      and item["log_non_inferior"])
        item["conditions_other_than_holm"] = others
        if item["void"]:
            item["status"] = "void_negative_control"
        elif rej and others:
            item["status"] = "pass_shadow_superiority"
        elif not family_complete:
            item["status"] = "not_rejected_provisional"
        else:
            item["status"] = "fail"
    return {
        "schema": SCHEMA, "model_id": C.MODEL_ID, "read_only": True, "writes": 0,
        "knowledge_cutoff": knowledge_cutoff, "latest_v13_as_of": latest, "settle_limit": settle_limit,
        "family_size": C.FAMILY_SIZE, "family_complete": family_complete, "alpha": C.ALPHA,
        "draws": draws, "draws_is_contract_value": draws == C.NULL_DRAWS,
        "holm": holm_out, "pairs": [pair_out[pair] for pair in pairs], "cells": cells_out,
        "code_pins_ok": True, "disclaimer": DISCLAIMER,
    }


def main_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


def render_table(result: dict[str, Any]) -> str:
    lines = [f"V15-VOL 섀도 판정 산술 (읽기 전용) — knowledge_cutoff {result['knowledge_cutoff']}",
             f"V13 최신 as_of {result['latest_v13_as_of']} · 접두 확정 지평 {result['settle_limit']} · "
             f"가족 {result['family_size']}쌍 완결={result['family_complete']}",
             f"부호반전 draws {result['draws']} (계약값 {C.NULL_DRAWS}: {result['draws_is_contract_value']})"
             + ("" if result["draws_is_contract_value"] else " — 계약값 아님: void·pass 라벨은 판정이 아니다"),
             f"{'arm':<15}{'cell':<11}{'n':>5}{'p':>9}{'CI90_lo':>11}{'null':>7}{'guard':>7}{'log':>6}"
             f"{'holm':>6}{'other':>7}  status"]
    for item in result["pairs"]:
        if not item["eligible"]:
            lines.append(f"{item['arm']:<15}{item['cell']:<11}{'-':>5}{1.0:>9.4f}{'-':>11}{'-':>7}{'-':>7}{'-':>6}"
                         f"{'-':>6}{'-':>7}  insufficient")
            continue
        lines.append(f"{item['arm']:<15}{item['cell']:<11}{item['n']:>5}{item['p']:>9.4f}"
                     f"{item['d_brier']['ci90'][0]:>11.5f}{item['sign_flip_null_pass_rate']:>7.3f}"
                     f"{str(item['single_episode_guard']['pass'])[0]:>7}{str(item['log_non_inferior'])[0]:>6}"
                     f"{str(item['holm_reject'])[0]:>6}{str(item['conditions_other_than_holm'])[0]:>7}  {item['status']}")
    lines.append("other = Holm 외 4조건(CI90 하한·부호반전 귀무·단일 에피소드·로그 비열화) — 접두 고정이라 F 는 확정(pass 불가)")
    lines.append(result["disclaimer"])
    return "\n".join(lines)
