"""tools/v13_vol_freeze_coefficients.py — V13-VOL champion 계수 동결 (Phase C).

계약 gates.champion(C-1 결과) 이 null 이면 거부. 셀별 champion 모형(ewma_logit 또는 persistence_pb) 을
설계창(2007-2014) 전체에 1회 적합해 data/timeseries_v13/vol/champion_coefficients.json 으로 동결한다.
- G0 무손상 대사: numpy 피처로 early/late 반창을 재적합해 사다리 json(rung-1 EWMA · rung-3 PB) 의
  bss_vs_clim 과 ≤1e-6 로 일치해야만 쓴다 (fail-closed).
- 80% 대역용 Cov(β): 정지 블록 부트스트랩(ℓ=13 · B=2000 · seed 20260907) 재적합 공분산.
- EWMA champion 셀에는 baseline_pb(홀드아웃 G2용) 도 동결. h63 iso 대상 셀(파생층 isotonic) 은 설계창 전체 cross-fit map.
- stdout 에 sha256·content_hash 를 인쇄 → 계약 frozen_coefficients 핀에 기입. 라이브 재적합 금지.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_fc.timeseries_v13 import contracts as C  # noqa: E402
from ai_fc.timeseries_v13 import features as F  # noqa: E402
from ai_fc.timeseries_v2.market_archive import read_market_observations  # noqa: E402

SPLIT = "2011-01-01"
RECON_TOL = 1e-6
K_FOLDS = 5


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _half_window_bss(feat, y, me, ml):
    """rung-1/3 eval_cell 과 같은 반창 적합 → bss_vs_clim 두 값."""
    out = {}
    for name, fit_m, ev_m in (("early_to_late", me, ml), ("late_to_early", ml, me)):
        clim = float(y[fit_m].mean())
        b, mu, sd = F.logit_fit(feat[fit_m], y[fit_m])
        pe = F.logit_predict(b, mu, sd, feat[ev_m]); ye = y[ev_m]
        out[name] = float(1 - ((pe - ye) ** 2).mean() / max(((clim - ye) ** 2).mean(), 1e-9))
    return out


def _cross_fit_map(feat, y, fit_mask, h, k=K_FOLDS):
    fit_idx = np.flatnonzero(fit_mask); n = len(fit_idx)
    bounds = np.linspace(0, n, k + 1).astype(int)
    oof = np.full(n, np.nan)
    for j in range(k):
        lo, hi = bounds[j], bounds[j + 1]
        start, end = int(fit_idx[lo]), int(fit_idx[hi - 1])
        tr = fit_idx[(fit_idx < start - h) | (fit_idx > end + h)]
        b, mu, sd = F.logit_fit(feat[tr], y[tr])
        oof[lo:hi] = F.logit_predict(b, mu, sd, feat[fit_idx[lo:hi]])
    return F.pav(oof, y[fit_idx])


def main() -> int:
    contract = C.load_contract_v13(ROOT)
    champion = contract["gates"]["champion"]
    if not champion.get("finalist_id") or not champion.get("cells"):
        print("REFUSED: gates.champion is null — run rung-3 (C-1) and record the champion first.")
        return 2
    pb_path = ROOT / C.LADDER_PB_RELATIVE
    ewma_path = ROOT / C.LADDER_EWMA_RELATIVE
    ladder_ewma = json.loads(ewma_path.read_text(encoding="utf-8"))["rungs"]["ewma_logit"]
    ladder_pb = json.loads(pb_path.read_text(encoding="utf-8"))
    if ladder_pb.get("finalist_id") != champion["finalist_id"]:
        print("REFUSED: ladder_pb_baseline.json finalist_id does not match the contract champion.")
        return 2
    iso_cells = set(contract["reliability"]["cross_fit_isotonic_h63"]["applies_to"])
    iso_layer = ladder_pb.get("iso_h63_derived_layer") or {}

    now = datetime.now(timezone.utc)
    panel = F.build_panel(read_market_observations(ROOT), start=C.DESIGN_WINDOW[0], end=C.DESIGN_WINDOW[1])
    dates, vix, ndx, rv = panel["dates"], panel["vix"], panel["ndx"], panel["rv21"]
    rv_nan_count = int((~np.isfinite(rv)).sum())
    rv_median = float(np.nanmedian(rv[np.isfinite(rv)]))
    vix_ewma = F.ewma(vix); rv_f = F.fill_rv_nan(rv, rv_median); rv_ewma = F.ewma(rv_f)
    early = np.array([d < SPLIT for d in dates]); late = ~early

    cells = {}; recon = {}; max_diff = 0.0
    for spec in C.cell_specs():
        name = spec["name"]; model = champion["cells"].get(name, "hold")
        if model == "hold":
            continue
        target = spec["target"]; h = spec["h"]
        if target == "vix_touch":
            y = F.labels_vix(vix, spec["K"], h); level, smooth = vix, vix_ewma
        else:
            y = F.labels_rv(rv, spec["theta"], h); level, smooth = rv_f, rv_ewma
        m = np.isfinite(y); me, ml = early & m, late & m
        feat = F.feature_matrix(model, level, smooth)
        # G0 대사 — 반창 BSS 를 사다리 결과와 비교
        got = _half_window_bss(feat, y, me, ml)
        if model == "ewma_logit":
            ref = {k: ladder_ewma[name][k]["bss_vs_clim"] for k in got}
        else:
            ref = {k: ladder_pb["cells"][name]["pb_vs_clim"][k]["bss_vs_clim"] for k in got}
        diffs = {k: abs(got[k] - ref[k]) for k in got}
        max_diff = max(max_diff, *diffs.values())
        recon[name] = {"model": model, "ladder": ref, "numpy": got, "abs_diff": diffs}
        # 설계창 전체 1회 적합 (등록 적합기: 200 Newton)
        Xf, yf = feat[m], y[m]
        beta, mu, sd = F.logit_fit(Xf, yf)
        cov = F.block_bootstrap_cov(Xf, yf, seed=C.BOOTSTRAP_SEED)
        cell = {
            "model": model, "target": target, "h": h,
            **({"K": spec["K"]} if target == "vix_touch" else {"theta": spec["theta"]}),
            "feature_names": F.feature_names(model, target),
            "beta": [float(v) for v in beta], "mu": [float(v) for v in mu], "sd": [float(v) for v in sd],
            "cov_beta": [[float(v) for v in row] for row in cov],
            "n_fit": int(m.sum()), "clim_base_rate": float(yf.mean()),
            "baseline_pb": None, "iso_map": None, "derived_layer": "raw",
            "gate_evidence": {
                "design_pass": True,
                "vs_climatology_bss": ref,
                "champion_rule": ladder_pb["cells"][name]["champion"],
                "ewma_beats_pb_both": ladder_pb["cells"][name]["ewma_vs_pb"]["ewma_beats_pb_both"],
                "neg_control_increment_pass_rate": ladder_pb["cells"][name].get("neg_control_increment_pass_rate"),
                "neg_control_pb_pass_rate": ladder_pb["cells"][name].get("neg_control_pb_pass_rate"),
                "neg_control_ewma_vs_clim_pass_rate": ladder_ewma[name].get("neg_control_pass_rate"),
            },
        }
        if model == "ewma_logit":
            pbf = F.feature_matrix("persistence_pb", level, None)
            pb_beta, pb_mu, pb_sd = F.logit_fit(pbf[m], yf)
            cell["baseline_pb"] = {"feature_names": F.feature_names("persistence_pb", target),
                                   "beta": [float(v) for v in pb_beta], "mu": [float(v) for v in pb_mu],
                                   "sd": [float(v) for v in pb_sd]}
        if name in iso_cells and iso_layer.get(name) == "isotonic":
            cell["iso_map"] = _cross_fit_map(feat, y, m, h)
            cell["derived_layer"] = "isotonic"
        cells[name] = cell
        print(f"{name:10s} {model:14s} n_fit={cell['n_fit']} clim={cell['clim_base_rate']:.4f} "
              f"recon Δ e2l {diffs['early_to_late']:.2e} l2e {diffs['late_to_early']:.2e} layer={cell['derived_layer']}", flush=True)

    recon_pass = bool(max_diff <= RECON_TOL)
    if not recon_pass:
        print(f"REFUSED: reconciliation failed — max |ΔBSS| {max_diff:.3e} > {RECON_TOL}. Nothing written.")
        return 1
    in_window = lambda series: [[d, float(v)] for d, v in zip(dates, series)]  # noqa: E731
    payload = {
        "schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION,
        "finalist_id": champion["finalist_id"], "champion_decided_at": champion.get("decided_at"),
        "champion_source_content_hash": champion.get("source_content_hash"),
        "prereg_commit": contract["amendments_applied"]["V13-D2prime"]["prereg_commit"],
        "fit_window": [str(dates[0]), str(dates[-1])], "n_panel": int(len(dates)),
        "alpha_ewma": C.EWMA_ALPHA, "ewma_seed_rule": "m0 = x[0]; non-finite carried forward; run continuously over full history",
        "rv_definition": "log(NASDAQCOM).diff().rolling(21).std(ddof=1) * sqrt(252)",
        "rv_nan_fill_median": rv_median, "rv_nan_count": rv_nan_count, "theta_rv": C.THETA_RV,
        "hyperparameters": {"iters": 200, "l2": 1e-3, "zscore_ddof": 0, "sd_floor_rule": "sd<1e-9 -> 1.0",
                            "clip": [1e-6, 1 - 1e-6], "optimizer": "newton"},
        "bootstrap": {"method": "stationary_block", "block_length": C.BLOCK_LENGTH,
                      "replicates": C.BOOTSTRAP_REPLICATES, "seed": C.BOOTSTRAP_SEED, "refit_tol": 1e-9},
        "band80": {"method": "delta_method", "z": C.Z80, "meaning": "coefficient_uncertainty_not_calibration"},
        "inputs_sha256": {"VIX": C.canonical_hash(in_window(vix)), "NASDAQCOM": C.canonical_hash(in_window(ndx))},
        "knowledge_cutoff": now.isoformat(timespec="seconds"),
        "provenance": {"git_head": _git_head(), "runner_sha256": _sha(Path(__file__)),
                       "features_sha256": _sha(ROOT / "src/ai_fc/timeseries_v13/features.py"),
                       "contract_sha256": _sha(ROOT / C.CONTRACT_RELATIVE),
                       "ladder_ewma_sha256": _sha(ewma_path), "ladder_pb_sha256": _sha(pb_path)},
        "cells": cells,
        "reconciliation": {"pass": recon_pass, "tolerance": RECON_TOL, "max_abs_bss_diff": max_diff, "cells": recon},
    }
    out = ROOT / C.COEFFICIENTS_RELATIVE
    if out.is_file():
        payload["previous_artifact_sha256"] = _sha(out)   # 재동결 이력 — 이전 바이트는 git 이력에 남는다
    payload["content_hash"] = C.canonical_hash(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    print(f"\nwrote {out.relative_to(ROOT)}")
    print(f"sha256={_sha(out)}")
    print(f"content_hash={payload['content_hash']}")
    print(f"finalist_id={payload['finalist_id']}  cells={len(cells)}  reconciliation max|Δ|={max_diff:.2e}")
    # 계약 핀 자동 기입 (frozen_coefficients 블록 안의 세 값만 치환 — 다른 줄 무변경)
    import re
    text = (ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8")
    head, sep, tail = text.partition("frozen_coefficients:\n")
    block, sep2, rest = tail.partition("  refit_prohibited:")
    block = re.sub(r"^  sha256: .*$", f"  sha256: {_sha(out)}", block, flags=re.M)
    block = re.sub(r"^  content_hash: .*$", f"  content_hash: {payload['content_hash']}", block, flags=re.M)
    block = re.sub(r"^  finalist_id: .*$", f"  finalist_id: {payload['finalist_id']}                    # gates.champion.finalist_id 와 일치해야 한다", block, flags=re.M)
    text = head + sep + block + sep2 + rest
    (ROOT / C.CONTRACT_RELATIVE).write_text(text, encoding="utf-8", newline="\n")
    pinned = yaml.safe_load(text)["frozen_coefficients"]
    print(f"contract pin: sha256 {'OK' if pinned['sha256'] == _sha(out) else 'NOT WRITTEN — pin manually'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
