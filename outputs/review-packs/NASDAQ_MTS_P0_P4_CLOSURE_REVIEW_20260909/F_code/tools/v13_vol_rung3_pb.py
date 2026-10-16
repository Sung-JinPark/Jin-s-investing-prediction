"""tools/v13_vol_rung3_pb.py — V13-VOL rung-3: 지속성 기준선 PB 대비 EWMA 증분 · champion 확정 · h63 cross-fit isotonic.

계약: data/contracts/multivariate_timeseries_v13_vol.yaml — V13-D2′ 사전등록 개정(결과 전 커밋 afec214e).
  baselines.persistence_pb      : logit(P | 당일 수준 1피처) — vix 셀 VIX_t, rv 셀 RV21_t (절편 포함)
  gates.G2_champion_vs_persistence_pb :
     (a) EWMA 가 PB 대비 양방향 CI90 하한 > 0 AND 증분 y-block 귀무 ≤ 0.10 → champion = ewma_logit
     (b) 아니면 PB 가 기후 대비 양방향 CI90 하한 > 0 AND PB y-block 귀무 ≤ 0.10 → champion = persistence_pb
     (c) 아니면 HOLD — finalist 표에서 제외
  reliability.cross_fit_isotonic_h63 : k=5 연속 블록 · embargo h · PAV · 사전등록 fallback(iso 유의 열위면 raw)
데이터·게이트·부트스트랩·귀무는 rung-1(tools/v13_vol_run.py) 재사용. 설계창 원장 재분석 — 새 창 0, 홀드아웃 미열람.
결정론 수치모델(dualdb §8 예외) — base rate 참조, LLM 캘리브레이션 아님.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from math import comb
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import v13_vol_run as R  # noqa: E402  (load_panel/labels/eval_cell/_logit_*/block_boot_ci/_ewma 재사용)
from v13_vol_rung2 import reliability  # noqa: E402

PREREG_COMMIT = "afec214e"
EXPERIMENT_LABEL = "V13VOL_pb_baseline"
RUNG = "persistence_pb_g2"
ISO_CELLS = ("vix25_h63", "vix30_h63", "rv_h63")
K_FOLDS = 5
NEG_DRAWS = 120
OUT = ROOT / "data/timeseries_v13/vol/ladder_pb_baseline.json"
LEDGER = ROOT / "data/timeseries_v13/ledgers/vol_experiments.jsonl"


# ── 피처 ──────────────────────────────────────────────────────────────────────
def pb_features(x):
    """PB = 당일 수준 단독 1피처 (n,1). 절편은 _logit_fit 이 붙인다."""
    return np.asarray(x, float).reshape(-1, 1)


# ── 모형 대 모형 쌍대 Brier (양방향) ─────────────────────────────────────────
def _dir_preds(feat, y, fit_m, ev_m):
    b, mu, sd = R._logit_fit(feat[fit_m], y[fit_m])
    return R._logit_pred(b, mu, sd, feat[ev_m])


def paired_model_ci(feat_a, feat_b, y, me, ml, seed, b=R.B):
    """d = BS_a − BS_b (양수 = b 우세). a=PB, b=EWMA 로 부르면 'ewma_beats_pb' = CI90 하한 > 0."""
    out = {}
    for name, fit_m, ev_m in (("early_to_late", me, ml), ("late_to_early", ml, me)):
        ye = y[ev_m]
        pa = _dir_preds(feat_a, y, fit_m, ev_m)
        pb = _dir_preds(feat_b, y, fit_m, ev_m)
        d = (pa - ye) ** 2 - (pb - ye) ** 2
        mean, lo, hi, se = R.block_boot_ci(d, seed, b)
        out[name] = {"n_eval": int(ev_m.sum()), "bs_a_pb": float(((pa - ye) ** 2).mean()),
                     "bs_b_ewma": float(((pb - ye) ** 2).mean()),
                     "paired_mean_pb_minus_ewma": mean, "ci90": [lo, hi], "mde": 1.645 * se,
                     "ewma_beats_pb": bool(lo > 0), "ewma_significantly_worse": bool(hi < 0)}
    out["ewma_beats_pb_both"] = bool(out["early_to_late"]["ewma_beats_pb"]
                                     and out["late_to_early"]["ewma_beats_pb"])
    return out


def _adopt_increment_fast(feat_a, feat_b, y, me, ml, seed):
    """경량 양방향 증분 채택: 각 방향 (BS_a − BS_b) 고속 CI90 하한 > 0."""
    for fit_m, ev_m, sd in ((me, ml, seed), (ml, me, seed + 7)):
        ye = y[ev_m]
        d = (_dir_preds(feat_a, y, fit_m, ev_m) - ye) ** 2 - (_dir_preds(feat_b, y, fit_m, ev_m) - ye) ** 2
        if R._boot_lower_fast(d, sd) <= 0:
            return False
    return True


def neg_control_increment(feat_a, feat_b, y, me, ml, seed, draws=NEG_DRAWS):
    """y-block(ℓ=13) 순열 귀무 — 라벨을 블록 순열한 뒤 'EWMA(b) 가 PB(a) 를 양방향으로 이기는' 비율."""
    rng = np.random.default_rng(seed); n = len(y)
    starts = np.arange(0, n, R.BLOCK); passes = 0
    for _ in range(draws):
        order = rng.permutation(len(starts))
        idx = np.concatenate([np.arange(starts[k], min(starts[k] + R.BLOCK, n)) for k in order])[:n]
        if _adopt_increment_fast(feat_a, feat_b, y[idx], me, ml, seed + 1):
            passes += 1
    return passes / draws


# ── PAV (가중 pool-adjacent-violators) ──────────────────────────────────────
def pav(p, y, w=None):
    """비감소 step map. 반환 {'p_max': [...], 'value': [...]} — p <= p_max[k] 인 첫 블록 k 의 value."""
    p = np.asarray(p, float); y = np.asarray(y, float)
    w = np.ones(len(p)) if w is None else np.asarray(w, float)
    order = np.argsort(p, kind="stable"); p, y, w = p[order], y[order], w[order]
    blocks = []  # [sum_wy, sum_w, p_max]
    for pi, yi, wi in zip(p, y, w):
        blocks.append([yi * wi, wi, pi])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b2 = blocks.pop(); b1 = blocks.pop()
            blocks.append([b1[0] + b2[0], b1[1] + b2[1], max(b1[2], b2[2])])
    return {"p_max": [float(b[2]) for b in blocks], "value": [float(b[0] / b[1]) for b in blocks]}


def apply_pav(pmap, p):
    p = np.asarray(p, float)
    pmax = np.asarray(pmap["p_max"], float); val = np.asarray(pmap["value"], float)
    k = np.searchsorted(pmax, p, side="left")
    k = np.clip(k, 0, len(val) - 1)
    return np.clip(val[k], 1e-6, 1 - 1e-6)


def cross_fit_isotonic(feat, y, fit_mask, h, k=K_FOLDS):
    """fit 창을 시간순 k 연속 블록으로 나눠 OOF 확률을 만들고 PAV 를 적합한다. 경계 embargo = h origins 양측.

    반환 {'map', 'oof_p', 'oof_y', 'folds': [{'fold', 'start', 'end', 'n_train', 'train_min', 'train_max'}]}
    (folds 는 무누수 검사용 — 학습 인덱스가 [start−h, end+h] 와 겹치지 않아야 한다).
    """
    fit_idx = np.flatnonzero(fit_mask)
    n = len(fit_idx)
    if n < 2 * k:
        raise ValueError("cross_fit_isotonic: fit window too small")
    bounds = np.linspace(0, n, k + 1).astype(int)
    oof_p = np.full(n, np.nan); folds = []
    for j in range(k):
        lo, hi = bounds[j], bounds[j + 1]           # fit_idx 의 위치 [lo, hi)
        start, end = int(fit_idx[lo]), int(fit_idx[hi - 1])
        train_pos = np.flatnonzero((fit_idx < start - h) | (fit_idx > end + h))
        if len(train_pos) < 10:
            raise ValueError("cross_fit_isotonic: fold training set too small after embargo")
        tr = fit_idx[train_pos]
        b, mu, sd = R._logit_fit(feat[tr], y[tr])
        oof_p[lo:hi] = R._logit_pred(b, mu, sd, feat[fit_idx[lo:hi]])
        folds.append({"fold": j, "start": start, "end": end, "n_train": int(len(tr)),
                      "train_min": int(tr.min()), "train_max": int(tr.max()),
                      "train_gap_ok": bool(((tr < start - h) | (tr > end + h)).all())})
    oof_y = y[fit_idx]
    return {"map": pav(oof_p, oof_y), "oof_p": oof_p, "oof_y": oof_y, "folds": folds}


def iso_eval(feat, y, me, ml, h, seed, b=R.B):
    """h63 셀: raw vs cross-fit isotonic 파생층. 양방향 Murphy + 쌍대 Brier(raw − iso) CI90 + 사전등록 fallback."""
    out = {}
    for name, fit_m, ev_m in (("early_to_late", me, ml), ("late_to_early", ml, me)):
        ye = y[ev_m]
        raw = _dir_preds(feat, y, fit_m, ev_m)
        cf = cross_fit_isotonic(feat, y, fit_m, h)
        iso = apply_pav(cf["map"], raw)
        d = (raw - ye) ** 2 - (iso - ye) ** 2          # 양수 = iso 우세
        mean, lo, hi, se = R.block_boot_ci(d, seed, b)
        out[name] = {"bs_raw": float(((raw - ye) ** 2).mean()), "bs_iso": float(((iso - ye) ** 2).mean()),
                     "paired_mean_raw_minus_iso": mean, "ci90": [lo, hi], "mde": 1.645 * se,
                     "iso_better": bool(lo > 0), "iso_significantly_worse": bool(hi < 0),
                     "reliability_raw": reliability(raw, ye), "reliability_iso": reliability(iso, ye),
                     "map_blocks": len(cf["map"]["value"]),
                     "folds_leak_free": bool(all(f["train_gap_ok"] for f in cf["folds"]))}
    out["fallback_to_raw"] = bool(out["early_to_late"]["iso_significantly_worse"]
                                  or out["late_to_early"]["iso_significantly_worse"])
    out["derived_layer"] = "raw" if out["fallback_to_raw"] else "isotonic"
    return out


# ── champion 규칙 (계약 gates.G2 — 순수 함수) ───────────────────────────────
def champion_rule(cell):
    inc = cell["ewma_vs_pb"]
    nc_inc = cell.get("neg_control_increment_pass_rate")
    if inc["ewma_beats_pb_both"] and nc_inc is not None and nc_inc <= 0.10:
        return "ewma_logit"
    pbc = cell["pb_vs_clim"]
    nc_pb = cell.get("neg_control_pb_pass_rate")
    if pbc["adopted"] and nc_pb is not None and nc_pb <= 0.10:
        return "persistence_pb"
    return "hold"


def finalist_id(champion_cells):
    live = {k: v for k, v in sorted(champion_cells.items()) if v != "hold"}
    if not live:
        return None
    digest = hashlib.sha256(json.dumps(live, sort_keys=True).encode("utf-8")).hexdigest()
    return f"V13VOL_champion_{digest[:12]}"


def family_p_binomial(k_obs, n=9, p=0.05):
    return float(sum(comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(k_obs, n + 1)))


def content_hash(row):
    body = {k: v for k, v in row.items() if k != "content_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _dump(res):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main():
    if LEDGER.exists() and any(json.loads(line).get("experiment_label") == EXPERIMENT_LABEL
                               for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()):
        print(f"{EXPERIMENT_LABEL} already in ledger — evaluation budget is single-use; refusing to re-run.")
        return 2
    idx, vix, ndx, rv = R.load_panel()
    dates = np.array([str(d)[:10] for d in idx]); early = dates < R.SPLIT; late = ~early
    vix_ewma = R._ewma(vix, 2 / 22)
    rv_f = np.where(np.isfinite(rv), rv, np.nanmedian(rv[np.isfinite(rv)]))
    rv_ewma = R._ewma(rv_f, 2 / 22)
    ewma_vix = np.column_stack([vix, vix_ewma]); ewma_rv = np.column_stack([rv_f, rv_ewma])
    pb_vix = pb_features(vix); pb_rv = pb_features(rv_f)
    specs = []
    for K in R.Ks:
        for h in R.HS:
            specs.append((f"vix{K}_h{h}", R.labels_vix(vix, K, h), ewma_vix, pb_vix, h))
    for h in R.HS:
        specs.append((f"rv_h{h}", R.labels_rv(rv, h), ewma_rv, pb_rv, h))

    res = {"schema": "v13_vol_rung3_pb", "prereg_commit": PREREG_COMMIT, "window": list(R.DESIGN),
           "split": R.SPLIT, "n": int(len(idx)), "cells": {}}
    cells = res["cells"]
    print("=== V13-VOL rung-3 PB(당일 수준) 기준선 — 본 결과 (양방향, B=2000) ===", flush=True)
    for name, y, ewf, pbf, h in specs:
        m = np.isfinite(y); me, ml = early & m, late & m
        cell = {"h": h, "pb_vs_clim": R.eval_cell(pbf, y, me, ml, R.SEED),
                "ewma_vs_pb": paired_model_ci(pbf, ewf, y, me, ml, R.SEED)}
        if name in ISO_CELLS:
            cell["iso"] = iso_eval(ewf, y, me, ml, h, R.SEED)
        cells[name] = cell
        e = cell["ewma_vs_pb"]["early_to_late"]; l = cell["ewma_vs_pb"]["late_to_early"]  # noqa: E741
        pe = cell["pb_vs_clim"]["early_to_late"]; pl = cell["pb_vs_clim"]["late_to_early"]
        print(f"{name:10s} PB-vs-clim BSS e2l {pe['bss_vs_clim']:+.3f} l2e {pl['bss_vs_clim']:+.3f} adopt={cell['pb_vs_clim']['adopted']} | "
              f"EWMA−PB e2l {e['paired_mean_pb_minus_ewma']:+.5f}[{e['ci90'][0]:+.5f},{e['ci90'][1]:+.5f}] "
              f"l2e {l['paired_mean_pb_minus_ewma']:+.5f}[{l['ci90'][0]:+.5f},{l['ci90'][1]:+.5f}] "
              f"ewma_beats_pb={cell['ewma_vs_pb']['ewma_beats_pb_both']}"
              + (f" | iso: {cell['iso']['derived_layer']}" if "iso" in cell else ""), flush=True)
    _dump(res)
    print("--- 건전 귀무(y-block) — (a) 증분: ewma_beats_pb 셀만 / (b) PB-vs-기후: 그 외 PB 채택 셀만 ---", flush=True)
    for name, y, ewf, pbf, h in specs:
        cell = cells[name]; m = np.isfinite(y); me, ml = early & m, late & m
        yf = np.where(m, y, 0.0)
        if cell["ewma_vs_pb"]["ewma_beats_pb_both"]:
            cell["neg_control_increment_pass_rate"] = neg_control_increment(pbf, ewf, yf, me, ml, R.SEED)
            print(f"  {name}: 증분 귀무 통과율 {cell['neg_control_increment_pass_rate']:.3f}", flush=True)
        else:
            cell["neg_control_increment_pass_rate"] = None
        if not (cell["ewma_vs_pb"]["ewma_beats_pb_both"]
                and cell["neg_control_increment_pass_rate"] is not None
                and cell["neg_control_increment_pass_rate"] <= 0.10) and cell["pb_vs_clim"]["adopted"]:
            cell["neg_control_pb_pass_rate"] = R.neg_control(pbf, yf, me, ml, R.SEED)
            print(f"  {name}: PB-vs-기후 귀무 통과율 {cell['neg_control_pb_pass_rate']:.3f}", flush=True)
        else:
            cell["neg_control_pb_pass_rate"] = None
        cell["champion"] = champion_rule(cell)
    champion_cells = {k: v["champion"] for k, v in cells.items()}
    k_obs = sum(1 for v in cells.values() if v["ewma_vs_pb"]["ewma_beats_pb_both"])
    res.update({
        "champion_cells": champion_cells,
        "hold_cells": [k for k, v in champion_cells.items() if v == "hold"],
        "finalist_id": finalist_id(champion_cells),
        "k_obs_ewma_beats_pb": k_obs,
        "family_p_binomial_ewma_beats_pb": family_p_binomial(k_obs),
        "iso_h63_derived_layer": {k: cells[k]["iso"]["derived_layer"] for k in ISO_CELLS},
        "hold_condition_triggered": all(v == "hold" for v in champion_cells.values()),
    })
    _dump(res)
    row = {"schema_version": 1, "experiment_label": EXPERIMENT_LABEL, "model": "event_probability.volatility_v13",
           "rung": RUNG, "window_role": "design", "window": list(R.DESIGN), "prereg_commit": PREREG_COMMIT,
           "evaluation_index": 3, "backtest_windows_opened": 0,
           "gate": "G2: EWMA 가 PB 대비 양방향 CI90 하한>0 ∧ 증분 y-block ≤0.10 → ewma_logit; 아니면 PB 기후 통과 ∧ 귀무 ≤0.10 → persistence_pb; 아니면 hold",
           "champion_cells": champion_cells, "hold_cells": res["hold_cells"], "finalist_id": res["finalist_id"],
           "k_obs_ewma_beats_pb": k_obs, "family_p_binomial": res["family_p_binomial_ewma_beats_pb"],
           "iso_h63_derived_layer": res["iso_h63_derived_layer"],
           "hold_condition_triggered": res["hold_condition_triggered"],
           "results_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
           "caveat": "설계창 한정·홀드아웃 미열람. PB=당일 수준 단독 로짓(자명 기준선). champion 은 셀별.",
           "knowledge_cutoff": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    row["content_hash"] = content_hash(row)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\nCHAMPION: {champion_cells}")
    print(f"HOLD cells: {res['hold_cells'] or 'none'} | finalist_id={res['finalist_id']} | k_obs(ewma>pb)={k_obs} "
          f"family_p={res['family_p_binomial_ewma_beats_pb']:.4f}")
    print(f"h63 derived layer: {res['iso_h63_derived_layer']}")
    print(f"ledger row content_hash={row['content_hash']}")
    print(f"wrote {OUT.relative_to(ROOT)} (sha256 {row['results_sha256']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
