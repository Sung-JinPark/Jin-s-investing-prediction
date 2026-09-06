#!/usr/bin/env python
"""tools/v12_reflect_baseline.py — S2-2 반사원리 기계 기준선 (읽기 전용).

기준선
------
드리프트 0 기하브라운운동의 first-passage 확률(반사원리):

    p_reflect = 2·Φ( −ln(S/K) / (σ√T) ),   K/S = 0.90,  T = 지평(세션)

σ 는 원점별 EWMA(λ=0.97) 일간 변동성이다. V8 자신이 쓰는 것과 **같은 재귀·같은 학습 슬라이스**를
쓴다 (``src/ai_fc/timeseries_v8/model.py::_ewma_variance_series`` 의 v_now):

    v[t] = λ·v[t−1] + (1−λ)·r[t−1]²,  v[0] = max(r[0]², 1e-16)
    σ_i  = sqrt(v[i])                      # 학습 슬라이스 endog[:i+1] 의 마지막 원소

즉 원점 당일 수익률 r[i] 는 σ 에 들어가지 않는다(V8 규약의 1세션 지연). 이 지연이 결론을
만드는지 확인하려고 비지연 변형을 민감도로 함께 낸다.

수익률 원천
-----------
``data/timeseries_v2/parquet/features_C1.parquet`` 의 ``nasdaq_return`` 열 = V8 의 endog[:, 0].
스크립트는 실행 시마다 417×4 원점 전부에서
``actual_log_return`` 과 ``first_touch_actual`` 을 재구성해 대사하고, 하나라도 어긋나면 중단한다.

비교
----
같은 417 원점·같은 y 위에서 V8 first_touch 확률 대비 Brier. 쌍대 손실차의 CI90 은 S1/S2-1 과
동일 규약(정상 블록 부트스트랩 ℓ=13, B=2000, seed 20260902, percentile[5,95]).

홀드아웃: 2015+ 봉인창은 계산하지 않는다. 설계창 417 원점만.

쓰기는 ``--out`` 한 파일뿐. 백테스트·홀드아웃·봉인 실행 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_first_touch_diag as ft   # noqa: E402  — S2-1 의 통계 헬퍼를 그대로 재사용

BARRIER = 0.90
LOG_BARRIER = math.log(BARRIER)          # ln(K/S) = −ln(S/K) < 0
LAMBDA = 0.97
LAMBDA_VARIANTS = (0.94, 0.97, 0.99)
BGK_BETA = 0.5825971579390106            # −ζ(1/2)/√(2π) — 이산 모니터링 배리어 보정

HORIZONS = ft.HORIZONS
FOCUS = ft.FOCUS_HORIZONS
SEED = ft.SEED
BLOCK = ft.BLOCK
REPLICATES = ft.REPLICATES

RETURNS_PARQUET = "data/timeseries_v2/parquet/features_C1.parquet"
RETURN_COLUMN = "nasdaq_return"

_NORM = statistics.NormalDist()


# --------------------------------------------------------------------------- 원천 + 대사

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def v8_selected_lambda(data: dict[str, Any]) -> dict[int, dict[str, float]]:
    """V8 이 원점마다 실제로 고른 ewma_lambda. run 이 0.97 만 쓴다는 보장은 없다 (실제로 아니다)."""
    run = json.loads((ROOT / data["run_path"]).read_text(encoding="utf-8"))
    out: dict[int, dict[str, float]] = {h: {} for h in HORIZONS}
    for row in run["scores"]:
        out[int(row["horizon"])][str(row["date"])] = float(row["ewma_lambda"])
    return out


def load_returns() -> dict[str, Any]:
    import pandas as pd

    path = ROOT / RETURNS_PARQUET
    frame = pd.read_parquet(path)
    dates = [d.date().isoformat() for d in frame.index]
    return {
        "path": RETURNS_PARQUET,
        "sha256": _sha256(path),
        "column": RETURN_COLUMN,
        "dates": dates,
        "index": {d: i for i, d in enumerate(dates)},
        "r": frame[RETURN_COLUMN].to_numpy(dtype=float),
        "n_sessions": len(dates),
        "span": [dates[0], dates[-1]],
    }


def reconcile(series: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """수익률 계열이 V8 endog[:, 0] 과 동일한지 원점 전수 재구성으로 확인한다."""
    r, pos = series["r"], series["index"]
    checked = ret_mismatch = touch_mismatch = 0
    worst = 0.0
    for horizon in HORIZONS:
        blk = data["per_horizon"][horizon]
        for date, y in zip(blk["dates"], blk["y"]):
            i = pos[date]
            seg = r[i + 1: i + 1 + horizon]
            if seg.size != horizon:
                raise RuntimeError(f"수익률 계열이 {date}/h{horizon} 을 덮지 못함")
            checked += 1
            touch = 1.0 if float(np.min(np.exp(np.cumsum(seg)))) <= BARRIER else 0.0
            if touch != float(y):
                touch_mismatch += 1
    # actual_log_return 대사는 run 원본에서 직접 (data 는 p/y 만 보존)
    run = json.loads((ROOT / data["run_path"]).read_text(encoding="utf-8"))
    for row in run["scores"]:
        i = pos[str(row["date"])]
        h = int(row["horizon"])
        diff = abs(float(np.sum(r[i + 1: i + 1 + h])) - float(row["actual_log_return"]))
        worst = max(worst, diff)
        if diff > 1e-12:
            ret_mismatch += 1
    ok = (ret_mismatch == 0 and touch_mismatch == 0)
    if not ok:
        raise RuntimeError(
            f"재구성 대사 실패 — ret_mismatch={ret_mismatch} touch_mismatch={touch_mismatch}")
    return {"origin_horizon_rows_checked": checked,
            "actual_log_return_rows_checked": len(run["scores"]),
            "actual_log_return_mismatches": ret_mismatch,
            "first_touch_actual_mismatches": touch_mismatch,
            "max_abs_actual_log_return_diff": worst,
            "identical_to_v8_endog_column0": ok}


# --------------------------------------------------------------------------- σ

def ewma_variance_series(returns: np.ndarray, decay: float) -> np.ndarray:
    """V8 ``_ewma_variance_series`` 와 동일한 재귀 (v[t] 는 r[t] 를 아직 보지 않았다)."""
    squared = np.square(np.asarray(returns, dtype=float))
    variance = np.empty_like(squared)
    variance[0] = max(float(squared[0]), 1e-16)
    lam = float(decay)
    for i in range(1, squared.size):
        variance[i] = lam * variance[i - 1] + (1.0 - lam) * squared[i - 1]
    return variance


def sigma_at_origins(series: dict[str, Any], dates: Sequence[str], decay: float,
                     *, include_origin_return: bool = False) -> np.ndarray:
    """원점별 σ. 계열 전체에 한 번 재귀를 돌리고 원점 위치만 읽는다(슬라이스별 재계산과 동일)."""
    variance = ewma_variance_series(series["r"], decay)
    pos = series["index"]
    idx = np.array([pos[d] for d in dates], dtype=int)
    if include_origin_return:
        # v[i+1] = λ·v[i] + (1−λ)·r[i]² — 원점 당일 수익률까지 반영한 변형
        return np.sqrt(np.maximum(variance[idx + 1], 1e-16))
    return np.sqrt(np.maximum(variance[idx], 1e-16))


# --------------------------------------------------------------------------- 기준선 확률

def p_reflect(sigma: np.ndarray, horizon: int, *, log_barrier: float = LOG_BARRIER) -> np.ndarray:
    """2·Φ(ln(K/S)/(σ√T)). σ→0 이면 0, 배리어=현재가면 1 로 수렴한다."""
    denom = np.maximum(sigma, 1e-16) * math.sqrt(float(horizon))
    z = log_barrier / denom
    return np.clip(2.0 * np.array([_NORM.cdf(float(v)) for v in z]), 0.0, 1.0)


def p_reflect_discrete(sigma: np.ndarray, horizon: int) -> np.ndarray:
    """Broadie–Glasserman–Kou 이산 모니터링 보정 — 배리어를 K·exp(−β·σ·√Δt) 로 낮춘다(Δt=1일)."""
    denom = np.maximum(sigma, 1e-16) * math.sqrt(float(horizon))
    z = (LOG_BARRIER - BGK_BETA * sigma) / denom
    return np.clip(2.0 * np.array([_NORM.cdf(float(v)) for v in z]), 0.0, 1.0)


def p_reflect_drift(sigma: np.ndarray, mu: np.ndarray, horizon: int) -> np.ndarray:
    """드리프트 있는 산술 브라운운동의 정확한 first-passage 확률(μ=0 이면 2Φ 로 환원)."""
    t = float(horizon)
    s = np.maximum(sigma, 1e-16)
    root = s * math.sqrt(t)
    a = (LOG_BARRIER - mu * t) / root
    b = (LOG_BARRIER + mu * t) / root
    expo = np.clip(2.0 * mu * LOG_BARRIER / np.square(s), -700.0, 700.0)
    out = np.array([_NORM.cdf(float(v)) for v in a]) + np.exp(expo) * np.array(
        [_NORM.cdf(float(v)) for v in b])
    return np.clip(out, 0.0, 1.0)


def mu_at_origins(series: dict[str, Any], dates: Sequence[str]) -> np.ndarray:
    """드리프트 변형용 μ̂ — V8 FHS 와 같은 정의(학습 슬라이스 전체 평균 수익률)."""
    r, pos = series["r"], series["index"]
    return np.array([float(np.mean(r[: pos[d] + 1])) for d in dates])


# --------------------------------------------------------------------------- 비교 통계

def _loss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (p - y) ** 2


def paired_block(p_a: np.ndarray, p_b: np.ndarray, y: np.ndarray,
                 draws: list[np.ndarray]) -> dict[str, Any]:
    """A 대비 B 의 쌍대 손실차. 양수 = A 가 우수 (loss_B − loss_A)."""
    point = float(np.mean(_loss(p_b, y) - _loss(p_a, y)))
    boot = [float(np.mean(_loss(p_b[i], y[i]) - _loss(p_a[i], y[i]))) for i in draws]
    wins = int(np.sum(_loss(p_a, y) < _loss(p_b, y)))
    return {"loss_diff": point, "ci90": ft.ci90(boot),
            "sign_test_a_better_origins": wins, "n": int(y.size),
            "bootstrap_p_a_not_better": float(np.mean(np.asarray(boot) <= 0.0))}


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    def rank(v: np.ndarray) -> np.ndarray:
        order = np.argsort(v, kind="mergesort")
        out = np.empty(v.size, dtype=float)
        sv = v[order]
        i = 0
        while i < v.size:
            j = i
            while j + 1 < v.size and sv[j + 1] == sv[i]:
                j += 1
            out[order[i:j + 1]] = (i + j) / 2.0 + 1.0
            i = j + 1
        return out
    ra, rb = rank(a), rank(b)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = math.sqrt(float(np.dot(ra, ra) * np.dot(rb, rb)))
    return float(np.dot(ra, rb) / denom) if denom > 0 else float("nan")


def model_block(p: np.ndarray, y: np.ndarray, draws: list[np.ndarray],
                *, with_ci: bool = True) -> dict[str, Any]:
    """한 확률계열의 자체 진단 — S2-1 과 같은 지표·같은 규약."""
    base = float(y.mean())
    qedges, qmeta = ft.quantile_edges(p)
    fedges = np.linspace(0.0, 1.0, ft.FIXED_BINS + 1)
    fedges[0], fedges[-1] = -1e-12, 1.0 + 1e-12
    top_mask = p >= qedges[-2]
    fit = ft.logistic_fit(ft.logit(p), y) if 0 < base < 1 else None
    out: dict[str, Any] = {
        "brier": ft.brier(p, y),
        "p_mean": float(p.mean()), "p_median": float(np.median(p)),
        "p_min": float(p.min()), "p_max": float(p.max()),
        "mean_calibration_gap": float(p.mean() - base),
        "top_quintile_edge": float(qedges[-2]),
        "top_quintile_n": int(top_mask.sum()),
        "top_quintile_mean_p": float(p[top_mask].mean()) if top_mask.any() else None,
        "top_quintile_observed": float(y[top_mask].mean()) if top_mask.any() else None,
        "top_quintile_gap": float(p[top_mask].mean() - y[top_mask].mean()) if top_mask.any() else None,
        "logistic_slope": fit[1] if fit else None,
        "logistic_intercept": fit[0] if fit else None,
        "auc": ft.auc(p, y),
        "quantile_bins": {"meta": qmeta, "edges": [float(v) for v in qedges],
                          "table": ft.bin_table(p, y, qedges)},
        "murphy_quantile_bins": ft.murphy(p, y, qedges),
        "murphy_fixed_bins": ft.murphy(p, y, fedges),
    }
    if not with_ci:
        return out
    boot = {"brier": [], "mean_calibration_gap": [], "top_quintile_gap": [],
            "logistic_slope": [], "auc": []}
    for idx in draws:
        pb, yb = p[idx], y[idx]
        boot["brier"].append(ft.brier(pb, yb))
        boot["mean_calibration_gap"].append(float(pb.mean() - yb.mean()))
        tm = pb >= qedges[-2]
        boot["top_quintile_gap"].append(
            float(pb[tm].mean() - yb[tm].mean()) if tm.any() else np.nan)
        fb = ft.logistic_fit(ft.logit(pb), yb)
        boot["logistic_slope"].append(fb[1] if fb and 0 < float(yb.mean()) < 1 else np.nan)
        ab = ft.auc(pb, yb)
        boot["auc"].append(ab if ab is not None else np.nan)
    out["ci90"] = {k: ft.ci90(v) for k, v in boot.items()}
    return out


# --------------------------------------------------------------------------- 지평 비교

def sigma_v8_selected(series: dict[str, Any], dates: Sequence[str],
                      lam_map: dict[str, float]) -> tuple[np.ndarray, dict[str, Any]]:
    """원점마다 V8 이 그 원점에서 고른 λ 로 σ 를 낸다 (V8 과 정확히 같은 변동성 입력)."""
    cache = {lam: ewma_variance_series(series["r"], lam)
             for lam in sorted({float(v) for v in lam_map.values()})}
    pos = series["index"]
    sigma = np.array([math.sqrt(max(float(cache[lam_map[d]][pos[d]]), 1e-16)) for d in dates])
    counts: dict[str, int] = {}
    for d in dates:
        counts[f"{lam_map[d]:g}"] = counts.get(f"{lam_map[d]:g}", 0) + 1
    return sigma, {"lambda_counts": counts, "distinct_lambdas": sorted(cache)}


def horizon_comparison(dates: Sequence[str], p_v8: np.ndarray, y: np.ndarray,
                       sigma: np.ndarray, horizon: int, series: dict[str, Any],
                       draws: list[np.ndarray],
                       lam_map: dict[str, float]) -> dict[str, Any]:
    base = float(y.mean())
    clim = np.full_like(y, base)
    pr = p_reflect(sigma, horizon)

    bs_v8, bs_re, bs_cl = ft.brier(p_v8, y), ft.brier(pr, y), ft.brier(clim, y)
    out: dict[str, Any] = {
        "horizon": horizon, "n": int(y.size), "touches": int(y.sum()), "base_rate": base,
        "sigma": {"mean": float(sigma.mean()), "median": float(np.median(sigma)),
                  "min": float(sigma.min()), "max": float(sigma.max()),
                  "annualized_mean_252": float(sigma.mean() * math.sqrt(252.0))},
        "brier": {"v8_first_touch": bs_v8, "reflection": bs_re,
                  "climatology_insample": bs_cl},
        "skill": {
            "bss_v8_vs_climatology": (1 - bs_v8 / bs_cl) if bs_cl > 0 else None,
            "bss_reflection_vs_climatology": (1 - bs_re / bs_cl) if bs_cl > 0 else None,
            "bss_v8_vs_reflection": (1 - bs_v8 / bs_re) if bs_re > 0 else None,
        },
        "paired": {
            "v8_vs_reflection": paired_block(p_v8, pr, y, draws),
            "reflection_vs_climatology": paired_block(pr, clim, y, draws),
            "v8_vs_climatology": paired_block(p_v8, clim, y, draws),
        },
        "agreement": {
            "spearman_p_v8_vs_p_reflect": spearman(p_v8, pr),
            "mean_abs_difference": float(np.mean(np.abs(p_v8 - pr))),
            "reflection_higher_share": float(np.mean(pr > p_v8)),
        },
        "reflection_diagnostic": model_block(pr, y, draws),
        "v8_diagnostic": model_block(p_v8, y, draws),
    }

    # ---- 변형 (민감도). 헤드라인은 위의 λ=0.97·연속모니터링·μ=0 하나뿐이다.
    variants: dict[str, Any] = {}
    for lam in LAMBDA_VARIANTS:
        s = sigma_at_origins(series, dates, lam)
        pv = p_reflect(s, horizon)
        variants[f"ewma_lambda_{lam}"] = {
            "brier": ft.brier(pv, y), "p_mean": float(pv.mean()),
            "sigma_mean": float(s.mean()),
            "paired_v8_vs_variant": paired_block(p_v8, pv, y, draws),
        }
    s_sel, sel_meta = sigma_v8_selected(series, dates, lam_map)
    pv = p_reflect(s_sel, horizon)
    variants["ewma_lambda_v8_selected_per_origin"] = {
        "brier": ft.brier(pv, y), "p_mean": float(pv.mean()),
        "sigma_mean": float(s_sel.mean()), **sel_meta,
        "note": "V8 이 각 원점에서 실제로 고른 λ — envelope 의 λ=0.97 고정과 달리 run 은 {0.94,0.97} 를 섞어 쓴다",
        "top_quintile_gap": model_block(pv, y, draws, with_ci=False)["top_quintile_gap"],
        "logistic_slope": model_block(pv, y, draws, with_ci=False)["logistic_slope"],
        "paired_v8_vs_variant": paired_block(p_v8, pv, y, draws),
        "paired_variant_vs_climatology": paired_block(pv, clim, y, draws),
    }
    s_incl = sigma_at_origins(series, dates, LAMBDA, include_origin_return=True)
    pv = p_reflect(s_incl, horizon)
    variants["ewma_includes_origin_day_return"] = {
        "brier": ft.brier(pv, y), "p_mean": float(pv.mean()),
        "sigma_mean": float(s_incl.mean()),
        "note": "V8 의 1세션 지연을 제거한 변형 — 지연이 결론을 만들지 않음을 보이는 용도",
        "paired_v8_vs_variant": paired_block(p_v8, pv, y, draws),
    }
    pv = p_reflect_discrete(sigma, horizon)
    variants["discrete_monitoring_bgk"] = {
        "brier": ft.brier(pv, y), "p_mean": float(pv.mean()), "beta": BGK_BETA,
        "note": "일간 종가 모니터링 보정 — 연속식은 구조적으로 터치를 과대추정한다",
        "top_quintile_gap": model_block(pv, y, draws, with_ci=False)["top_quintile_gap"],
        "logistic_slope": model_block(pv, y, draws, with_ci=False)["logistic_slope"],
        "paired_v8_vs_variant": paired_block(p_v8, pv, y, draws),
        "paired_variant_vs_climatology": paired_block(pv, clim, y, draws),
    }
    mu = mu_at_origins(series, dates)
    pv = p_reflect_drift(sigma, mu, horizon)
    variants["drift_mu_hat"] = {
        "brier": ft.brier(pv, y), "p_mean": float(pv.mean()),
        "mu_mean_daily": float(mu.mean()),
        "note": "μ̂ = 학습 슬라이스 평균 수익률(V8 FHS 정의). μ=0 이면 2Φ 로 환원",
        "top_quintile_gap": model_block(pv, y, draws, with_ci=False)["top_quintile_gap"],
        "logistic_slope": model_block(pv, y, draws, with_ci=False)["logistic_slope"],
        "paired_v8_vs_variant": paired_block(p_v8, pv, y, draws),
        "paired_variant_vs_climatology": paired_block(pv, clim, y, draws),
    }
    out["variants"] = variants
    out["p_reflect"] = [float(v) for v in pr]
    out["sigma_per_origin"] = [float(v) for v in sigma]
    return out


# --------------------------------------------------------------------------- 국면 비교

def regime_comparison(p_v8: np.ndarray, pr: np.ndarray, y: np.ndarray, mask: np.ndarray,
                      label: str, edges: dict[str, float], *, seed: int) -> dict[str, Any]:
    n = int(mask.sum())
    out: dict[str, Any] = {"regime": label, "n": n}
    if n < 10:
        out["skipped"] = "원점 < 10"
        return out
    pv, pf, ys = p_v8[mask], pr[mask], y[mask]
    base = float(ys.mean())
    clim = np.full_like(ys, base)
    bs_v8, bs_re, bs_cl = ft.brier(pv, ys), ft.brier(pf, ys), ft.brier(clim, ys)
    draws = ft.block_index_draws(n, seed=seed)
    top_v8 = pv >= edges["v8"]
    top_re = pf >= edges["reflection"]
    fit_re = ft.logistic_fit(ft.logit(pf), ys) if 0 < base < 1 else None
    fit_v8 = ft.logistic_fit(ft.logit(pv), ys) if 0 < base < 1 else None
    out.update({
        "touches": int(ys.sum()), "base_rate": base,
        "brier": {"v8_first_touch": bs_v8, "reflection": bs_re, "climatology_insample": bs_cl},
        "bss_within_regime": {
            "v8": (1 - bs_v8 / bs_cl) if bs_cl > 0 else None,
            "reflection": (1 - bs_re / bs_cl) if bs_cl > 0 else None,
        },
        "mean_calibration_gap": {"v8": float(pv.mean() - base),
                                 "reflection": float(pf.mean() - base)},
        "top_quintile_gap": {
            "v8": float(pv[top_v8].mean() - ys[top_v8].mean()) if top_v8.sum() >= 5 else None,
            "reflection": float(pf[top_re].mean() - ys[top_re].mean()) if top_re.sum() >= 5 else None,
            "n": {"v8": int(top_v8.sum()), "reflection": int(top_re.sum())},
            "global_edges": edges,
        },
        "logistic_slope": {"v8": fit_v8[1] if fit_v8 else None,
                           "reflection": fit_re[1] if fit_re else None},
        "auc": {"v8": ft.auc(pv, ys), "reflection": ft.auc(pf, ys)},
        "paired_v8_vs_reflection": paired_block(pv, pf, ys, draws),
    })
    gaps_re, gaps_mean_re = [], []
    for idx in draws:
        pb, yb = pf[idx], ys[idx]
        gaps_mean_re.append(float(pb.mean() - yb.mean()))
        tm = pb >= edges["reflection"]
        gaps_re.append(float(pb[tm].mean() - yb[tm].mean()) if tm.sum() >= 3 else np.nan)
    out["ci90_reflection"] = {"mean_calibration_gap": ft.ci90(gaps_mean_re),
                              "top_quintile_gap": ft.ci90(gaps_re)}
    out["caveat"] = ("부분표본은 시간축이 비연속 — 블록 부트스트랩은 근사"
                     if label.endswith("p80") else "연속 구간")
    return out


# --------------------------------------------------------------------------- 판정

def build_verdict(per_h: dict[int, dict[str, Any]],
                  regimes: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    """사전 명시 질문 3개. S2-1 의 open_question 을 그대로 형식화한 것."""
    q1 = {}
    for h in FOCUS:
        pair = per_h[h]["paired"]["v8_vs_reflection"]
        c = pair["ci90"]
        q1[f"h{h}"] = {
            "loss_diff_v8_minus_reflection": pair["loss_diff"],
            "ci90": [c["ci90_lower"], c["ci90_upper"]] if c else None,
            "v8_strictly_better": bool(c and c["ci90_lower"] > 0),
            "reflection_strictly_better": bool(c and c["ci90_upper"] < 0),
        }
    q2 = {}
    for h in FOCUS:
        r = per_h[h]["reflection_diagnostic"]
        c = (r.get("ci90") or {}).get("top_quintile_gap")
        cs = (r.get("ci90") or {}).get("logistic_slope")
        q2[f"h{h}"] = {
            "top_quintile_gap": r["top_quintile_gap"],
            "top_quintile_gap_ci90": [c["ci90_lower"], c["ci90_upper"]] if c else None,
            "mean_calibration_gap": r["mean_calibration_gap"],
            "logistic_slope": r["logistic_slope"],
            "logistic_slope_ci90": [cs["ci90_lower"], cs["ci90_upper"]] if cs else None,
            "overconfident_direction": bool((r["top_quintile_gap"] or 0) > 0),
        }
    cells = []
    for h in FOCUS:
        for row in regimes[h]:
            if row.get("skipped"):
                continue
            cells.append({
                "horizon": h, "regime": row["regime"],
                "reflection_top_gap": row["top_quintile_gap"]["reflection"],
                "reflection_mean_gap": row["mean_calibration_gap"]["reflection"],
                "v8_top_gap": row["top_quintile_gap"]["v8"],
                "v8_mean_gap": row["mean_calibration_gap"]["v8"],
                "both_positive": bool((row["top_quintile_gap"]["reflection"] or 0) > 0
                                      and (row["top_quintile_gap"]["v8"] or 0) > 0),
            })
    shared = sum(1 for c in cells if c["both_positive"])
    return {
        "Q1_does_v8_beat_the_machine_baseline": {
            "statement": "쌍대 손실차 CI90 하한 > 0 이면 V8 이 기준선보다 엄밀히 우수",
            "by_horizon": q1,
            "v8_beats_baseline_both_horizons": all(v["v8_strictly_better"] for v in q1.values()),
            "baseline_beats_v8_any_horizon": any(v["reflection_strictly_better"] for v in q1.values()),
        },
        "Q2_is_the_baseline_also_overconfident": {
            "statement": "기준선도 상위분위에서 과대예측이면 과신은 V8 결함이 아니라 표적의 구조",
            "by_horizon": q2,
            "baseline_overconfident_both_horizons": all(
                v["overconfident_direction"] for v in q2.values()),
        },
        "Q3_shared_overconfidence_across_regimes": {
            "statement": "국면 셀에서 V8·기준선 상위분위 gap 이 동시에 양수인 비율",
            "cells_total": len(cells), "both_positive_cells": shared, "cells": cells,
        },
    }


# --------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/timeseries_v12/diagnostics/reflection_baseline.json")
    args = parser.parse_args()

    data = ft.load_first_touch()
    series = load_returns()
    recon = reconcile(series, data)
    primary = ft.load_primary()
    lam_by_h = v8_selected_lambda(data)
    draws = ft.block_index_draws(417, seed=SEED)

    per_h: dict[int, dict[str, Any]] = {}
    regimes: dict[int, list[dict[str, Any]]] = {}
    for horizon in HORIZONS:
        blk = data["per_horizon"][horizon]
        dates, p_v8, y = blk["dates"], blk["p"], blk["y"]
        sigma = sigma_at_origins(series, dates, LAMBDA)
        use = draws if p_v8.size == 417 else ft.block_index_draws(p_v8.size, seed=SEED)
        per_h[horizon] = horizon_comparison(dates, p_v8, y, sigma, horizon, series, use,
                                            lam_by_h[horizon])
        if horizon not in FOCUS:
            regimes[horizon] = [{"regime": "all", "skipped": "터치 표본 부족 (h1=0, h5=4)"}]
            continue
        pr = np.array(per_h[horizon]["p_reflect"])
        edges = {"v8": float(per_h[horizon]["v8_diagnostic"]["top_quintile_edge"]),
                 "reflection": float(per_h[horizon]["reflection_diagnostic"]["top_quintile_edge"])}
        gfc = np.array([ft.GFC_CANONICAL[0] <= d <= ft.GFC_CANONICAL[1] for d in dates])
        pmap = primary.get(horizon) or primary.get(21) or {}
        pvals = np.array([pmap.get(d, np.nan) for d in dates])
        matched = np.isfinite(pvals)
        thr = float(np.percentile(pvals[matched], ft.CALM_PCT)) if matched.any() else np.nan
        rows = [
            regime_comparison(p_v8, pr, y, gfc, "gfc", edges, seed=SEED + 11),
            regime_comparison(p_v8, pr, y, ~gfc, "non_gfc", edges, seed=SEED + 12),
            regime_comparison(p_v8, pr, y, matched & (pvals <= thr), "calm_p80", edges, seed=SEED + 13),
            regime_comparison(p_v8, pr, y, matched & (pvals > thr), "storm_p80", edges, seed=SEED + 14),
        ]
        for row in rows:
            if row["regime"].endswith("p80"):
                row["primary_threshold_p80"] = thr
        regimes[horizon] = rows

    payload = {
        "schema": "v12_reflection_baseline_v1",
        "task_id": "S2-2",
        "generated_by": "tools/v12_reflect_baseline.py",
        "baseline": {
            "formula": "p_reflect = 2·Φ(−ln(S/K)/(σ√T)) = 2·Φ(ln(0.90)/(σ√T))",
            "barrier_k_over_s": BARRIER,
            "log_barrier": LOG_BARRIER,
            "sigma": "EWMA λ=0.97 일간 변동성 — V8 _ewma_variance_series 재귀·같은 학습 슬라이스",
            "lambda_note": "envelope 는 λ=.97 을 고정한다. V8 run 자체는 원점마다 {0.94, 0.97} 중 "
                           "하나를 고르므로 λ=.97 은 'V8 과 동일한 σ' 가 아니다. 동일 σ 판본은 "
                           "variants.ewma_lambda_v8_selected_per_origin.",
            "sigma_lag_note": "V8 규약상 v[i] 는 r[i−1] 까지만 본다 (원점 당일 수익률 제외). "
                              "비지연 변형은 variants.ewma_includes_origin_day_return.",
            "assumptions": ["드리프트 0", "상수 변동성", "연속 모니터링", "정규 증분"],
            "known_biases": [
                "연속 모니터링 가정 — 실제 판정은 일간 종가 최소값이므로 구조적 과대추정 "
                "(variants.discrete_monitoring_bgk 로 계량)",
                "드리프트 0 — 표본 기간 나스닥 μ̂>0 이면 하방 터치 과대추정 (variants.drift_mu_hat)",
                "정규 증분 — 실수익률 첨도로 짧은 지평 과소·긴 지평 과대 방향 불명확 [미검증]",
            ],
        },
        "target": {
            "event": "지평 내 지수 경로 최소값 ≤ 0.90 (원점 대비 −10% 터치)",
            "run": {k: data[k] for k in ("experiment_label", "experiment_id",
                                         "run_path", "run_sha256", "window", "window_role")},
            "returns_source": {k: series[k] for k in ("path", "sha256", "column",
                                                      "n_sessions", "span")},
            "reconciliation": recon,
            "holdout_policy": "2015+ 봉인창 미계산 — 설계창 417 원점만 (S2-1 과 동일)",
        },
        "method": {
            "bootstrap": {"type": "stationary block", "block": BLOCK, "replicates": REPLICATES,
                          "seed": SEED, "percentile": [5, 95], "note": "S1·S2-1 규약과 동일"},
            "loss_diff_convention": "loss_diff(A vs B) = mean((p_B−y)² − (p_A−y)²); 양수 = A 우수",
            "gfc_window": list(ft.GFC_CANONICAL),
            "calm_definition": f"V10 primary(EWMA97 분산비) ≤ p{int(ft.CALM_PCT)}",
            "not_computed": "T3 혼합 앵커 p′=(1−w)p+w·p_reflect 의 w 탐색은 S3-0 사전등록 뒤 S3-1 소관 — "
                            "본 태스크에서 계산하지 않는다.",
        },
        "per_horizon": {str(h): per_h[h] for h in HORIZONS},
        "regimes": {str(h): regimes[h] for h in HORIZONS},
        "verdict": build_verdict(per_h, regimes),
    }

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")

    print(f"wrote {args.out}")
    print(f"  재구성 대사: {recon['actual_log_return_rows_checked']} 행 "
          f"불일치 {recon['actual_log_return_mismatches']}/{recon['first_touch_actual_mismatches']} "
          f"max|Δ|={recon['max_abs_actual_log_return_diff']:.2e}")
    for h in FOCUS:
        b = per_h[h]
        pr = b["paired"]["v8_vs_reflection"]
        c = pr["ci90"]
        print(f"  h{h}: base={b['base_rate']:.4f} σ̄={b['sigma']['mean']:.5f} "
              f"BS_v8={b['brier']['v8_first_touch']:.5f} "
              f"BS_reflect={b['brier']['reflection']:.5f} "
              f"BS_clim={b['brier']['climatology_insample']:.5f}")
        print(f"       p̄_reflect={b['reflection_diagnostic']['p_mean']:.4f} "
              f"BSS(v8|reflect)={b['skill']['bss_v8_vs_reflection']:+.4f} "
              f"loss_diff={pr['loss_diff']:+.5f} "
              + (f"CI90=[{c['ci90_lower']:+.5f},{c['ci90_upper']:+.5f}]" if c else ""))
        r = b["reflection_diagnostic"]
        rc = (r.get("ci90") or {}).get("top_quintile_gap")
        print(f"       reflect: top_gap={r['top_quintile_gap']:+.4f}"
              + (f" CI90=[{rc['ci90_lower']:+.4f},{rc['ci90_upper']:+.4f}]" if rc else "")
              + f" slope={r['logistic_slope']:.4f} AUC={r['auc']:.4f} "
                f"ρ_s(v8,reflect)={b['agreement']['spearman_p_v8_vs_p_reflect']:.4f}")
    v = payload["verdict"]
    print(f"  Q1 v8>기준선 두 지평: {v['Q1_does_v8_beat_the_machine_baseline']['v8_beats_baseline_both_horizons']}"
          f" | Q2 기준선도 과신: {v['Q2_is_the_baseline_also_overconfident']['baseline_overconfident_both_horizons']}"
          f" | Q3 공유 셀 {v['Q3_shared_overconfidence_across_regimes']['both_positive_cells']}"
          f"/{v['Q3_shared_overconfidence_across_regimes']['cells_total']}")


if __name__ == "__main__":
    main()
