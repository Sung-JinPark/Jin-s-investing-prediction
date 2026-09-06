#!/usr/bin/env python
"""tools/v12_lowcost_options.py — S1-3 저비용 옵션 판정 수치 산출 (읽기 전용).

PROMPT 4문("놓친 저비용 옵션": V10 조합 격자 · V11 저모멘텀 조건부 recenter · 트랙 간 신호 결합)의
근거 수치를 커밋된 run/ledger/diagnostic 만으로 만든다. 백테스트·홀드아웃·봉인 실행 0.
쓰기는 ``--out`` 한 파일뿐(기본 ``docs/review/lowcost_options.json``).

무엇을 계산하는가
-----------------
A. **V10 조합 격자** — 5축(W1 상태조건 κ / W2 혼합가중 / W3 블렌드 γ / W4 재보정 / W5 h5)의
   축별 후보를 **origin별 Δ 합**으로 결합한 대리(surrogate) 격자 143조합. 각 조합에
   S1-1 판정식(상위5% 제거 부호반전 ∧ GFC 제외 평균 < mde50)을 그대로 적용한다.
B. **V11 저모멘텀 조건부** — S1-1 산출(``docs/review/verdict_recompute.json``)에서 해당 셀만
   추출·요약한다(재계산 아님 — 같은 수치를 다시 만들지 않는다).
C. **트랙 결합** — V10 챔피언 · V9 최선 exog · V11 P1 recenter(정본 split forward)의 origin별 Δ를
   같은 417 origin 축에 정렬해 상관·합 결합·**표본외창(2011–14) 결합 Δ + CI90**을 낸다.

정직성 경계 (본 스크립트가 만들 수 **없는** 것)
-----------------------------------------------
* 조합 격자는 **가법 대리지표**다. 실제 조합은 파이프라인 재실행(=백테스트)이라 이 루프에서 금지다.
  가법성이 정확히 성립하는 것은 각 층이 예측분포의 서로 다른 부분에 작용할 때뿐이며,
  W1·W3처럼 같은 분산 축을 건드리는 층 사이에서는 근사다. → 산출 필드 ``surrogate=true``.
* 단, **GFC 견인 비중은 가법 하에서 성분 비중의 Δ-가중 평균**이므로, 모든 성분이 높은 GFC 비중을
  가지면 어떤 양의 결합도 그 아래로 못 내려간다 — 이 구조적 함의는 근사에 덜 민감하다.
* V11 성분의 기준선이 V10 E0 와 같은지는 ``baseline_identity_check`` 로 실측해 병기한다.

방법 정본은 S1-1(``tools/v12_recompute_verdict.py``)과 동일: 쌍대 통계 = origin별
d_i = mean_{h∈{21,63}}(crps_base − crps_exp), CI90 = 정상 블록 부트스트랩(ℓ=13, B=2000,
seed 20260902, percentile[5,95]), mde50 = 1.645·se.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

LONG_HORIZONS = (21, 63)
GFC_CANONICAL = ("2008-01-01", "2009-06-30")
SPLIT_BOUNDARY = "2010-12-31"          # V11 정본 split — 전반 2007–10 / 후반 2011–14
DUAL_BLOCK = 13
DUAL_REPLICATES = 2000
DUAL_SEED = 20260902
CALM_PCT = 80.0
BOOTSTRAP_BUDGET = 140                 # 초과 시 truncated 로 기록(조용한 절단 금지)

_NORM = statistics.NormalDist()
_INV_SQRT_PI = 1.0 / math.sqrt(math.pi)

V10_AXES = {
    "W1": ["V10_W1_kappa_05", "V10_W1_kappa_10", "V10_W1_sens_rv_kappa_10"],
    "W2": ["V10_W2_S1", "V10_W2_S2", "V10_W2_S3"],
    "W3": ["V10_W3_gamma_m010", "V10_W3_gamma_m020"],
    "W4": ["V10_W4a_isotonic", "V10_W4b_two_layer"],
    "W5": ["V10_W5_h5"],
}
V9_EXOG = ["V9_E1_m2sl_liquidity", "V9_E2_totci_credit",
           "V9_E3_totll_credit", "V9_E4_wrmfns_mmf"]


# --------------------------------------------------------------------------- 공통 로더

def _ledger(track: str) -> list[dict[str, Any]]:
    path = ROOT / f"data/timeseries_{track}/ledgers/development_experiments.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _experiment_id(track: str, label: str) -> str:
    for row in _ledger(track):
        if row.get("experiment_label") == label:
            return str(row["experiment_id"])
    raise KeyError(f"{track}: {label!r} not in ledger")


def _load_run(track: str, label: str) -> dict[str, Any]:
    path = ROOT / f"data/timeseries_{track}/runs/dev_{_experiment_id(track, label)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _crps_map(run: dict[str, Any]) -> dict[tuple[str, int], float]:
    return {(s["date"], int(s["horizon"])): float(s["model_crps"]) for s in run["scores"]}


def per_origin_delta(base_run: dict[str, Any], exp_run: dict[str, Any]) -> tuple[list[str], np.ndarray]:
    base = _crps_map(base_run)
    by_origin: dict[str, list[float]] = {}
    for score in exp_run["scores"]:
        horizon = int(score["horizon"])
        key = (score["date"], horizon)
        if horizon in LONG_HORIZONS and key in base:
            by_origin.setdefault(score["date"], []).append(base[key] - float(score["model_crps"]))
    origins = sorted(by_origin)
    return origins, np.array([float(np.mean(by_origin[o])) for o in origins])


def mean_long_crps(run: dict[str, Any]) -> float:
    return float(np.mean([float(s["model_crps"]) for s in run["scores"]
                          if int(s["horizon"]) in LONG_HORIZONS]))


class Bootstrapper:
    """S1-1 과 동일한 블록 부트스트랩. 호출 횟수를 세어 예산 초과를 기록한다."""

    def __init__(self, budget: int = BOOTSTRAP_BUDGET) -> None:
        self.budget = budget
        self.calls = 0
        self.refused = 0

    def ci90(self, per_origin: np.ndarray, *, seed: int = DUAL_SEED,
             block: int = DUAL_BLOCK, replicates: int = DUAL_REPLICATES) -> dict[str, Any] | None:
        if self.calls >= self.budget:
            self.refused += 1
            return None
        self.calls += 1
        rng = np.random.default_rng(seed)
        n = len(per_origin)
        draws = []
        for _ in range(replicates):
            picks: list[float] = []
            while len(picks) < n:
                start = int(rng.integers(0, n))
                length = int(rng.geometric(1.0 / block))
                picks.extend(per_origin[(start + np.arange(length)) % n])
            draws.append(float(np.mean(picks[:n])))
        lower, upper = np.percentile(draws, [5, 95])
        se = float(np.std(draws, ddof=1))
        return {"ci90": [float(lower), float(upper)], "bootstrap_se": se,
                "mde50": 1.645 * se, "ci90_lower_positive": bool(lower > 0)}


# --------------------------------------------------------------------------- 판정식 (S1-1 승계)

def artifact_profile(origins: Sequence[str], deltas: np.ndarray, denom: float,
                     boot: Bootstrapper | None, *, with_ci: bool,
                     with_trimmed_ci: bool = False) -> dict[str, Any]:
    """S1-1 판정식 입력 일체: 평균·상대개선·GFC 견인·상위5% 제거·후반창."""
    n = len(origins)
    mean = float(deltas.mean())
    gfc_mask = np.array([GFC_CANONICAL[0] <= o <= GFC_CANONICAL[1] for o in origins])
    post_mask = np.array([o > SPLIT_BOUNDARY for o in origins])
    total = float(deltas.sum())

    drop = math.ceil(0.05 * n)
    order = np.argsort(deltas)
    trimmed = deltas[np.sort(order[: n - drop])]
    top_sum = float(deltas[order[n - drop:]].sum())

    out: dict[str, Any] = {
        "origin_count": n,
        "mean_delta": mean,
        "relative_improvement": mean / denom,
        "net_delta_sum": total,
        "gfc_origin_share": float(gfc_mask.mean()),
        "gfc_delta_share": (float(deltas[gfc_mask].sum()) / total) if total else None,
        # 순델타가 0 근처면 견인 비중은 분모 폭발로 무의미. mde50 대비 판정은 CI 산출 시에만 가능하므로
        # 여기서는 None 으로 두고 아래 CI 분기에서 채운다 (부호만으로 판단하지 않는다).
        "gfc_delta_share_interpretable": None,
        "mean_excluding_gfc": float(deltas[~gfc_mask].mean()),
        "post2010_mean": float(deltas[post_mask].mean()),
        "post2010_n": int(post_mask.sum()),
        "top5pct": {
            "origins_dropped": drop,
            "share_of_net": (top_sum / total) if total else None,
            "mean_after_removal": float(trimmed.mean()),
            "sign_flips": bool(mean > 0 and trimmed.mean() < 0),
        },
    }
    if with_ci and boot is not None:
        full = boot.ci90(deltas)
        if full:
            out.update({"ci90": full["ci90"], "bootstrap_se": full["bootstrap_se"],
                        "mde50": full["mde50"], "ci90_lower_positive": full["ci90_lower_positive"]})
            out["mean_excluding_gfc_over_mde50"] = out["mean_excluding_gfc"] / full["mde50"]
            out["artifact_verdict"] = bool(out["top5pct"]["sign_flips"]
                                           and out["mean_excluding_gfc"] < full["mde50"])
            # 견인 비중 해석 가능 조건: 평균이 양이고 순델타가 mde50 규모를 넘을 것
            out["gfc_delta_share_interpretable"] = bool(mean > 0 and mean > full["mde50"] * 0.5)
        post_ci = boot.ci90(deltas[post_mask])
        if post_ci:
            out["post2010_ci90"] = post_ci["ci90"]
            out["post2010_ci90_lower_positive"] = post_ci["ci90_lower_positive"]
        if with_trimmed_ci:
            tci = boot.ci90(trimmed)
            if tci:
                out["top5pct"]["ci90_after_removal"] = tci["ci90"]
                out["top5pct"]["ci90_lower_positive_after_removal"] = tci["ci90_lower_positive"]
    return out


# --------------------------------------------------------------------------- A. V10 조합 격자

def v10_grid(boot: Bootstrapper) -> dict[str, Any]:
    e0 = _load_run("v10", "V10_E0_identity")
    denom = mean_long_crps(e0)
    labels = [lab for axis in V10_AXES.values() for lab in axis]
    deltas: dict[str, np.ndarray] = {}
    origins: list[str] = []
    singles: list[dict[str, Any]] = []

    # 프록시 게이트 통과 여부는 원장 필드에서 읽는다(하드코딩 금지) — 커버리지 대역 이탈 축을 가린다.
    proxy_pass = {r["experiment_label"]: bool((r.get("proxy") or {}).get("pass"))
                  for r in _ledger("v10")}
    h63_cov = {r["experiment_label"]: r["horizons"]["63"].get("coverage_p10_p90")
               for r in _ledger("v10")}

    for label in labels:
        o, d = per_origin_delta(e0, _load_run("v10", label))
        origins = origins or o
        assert o == origins, f"origin 축 불일치: {label}"
        deltas[label] = d
        axis = next(a for a, members in V10_AXES.items() if label in members)
        record = {"label": label, "axis": axis, "identical_to_e0": bool(np.all(d == 0.0)),
                  "proxy_pass": proxy_pass.get(label), "h63_coverage_p10_p90": h63_cov.get(label)}
        record.update(artifact_profile(o, d, denom, boot, with_ci=not record["identical_to_e0"]))
        singles.append(record)

    live = [s["label"] for s in singles if not s["identical_to_e0"]]
    corr = {a: {b: float(np.corrcoef(deltas[a], deltas[b])[0, 1]) for b in live} for a in live}

    # 축별 최선(평균 Δ 최대) — 조합 격자의 대표 후보
    axis_best = {}
    for axis, members in V10_AXES.items():
        live_members = [m for m in members if m in live]
        if live_members:
            axis_best[axis] = max(live_members, key=lambda m: float(deltas[m].mean()))

    # 격자: 축마다 (미사용 | 후보 하나) — 전 조합. 단일 축만 쓰는 조합은 singles 와 중복이라 제외.
    axis_options = [[None] + [m for m in members if m in live] for members in V10_AXES.values()]
    combos: list[dict[str, Any]] = []
    for picks in itertools.product(*axis_options):
        chosen = [p for p in picks if p]
        if len(chosen) < 2:
            continue
        d = np.sum([deltas[c] for c in chosen], axis=0)
        rec = {"members": chosen, "n_axes": len(chosen), "surrogate": True}
        rec.update(artifact_profile(origins, d, denom, None, with_ci=False))
        combos.append(rec)

    # 부트스트랩은 '탈출 후보'에만 — 상위5% 제거 후에도 양수이거나, GFC 제외 평균이 가장 큰 조합.
    escape = [c for c in combos if not c["top5pct"]["sign_flips"]]
    by_calm = sorted(combos, key=lambda c: -c["mean_excluding_gfc"])[:5]
    by_post = sorted(combos, key=lambda c: -c["post2010_mean"])[:5]
    all_best = {"members": [axis_best[a] for a in sorted(axis_best)], "role": "축별 최선 전축 결합"}
    d_all = np.sum([deltas[m] for m in all_best["members"]], axis=0)
    all_best.update(artifact_profile(origins, d_all, denom, boot, with_ci=True))

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = {tuple(all_best["members"])}
    for cand in escape[:10] + by_calm + by_post:
        key = tuple(cand["members"])
        if key in seen:
            continue
        seen.add(key)
        d = np.sum([deltas[m] for m in cand["members"]], axis=0)
        rec = dict(cand)
        rec.update(artifact_profile(origins, d, denom, boot, with_ci=True))
        selected.append(rec)

    # 적격 격자: 프록시 게이트(커버리지 대역 포함) PASS 이고 Δ≠0 인 후보만. W1 주상태·W2 전 세트는
    # h63 p10–p90 커버리지 대역(0.84) 이탈로 FAIL 이라 조합에 넣어도 채택 불가 — 여기서 배제한다.
    adm_labels = [lab for lab in live if proxy_pass.get(lab)]
    adm_options = [[None] + [m for m in members if m in adm_labels] for members in V10_AXES.values()]
    admissible: list[dict[str, Any]] = []
    for picks in itertools.product(*adm_options):
        chosen = [p for p in picks if p]
        if len(chosen) < 2:
            continue
        d = np.sum([deltas[c] for c in chosen], axis=0)
        rec = {"members": chosen, "n_axes": len(chosen), "surrogate": True, "proxy_pass_members": True}
        rec.update(artifact_profile(origins, d, denom, boot, with_ci=True, with_trimmed_ci=True))
        admissible.append(rec)

    return {
        "baseline": "V10_E0_identity",
        "denominator_mean_long_crps": denom,
        "origin_count": len(origins),
        "singles": singles,
        "admissible_labels": adm_labels,
        "admissible_grid": admissible,
        "admissible_note": ("프록시 PASS 후보만으로 만든 조합 격자. 조합의 커버리지 프록시 자체는 "
                            "Δ 합으로 계산 불가(분포 성질) — 성분이 PASS 라도 조합이 PASS 라는 보장은 없다."),
        "per_origin_delta_correlation": corr,
        "axis_best": axis_best,
        "grid_size": len(combos),
        "grid": combos,
        "all_axis_best_combo": all_best,
        "escape_candidates_count": len(escape),
        "bootstrapped_selection": selected,
        "grid_definition": "축마다 (미사용|후보1) 선택 후 origin별 Δ 합 — 가법 대리지표",
    }


# --------------------------------------------------------------------------- B. V11 저모멘텀

def v11_low_momentum() -> dict[str, Any]:
    path = ROOT / "docs/review/verdict_recompute.json"
    src = json.loads(path.read_text(encoding="utf-8"))
    cells = [r for r in src["v11"]["results"]
             if r.get("variant") == "low_mom_tertile" and "improved" in r]
    linear = [r for r in src["v11"]["results"]
              if r.get("variant") == "p1_linear" and "improved" in r]

    def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        combos: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for r in rows:
            combos.setdefault((r["horizon"], r["boundary"]), []).append(r)
        both_sign = [k for k, v in combos.items() if len(v) == 2 and all(x["improved"] for x in v)]
        both_ci = [k for k, v in combos.items()
                   if len(v) == 2 and all(x["improvement_ci90_lower_positive"] for x in v)]
        fwd_ci = [k for k, v in combos.items()
                  for x in v if x["direction"] == "forward" and x["improvement_ci90_lower_positive"]]
        return {
            "cells": len(rows),
            "combos": len(combos),
            "both_directions_sign_improved": [{"horizon": h, "boundary": b} for h, b in both_sign],
            "both_directions_ci90_positive": [{"horizon": h, "boundary": b} for h, b in both_ci],
            "forward_only_ci90_positive": [{"horizon": h, "boundary": b} for h, b in fwd_ci],
            "worst_reverse_relative_change": max(
                (r["crps_relative_change"] for r in rows if r["direction"] == "reverse"), default=None),
            "cells_detail": [
                {"horizon": r["horizon"], "boundary": r["boundary"], "direction": r["direction"],
                 "improvement_mean": r["improvement_mean"], "ci90": r["improvement_ci90"],
                 "ci90_lower_positive": r["improvement_ci90_lower_positive"],
                 "crps_relative_change": r["crps_relative_change"],
                 "mde50": 1.645 * r["bootstrap_se"],
                 "abs_effect_over_mde50": abs(r["improvement_mean"]) / (1.645 * r["bootstrap_se"])
                 if r["bootstrap_se"] else None}
                for r in rows],
        }

    return {
        "source": "docs/review/verdict_recompute.json (S1-1 산출 — 재계산 아님)",
        "adoption_rule": "양방향 CI90 하한 > 0",
        "low_mom_tertile": _summary(cells),
        "p1_linear_reference": _summary(linear),
        "permutation_null": src["v11"]["summary"]["permutation_null"],
    }


# --------------------------------------------------------------------------- C. 트랙 결합

def _norm_crps_unit(z: float) -> float:
    return z * (2.0 * _NORM.cdf(z) - 1.0) + 2.0 * _NORM.pdf(z) - _INV_SQRT_PI


def _norm_crps_unit_vec(z: np.ndarray) -> np.ndarray:
    from scipy.special import ndtr  # noqa: PLC0415
    pdf = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return z * (2.0 * ndtr(z) - 1.0) + 2.0 * pdf - _INV_SQRT_PI


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    var = float(((x - x.mean()) ** 2).sum())
    if var <= 0:
        return float(y.mean()), 0.0
    b = float(((x - x.mean()) * (y - y.mean())).sum() / var)
    return float(y.mean() - b * x.mean()), b


def _v11_frame(horizon: int) -> dict[str, list]:
    path = ROOT / "data/timeseries_v11/diagnostics/aligned_origin_frame.json"
    return json.loads(path.read_text(encoding="utf-8"))["horizons"][str(horizon)]


def v11_recenter_delta(origins: Sequence[str]) -> tuple[np.ndarray, dict[str, Any]]:
    """정본 split forward(2007–10 적합 → 2011–14 적용, calm p80)의 origin별 Δ를 417축에 정렬.

    맵이 발화하지 않는 origin(비-calm 또는 학습창)은 Δ=0 — '적용하지 않았다'를 0 으로 둔다.
    """
    index = {o: i for i, o in enumerate(origins)}
    fired = np.zeros(len(origins), dtype=float)
    counts = np.zeros(len(origins), dtype=float)
    meta: dict[str, Any] = {"horizons": {}}
    for horizon in LONG_HORIZONS:
        frame = _v11_frame(horizon)
        primary = np.array(frame["primary"], dtype=float)
        threshold = float(np.percentile(primary, CALM_PCT))
        rows = []
        for i, date in enumerate(frame["date"]):
            if primary[i] > threshold:
                continue
            u = min(max(float(frame["u"][i]), 1e-6), 1.0 - 1e-6)
            z = _NORM.inv_cdf(u)
            crps = float(frame["crps"][i])
            sigma = crps / _norm_crps_unit(z)
            rows.append((date, sigma, sigma * z, crps, float(frame["P1_ret_mom_21"][i])))
        dates = [r[0] for r in rows]
        sigma = np.array([r[1] for r in rows])
        raw_err = np.array([r[2] for r in rows])
        crps = np.array([r[3] for r in rows])
        p1 = np.array([r[4] for r in rows])
        train = np.array([i for i, d in enumerate(dates) if d <= SPLIT_BOUNDARY])
        test = np.array([i for i, d in enumerate(dates) if d > SPLIT_BOUNDARY])
        a, b = _ols(p1[train], raw_err[train])
        shifts = a + b * p1[test]
        after = sigma[test] * _norm_crps_unit_vec((raw_err[test] - shifts) / sigma[test])
        d = crps[test] - after
        for j, idx in enumerate(test):
            k = index[dates[idx]]
            fired[k] += float(d[j])
            counts[k] += 1.0
        meta["horizons"][horizon] = {
            "calm_threshold_p80": threshold, "train_n": int(train.size), "test_n": int(test.size),
            "fit_intercept": a, "fit_slope": b,
            "mean_improvement_on_fired": float(d.mean()),
            "crps_relative_change": float((float(after.mean()) - float(crps[test].mean()))
                                          / float(crps[test].mean())),
        }
    delta = np.divide(fired, np.maximum(counts, 1.0))
    meta["origins_fired"] = int((counts > 0).sum())
    meta["origins_total"] = len(origins)
    return delta, meta


def track_combination(boot: Bootstrapper) -> dict[str, Any]:
    e0_10 = _load_run("v10", "V10_E0_identity")
    denom = mean_long_crps(e0_10)
    origins, d_v10 = per_origin_delta(e0_10, _load_run("v10", "V10_W3_gamma_m010"))

    e0_9 = _load_run("v9", "V9_E0_identity_no_new_features")
    v9_deltas = {}
    for label in V9_EXOG:
        o9, d9 = per_origin_delta(e0_9, _load_run("v9", label))
        assert o9 == origins, f"V9 origin 축 불일치: {label}"
        v9_deltas[label] = d9
    v9_best = max(v9_deltas, key=lambda k: float(v9_deltas[k].mean()))

    d_v11, v11_meta = v11_recenter_delta(origins)

    # 기준선 동일성 실측: V11 프레임의 crps 가 V10 E0 의 crps 와 같은 값인가?
    base_map = _crps_map(e0_10)
    diffs = []
    for horizon in LONG_HORIZONS:
        frame = _v11_frame(horizon)
        for date, crps in zip(frame["date"], frame["crps"]):
            key = (date, horizon)
            if key in base_map:
                diffs.append(abs(float(crps) - base_map[key]))
    # V9 의 E0 는 별도 파이프라인 기준선 — V10 E0 와 같은 값인지도 실측한다(가법 대리의 전제).
    v9_map = _crps_map(e0_9)
    v9_diffs = [abs(v - base_map[k]) for k, v in v9_map.items()
                if k[1] in LONG_HORIZONS and k in base_map]
    identity = {"n_compared": len(diffs),
                "max_abs_diff": float(max(diffs)) if diffs else None,
                "mean_abs_diff": float(np.mean(diffs)) if diffs else None,
                "v10_e0_mean_long_crps": denom,
                "v9_e0_vs_v10_e0": {
                    "n_compared": len(v9_diffs),
                    "max_abs_diff": float(max(v9_diffs)) if v9_diffs else None,
                    "mean_abs_diff": float(np.mean(v9_diffs)) if v9_diffs else None,
                    "v9_e0_mean_long_crps": mean_long_crps(e0_9)}}

    components = {"v10_champion": d_v10, f"v9_best({v9_best})": v9_deltas[v9_best], "v11_recenter": d_v11}
    corr = {a: {b: float(np.corrcoef(components[a], components[b])[0, 1]) for b in components}
            for a in components}

    results: dict[str, Any] = {}
    for name, d in components.items():
        results[name] = artifact_profile(origins, d, denom, boot, with_ci=True)
    for combo in (("v10_champion", f"v9_best({v9_best})"),
                  ("v10_champion", "v11_recenter"),
                  (f"v9_best({v9_best})", "v11_recenter"),
                  ("v10_champion", f"v9_best({v9_best})", "v11_recenter")):
        d = np.sum([components[c] for c in combo], axis=0)
        results["+".join(combo)] = artifact_profile(origins, d, denom, boot, with_ci=True)

    return {
        "baseline_identity_check": identity,
        "v9_best_label": v9_best,
        "v9_all_means": {k: float(v.mean()) for k, v in v9_deltas.items()},
        "v11_recenter_meta": v11_meta,
        "per_origin_delta_correlation": corr,
        "profiles": results,
        "surrogate_note": "성분 기준선이 트랙마다 달라(합은 가법 대리지표) — baseline_identity_check 로 실측 병기",
    }


# --------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/review/lowcost_options.json")
    args = parser.parse_args()

    boot = Bootstrapper()
    payload: dict[str, Any] = {
        "schema": "v12_lowcost_options_v1",
        "task": "S1-3",
        "read_only": True,
        "method": {
            "paired_statistic": "origin별 d_i = mean_{h∈{21,63}}(crps_base − crps_exp)",
            "bootstrap": {"kind": "stationary block", "block": DUAL_BLOCK,
                          "replicates": DUAL_REPLICATES, "seed": DUAL_SEED,
                          "percentiles": [5, 95], "mde50": "1.645·se"},
            "gfc_window": list(GFC_CANONICAL),
            "split_boundary": SPLIT_BOUNDARY,
            "artifact_rule": "S1-1 승계: 상위5% 제거 시 부호반전 ∧ GFC 제외 평균 Δ < mde50",
        },
        "A_v10_combination_grid": v10_grid(boot),
        "B_v11_low_momentum_conditional": v11_low_momentum(),
        "C_track_combination": track_combination(boot),
    }
    payload["bootstrap_usage"] = {"calls": boot.calls, "budget": boot.budget,
                                  "refused_due_to_budget": boot.refused}

    out = ROOT / args.out
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} (bootstrap calls={boot.calls}, refused={boot.refused})")


if __name__ == "__main__":
    main()
