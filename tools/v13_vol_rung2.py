"""tools/v13_vol_rung2.py — V13-VOL rung-2 HAR-logistic + EWMA 대비 증분 + reliability.

핵심 질문(사용자 Q1): richer 모형(HAR 다중스케일)이 EWMA-logit(사실상 지속성)보다 진짜 증분을 주는가.
증분 = 쌍대 Brier(EWMA − HAR) CI90 하한 > 0. 없으면 '스킬은 지속성 지배' 확정.
reliability = Murphy 분해(rel/res/unc) 보고 의무(계약 G4). 게이트·부트스트랩·데이터는 rung-1 재사용.
결정론 수치모델(dualdb §8) — 봉인 market_archive read-only, 홀드아웃 미열람.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import v13_vol_run as R  # noqa: E402  (load_panel/labels/eval_cell/_logit_*/block_boot_ci/_ewma 재사용)


def har_components(x):
    """HAR 성분: 당일 / 5일 평균 / 22일 평균 (Corsi 2009 다중스케일)."""
    x = np.asarray(x, float)
    c1 = x.copy()
    c5 = np.array([x[max(0, i - 4):i + 1].mean() for i in range(len(x))])
    c22 = np.array([x[max(0, i - 21):i + 1].mean() for i in range(len(x))])
    return np.column_stack([c1, c5, c22])


def ewma_pred_windowed(feat, y, me, ml):
    """EWMA-logit 예측을 두 방향 eval 창에서 재산출(증분 비교용)."""
    out = {}
    for name, fit_m, ev_m in (("early_to_late", me, ml), ("late_to_early", ml, me)):
        b, mu, sd = R._logit_fit(feat[fit_m], y[fit_m])
        out[name] = R._logit_pred(b, mu, sd, feat[ev_m])
    return out


def reliability(p, y, bins=10):
    """Murphy 분해: uncertainty − resolution + reliability = Brier."""
    p = np.clip(p, 1e-6, 1 - 1e-6); ybar = y.mean(); unc = ybar * (1 - ybar)
    edges = np.linspace(0, 1, bins + 1); rel = res = 0.0; n = len(y); curve = []
    for k in range(bins):
        m = (p >= edges[k]) & (p < edges[k + 1] if k < bins - 1 else p <= 1.0)
        if m.sum() == 0:
            continue
        pk = p[m].mean(); ok = y[m].mean(); nk = m.sum()
        rel += nk / n * (pk - ok) ** 2
        res += nk / n * (ok - ybar) ** 2
        curve.append({"bin": k, "n": int(nk), "pred": round(float(pk), 4), "obs": round(float(ok), 4)})
    return {"reliability": float(rel), "resolution": float(res), "uncertainty": float(unc),
            "brier_check": float(unc - res + rel), "curve": curve}


def main():
    idx, vix, ndx, rv = R.load_panel()
    dates = np.array([str(d)[:10] for d in idx]); early = dates < R.SPLIT; late = ~early
    rv_f = np.where(np.isfinite(rv), rv, np.nanmedian(rv[np.isfinite(rv)]))
    har_vix = har_components(vix); har_rv = har_components(rv_f)
    ewma_vix = np.column_stack([vix, R._ewma(vix, 2 / 22)]); ewma_rv = np.column_stack([rv_f, R._ewma(rv_f, 2 / 22)])
    specs = []
    for K in R.Ks:
        for h in R.HS:
            specs.append((f"vix{K}_h{h}", R.labels_vix(vix, K, h), har_vix, ewma_vix))
    for h in R.HS:
        specs.append((f"rv_h{h}", R.labels_rv(rv, h), har_rv, ewma_rv))
    cells = {}
    print("=== V13-VOL rung-2 HAR-logistic (vs 기후 채택 · vs EWMA 증분 · reliability) ===")
    for name, y, harf, ewf in specs:
        m = np.isfinite(y); me, ml = early & m, late & m
        cell = R.eval_cell(harf, y, me, ml, R.SEED)          # HAR vs 기후 (양방향 채택)
        # 증분 vs EWMA (양방향)
        ewp = ewma_pred_windowed(ewf, y, me, ml); inc = {}
        for dname, ev_m in (("early_to_late", ml), ("late_to_early", me)):
            b, mu, sd = R._logit_fit(harf[me if dname == "early_to_late" else ml],
                                     y[me if dname == "early_to_late" else ml])
            hp = R._logit_pred(b, mu, sd, harf[ev_m]); ye = y[ev_m]
            d = (ewp[dname] - ye) ** 2 - (hp - ye) ** 2       # 양수 = HAR가 EWMA보다 우세
            mean, lo, hi, se = R.block_boot_ci(d, R.SEED)
            inc[dname] = {"paired_mean_har_minus_ewma": mean, "ci90": [lo, hi], "mde": 1.645 * se,
                          "har_beats_ewma": bool(lo > 0)}
            if dname == "early_to_late":
                cell["reliability_har_late"] = reliability(hp, ye)
        cell["increment_vs_ewma"] = inc
        cell["increment_adopted"] = bool(inc["early_to_late"]["har_beats_ewma"]
                                         and inc["late_to_early"]["har_beats_ewma"])
        cells[name] = cell
        e = cell["early_to_late"]; ie = inc["early_to_late"]; il = inc["late_to_early"]
        print(f"{name:10s} HAR vs기후 BSS {e['bss_vs_clim']:+.3f} adopt={cell['adopted']} | "
              f"증분 e2l {ie['paired_mean_har_minus_ewma']:+.5f}[{ie['ci90'][0]:+.5f},{ie['ci90'][1]:+.5f}] "
              f"l2e {il['paired_mean_har_minus_ewma']:+.5f}[{il['ci90'][0]:+.5f},{il['ci90'][1]:+.5f}] "
              f"증분채택={cell['increment_adopted']}", flush=True)
    inc_cells = [k for k, v in cells.items() if v["increment_adopted"]]
    res = {"schema": "v13_vol_rung2_har", "window": R.load_panel.__doc__ and list(R.DESIGN)
           if hasattr(R, "DESIGN") else None, "cells": cells,
           "har_adopted_vs_clim": [k for k, v in cells.items() if v["adopted"]],
           "har_increment_over_ewma_cells": inc_cells,
           "verdict": ("HAR가 지속성(EWMA) 대비 증분 있음" if inc_cells
                       else "증분 없음 — 스킬은 변동성 지속성 지배(richer 무익)")}
    (ROOT / "data/timeseries_v13/vol/ladder_har_logit.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"\nHAR vs 기후 채택: {res['har_adopted_vs_clim']}")
    print(f"HAR가 EWMA 대비 증분 있는 셀: {inc_cells or 'none'}")
    print(f"VERDICT: {res['verdict']}")


if __name__ == "__main__":
    main()
