#!/usr/bin/env python
"""tools/v12_transfer_test.py — S3-1 사전등록 T1~T5 양방향 전이 검정 (읽기 전용).

등록부
------
``data/timeseries_v12/prereg/hypotheses.json`` (S3-0, 커밋 ec496463 — 결과 보기 전 고정).
이 스크립트는 그 등록부의 명세를 **그대로** 실행한다. 손잡이는 전부 등록부에서 읽거나 상수로
고정돼 있고, 결과를 본 뒤 바꿀 수 있는 선택지를 두지 않는다.

검정
----
표적 y = first_touch_actual, p = V8 first_touch_probability (E0 run, 417 origin × h21/h63).
분할 2010-12-31 (전반 209 / 후반 208). 방향 = 전→후 · 후→전. 모수는 **학습창에서만** 적합하고
평가창에서 재계산하지 않는다 (τ·b·λ·w 전부).

  Δ = mean_i[ (p_i − y_i)² − (p′_i − y_i)² ]      (평가창, 양수 = 개선)
  CI90 = 정상 블록 부트스트랩 ℓ=13, B=2000, seed 20260902, percentile[5,95]
  A1 채택 = 양방향 모두 CI90 하한 > 0
  A2 (추가 등록) = p_reflect 대비 쌍대 Δ_ref 의 CI90 하한도 양방향 > 0

가설
----
  T1 상단 수축   p′ = p − λ(p−b)·1{p>τ},  τ=학습창 p 의 80분위, b=학습창 터치율   (λ 1개)
  T2 최소 λ      T1 과 같은 맵, λ* = min(λ̂_early, λ̂_late)                        (λ 1개, 보수)
  T3 반사 앵커   p′ = (1−w)p + w·p_reflect,  p_reflect = 2Φ(ln0.9/(σ√h)), σ=EWMA .97  (w 1개)
  T4 지평 정합   p21 > p63 인 원점에서 두 값을 평균(2점 PAV)                        (자유도 0)
  T5 음성 대조   N1 순열 1000회에 T1 전 절차 재적용 — 통과율 > 10% 면 검정 결함

귀무 N1
-------
각 창 안에서 p 를 무작위 치환(y 고정, 창별 독립), 순열마다 적합→전이→부트스트랩 전 파이프라인
재실행, A1 통과 **셀** 수 k 를 센다. seed = 20260906 + perm_index. p_reflect 는 치환하지 않는다
(등록부가 치환 대상으로 p 만 지정) — 이 비대칭의 결과는 결과 JSON 의 caveat 에 그대로 기록한다.

쓰기는 ``--out`` 한 파일뿐. 백테스트·홀드아웃·봉인 실행 0. 2015+ 봉인창 미계산.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_first_touch_diag as ft      # noqa: E402
import v12_reflect_baseline as rb      # noqa: E402

PREREG_PATH = "data/timeseries_v12/prereg/hypotheses.json"
S22_PATH = "data/timeseries_v12/diagnostics/reflection_baseline.json"
RUN_SHA256 = "38dde7a8d029f2f02000d6174f995da52cdc2428e072926f0d8b08067e0a6727"

SPLIT = "2010-12-31"
FOCUS = (21, 63)
GRID = np.round(np.linspace(0.0, 1.0, 101), 2)     # 101점, step 0.01 (등록부 고정)
TAU_Q = 80.0                                        # 학습창 p 의 80분위 (등록부 고정)

SEED = ft.SEED                                      # 20260902
BLOCK = ft.BLOCK                                    # 13
REPLICATES = ft.REPLICATES                          # 2000
Z90 = 1.6448536269514722

PERM_SEED_BASE = 20260906
PERM_COUNT = 1000
T5_THRESHOLD = 0.10

WINDOWS = ("early", "late")
OPPOSITE = {"early": "late", "late": "early"}
WINDOW_LABEL = {"early": "전반(2007–10)", "late": "후반(2011–14)"}
HYPOTHESES = ("T1", "T2", "T3", "T4")


# --------------------------------------------------------------------------- 유틸

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def draws_matrix(n: int, *, seed: int = SEED, replicates: int = REPLICATES) -> np.ndarray:
    """ft.block_index_draws 를 행렬로 — 같은 n 이면 같은 draws 를 모든 가설이 공유한다."""
    return np.asarray(ft.block_index_draws(n, seed=seed, block=BLOCK, replicates=replicates),
                      dtype=np.int32)


def ci_from_boot(boot: np.ndarray) -> dict[str, float]:
    """ft.ci90 와 동일한 산식 (percentile[5,95] · std ddof=1) 의 벡터판."""
    finite = boot[np.isfinite(boot)]
    if finite.size < 2:
        return {"ci90_lower": float("nan"), "ci90_upper": float("nan"),
                "bootstrap_se": float("nan"), "replicates_used": int(finite.size)}
    lower, upper = np.percentile(finite, [5, 95])
    return {"ci90_lower": float(lower), "ci90_upper": float(upper),
            "bootstrap_se": float(np.std(finite, ddof=1)),
            "replicates_used": int(finite.size)}


def fit_theta(e: np.ndarray, u: np.ndarray) -> tuple[float, float]:
    """학습창 Brier 최소화. p′ = p + θ·u 이므로 Brier(θ) 는 θ 의 2차식.

    격자 101점을 전부 평가하고 argmin (동점이면 가장 작은 θ — 등록부의 tie_break).
    """
    n = float(e.size)
    m_ee = float(np.dot(e, e)) / n
    m_eu = float(np.dot(e, u)) / n
    m_uu = float(np.dot(u, u)) / n
    curve = m_ee + 2.0 * GRID * m_eu + np.square(GRID) * m_uu
    i = int(np.argmin(curve))                       # 첫 최소 = 가장 작은 θ
    return float(GRID[i]), float(curve[i])


def t1_shift(p: np.ndarray, tau: float, b: float) -> np.ndarray:
    """u = −(p−b)·1{p>τ}. p′ = p + λ·u = p − λ(p−b)1{p>τ}."""
    return -(p - b) * (p > tau)


def pav_pair(p21: np.ndarray, p63: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """2점 PAV — p21 > p63 인 원점에서 두 값을 그 평균으로 대체(단조 원뿔로의 L2 사영)."""
    viol = p21 > p63
    mid = 0.5 * (p21 + p63)
    return np.where(viol, mid, p21), np.where(viol, mid, p63), int(viol.sum())


# --------------------------------------------------------------------------- 표본

def build_sample() -> dict[str, Any]:
    data = ft.load_first_touch()
    if data["run_sha256"] != RUN_SHA256:
        raise RuntimeError(f"V8 run 해시 불일치 — 봉인 위반 가능: {data['run_sha256']}")
    series = rb.load_returns()

    horizons: dict[int, dict[str, Any]] = {}
    dates_ref: list[str] | None = None
    for h in FOCUS:
        blk = data["per_horizon"][h]
        dates = list(blk["dates"])
        if dates_ref is None:
            dates_ref = dates
        elif dates != dates_ref:
            raise RuntimeError("h21·h63 원점 날짜 집합이 다르다 — T4 정렬 전제 위반")
        sigma = rb.sigma_at_origins(series, dates, rb.LAMBDA)
        pr = rb.p_reflect(sigma, h)
        early = np.array([d <= SPLIT for d in dates])
        horizons[h] = {"dates": dates, "p": blk["p"], "y": blk["y"], "p_reflect": pr,
                       "sigma": sigma, "early": early}

    # S2-2 산출물의 p_reflect 와 대사 — 재계산이 S2-2 헤드라인 변형과 같은 배열인지 확인
    s22 = json.loads((ROOT / S22_PATH).read_text(encoding="utf-8"))
    reflect_recon = {}
    for h in FOCUS:
        ref = np.asarray(s22["per_horizon"][str(h)]["p_reflect"], dtype=float)
        diff = float(np.max(np.abs(ref - horizons[h]["p_reflect"])))
        reflect_recon[f"h{h}"] = {"max_abs_diff_vs_s2_2": diff, "identical": bool(diff == 0.0)}
        if diff > 1e-12:
            raise RuntimeError(f"p_reflect 가 S2-2 산출물과 다르다 (h{h}, max|Δ|={diff:.3e})")

    return {
        "run": {k: data[k] for k in ("experiment_label", "experiment_id", "run_path",
                                     "run_sha256", "window", "window_role")},
        "returns_source": {k: series[k] for k in ("path", "sha256", "column", "n_sessions", "span")},
        "reflect_reconciliation": reflect_recon,
        "dates": dates_ref,
        "horizons": horizons,
    }


def split_windows(sample: dict[str, Any]) -> dict[str, Any]:
    early = sample["horizons"][FOCUS[0]]["early"]
    idx = {"early": np.flatnonzero(early), "late": np.flatnonzero(~early)}
    pw: dict[int, dict[str, np.ndarray]] = {}
    yw: dict[int, dict[str, np.ndarray]] = {}
    prw: dict[int, dict[str, np.ndarray]] = {}
    for h in FOCUS:
        blk = sample["horizons"][h]
        pw[h] = {w: blk["p"][idx[w]] for w in WINDOWS}
        yw[h] = {w: blk["y"][idx[w]] for w in WINDOWS}
        prw[h] = {w: blk["p_reflect"][idx[w]] for w in WINDOWS}
    return {"idx": idx, "p": pw, "y": yw, "p_reflect": prw,
            "n": {w: int(idx[w].size) for w in WINDOWS}}


# --------------------------------------------------------------------------- 한 셀 산출

def _record(hyp: str, horizon: int, direction: str, fit_window: str | None, eval_window: str,
            p_eval: np.ndarray, pp: np.ndarray, y_eval: np.ndarray, pr_eval: np.ndarray,
            draws: np.ndarray, *, detail: bool, extra: dict[str, Any]) -> dict[str, Any]:
    d = (p_eval - y_eval) ** 2 - (pp - y_eval) ** 2
    delta = float(d.mean())
    boot = d[draws].mean(axis=1)
    ci = ci_from_boot(boot)
    rec: dict[str, Any] = {
        "hypothesis_id": hyp,
        "horizon": horizon,
        "direction": direction,
        "fit_window": fit_window,
        "eval_window": eval_window,
        "n_eval": int(y_eval.size),
        "touches_eval": int(y_eval.sum()),
        "brier_p": float(np.mean((p_eval - y_eval) ** 2)),
        "brier_p_prime": float(np.mean((pp - y_eval) ** 2)),
        "delta": delta,
        "ci90_lower": ci["ci90_lower"],
        "ci90_upper": ci["ci90_upper"],
        "bootstrap_se": ci["bootstrap_se"],
        "A1_pass": bool(np.isfinite(ci["ci90_lower"]) and ci["ci90_lower"] > 0.0),
    }
    rec.update(extra)
    if not detail:
        return rec

    se = ci["bootstrap_se"]
    mde = Z90 * se
    rec["mde_1645se"] = mde
    rec["mde_share_of_brier"] = (mde / rec["brier_p"]) if rec["brier_p"] > 0 else None
    rec["inconclusive_by_mde"] = bool(abs(delta) < mde)

    # 집중도 (K-concentration) — 상위 5% |d_i|
    abs_d = np.abs(d)
    total_abs = float(abs_d.sum())
    order = np.argsort(-abs_d, kind="mergesort")
    k5 = max(1, int(round(0.05 * d.size)))
    kept = np.delete(d, order[:k5])
    delta_drop = float(kept.mean()) if kept.size else float("nan")
    rec["top5pct_origins"] = k5
    rec["top5_abs_share"] = (float(abs_d[order[:k5]].sum() / total_abs) if total_abs > 0 else None)
    rec["top5count_abs_share"] = (float(abs_d[order[:5]].sum() / total_abs) if total_abs > 0 else None)
    rec["top5count_note"] = ("S2-3 split_power 는 상위 '5개 원점' 비중을 top5_abs_share_of_sum 으로 "
                             "적었다. 등록부의 정의는 상위 '5%' 이므로 top5_abs_share 가 정본이고, "
                             "S2-3 수치와의 비교용으로 top5count_abs_share 를 병기한다.")
    rec["delta_after_top5pct_drop"] = delta_drop
    rec["sign_after_top5pct_drop"] = int(np.sign(delta_drop)) if np.isfinite(delta_drop) else None
    # 등록부는 "부호가 뒤집히는 셀" 을 취약으로 규정한다. 제거 후 Δ 가 정확히 0 인 경우(=Δ 전부가
    # 제거된 원점에 있던 경우)가 실제로 나왔으므로, 넓은 읽기(0 도 불일치)와 좁은 읽기(반대부호만)를
    # 둘 다 기록한다. 어느 쪽도 채택 요건이 아니다(등록부 does_not_override_adoption).
    rec["concentration_fragile"] = bool(
        np.isfinite(delta_drop) and delta != 0.0 and np.sign(delta_drop) != np.sign(delta))
    rec["concentration_sign_reversed"] = bool(
        np.isfinite(delta_drop) and delta != 0.0 and np.sign(delta_drop) * np.sign(delta) < 0)
    rec["concentration_sign_vanishes"] = bool(
        np.isfinite(delta_drop) and delta != 0.0 and delta_drop == 0.0)

    # A2 — p_reflect 대비
    d_ref = (pr_eval - y_eval) ** 2 - (pp - y_eval) ** 2
    ci_ref = ci_from_boot(d_ref[draws].mean(axis=1))
    rec["brier_reflection"] = float(np.mean((pr_eval - y_eval) ** 2))
    rec["delta_vs_reflection"] = float(d_ref.mean())
    rec["ci90_lower_vs_reflection"] = ci_ref["ci90_lower"]
    rec["ci90_upper_vs_reflection"] = ci_ref["ci90_upper"]
    rec["bootstrap_se_vs_reflection"] = ci_ref["bootstrap_se"]
    rec["A2_pass"] = bool(np.isfinite(ci_ref["ci90_lower"]) and ci_ref["ci90_lower"] > 0.0)
    return rec


# --------------------------------------------------------------------------- family 평가

def evaluate_family(pw: dict[int, dict[str, np.ndarray]],
                    yw: dict[int, dict[str, np.ndarray]],
                    prw: dict[int, dict[str, np.ndarray]],
                    draws: dict[str, np.ndarray],
                    *, detail: bool = False) -> list[dict[str, Any]]:
    """T1~T4 × 지평 2 × 방향 2 = 16 결과. 하나도 생략하지 않는다."""
    records: list[dict[str, Any]] = []

    # ---- T1 적합 (학습창별) — T2 가 재사용한다
    fits: dict[int, dict[str, dict[str, Any]]] = {h: {} for h in FOCUS}
    for h in FOCUS:
        for w in WINDOWS:
            p_t, y_t = pw[h][w], yw[h][w]
            tau = float(np.percentile(p_t, TAU_Q))
            b = float(y_t.mean())
            u = t1_shift(p_t, tau, b)
            theta, _ = fit_theta(p_t - y_t, u)
            fits[h][w] = {"lambda": theta, "tau": tau, "b": b,
                          "train_upper_n": int((p_t > tau).sum()),
                          "train_n": int(p_t.size)}

    # ---- T3 적합 (학습창별)
    w_fits: dict[int, dict[str, dict[str, Any]]] = {h: {} for h in FOCUS}
    for h in FOCUS:
        for w in WINDOWS:
            p_t, y_t, pr_t = pw[h][w], yw[h][w], prw[h][w]
            theta, _ = fit_theta(p_t - y_t, pr_t - p_t)
            w_fits[h][w] = {"w": theta, "train_n": int(p_t.size)}

    # ---- T1 · T2 · T3 전이
    for h in FOCUS:
        for fw in WINDOWS:
            ev = OPPOSITE[fw]
            direction = f"{fw}_to_{ev}"
            p_e, y_e, pr_e = pw[h][ev], yw[h][ev], prw[h][ev]
            f = fits[h][fw]
            upper = p_e > f["tau"]
            u_e = t1_shift(p_e, f["tau"], f["b"])

            # T1
            lam = f["lambda"]
            pp = p_e + lam * u_e
            extra = {
                "parameter_name": "lambda", "fitted_parameter": lam,
                "tau": f["tau"], "b": f["b"],
                "train_n": f["train_n"], "train_upper_n": f["train_upper_n"],
                "eval_upper_set_n": int(upper.sum()),
                "degenerate": ("평가창 상단집합 공집합 → p′=p" if int(upper.sum()) == 0 else
                               ("λ*=0 → p′=p" if lam == 0.0 else None)),
            }
            records.append(_record("T1", h, direction, fw, ev, p_e, pp, y_e, pr_e,
                                   draws[ev], detail=detail, extra=extra))

            # T2 — λ* = min(λ̂_early, λ̂_late), τ·b 는 학습창 값 그대로
            lam_star = min(fits[h]["early"]["lambda"], fits[h]["late"]["lambda"])
            binder = ("early" if fits[h]["early"]["lambda"] <= fits[h]["late"]["lambda"] else "late")
            pp2 = p_e + lam_star * u_e
            extra2 = {
                "parameter_name": "lambda_star", "fitted_parameter": lam_star,
                "lambda_hat_early": fits[h]["early"]["lambda"],
                "lambda_hat_late": fits[h]["late"]["lambda"],
                "lambda_star_binder": binder,
                "uses_eval_window_information": bool(binder == ev),
                "tau": f["tau"], "b": f["b"],
                "train_n": f["train_n"], "train_upper_n": f["train_upper_n"],
                "eval_upper_set_n": int(upper.sum()),
                "degenerate": ("λ*=0 → p′=p, Δ=0 (등록부 degenerate_case — '미달')"
                               if lam_star == 0.0 else
                               ("평가창 상단집합 공집합 → p′=p" if int(upper.sum()) == 0 else None)),
            }
            records.append(_record("T2", h, direction, fw, ev, p_e, pp2, y_e, pr_e,
                                   draws[ev], detail=detail, extra=extra2))

            # T3
            wt = w_fits[h][fw]["w"]
            pp3 = p_e + wt * (pr_e - p_e)
            extra3 = {
                "parameter_name": "w", "fitted_parameter": wt,
                "tau": None, "b": None,
                "train_n": w_fits[h][fw]["train_n"],
                "degenerate": ("w*=0 → p′=p" if wt == 0.0 else None),
            }
            records.append(_record("T3", h, direction, fw, ev, p_e, pp3, y_e, pr_e,
                                   draws[ev], detail=detail, extra=extra3))

    # ---- T4 — 자유도 0. 방향 두 개를 창 두 개로 치환 (등록부 bidirectional_degeneracy)
    for w in WINDOWS:
        p21, p63 = pw[21][w], pw[63][w]
        c21, c63, viol = pav_pair(p21, p63)
        for h, p_e, pp in ((21, p21, c21), (63, p63, c63)):
            extra4 = {
                "parameter_name": None, "fitted_parameter": None,
                "tau": None, "b": None,
                "monotonicity_violations": viol,
                "violation_share": float(viol / p21.size),
                "direction_role": "window_analogue (자유도 0 → 학습창 없음, 등록부가 방향 2개를 창 2개로 치환)",
                "degenerate": ("단조 위반 0건 → p′=p, Δ=0 (구조 제약이 이 표본에서 무비용)"
                               if viol == 0 else None),
            }
            records.append(_record("T4", h, f"{w}_window", None, w, p_e, pp,
                                   yw[h][w], prw[h][w], draws[w], detail=detail, extra=extra4))
    return records


def cell_rollup(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for hyp in HYPOTHESES:
        for h in FOCUS:
            rows = [r for r in records if r["hypothesis_id"] == hyp and r["horizon"] == h]
            a1 = [bool(r["A1_pass"]) for r in rows]
            a2 = [bool(r.get("A2_pass")) for r in rows]
            cells.append({
                "hypothesis_id": hyp, "horizon": h,
                "directions": [r["direction"] for r in rows],
                "delta_by_direction": {r["direction"]: r["delta"] for r in rows},
                "ci90_lower_by_direction": {r["direction"]: r["ci90_lower"] for r in rows},
                "A1_direction_pass": {r["direction"]: bool(r["A1_pass"]) for r in rows},
                "A1_cell_adopted": bool(len(rows) == 2 and all(a1)),
                "A2_cell_pass": bool(len(rows) == 2 and all(a2)),
                "inconclusive_by_mde": [r["direction"] for r in rows if r.get("inconclusive_by_mde")],
                "concentration_fragile": [r["direction"] for r in rows if r.get("concentration_fragile")],
                "concentration_sign_reversed": [r["direction"] for r in rows
                                                if r.get("concentration_sign_reversed")],
                "concentration_sign_vanishes": [r["direction"] for r in rows
                                                if r.get("concentration_sign_vanishes")],
                "degenerate": {r["direction"]: r.get("degenerate") for r in rows},
            })
    return cells


def count_adopted(records: list[dict[str, Any]]) -> tuple[int, dict[str, bool]]:
    per_cell: dict[str, bool] = {}
    for hyp in HYPOTHESES:
        for h in FOCUS:
            rows = [r for r in records if r["hypothesis_id"] == hyp and r["horizon"] == h]
            per_cell[f"{hyp}_h{h}"] = bool(len(rows) == 2 and all(r["A1_pass"] for r in rows))
    return sum(per_cell.values()), per_cell


# --------------------------------------------------------------------------- 귀무 N1

def permutation_null(win: dict[str, Any], draws: dict[str, np.ndarray],
                     *, count: int, verbose_every: int = 50) -> dict[str, Any]:
    """N1 — 창 안에서 p 치환(y 고정, 창별 독립). 순열마다 전 파이프라인 재실행."""
    k_counts: list[int] = []
    cell_pass: dict[str, int] = {f"{hyp}_h{h}": 0 for hyp in HYPOTHESES for h in FOCUS}
    t1_cell_pass = {f"h{h}": 0 for h in FOCUS}
    direction_pass: dict[str, int] = {}
    t0 = time.time()
    for i in range(count):
        rng = np.random.default_rng(PERM_SEED_BASE + i)
        pw = {h: {w: win["p"][h][w][rng.permutation(win["p"][h][w].size)] for w in WINDOWS}
              for h in FOCUS}
        recs = evaluate_family(pw, win["y"], win["p_reflect"], draws, detail=False)
        k, per_cell = count_adopted(recs)
        k_counts.append(k)
        for key, val in per_cell.items():
            if val:
                cell_pass[key] += 1
        for h in FOCUS:
            if per_cell[f"T1_h{h}"]:
                t1_cell_pass[f"h{h}"] += 1
        for r in recs:
            key = f"{r['hypothesis_id']}_h{r['horizon']}_{r['direction']}"
            direction_pass[key] = direction_pass.get(key, 0) + int(bool(r["A1_pass"]))
        if verbose_every and (i + 1) % verbose_every == 0:
            el = time.time() - t0
            print(f"    perm {i + 1}/{count}  elapsed={el:.1f}s  "
                  f"proj={el / (i + 1) * count:.1f}s  mean_k={np.mean(k_counts):.3f}", flush=True)
    arr = np.asarray(k_counts, dtype=int)
    return {
        "replicates": count,
        "elapsed_sec": time.time() - t0,
        "k_distribution": {str(j): int((arr == j).sum()) for j in range(9)},
        "k_mean": float(arr.mean()),
        "k_max": int(arr.max()),
        "p_k_ge": {str(j): float((arr >= j).mean()) for j in range(9)},
        "cell_pass_counts": cell_pass,
        "cell_pass_rate": {k: v / count for k, v in cell_pass.items()},
        "direction_pass_rate": {k: v / count for k, v in sorted(direction_pass.items())},
        "t1_cell_pass_counts": t1_cell_pass,
        "k_samples_head": [int(v) for v in arr[:20]],
    }


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/timeseries_v12/diagnostics/transfer_results.json")
    ap.add_argument("--permutations", type=int, default=PERM_COUNT)
    ap.add_argument("--pilot", type=int, default=0,
                    help="순열 소요 투영용 파일럿 횟수 (>0 이면 이 횟수만 돌고 종료·미기록)")
    args = ap.parse_args()

    sample = build_sample()
    win = split_windows(sample)
    if win["n"]["early"] != 209 or win["n"]["late"] != 208:
        raise RuntimeError(f"분할 크기 불일치: {win['n']}")

    draws = {w: draws_matrix(win["n"][w]) for w in WINDOWS}
    draws_full = draws_matrix(len(sample["dates"]))

    # ft.ci90 와 벡터판이 같은 수를 내는지 1회 대사 (규약 동일성 증거)
    probe = ((sample["horizons"][21]["p"] - sample["horizons"][21]["y"]) ** 2)
    boot_probe = probe[draws_full].mean(axis=1)
    ref_ci = ft.ci90([float(v) for v in boot_probe])
    fast_ci = ci_from_boot(boot_probe)
    ci_agree = {
        "lower_diff": abs(ref_ci["ci90_lower"] - fast_ci["ci90_lower"]),
        "upper_diff": abs(ref_ci["ci90_upper"] - fast_ci["ci90_upper"]),
        "se_diff": abs(ref_ci["bootstrap_se"] - fast_ci["bootstrap_se"]),
    }
    if max(ci_agree.values()) > 0.0:
        raise RuntimeError(f"ci90 벡터판이 ft.ci90 와 다르다: {ci_agree}")

    if args.pilot > 0:
        t0 = time.time()
        null = permutation_null(win, draws, count=args.pilot, verbose_every=max(1, args.pilot // 4))
        el = time.time() - t0
        print(f"pilot {args.pilot} perms in {el:.2f}s → {el / args.pilot:.4f}s/perm "
              f"→ 1000 perms ≈ {el / args.pilot * 1000:.0f}s")
        print(f"  k dist: {null['k_distribution']}  mean_k={null['k_mean']:.3f}")
        print(f"  cell pass rate: {json.dumps(null['cell_pass_rate'])}")
        return

    t_obs = time.time()
    records = evaluate_family(win["p"], win["y"], win["p_reflect"], draws, detail=True)
    obs_sec = time.time() - t_obs
    cells = cell_rollup(records)
    k_obs, per_cell_obs = count_adopted(records)

    # T4 풀표본 (보고만 — 채택 근거 아님)
    p21f, p63f = sample["horizons"][21]["p"], sample["horizons"][63]["p"]
    c21f, c63f, violf = pav_pair(p21f, p63f)
    t4_full = {}
    for h, p_e, pp in ((21, p21f, c21f), (63, p63f, c63f)):
        y_f = sample["horizons"][h]["y"]
        d = (p_e - y_f) ** 2 - (pp - y_f) ** 2
        ci = ci_from_boot(d[draws_full].mean(axis=1))
        t4_full[f"h{h}"] = {"n": int(y_f.size), "monotonicity_violations": violf,
                            "delta": float(d.mean()), **ci,
                            "adoption_use": "보고 전용 — 채택 근거로 쓰지 않는다(등록부 full_sample)"}

    # 상단집합 전이 구조 — 왜 방향에 따라 맵의 적용 범위가 갈리는지의 사실 기록(가설 아님)
    upper_structure: dict[str, Any] = {}
    for rec in records:
        if rec["hypothesis_id"] != "T1":
            continue
        upper_structure[f"h{rec['horizon']}_{rec['direction']}"] = {
            "tau_from_training_window": rec["tau"],
            "train_upper_n": rec["train_upper_n"],
            "train_n": rec["train_n"],
            "eval_upper_set_n": rec["eval_upper_set_n"],
            "eval_n": rec["n_eval"],
            "eval_upper_share": rec["eval_upper_set_n"] / rec["n_eval"],
        }
    upper_structure["note"] = (
        "τ 는 학습창 p 의 80분위이므로 학습창에서는 정의상 약 20%를 덮는다. 평가창에서 이 τ 가 덮는 "
        "비율이 방향에 따라 갈리는 것은 두 창의 p 분포가 다르기 때문이며, 이는 결과가 아니라 표본의 "
        "성질이다. T1·T2 의 맵이 평가창에서 실제로 건드리는 원점 수를 보여 주는 사실 기록.")

    print(f"관측 16결과 산출 {obs_sec:.2f}s · k_obs={k_obs}", flush=True)
    for r in records:
        print(f"  {r['hypothesis_id']} h{r['horizon']:<2} {r['direction']:<16} "
              f"θ={('%.2f' % r['fitted_parameter']) if r['fitted_parameter'] is not None else '  — '} "
              f"Δ={r['delta']:+.6f} CI90=[{r['ci90_lower']:+.6f},{r['ci90_upper']:+.6f}] "
              f"A1={'PASS' if r['A1_pass'] else 'fail'} A2={'PASS' if r.get('A2_pass') else 'fail'}",
              flush=True)

    null = permutation_null(win, draws, count=args.permutations)
    t1_rate_pooled = sum(null["t1_cell_pass_counts"].values()) / (2.0 * args.permutations)
    t1_rate_by_cell = {k: v / args.permutations for k, v in null["t1_cell_pass_counts"].items()}
    t5_fail = bool(t1_rate_pooled > T5_THRESHOLD or any(v > T5_THRESHOLD
                                                        for v in t1_rate_by_cell.values()))
    p_ge_kobs = float(np.asarray([null["k_distribution"][str(j)] for j in range(9)])[k_obs:].sum()
                      / args.permutations) if k_obs <= 8 else 0.0

    adopted_cells = [f"{c['hypothesis_id']}_h{c['horizon']}" for c in cells if c["A1_cell_adopted"]]
    payload: dict[str, Any] = {
        "schema": "v12_s3_transfer_results_v1",
        "task_id": "S3-1",
        "generated_by": "tools/v12_transfer_test.py",
        "prereg": {
            "path": PREREG_PATH,
            "sha256": _sha256(ROOT / PREREG_PATH),
            "commit": "ec49646345f1f60292e418a366cb07c3e822f49c",
            "note": "등록부는 결과 보기 전 커밋됐다. 본 태스크는 등록부 명세만 실행한다.",
        },
        "target": {
            **sample["run"],
            "returns_source": sample["returns_source"],
            "p_reflect_reconciliation": sample["reflect_reconciliation"],
            "holdout_policy": "2015+ 봉인창 미계산 (S2 정책 승계)",
            "horizons_evaluated": list(FOCUS),
            "horizons_excluded": [1, 5],
        },
        "method": {
            "split": {"boundary": SPLIT, "n": win["n"],
                      "labels": {w: WINDOW_LABEL[w] for w in WINDOWS}},
            "grid": {"support": [0.0, 1.0], "step": 0.01, "points": int(GRID.size),
                     "tie_break": "동점 시 최소값"},
            "tau_quantile": TAU_Q,
            "bootstrap": {"type": "stationary block", "block": BLOCK, "replicates": REPLICATES,
                          "seed": SEED, "percentile": [5, 95],
                          "draw_sharing": "n 별 1벌을 모든 가설·지평이 공유 (등록부 draw_sharing)"},
            "ci90_implementation_check": ci_agree,
            "test_statistic": "Δ = mean[(p−y)² − (p′−y)²] (평가창, 양수 = 개선)",
            "nuisance_frozen": "τ·b·λ·w 전부 학습창 값 — 평가창 재계산 없음",
            "permutation_null": {"id": "N1", "replicates": args.permutations,
                                 "seed": f"{PERM_SEED_BASE} + perm_index",
                                 "unit": "창별·지평별 독립 치환 (y 고정, p_reflect 미치환)",
                                 "inner_bootstrap_replicates": REPLICATES,
                                 "computational_fallback_used": False},
        },
        "records": records,
        "cells": cells,
        "upper_set_transfer_structure": upper_structure,
        "t4_full_sample": t4_full,
        "adoption": {
            "rule_A1": "양방향(또는 T4 의 두 창) 모두 CI90 하한 > 0",
            "rule_A2": "p_reflect 대비 Δ_ref 의 CI90 하한도 양방향 > 0 (추가 등록, A1 을 취소하지 않음)",
            "k_obs": k_obs,
            "adopted_cells": adopted_cells,
            "A1_by_cell": per_cell_obs,
            "A2_by_cell": {f"{c['hypothesis_id']}_h{c['horizon']}": c["A2_cell_pass"] for c in cells},
        },
        "multiplicity_null": {
            **null,
            "k_obs": k_obs,
            "p_k_ge_kobs": p_ge_kobs,
            "family_claim_threshold": 0.05,
            "family_claim_supported": bool(p_ge_kobs <= 0.05),
        },
        "t5_negative_control": {
            "definition": "N1 순열 1000회에 T1 전 절차 재적용 — T1 두 셀의 A1 통과율",
            "pass_rate_pooled": t1_rate_pooled,
            "pass_rate_by_cell": t1_rate_by_cell,
            "threshold": T5_THRESHOLD,
            "failed": t5_fail,
            "rule": "통과율 > 10.0% → 검정 기계 결함 판정, S3 채택 전부 무효 + S4 부정 결과 계약",
            "interpretation_limit": ("통과율 ≤ 10% 는 '검정에 결함이 없다' 가 아니라 '이 음성 대조가 "
                                     "결함을 잡아내지 못했다' 는 뜻이다."),
        },
        "verdict": {
            "adopted_cells_before_T5": adopted_cells,
            "T5_failed": t5_fail,
            "adopted_cells_final": [] if t5_fail else adopted_cells,
            "s4_contract": ("부정 결과 계약 (T5 실패 — 등록부 pre_committed_interpretation.T5_fail 우선)"
                            if t5_fail else
                            ("V12 계약 draft (채택 ≥ 1)" if adopted_cells else
                             "부정 결과 계약 (채택 0 — 등록부 adopted_0)")),
        },
        "caveats": [
            "N1 은 p 의 주변분포와 y 의 기저율을 보존하되 시계열 의존을 파괴한다. 블록 부트스트랩이 "
            "보존하려는 구조를 귀무는 없애므로 N1 은 '짝짓기 없음' 귀무이지 '시계열 구조 없음' 귀무가 "
            "아니다 (등록부 multiplicity.null.destroys 그대로).",
            "N1 은 p 만 치환한다. T3 의 p_reflect 와 T4 의 상대 지평 확률은 치환되지 않으므로, 이 두 "
            "가설에 대해 N1 은 '맵이 쓰는 외생 정보까지 없앤' 귀무가 아니다. 귀무 아래 통과율이 부풀 수 "
            "있고 그만큼 P(k ≥ k_obs) 는 보수적으로(=크게) 나온다.",
            "T2 의 λ* = min(λ̂_early, λ̂_late) 는 정의상 평가창 적합값을 참조한다. λ*_binder 가 평가창일 "
            "때 그 방향은 순수한 표본외 전이가 아니다 — 레코드의 uses_eval_window_information 로 표시.",
            "T4 의 두 셀(h21·h63)은 같은 교정에서 파생돼 독립이 아니다. family 8셀 다중검정 산술이 이 "
            "상관을 무시한다 [미검증].",
            "집중도 지표의 정본은 상위 5%(top5_abs_share)다. S2-3 이 보고한 34.5% 는 상위 5개 원점 "
            "기준이며 비교하려면 top5count_abs_share 를 봐야 한다.",
            "집중도 취약 라벨은 두 읽기를 병기한다 — concentration_fragile 은 '제거 후 부호가 원래와 "
            "다름'(0 포함, 넓은 읽기)이고 concentration_sign_reversed 는 '반대 부호'(좁은 읽기), "
            "concentration_sign_vanishes 는 '제거 후 Δ 가 정확히 0'(Δ 전부가 제거된 원점에 있었음)이다. "
            "어느 라벨도 채택 요건이 아니며(등록부 does_not_override_adoption) 이 표본에서는 채택 셀이 "
            "0 이라 라벨 선택이 어떤 판정도 바꾸지 않는다.",
            "국면 셀 CI 층화는 적용하지 않았다 (S2 규약 승계). h1/h5 는 판정 제외.",
        ],
        "timing": {"observed_sec": obs_sec, "null_sec": null["elapsed_sec"]},
    }

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")

    print(f"wrote {args.out}")
    print(f"  k_obs={k_obs} 채택={adopted_cells or '없음'}")
    print(f"  귀무 k 분포={null['k_distribution']} mean_k={null['k_mean']:.3f} "
          f"P(k≥k_obs)={p_ge_kobs:.4f}")
    print(f"  T5 통과율 pooled={t1_rate_pooled:.4f} by_cell={t1_rate_by_cell} "
          f"→ {'실패(검정 결함)' if t5_fail else '통과'}")


if __name__ == "__main__":
    main()
