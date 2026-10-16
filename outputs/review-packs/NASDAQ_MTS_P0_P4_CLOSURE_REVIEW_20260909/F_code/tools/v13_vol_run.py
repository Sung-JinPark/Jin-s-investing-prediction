"""tools/v13_vol_run.py — V13-VOL 사다리 rung 평가 (climatology · ewma_logit).

정본 계약: data/contracts/multivariate_timeseries_v13_vol.yaml (사전등록, 결과 전 커밋 de5cddc2).
데이터: read_market_observations(봉인 V2 모듈 read-only) — VIX·NASDAQCOM 일간, PIT(available_at<=origin).
게이트: 기후 대비 쌍대 Brier CI90 하한>0 · 양방향 전이(early<->late) · y-block(ℓ=13) 건전 귀무 통과율<=0.10.
결정론 수치모델(dualdb §8 예외) — base rate 참조, LLM 캘리브레이션 아님.
"""
from __future__ import annotations
import json, sys, math
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_fc.timeseries_v2.market_archive import read_market_observations  # noqa: E402

DESIGN = ("2007-01-01", "2014-12-31")
SPLIT = "2011-01-01"
BLOCK = 13
B = 2000
SEED = 20260907
THETA_RV = 0.1694
Ks = (25, 30)
HS = (5, 21, 63)


def load_panel():
    import pandas as pd
    by = {}
    for o in read_market_observations(ROOT):
        d = o.model_dump(mode="json") if hasattr(o, "model_dump") else o
        by.setdefault(d["series_id"], {})[d["observation_time"]] = float(d["value"])
    def ser(sid):
        it = sorted(by[sid].items())
        return pd.Series([v for _, v in it], index=pd.to_datetime([t for t, _ in it]))
    vix = ser("VIX"); ndx = ser("NASDAQCOM")
    idx = vix.index.intersection(ndx.index)
    idx = idx[(idx >= DESIGN[0]) & (idx <= DESIGN[1])]
    vix = vix.reindex(idx); ndx = ndx.reindex(idx)
    r = np.log(ndx).diff()
    rv21 = r.rolling(21).std() * math.sqrt(252)
    return idx, vix.values, ndx.values, rv21.values


def labels_vix(vix, K, h):
    n = len(vix); y = np.full(n, np.nan)
    for i in range(n - h):
        y[i] = 1.0 if (vix[i + 1:i + 1 + h] >= K).any() else 0.0
    return y


def labels_rv(rv, h):
    n = len(rv); y = np.full(n, np.nan)
    for i in range(n - h):
        w = rv[i + 1:i + 1 + h]
        if np.isfinite(w).any():
            y[i] = 1.0 if (w[np.isfinite(w)] > THETA_RV).any() else 0.0
    return y


def _logit_fit(X, y, iters=200, lr=0.3, l2=1e-3):
    # 표준화 + 뉴턴류 경사(간단·안정). X: (n,p) 절편 제외 원자료.
    mu = X.mean(0); sd = X.std(0); sd[sd < 1e-9] = 1.0
    Xs = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    beta = np.zeros(Xs.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xs @ beta)); p = np.clip(p, 1e-6, 1 - 1e-6)
        g = Xs.T @ (p - y) / len(y) + l2 * beta
        W = p * (1 - p)
        H = (Xs * W[:, None]).T @ Xs / len(y) + l2 * np.eye(Xs.shape[1])
        beta -= np.linalg.solve(H, g)
    return beta, mu, sd


def _logit_pred(beta, mu, sd, X):
    Xs = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    return np.clip(1 / (1 + np.exp(-Xs @ beta)), 1e-6, 1 - 1e-6)


def block_boot_ci(d, seed, b=B):
    rng = np.random.default_rng(seed); n = len(d); reps = []
    for _ in range(b):
        idx = []
        while len(idx) < n:
            s = int(rng.integers(0, n)); L = int(rng.geometric(1.0 / BLOCK))
            idx.extend((s + np.arange(L)) % n)
        reps.append(float(np.mean(d[np.asarray(idx[:n])])))
    lo, hi = np.percentile(reps, [5, 95]); se = float(np.std(reps, ddof=1))
    return float(np.mean(d)), lo, hi, se


def eval_cell(feat, y, mask_early, mask_late, seed, b=B):
    """양방향 전이: fit early→eval late, fit late→eval early. 각 방향 기후 대비 쌍대 Brier CI."""
    out = {}
    for name, fit_m, ev_m in (("early_to_late", mask_early, mask_late),
                              ("late_to_early", mask_late, mask_early)):
        Xf, yf = feat[fit_m], y[fit_m]; Xe, ye = feat[ev_m], y[ev_m]
        clim = float(yf.mean())                       # 학습창 기저율
        beta, mu, sd = _logit_fit(Xf, yf)
        pe = _logit_pred(beta, mu, sd, Xe)
        bs_clim = (clim - ye) ** 2; bs_mod = (pe - ye) ** 2
        d = bs_clim - bs_mod                           # 양수 = 모형 우세
        mean, lo, hi, se = block_boot_ci(d, seed, b)
        bss = 1 - bs_mod.mean() / max(bs_clim.mean(), 1e-9)
        out[name] = {"n_fit": int(fit_m.sum()), "n_eval": int(ev_m.sum()),
                     "clim_base_rate": clim, "bs_clim": float(bs_clim.mean()),
                     "bs_model": float(bs_mod.mean()), "bss_vs_clim": float(bss),
                     "paired_mean": mean, "ci90": [lo, hi], "mde": 1.645 * se,
                     "adopt_dir": bool(lo > 0)}
    out["adopted"] = bool(out["early_to_late"]["adopt_dir"] and out["late_to_early"]["adopt_dir"])
    return out


def _boot_lower_fast(d, seed, b=400, block=BLOCK):
    """벡터화 고정블록 순환 부트스트랩 — CI90 하한만 반환(neg_control 전용 경량 근사)."""
    rng = np.random.default_rng(seed); n = len(d)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(b, nb))
    off = np.arange(block)
    idx = (starts[:, :, None] + off[None, None, :]) % n      # (b, nb, block)
    idx = idx.reshape(b, nb * block)[:, :n]
    means = d[idx].mean(axis=1)
    return float(np.percentile(means, 5))


def _adopt_fast(feat, y, me, ml, seed):
    """양방향 채택(경량): 각 방향 기후 대비 쌍대 Brier 의 고속 CI90 하한>0."""
    for fit_m, ev_m, sd in ((me, ml, seed), (ml, me, seed + 7)):
        Xf, yf = feat[fit_m], y[fit_m]; Xe, ye = feat[ev_m], y[ev_m]
        clim = float(yf.mean())
        beta, mu, s = _logit_fit(Xf, yf)
        pe = _logit_pred(beta, mu, s, Xe)
        d = (clim - ye) ** 2 - (pe - ye) ** 2
        if _boot_lower_fast(d, sd) <= 0:
            return False
    return True


def neg_control(feat, y, mask_early, mask_late, seed, draws=120):
    """y-block(ℓ=13) 순열 귀무: 사건 라벨 블록순열 → 양방향 채택률. 통과율<=0.10 이어야 건전."""
    rng = np.random.default_rng(seed); n = len(y)
    starts = np.arange(0, n, BLOCK); passes = 0
    for _ in range(draws):
        order = rng.permutation(len(starts))
        idx = np.concatenate([np.arange(starts[k], min(starts[k] + BLOCK, n)) for k in order])[:n]
        if _adopt_fast(feat, y[idx], mask_early, mask_late, seed + 1):
            passes += 1
    return passes / draws


def main():
    idx, vix, ndx, rv = load_panel()
    dates = np.array([str(d)[:10] for d in idx])
    early = dates < SPLIT; late = ~early
    ewma = lambda x, lam: _ewma(x, lam)
    results = {"schema": "v13_vol_ladder", "window": list(DESIGN), "split": SPLIT,
               "n": int(len(idx)), "rungs": {}}
    # 특성: vix_touch -> [VIX_t, EWMA21(VIX)], rv_exceedance -> [RV21_t, EWMA21(RV21)]
    vix_ewma = _ewma(vix, 2 / (21 + 1))
    rv_f = np.where(np.isfinite(rv), rv, np.nanmedian(rv[np.isfinite(rv)]))
    rv_ewma = _ewma(rv_f, 2 / (21 + 1))
    specs = []
    for K in Ks:
        for h in HS:
            specs.append((f"vix{K}_h{h}", labels_vix(vix, K, h), np.column_stack([vix, vix_ewma])))
    for h in HS:
        specs.append((f"rv_h{h}", labels_rv(rv, h), np.column_stack([rv_f, rv_ewma])))
    # 1단계: 본 결과(B=2000) — 빠름. 먼저 출력·저장.
    cells = {}
    for name, y, feat in specs:
        m = np.isfinite(y); me, ml = early & m, late & m
        cells[name] = eval_cell(feat, y, me, ml, SEED)
    print("=== V13-VOL ewma_logit vs climatology (양방향 전이, 본 결과) ===")
    for k, v in cells.items():
        e = v["early_to_late"]; l = v["late_to_early"]
        print(f"{k:10s} BSS e2l {e['bss_vs_clim']:+.3f} CI[{e['ci90'][0]:+.4f},{e['ci90'][1]:+.4f}] "
              f"| l2e {l['bss_vs_clim']:+.3f} CI[{l['ci90'][0]:+.4f},{l['ci90'][1]:+.4f}] | adopt={v['adopted']}", flush=True)
    results["rungs"]["ewma_logit"] = cells
    (ROOT / "data/timeseries_v13/vol").mkdir(parents=True, exist_ok=True)
    (ROOT / "data/timeseries_v13/vol/ladder_ewma_logit.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    # 2단계: 건전 귀무(경량) — 채택 후보에만 돌린다(비채택은 negctl 무의미).
    print("--- 건전 귀무(y-block) 통과율 (채택 셀만) ---", flush=True)
    for name, y, feat in specs:
        if not cells[name]["adopted"]:
            cells[name]["neg_control_pass_rate"] = None; continue
        m = np.isfinite(y); me, ml = early & m, late & m
        pr = neg_control(feat, np.where(m, y, 0.0), me, ml, SEED)
        cells[name]["neg_control_pass_rate"] = pr
        print(f"  {name}: {pr:.3f}", flush=True)
    # 요약 — 채택 = 양방향 CI90 하한>0 AND 건전 귀무 통과율<=0.10
    adopted = [k for k, v in cells.items()
               if v["adopted"] and v.get("neg_control_pass_rate") is not None
               and v["neg_control_pass_rate"] <= 0.10]
    results["ewma_logit_adopted_cells"] = adopted
    results["ewma_logit_k_obs"] = len(adopted)
    (ROOT / "data/timeseries_v13/vol/ladder_ewma_logit.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"\nADOPTED (양방향 CI90>0 AND 건전귀무<=0.10): {adopted or 'none'}  k_obs={len(adopted)}")
    print("wrote data/timeseries_v13/vol/ladder_ewma_logit.json")


def _ewma(x, alpha):
    out = np.empty(len(x)); m = x[0] if np.isfinite(x[0]) else 0.0
    for i, v in enumerate(x):
        if np.isfinite(v):
            m = alpha * v + (1 - alpha) * m
        out[i] = m
    return out


if __name__ == "__main__":
    main()
