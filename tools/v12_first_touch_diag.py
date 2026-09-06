#!/usr/bin/env python
"""tools/v12_first_touch_diag.py — S2-1 first_touch 실력 계측 (읽기 전용).

표적
----
V8 ``E0_neutral_v2_identity`` run 의 origin별 (first_touch_probability, first_touch_actual).
터치 정의 = 원점 대비 지수 경로의 **구간 최소값 ≤ 0.90** (즉 −10% 이상 낙폭을 지평 안에서 한 번이라도
터치). 정본: ``src/ai_fc/timeseries_v8/backtest.py`` ::

    touch_actual = bool(np.min(np.exp(np.cumsum(actual_daily))) <= 0.90)
    touch_probability = float(np.mean(np.min(index_paths[:, :horizon], axis=1) <= 0.90))

p 는 2000 경로의 비율이므로 해상도는 1/2000. p=0 은 "<1/2000" 의 절단이라 로짓 변환 시
해상도 셀 중앙(1/4000)으로 클립한다.

계측 항목 (envelope S2-1 spec)
------------------------------
1. 지평별 Brier · 기후 Brier(① 표본내 상수기후 b, ② 전향적 확장기후 — 만기 도래분만 사용)
2. Brier skill (BSS) — 두 기후 각각. CI90 = 정상 블록 부트스트랩(ℓ=13, B=2000, seed 20260902).
3. Murphy 분해 REL − RES + UNC (10등간 bin · 5분위 bin 두 규약, 구간내 산포 잔차 명시).
4. 5분위 신뢰도 표 (p̄, 관측빈도, gap, Wilson CI).
5. 국면 분해 — GFC(2008-01-01~2009-06-30) vs 비GFC, calm(V10 primary ≤ p80) vs storm.
6. 과신 구조 재현 판정 — 사전 명시 3조건(O1 상위분위 gap, O2 로지스틱 기울기<1, O3 국면 초월).

부수: AUC(판별력), 지평 단조성(T4 근거), S3 split 터치 수(검정력).

방법 규약은 S1(tools/v12_recompute_verdict.py)과 동일하게 유지한다 — 부트스트랩 블록 13,
복제 2000, seed 20260902, percentile[5,95].

쓰기는 ``--out`` 한 파일뿐. 백테스트·홀드아웃·봉인 실행 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

V8_RUN_LABEL = "E0_neutral_v2_identity"
HORIZONS = (1, 5, 21, 63)
FOCUS_HORIZONS = (21, 63)

GFC_CANONICAL = ("2008-01-01", "2009-06-30")   # src/ai_fc/timeseries/backtest.py 정본
CALM_PCT = 80.0                                 # V11 동결문서 규약 (S1-2 canonical)

BLOCK = 13
REPLICATES = 2000
SEED = 20260902

PATH_COUNT = 2000
P_EPS = 1.0 / (2 * PATH_COUNT)                  # 몬테카를로 해상도 셀 중앙

QUANTILE_BINS = 5
FIXED_BINS = 10
EXPANDING_MIN_TRAIN = 20

S3_SPLIT = ("2010-12-31",)                      # 전반 ≤ 2010-12-31 < 후반 (설계도 §2)

_NORM = statistics.NormalDist()


# --------------------------------------------------------------------------- 적재

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _v8_experiment_id(label: str) -> str:
    path = ROOT / "data/timeseries_v8/ledgers/development_experiments.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("experiment_label") == label:
            return str(row["experiment_id"])
    raise KeyError(f"v8 ledger 에 experiment_label={label!r} 없음")


def load_first_touch() -> dict[str, Any]:
    exp_id = _v8_experiment_id(V8_RUN_LABEL)
    path = ROOT / f"data/timeseries_v8/runs/dev_{exp_id}.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    per_h: dict[int, dict[str, Any]] = {}
    for horizon in HORIZONS:
        rows = sorted((s for s in run["scores"] if int(s["horizon"]) == horizon),
                      key=lambda s: s["date"])
        per_h[horizon] = {
            "dates": [str(s["date"]) for s in rows],
            "p": np.array([float(s["first_touch_probability"]) for s in rows]),
            "y": np.array([1.0 if s["first_touch_actual"] else 0.0 for s in rows]),
        }
    return {
        "experiment_label": V8_RUN_LABEL,
        "experiment_id": exp_id,
        "run_path": path.relative_to(ROOT).as_posix(),
        "run_sha256": _sha256(path),
        "path_count": int(run.get("path_count", PATH_COUNT)),
        "window": run.get("window"),
        "window_role": run.get("window_role"),
        "per_horizon": per_h,
    }


def load_primary() -> dict[int, dict[str, float]]:
    """V10 primary(EWMA97 분산비) — origin별 위기 상태 프록시. V11 정렬 프레임에서 읽는다."""
    path = ROOT / "data/timeseries_v11/diagnostics/aligned_origin_frame.json"
    frame = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, dict[str, float]] = {}
    for key, payload in frame["horizons"].items():
        horizon = int(str(key).lstrip("h"))
        out[horizon] = {str(d): float(v) for d, v in zip(payload["date"], payload["primary"])}
    return out


# --------------------------------------------------------------------------- 부트스트랩

def block_index_draws(n: int, *, seed: int = SEED, block: int = BLOCK,
                      replicates: int = REPLICATES) -> list[np.ndarray]:
    """정상 블록 부트스트랩 인덱스(감싸기). S1 의 dual_ci90 와 동일한 RNG 호출 순서."""
    rng = np.random.default_rng(seed)
    draws: list[np.ndarray] = []
    for _ in range(replicates):
        idx: list[int] = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(1.0 / block))
            idx.extend(((start + np.arange(length)) % n).tolist())
        draws.append(np.asarray(idx[:n], dtype=int))
    return draws


def ci90(values: Sequence[float]) -> dict[str, Any] | None:
    finite = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if finite.size < 2:
        return None
    lower, upper = np.percentile(finite, [5, 95])
    se = float(np.std(finite, ddof=1))
    return {"ci90_lower": float(lower), "ci90_upper": float(upper),
            "bootstrap_se": se, "mde50": 1.645 * se, "replicates_used": int(finite.size)}


def wilson(successes: int, n: int, z: float = 1.6448536269514722) -> list[float] | None:
    """Wilson 구간(기본 90%). 관측빈도의 표본오차 표시용."""
    if n <= 0:
        return None
    phat = successes / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return [float(max(0.0, center - half)), float(min(1.0, center + half))]


# --------------------------------------------------------------------------- 통계

def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def auc(p: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = p[y > 0.5], p[y < 0.5]
    if pos.size == 0 or neg.size == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(p.size, dtype=float)
    sorted_p = p[order]
    i = 0
    while i < p.size:                                   # 동점 평균 순위
        j = i
        while j + 1 < p.size and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    r_pos = float(np.sum(ranks[y > 0.5]))
    n1, n0 = float(pos.size), float(neg.size)
    return float((r_pos - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def logit(p: np.ndarray, eps: float = P_EPS) -> np.ndarray:
    q = np.clip(p, eps, 1.0 - eps)
    return np.log(q / (1.0 - q))


def logistic_fit(x: np.ndarray, y: np.ndarray, *, ridge: float = 1e-6,
                 iters: int = 60) -> tuple[float, float] | None:
    """y ~ σ(a + b·x) IRLS. b<1 = 과신(예측이 실제보다 뾰족함), b>1 = 과소신뢰."""
    design = np.column_stack([np.ones_like(x), x])
    beta = np.zeros(2)
    for _ in range(iters):
        eta = design @ beta
        mu = 1.0 / (1.0 + np.exp(-np.clip(eta, -60, 60)))
        w = np.clip(mu * (1 - mu), 1e-9, None)
        grad = design.T @ (y - mu) - ridge * beta
        hess = design.T @ (design * w[:, None]) + ridge * np.eye(2)
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            return None
        beta = beta + step
        if not np.all(np.isfinite(beta)):
            return None
        if float(np.max(np.abs(step))) < 1e-10:
            break
    if not np.all(np.isfinite(beta)):
        return None
    return float(beta[0]), float(beta[1])


def bin_table(p: np.ndarray, y: np.ndarray, edges: np.ndarray) -> list[dict[str, Any]]:
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, len(edges) - 2)
    rows = []
    for k in range(len(edges) - 1):
        mask = idx == k
        n = int(mask.sum())
        if n == 0:
            rows.append({"bin": k, "edges": [float(edges[k]), float(edges[k + 1])],
                         "n": 0, "mean_p": None, "observed": None, "gap": None,
                         "touches": 0, "observed_ci90_wilson": None})
            continue
        mean_p = float(p[mask].mean())
        obs = float(y[mask].mean())
        rows.append({
            "bin": k, "edges": [float(edges[k]), float(edges[k + 1])], "n": n,
            "touches": int(y[mask].sum()), "mean_p": mean_p, "observed": obs,
            "gap": mean_p - obs, "observed_ci90_wilson": wilson(int(y[mask].sum()), n),
        })
    return rows


def murphy(p: np.ndarray, y: np.ndarray, edges: np.ndarray) -> dict[str, Any]:
    n = p.size
    ybar = float(y.mean())
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, len(edges) - 2)
    rel = res = 0.0
    for k in range(len(edges) - 1):
        mask = idx == k
        nk = int(mask.sum())
        if nk == 0:
            continue
        pk = float(p[mask].mean())
        yk = float(y[mask].mean())
        rel += nk / n * (pk - yk) ** 2
        res += nk / n * (yk - ybar) ** 2
    unc = ybar * (1 - ybar)
    bs = brier(p, y)
    return {
        "reliability": rel, "resolution": res, "uncertainty": unc,
        "rel_minus_res_plus_unc": rel - res + unc,
        "brier": bs,
        # REL−RES+UNC 는 '구간 평균 예측' 의 Brier 다. 원 예측과의 차 = 구간내 산포 + 교차항.
        # 음수 = binning 이 구간 안의 판별력을 버렸다는 뜻(원 예측이 더 낫다).
        "binning_residual": bs - (rel - res + unc),
        "binning_residual_meaning": "BS − (REL−RES+UNC); 음수 = binning 이 구간내 판별력을 소실",
        "bins_used": int(len({int(i) for i in idx})),
    }


def quantile_edges(p: np.ndarray, bins: int = QUANTILE_BINS) -> tuple[np.ndarray, dict[str, Any]]:
    """분위 경계. 동점 질량으로 경계가 붕괴되면 유효 bin 수를 함께 보고한다."""
    qs = np.linspace(0, 1, bins + 1)
    raw = np.quantile(p, qs)
    edges = np.unique(raw)
    if edges.size < 2:                              # 전 원점 동일 p (퇴화)
        edges = np.array([float(p.min()), float(p.max())])
    edges[0] = min(edges[0], float(p.min())) - 1e-12
    edges[-1] = max(edges[-1], float(p.max())) + 1e-12
    meta = {"requested_bins": bins, "effective_bins": int(len(edges) - 1),
            "raw_quantiles": [float(v) for v in raw],
            "collapsed_by_ties": bool(len(edges) - 1 < bins)}
    return edges, meta


# --------------------------------------------------------------------------- 확장 기후

def _to_date(text: str) -> date:
    y, m, d = (int(v) for v in text.split("-"))
    return date(y, m, d)


def expanding_climatology(dates: Sequence[str], y: np.ndarray, horizon: int,
                          *, slack_days: int = 7,
                          min_train: int = EXPANDING_MIN_TRAIN) -> dict[str, Any]:
    """전향적 기후 — 각 원점 시점에 **이미 만기가 지난** 과거 원점의 터치율만 사용.

    만기 판정은 달력 근사: h 세션 ≈ ceil(h·7/5) 달력일 + slack_days(휴일 여유).
    Jeffreys 평활 (touches+0.5)/(n+1). 학습표본 < min_train 인 앞부분 원점은 비교에서 제외한다.
    """
    maturity_days = math.ceil(horizon * 7 / 5) + slack_days
    dts = [_to_date(d) for d in dates]
    clim = np.full(len(dts), np.nan)
    train_n = np.zeros(len(dts), dtype=int)
    for i, di in enumerate(dts):
        matured = [j for j in range(i) if (dts[j] - di).days + maturity_days <= 0]
        train_n[i] = len(matured)
        if len(matured) >= min_train:
            hits = float(np.sum(y[matured]))
            clim[i] = (hits + 0.5) / (len(matured) + 1.0)
    eligible = np.isfinite(clim)
    return {"climatology": clim, "eligible": eligible, "train_n": train_n,
            "maturity_days": maturity_days, "slack_days": slack_days,
            "min_train": min_train, "eligible_n": int(eligible.sum())}


# --------------------------------------------------------------------------- 지평 계측

def horizon_block(dates: Sequence[str], p: np.ndarray, y: np.ndarray,
                  horizon: int, draws: list[np.ndarray]) -> dict[str, Any]:
    n = p.size
    base = float(y.mean())
    bs = brier(p, y)
    clim_in = base * (1 - base)
    bss_in = (1 - bs / clim_in) if clim_in > 0 else None

    # 표본내 상수기후 대비 원점별 손실차 (양수 = 모델 우수)
    loss_model = (p - y) ** 2
    loss_clim = (base - y) ** 2
    diff = loss_clim - loss_model

    qedges, qmeta = quantile_edges(p)
    fedges = np.linspace(0.0, 1.0, FIXED_BINS + 1)
    fedges[0] = -1e-12
    fedges[-1] = 1.0 + 1e-12

    fit = logistic_fit(logit(p), y) if 0 < base < 1 else None
    top_mask = p >= qedges[-2]
    top_gap = float(p[top_mask].mean() - y[top_mask].mean()) if top_mask.any() else None

    exp_clim = expanding_climatology(dates, y, horizon)
    elig = exp_clim["eligible"]
    if elig.sum() >= 30:
        p_e, y_e, c_e = p[elig], y[elig], exp_clim["climatology"][elig]
        bs_model_e = brier(p_e, y_e)
        bs_clim_e = brier(c_e, y_e)
        bss_e = (1 - bs_model_e / bs_clim_e) if bs_clim_e > 0 else None
        exp_summary = {
            "eligible_n": int(elig.sum()), "maturity_days": exp_clim["maturity_days"],
            "min_train": exp_clim["min_train"],
            "model_brier_on_eligible": bs_model_e,
            "expanding_climatology_brier": bs_clim_e,
            "bss_vs_expanding": bss_e,
            "climatology_mean": float(c_e.mean()),
            "observed_base_on_eligible": float(y_e.mean()),
        }
    else:
        p_e = y_e = c_e = None
        exp_summary = {"eligible_n": int(elig.sum()), "skipped": "적격 원점 < 30"}

    # ---- 부트스트랩 (동일 리샘플 인덱스로 모든 통계 재계산)
    boot: dict[str, list[float]] = {"brier": [], "bss_insample": [], "top_quintile_gap": [],
                                    "logistic_slope": [], "auc": [], "bss_expanding": [],
                                    "loss_diff_insample_fixed_b": [],
                                    "loss_diff_insample_replicate_b": [],
                                    "loss_diff_expanding": []}
    fails = {"logistic": 0, "auc": 0}
    idx_e = np.flatnonzero(elig)
    draws_e = None
    if p_e is not None and idx_e.size >= 30:
        draws_e = block_index_draws(int(idx_e.size), seed=SEED + 1)
    for r, idx in enumerate(draws):
        pb, yb = p[idx], y[idx]
        bb = float(yb.mean())
        boot["brier"].append(brier(pb, yb))
        boot["bss_insample"].append((1 - brier(pb, yb) / (bb * (1 - bb))) if 0 < bb < 1 else np.nan)
        boot["loss_diff_insample_fixed_b"].append(
            float(np.mean((base - yb) ** 2 - (pb - yb) ** 2)))
        boot["loss_diff_insample_replicate_b"].append(
            float(np.mean((bb - yb) ** 2 - (pb - yb) ** 2)))
        tm = pb >= qedges[-2]                       # 경계는 점추정에서 고정(추정량 불변)
        boot["top_quintile_gap"].append(float(pb[tm].mean() - yb[tm].mean()) if tm.any() else np.nan)
        fb = logistic_fit(logit(pb), yb)
        if fb is None or not (0 < bb < 1):
            boot["logistic_slope"].append(np.nan)
            fails["logistic"] += 1
        else:
            boot["logistic_slope"].append(fb[1])
        ab = auc(pb, yb)
        if ab is None:
            boot["auc"].append(np.nan)
            fails["auc"] += 1
        else:
            boot["auc"].append(ab)
        if draws_e is not None:
            je = draws_e[r]
            pe, ye, ce = p_e[je], y_e[je], c_e[je]
            bs_c = brier(ce, ye)
            boot["bss_expanding"].append((1 - brier(pe, ye) / bs_c) if bs_c > 0 else np.nan)
            boot["loss_diff_expanding"].append(
                float(np.mean((ce - ye) ** 2 - (pe - ye) ** 2)))

    return {
        "horizon": horizon,
        "n": n, "touches": int(y.sum()), "base_rate": base,
        "p_mean": float(p.mean()), "p_median": float(np.median(p)),
        "p_max": float(p.max()), "p_zero_count": int((p <= 0).sum()),
        "brier": bs,
        "climatology_brier_insample": clim_in,
        "brier_skill_vs_insample_climatology": bss_in,
        "mean_loss_diff_vs_climatology": float(diff.mean()),
        "auc": auc(p, y),
        "logistic_recalibration": (
            {"intercept": fit[0], "slope": fit[1],
             "slope_lt_1_means_overconfident": True} if fit else None),
        "top_quintile_gap": top_gap,
        "quantile_bins": {"meta": qmeta, "edges": [float(v) for v in qedges],
                          "table": bin_table(p, y, qedges)},
        "fixed_bins": {"edges": [float(v) for v in fedges],
                       "table": bin_table(p, y, fedges)},
        "murphy_quantile_bins": murphy(p, y, qedges),
        "murphy_fixed_bins": murphy(p, y, fedges),
        "expanding_climatology": exp_summary,
        "point_estimates": {
            "loss_diff_insample_fixed_b": float(diff.mean()),
            "loss_diff_insample_replicate_b": float(diff.mean()),
            "loss_diff_expanding": (float(np.mean((c_e - y_e) ** 2 - (p_e - y_e) ** 2))
                                    if p_e is not None else None),
        },
        "ci90": {k: ci90(v) for k, v in boot.items() if v},
        "bootstrap_failures": fails,
    }


# --------------------------------------------------------------------------- 국면 분해

def regime_block(dates: Sequence[str], p: np.ndarray, y: np.ndarray,
                 mask: np.ndarray, label: str, global_top_edge: float,
                 *, seed: int) -> dict[str, Any]:
    n = int(mask.sum())
    out: dict[str, Any] = {"regime": label, "n": n, "origin_share": float(mask.mean())}
    if n < 10:
        out["skipped"] = "원점 < 10"
        return out
    ps, ys = p[mask], y[mask]
    base = float(ys.mean())
    bs = brier(ps, ys)
    clim = base * (1 - base)
    out.update({
        "touches": int(ys.sum()), "base_rate": base, "p_mean": float(ps.mean()),
        "brier": bs, "climatology_brier_insample": clim,
        "brier_skill_vs_insample_climatology": (1 - bs / clim) if clim > 0 else None,
        "mean_calibration_gap": float(ps.mean() - ys.mean()),
        "auc": auc(ps, ys),
    })
    top = ps >= global_top_edge
    out["top_quintile_global_edge"] = float(global_top_edge)
    out["top_quintile_n"] = int(top.sum())
    out["top_quintile_gap"] = (float(ps[top].mean() - ys[top].mean())
                               if top.sum() >= 5 else None)
    fit = logistic_fit(logit(ps), ys) if 0 < base < 1 else None
    out["logistic_slope"] = fit[1] if fit else None
    draws = block_index_draws(n, seed=seed)
    gaps, slopes, mean_gaps = [], [], []
    for idx in draws:
        pb, yb = ps[idx], ys[idx]
        mean_gaps.append(float(pb.mean() - yb.mean()))
        tm = pb >= global_top_edge
        gaps.append(float(pb[tm].mean() - yb[tm].mean()) if tm.sum() >= 3 else np.nan)
        fb = logistic_fit(logit(pb), yb)
        slopes.append(fb[1] if fb and 0 < float(yb.mean()) < 1 else np.nan)
    out["ci90"] = {"mean_calibration_gap": ci90(mean_gaps),
                   "top_quintile_gap": ci90(gaps),
                   "logistic_slope": ci90(slopes)}
    out["caveat"] = ("부분표본은 시간축이 비연속 — 블록 부트스트랩은 근사"
                     if label.startswith("calm") or label.startswith("storm")
                     else "연속 구간")
    return out


# --------------------------------------------------------------------------- 판정

def replication_verdict(per_h: dict[int, dict[str, Any]],
                        regimes: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    """사전 명시 3조건. 결과를 보기 전에 정한 형식 그대로 채운다."""
    conditions: dict[str, Any] = {}

    o1 = {}
    for h in FOCUS_HORIZONS:
        block = per_h[h]
        c = (block.get("ci90") or {}).get("top_quintile_gap")
        o1[f"h{h}"] = {
            "point": block["top_quintile_gap"],
            "ci90": [c["ci90_lower"], c["ci90_upper"]] if c else None,
            "pass": bool(block["top_quintile_gap"] is not None
                         and block["top_quintile_gap"] > 0 and c and c["ci90_lower"] > 0),
        }
    conditions["O1_top_quintile_gap_positive"] = {
        "statement": "상위 5분위에서 평균 예측확률 > 관측빈도, CI90 하한 > 0",
        "by_horizon": o1, "pass": all(v["pass"] for v in o1.values()),
    }

    o2 = {}
    for h in FOCUS_HORIZONS:
        block = per_h[h]
        fit = block.get("logistic_recalibration")
        c = (block.get("ci90") or {}).get("logistic_slope")
        o2[f"h{h}"] = {
            "slope": fit["slope"] if fit else None,
            "ci90": [c["ci90_lower"], c["ci90_upper"]] if c else None,
            "pass": bool(fit and fit["slope"] < 1.0 and c and c["ci90_upper"] < 1.0),
        }
    conditions["O2_logistic_slope_below_one"] = {
        "statement": "로짓 재보정 기울기 b < 1 (예측이 실제보다 뾰족), CI90 상한 < 1",
        "by_horizon": o2, "pass": all(v["pass"] for v in o2.values()),
    }

    o3 = {}
    for h in FOCUS_HORIZONS:
        rows = {r["regime"]: r for r in regimes[h] if not r.get("skipped")}
        detail = {}
        for name, row in rows.items():
            detail[name] = {"top_quintile_gap": row.get("top_quintile_gap"),
                            "mean_calibration_gap": row.get("mean_calibration_gap"),
                            "top_quintile_n": row.get("top_quintile_n"),
                            "positive": bool((row.get("top_quintile_gap") or 0) > 0)}
        pairs = [("gfc", "non_gfc"), ("calm_p80", "storm_p80")]
        pair_ok = {}
        for a, b in pairs:
            va = detail.get(a, {}).get("top_quintile_gap")
            vb = detail.get(b, {}).get("top_quintile_gap")
            pair_ok[f"{a}|{b}"] = bool(va is not None and vb is not None and va > 0 and vb > 0)
        o3[f"h{h}"] = {"regimes": detail, "pair_both_positive": pair_ok,
                       "pass": all(pair_ok.values())}
    conditions["O3_regime_invariant"] = {
        "statement": "상위분위 gap 양수가 GFC/비GFC · calm/storm 두 쌍 모두에서 성립 (부호만, CI 미요구)",
        "by_horizon": o3, "pass": all(v["pass"] for v in o3.values()),
    }

    # 설계도 §1 의 문자 그대로의 조건("두 지평·국면 초월로 재현")은 부호 재현이다.
    # 통계적 강도(CI90)를 요구하는 O1 과 나눠서 둘 다 공표한다 — 어느 쪽도 사후 완화하지 않는다.
    cells: list[dict[str, Any]] = []
    for h in FOCUS_HORIZONS:
        for row in regimes[h]:
            if row.get("skipped"):
                continue
            cells.append({
                "horizon": h, "regime": row["regime"], "n": row["n"],
                "top_quintile_gap": row.get("top_quintile_gap"),
                "mean_calibration_gap": row.get("mean_calibration_gap"),
                "logistic_slope": row.get("logistic_slope"),
                "top_gap_positive": bool((row.get("top_quintile_gap") or 0) > 0),
                "mean_gap_positive": bool((row.get("mean_calibration_gap") or 0) > 0),
                "slope_below_one": bool(row.get("logistic_slope") is not None
                                        and row["logistic_slope"] < 1.0),
            })
    direction_only = {
        "definition": "설계도 §1 문자 조건 — 부호(방향)만 두 지평·네 국면 셀에서 재현되는가",
        "cells_total": len(cells),
        "top_gap_positive_cells": sum(1 for c in cells if c["top_gap_positive"]),
        "mean_gap_positive_cells": sum(1 for c in cells if c["mean_gap_positive"]),
        "slope_below_one_cells": sum(1 for c in cells if c["slope_below_one"]),
        "slope_exceptions": [f"h{c['horizon']}/{c['regime']}={c['logistic_slope']:.4f}"
                             for c in cells if not c["slope_below_one"]],
        "pooled_horizons_top_gap_positive": sum(
            1 for h in FOCUS_HORIZONS if (per_h[h]["top_quintile_gap"] or 0) > 0),
        "cells": cells,
    }
    direction_only["pass"] = bool(
        direction_only["top_gap_positive_cells"] == direction_only["cells_total"]
        and direction_only["pooled_horizons_top_gap_positive"] == len(FOCUS_HORIZONS))

    replicated = bool(conditions["O1_top_quintile_gap_positive"]["pass"]
                      and conditions["O3_regime_invariant"]["pass"])
    return {
        "direction_only_replication": direction_only,
        "gate_definition": "재현 = O1(두 지평 CI90 하한>0) AND O3(두 국면쌍 부호 일치). "
                           "O2 는 보강 증거(구조 형태)로만 사용.",
        "conditions": conditions,
        "overconfidence_replicated_across_horizons_and_regimes": replicated,
        "s3_entry_condition_met_strict": replicated,
        "s3_entry_condition_met_design_literal": direction_only["pass"],
        "note": ("두 판정이 갈리면 S2-3 이 진입/중단을 결정한다 — S2-1 은 계측과 두 기준의 "
                 "결과를 모두 공표할 뿐 기준을 사후 선택하지 않는다."),
    }


# --------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/timeseries_v12/diagnostics/first_touch_diagnostic.json")
    args = parser.parse_args()

    data = load_first_touch()
    primary = load_primary()
    draws = block_index_draws(417, seed=SEED)

    per_h: dict[int, dict[str, Any]] = {}
    regimes: dict[int, list[dict[str, Any]]] = {}
    for horizon in HORIZONS:
        blk = data["per_horizon"][horizon]
        dates, p, y = blk["dates"], blk["p"], blk["y"]
        use_draws = draws if p.size == 417 else block_index_draws(p.size, seed=SEED)
        per_h[horizon] = horizon_block(dates, p, y, horizon, use_draws)
        if horizon not in FOCUS_HORIZONS:
            # h1(터치 0건)·h5(4건)은 국면 분해가 퇴화 — 계측만 하고 분해는 생략한다.
            regimes[horizon] = [{"regime": "all", "skipped": "터치 표본 부족 (h1=0, h5=4)"}]
            continue

        top_edge = float(per_h[horizon]["quantile_bins"]["edges"][-2])
        gfc = np.array([GFC_CANONICAL[0] <= d <= GFC_CANONICAL[1] for d in dates])
        pmap = primary.get(horizon) or primary.get(21) or {}
        pvals = np.array([pmap.get(d, np.nan) for d in dates])
        matched = np.isfinite(pvals)
        thr = float(np.percentile(pvals[matched], CALM_PCT)) if matched.any() else np.nan
        calm = matched & (pvals <= thr)
        storm = matched & (pvals > thr)
        rows = [
            regime_block(dates, p, y, gfc, "gfc", top_edge, seed=SEED + 11),
            regime_block(dates, p, y, ~gfc, "non_gfc", top_edge, seed=SEED + 12),
            regime_block(dates, p, y, calm, "calm_p80", top_edge, seed=SEED + 13),
            regime_block(dates, p, y, storm, "storm_p80", top_edge, seed=SEED + 14),
        ]
        for row in rows:
            if row["regime"].endswith("p80"):
                row["primary_threshold_p80"] = thr
                row["primary_matched"] = int(matched.sum())
                row["primary_missing"] = int((~matched).sum())
                row["nominal_share"] = CALM_PCT / 100.0 if row["regime"] == "calm_p80" \
                    else 1 - CALM_PCT / 100.0
        regimes[horizon] = rows

    # 지평 단조성 (T4 근거) — 같은 원점에서 h21 터치는 h63 터치의 부분집합이어야 한다.
    d21, d63 = data["per_horizon"][21], data["per_horizon"][63]
    common = [i for i, d in enumerate(d21["dates"]) if d in set(d63["dates"])]
    idx63 = {d: i for i, d in enumerate(d63["dates"])}
    p21 = np.array([d21["p"][i] for i in common])
    p63 = np.array([d63["p"][idx63[d21["dates"][i]]] for i in common])
    y21 = np.array([d21["y"][i] for i in common])
    y63 = np.array([d63["y"][idx63[d21["dates"][i]]] for i in common])
    monotone = {
        "common_origins": len(common),
        "actual_violations_y21_gt_y63": int(np.sum(y21 > y63)),
        "probability_violations_p21_gt_p63": int(np.sum(p21 > p63)),
        "max_violation_magnitude": float(np.max(np.maximum(p21 - p63, 0.0))),
        "note": "터치는 지평 단조 — 위반 0 이면 T4 제약은 이 표본에서 무비용(자유도 0)",
    }

    # S3 split 검정력
    split = S3_SPLIT[0]
    power = {}
    for horizon in FOCUS_HORIZONS:
        blk = data["per_horizon"][horizon]
        early = np.array([d <= split for d in blk["dates"]])
        power[f"h{horizon}"] = {
            "split": split,
            "early_n": int(early.sum()), "early_touches": int(blk["y"][early].sum()),
            "late_n": int((~early).sum()), "late_touches": int(blk["y"][~early].sum()),
            "early_base": float(blk["y"][early].mean()),
            "late_base": float(blk["y"][~early].mean()),
        }

    design_claims = {
        "source": "docs/design/V12_EVENT_TRACK_SUNDAY_OPUS_LOOP_DESIGN_260904.md §0",
        "claimed": {"bss_h21": 0.046, "bss_h63": 0.099,
                    "h63_top_bin_p": 0.61, "h63_top_bin_observed": 0.43,
                    "h21_top_bin_p": 0.34, "h21_top_bin_observed": 0.21},
        "recomputed": {
            "bss_h21_vs_insample_climatology": per_h[21]["brier_skill_vs_insample_climatology"],
            "bss_h63_vs_insample_climatology": per_h[63]["brier_skill_vs_insample_climatology"],
            "h21_top_quintile_mean_p": per_h[21]["quantile_bins"]["table"][-1]["mean_p"],
            "h21_top_quintile_observed": per_h[21]["quantile_bins"]["table"][-1]["observed"],
            "h63_top_quintile_mean_p": per_h[63]["quantile_bins"]["table"][-1]["mean_p"],
            "h63_top_quintile_observed": per_h[63]["quantile_bins"]["table"][-1]["observed"],
        },
    }

    payload = {
        "schema": "v12_first_touch_diagnostic_v1",
        "task_id": "S2-1",
        "generated_by": "tools/v12_first_touch_diag.py",
        "target": {
            "event": "지평 내 지수 경로 최소값 ≤ 0.90 (원점 대비 −10% 터치)",
            "source_code": "src/ai_fc/timeseries_v8/backtest.py (touch_actual/touch_probability)",
            "run": {k: data[k] for k in ("experiment_label", "experiment_id", "run_path",
                                         "run_sha256", "path_count", "window", "window_role")},
            "holdout_policy": (
                "2015 년 이후(봉인 run) first_touch 는 본 진단에서 계산하지 않는다 — "
                "V12 잠재 홀드아웃 보존. 탐색 중 관측된 것은 봉인 run 전체(1011 원점) 집계 "
                "터치율뿐이며 국면·보정 통계는 산출하지 않았다."),
        },
        "method": {
            "bootstrap": {"type": "stationary block", "block": BLOCK,
                          "replicates": REPLICATES, "seed": SEED,
                          "percentile": [5, 95], "note": "S1 규약과 동일"},
            "p_clip_for_logit": P_EPS,
            "quantile_bins": QUANTILE_BINS, "fixed_bins": FIXED_BINS,
            "gfc_window": list(GFC_CANONICAL),
            "calm_definition": f"V10 primary(EWMA97 분산비) ≤ p{int(CALM_PCT)}",
            "expanding_climatology": "만기 도래 원점만 · Jeffreys 평활 · 달력 근사 만기",
        },
        "per_horizon": per_h,
        "regimes": {str(h): regimes[h] for h in HORIZONS},
        "horizon_monotonicity": monotone,
        "s3_split_power": power,
        "design_section0_claim_check": design_claims,
        "verdict": replication_verdict(per_h, regimes),
    }

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")

    v = payload["verdict"]
    print(f"wrote {args.out}")
    for h in FOCUS_HORIZONS:
        b = per_h[h]
        ci = b["ci90"] or {}
        c_bss, c_gap = ci.get("bss_insample"), ci.get("top_quintile_gap")
        print(f"  h{h}: n={b['n']} touches={b['touches']} base={b['base_rate']:.4f} "
              f"BS={b['brier']:.5f} clim={b['climatology_brier_insample']:.5f} "
              f"BSS={b['brier_skill_vs_insample_climatology']:+.4f}"
              + (f" CI90=[{c_bss['ci90_lower']:+.4f},{c_bss['ci90_upper']:+.4f}]" if c_bss else ""))
        print(f"       top-quintile gap={b['top_quintile_gap']:+.4f}"
              + (f" CI90=[{c_gap['ci90_lower']:+.4f},{c_gap['ci90_upper']:+.4f}]" if c_gap else "")
              + f" slope={b['logistic_recalibration']['slope']:.4f}"
              + f" AUC={b['auc']:.4f}"
              + f" BSS_exp={b['expanding_climatology'].get('bss_vs_expanding'):.4f}")
    d = v["direction_only_replication"]
    print(f"  strict(O1&O3)={v['s3_entry_condition_met_strict']} "
          f"design_literal={v['s3_entry_condition_met_design_literal']} "
          f"(top_gap>0 {d['top_gap_positive_cells']}/{d['cells_total']} 셀)")


if __name__ == "__main__":
    main()
