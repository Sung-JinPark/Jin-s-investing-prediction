"""V11 값싼 직교 진단 — 평시 직교 상태 프록시의 필요조건 스크린.

정본: docs/design/v11_orthogonal_calm_diagnostic_260903.md (사전등록).
이 모듈은 결정론 수치 분석이다 — 어떤 학습·가중치 갱신도 없고, 홀드아웃/봉인 창을 열지 않으며
(design 창 origin만), 원장·예측·봉인 파일을 수정하지 않는다. 산출은 설계 참조이지 캘리브레이션
표본이 아니다.

필요조건 스크린: 평시(비위기) design origin에서 V8(=E0)의 예측 결함(PIT 위치·CRPS)을 예측하는,
V10 vol-state에 직교인 상태 프록시가 하나라도 있는가. 없으면 V11은 값싸게 중단.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

# design 창 — 홀드아웃(2015+)·봉인(2019+)은 절대 열지 않는다.
DESIGN_START = "2007-01-01"
DESIGN_END = "2014-12-31"
SUBPERIOD_SPLIT = "2011-01-01"
E0_RUN_RELATIVE = "data/timeseries_v10/runs/dev_tsv10-exp-a38c2154e2e9bc1705b5.json"
OUTPUT_RELATIVE = "data/timeseries_v11/diagnostics/orthogonal_calm_screen.json"

CALM_PRIMARY_PERCENTILE = 80.0   # 상위 20% primary = 위기 → 제외
BLOCK = 13
BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260903
ORTHOGONALITY_MAX_ABS_SPEARMAN = 0.30
PIT_LOCATION_FLOOR = 0.03        # |Δ(u-0.5)| 바닥
CRPS_RELATIVE_FLOOR = 0.005      # 상대 |Δ(CRPS)| 바닥 (E0 장기 CRPS 대비)

LONG_HORIZONS = (21, 63)


# --------------------------------------------------------------------------- #
# PIT: E0 5분위 → 예측 CDF, actual에서 u = F(actual)                          #
# --------------------------------------------------------------------------- #
_QUANTILE_LEVELS = np.array([0.10, 0.25, 0.50, 0.75, 0.90])


def _pit_from_quantiles(actual: float, q: np.ndarray) -> float:
    """5분위 [p10,p25,median,p75,p90]로 만든 선형 CDF에서 PIT u=F(actual).

    구간 내부는 선형 보간, 꼬리는 인접 구간 기울기로 선형 외삽(0.001~0.999 클립).
    분위가 단조가 아니면(수치 잡음) 강제 단조화.
    """
    q = np.maximum.accumulate(np.asarray(q, dtype=float))
    if actual <= q[0]:
        span = max(q[1] - q[0], 1e-12)
        slope = (_QUANTILE_LEVELS[1] - _QUANTILE_LEVELS[0]) / span
        return float(np.clip(_QUANTILE_LEVELS[0] + slope * (actual - q[0]), 0.001, 0.999))
    if actual >= q[-1]:
        span = max(q[-1] - q[-2], 1e-12)
        slope = (_QUANTILE_LEVELS[-1] - _QUANTILE_LEVELS[-2]) / span
        return float(np.clip(_QUANTILE_LEVELS[-1] + slope * (actual - q[-1]), 0.001, 0.999))
    return float(np.interp(actual, q, _QUANTILE_LEVELS))


def _load_e0_origin_frame(root: Path) -> dict[int, dict[str, np.ndarray]]:
    """E0 스코어 → horizon별 {date, u(PIT), crps, resid_iqr} (design 창만)."""
    run = json.loads((root / E0_RUN_RELATIVE).read_text(encoding="utf-8"))
    out: dict[int, dict[str, list]] = {h: {"date": [], "u": [], "crps": [], "resid_iqr": []}
                                       for h in LONG_HORIZONS}
    for s in run["scores"]:
        h = int(s["horizon"])
        if h not in LONG_HORIZONS:
            continue
        d = str(s["date"])
        if not (DESIGN_START <= d <= DESIGN_END):
            continue
        q = np.array([s["p10"], s["p25"], s["median"], s["p75"], s["p90"]], dtype=float)
        actual = float(s["actual_log_return"])
        u = _pit_from_quantiles(actual, q)
        iqr = max(float(s["p75"]) - float(s["p25"]), 1e-9)
        out[h]["date"].append(d)
        out[h]["u"].append(u)
        out[h]["crps"].append(float(s["model_crps"]))
        out[h]["resid_iqr"].append((actual - float(s["median"])) / iqr)
    frame: dict[int, dict[str, np.ndarray]] = {}
    for h, cols in out.items():
        order = np.argsort(cols["date"])
        frame[h] = {k: np.asarray(v)[order] if k == "date"
                    else np.asarray(v, dtype=float)[order] for k, v in cols.items()}
    return frame


# --------------------------------------------------------------------------- #
# 후보 상태 프록시 P1~P9 (trailing·PIT안전) + V10 primary(직교/평시 기준)      #
# --------------------------------------------------------------------------- #
def _trailing_sum(x: np.ndarray, w: int) -> np.ndarray:
    c = np.concatenate(([0.0], np.cumsum(x)))
    idx = np.arange(1, len(x) + 1)
    start = np.maximum(0, idx - w)
    complete = (idx - start) >= w
    out = np.where(complete, c[idx] - c[start], np.nan)
    return out


def _trailing_mean_square(x: np.ndarray, w: int) -> np.ndarray:
    sq = np.square(x)
    c = np.concatenate(([0.0], np.cumsum(sq)))
    idx = np.arange(1, len(x) + 1)
    start = np.maximum(0, idx - w)
    counts = idx - start
    complete = counts >= w
    return np.where(complete, (c[idx] - c[start]) / np.maximum(counts, 1), np.nan)


def _trailing_z(x: np.ndarray, w: int) -> np.ndarray:
    c = np.concatenate(([0.0], np.cumsum(x)))
    c2 = np.concatenate(([0.0], np.cumsum(np.square(x))))
    idx = np.arange(1, len(x) + 1)
    start = np.maximum(0, idx - w)
    counts = idx - start
    complete = counts >= w
    mean = (c[idx] - c[start]) / np.maximum(counts, 1)
    var = (c2[idx] - c2[start]) / np.maximum(counts, 1) - np.square(mean)
    std = np.sqrt(np.maximum(var, 1e-18))
    return np.where(complete, (x - mean) / std, np.nan)


def _rolling_corr(a: np.ndarray, b: np.ndarray, w: int) -> np.ndarray:
    n = len(a)
    out = np.full(n, np.nan)
    for i in range(w, n + 1):
        aa = a[i - w:i]
        bb = b[i - w:i]
        sa, sb = aa.std(), bb.std()
        if sa > 1e-12 and sb > 1e-12:
            out[i - 1] = float(np.corrcoef(aa, bb)[0, 1])
    return out


def build_proxies(bundle) -> dict[str, np.ndarray]:
    names = list(bundle.endogenous_names)
    endog = bundle.endogenous
    exog = bundle.exogenous
    ret = endog[:, names.index("nasdaq_return")]
    vixc = endog[:, names.index("vix_change")]
    curvec = endog[:, names.index("curve_change_bps")]
    dollarc = endog[:, names.index("dollar_change")]
    growth = exog[:, list(bundle.exogenous_names).index("growth_factor")]
    dfm_age = exog[:, list(bundle.exogenous_names).index("dfm_age_since_release")]

    rv21 = _trailing_mean_square(ret, 21)
    rv252 = _trailing_mean_square(ret, 252)
    # P4: 표준화된 (누적 vix_change − RV21) = VRP 프록시 (trailing z, PIT안전)
    vrp = _trailing_z(_trailing_sum(vixc, 21), 252) - _trailing_z(np.sqrt(rv21), 252)
    return {
        "P1_ret_mom_21": _trailing_sum(ret, 21),
        "P2_ret_trend_126": _trailing_sum(ret, 126),
        "P3_rv21_over_rv252": rv21 / rv252,
        "P4_vrp_proxy": vrp,
        "P5_curve_state_63": _trailing_sum(curvec, 63),
        "P6_dollar_trend_63": _trailing_sum(dollarc, 63),
        "P7_growth_factor": growth,
        "P8_nasdaq_dollar_corr_63": _rolling_corr(ret, dollarc, 63),
        "P9_dfm_age_control": dfm_age,
    }


# --------------------------------------------------------------------------- #
# 검정: calm 3분위 gradient + 블록 부트스트랩 CI + 직교 + 하위기간             #
# --------------------------------------------------------------------------- #
def _tertile_delta(proxy: np.ndarray, metric: np.ndarray) -> float:
    order = np.argsort(proxy)
    n = len(order)
    k = n // 3
    if k < 5:
        return float("nan")
    bottom = metric[order[:k]]
    top = metric[order[-k:]]
    return float(np.mean(top) - np.mean(bottom))


def _block_bootstrap_delta_ci(proxy: np.ndarray, metric: np.ndarray,
                              seed: int) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    n = len(proxy)
    reps = []
    for _ in range(BOOTSTRAP):
        picks: list[int] = []
        while len(picks) < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(1.0 / BLOCK))
            picks.extend((start + np.arange(length)) % n)
        idx = np.asarray(picks[:n])
        reps.append(_tertile_delta(proxy[idx], metric[idx]))
    reps = np.asarray([r for r in reps if np.isfinite(r)])
    lo, hi = np.percentile(reps, [5, 95])
    return float(lo), float(hi), float(np.std(reps, ddof=1))


def run_orthogonal_calm_diagnostic(root: Path) -> dict[str, Any]:
    from ai_fc.timeseries_v8.pipeline import _development_bundle, require_dfm_runtime
    from ai_fc.timeseries_v8.contracts import load_contract_v8
    from ai_fc.timeseries_v10.state import build_state_series

    require_dfm_runtime()
    bundle = _development_bundle(root, load_contract_v8(root))
    dates = np.asarray([str(d) for d in bundle.dates])
    date_to_idx = {d: i for i, d in enumerate(dates)}
    proxies = build_proxies(bundle)
    ret = bundle.endogenous[:, list(bundle.endogenous_names).index("nasdaq_return")]
    primary, _ = build_state_series(ret)

    e0 = _load_e0_origin_frame(root)
    from statistics import median as _median

    def _align(origin_dates: np.ndarray, series: np.ndarray) -> np.ndarray:
        return np.asarray([series[date_to_idx[d]] if d in date_to_idx else np.nan
                           for d in origin_dates])

    metrics = ("pit_location", "crps", "pit_tail")
    results: dict[str, Any] = {
        "schema_version": 1,
        "protocol": "docs/design/v11_orthogonal_calm_diagnostic_260903.md",
        "window": {"design_start": DESIGN_START, "design_end": DESIGN_END},
        "calm_primary_percentile": CALM_PRIMARY_PERCENTILE,
        "block": BLOCK, "bootstrap": BOOTSTRAP, "seed": BOOTSTRAP_SEED,
        "e0_long_crps": None,
        "tests": [],
    }
    e0_long_crps = float(np.mean([np.mean(e0[h]["crps"]) for h in LONG_HORIZONS]))
    results["e0_long_crps"] = e0_long_crps

    passes: list[str] = []
    for h in LONG_HORIZONS:
        odates = e0[h]["date"]
        prim = _align(odates, primary)
        calm_mask = np.isfinite(prim) & (prim <= np.nanpercentile(prim, CALM_PRIMARY_PERCENTILE))
        u = e0[h]["u"]
        metric_values = {
            "pit_location": u - 0.5,
            "crps": e0[h]["crps"],
            "pit_tail": np.abs(u - 0.5),
        }
        subperiod = odates < SUBPERIOD_SPLIT
        for pname, pseries in proxies.items():
            pvals = _align(odates, pseries)
            valid = calm_mask & np.isfinite(pvals)
            if valid.sum() < 30:
                continue
            pv = pvals[valid]
            spearman = float(_spearman(pv, prim[valid]))
            for m in metrics:
                mv = metric_values[m][valid]
                delta = _tertile_delta(pv, mv)
                lo, hi, se = _block_bootstrap_delta_ci(
                    pv, mv, seed=BOOTSTRAP_SEED + h + hash(pname + m) % 9973)
                sig = (lo > 0) or (hi < 0)
                # 효과크기 바닥
                if m == "crps":
                    size_ok = abs(delta) >= CRPS_RELATIVE_FLOOR * e0_long_crps
                    rel = delta / e0_long_crps
                else:
                    size_ok = abs(delta) >= PIT_LOCATION_FLOOR
                    rel = None
                # 하위기간 부호
                d1 = _tertile_delta(pv[subperiod[valid]], mv[subperiod[valid]])
                d2 = _tertile_delta(pv[~subperiod[valid]], mv[~subperiod[valid]])
                sub_ok = (np.isfinite(d1) and np.isfinite(d2)
                          and np.sign(d1) == np.sign(d2) and np.sign(d1) == np.sign(delta))
                ortho_ok = abs(spearman) < ORTHOGONALITY_MAX_ABS_SPEARMAN
                is_pass = bool(sig and size_ok and ortho_ok and sub_ok)
                label = f"{pname}|{m}|h{h}"
                results["tests"].append({
                    "label": label, "proxy": pname, "metric": m, "horizon": h,
                    "n_calm": int(valid.sum()), "delta": delta,
                    "delta_relative_crps": rel, "ci90": [lo, hi], "bootstrap_se": se,
                    "significant": bool(sig), "size_ok": bool(size_ok),
                    "spearman_vs_primary": spearman, "orthogonal": bool(ortho_ok),
                    "subperiod_delta": [d1, d2], "subperiod_consistent": bool(sub_ok),
                    "PASS": is_pass,
                })
                if is_pass:
                    passes.append(label)

    p9_pass = [p for p in passes if p.startswith("P9_")]
    results["passing"] = passes
    results["p9_control_tripped"] = p9_pass
    results["verdict"] = (
        "PROCEED_TO_ADVERSARIAL_VERIFY" if passes and not p9_pass
        else "SUSPECT_MULTIPLE_TESTING" if p9_pass
        else "FREEZE_V11_NO_CALM_ORTHOGONAL_SIGNAL"
    )
    out = root / OUTPUT_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8", newline="\n")
    return results


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ar = np.argsort(np.argsort(a)).astype(float)
    br = np.argsort(np.argsort(b)).astype(float)
    if ar.std() < 1e-12 or br.std() < 1e-12:
        return 0.0
    return float(np.corrcoef(ar, br)[0, 1])


if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("..")
    res = run_orthogonal_calm_diagnostic(root)
    print(f"verdict: {res['verdict']}")
    print(f"E0 long CRPS: {res['e0_long_crps']:.6f}  |  tests: {len(res['tests'])}")
    print(f"PASS: {res['passing'] or 'none'}")
    hdr = f"{'test':34s} {'n':>4s} {'delta':>11s} {'ci90':>24s} {'rho':>6s} {'sub':>4s} PASS"
    print(hdr)
    for t in sorted(res["tests"], key=lambda x: (not x["PASS"], -abs(x["delta"]))):
        mark = "*" if t["PASS"] else ("sig" if t["significant"] else "")
        print(f"{t['label']:34s} {t['n_calm']:4d} {t['delta']:+11.5f} "
              f"[{t['ci90'][0]:+.5f},{t['ci90'][1]:+.5f}] {t['spearman_vs_primary']:+.2f} "
              f"{str(t['subperiod_consistent'])[0]:>4s} {mark}")
