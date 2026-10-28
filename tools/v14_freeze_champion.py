"""tools/v14_freeze_champion.py — V14 조건부 전이 champion 계수 동결 (V14-D10, 1회용).

설계창(2007-01-01~2014-12-31) **전체**의 조건 충족 원점으로 셀별 conditional_persistence_pb(절편 + 표준화 당일 수준
1피처: cvix 셀 VIX_t · crv 셀 RV21_t)를 1회 적합해 data/timeseries_v14/vol/champion_coefficients.json 으로 쓴다.

- 패널: build_panel(start=data_policy.lookback_for_features '2005-01-01', end=설계창 끝 '2014-12-31') — rung-1 러너
  (tools/v14_cond_diagnostics.panel_context)와 같은 패널. 2015+ 행은 패널에 들어오지 않으며 들어오면 거부한다.
  2005-2006 은 RV21 워밍업용 선행창일 뿐 적합 원점이 아니다(적합 = 설계창 ∧ 조건 충족 ∧ 유한 라벨 ∧ 유한 피처).
- 적합기: 공유 ai_fc.timeseries_v13.features.logit_fit (zscore ddof0 · Newton 200 · l2 1e-3). 신규 적합기 0.
- 대사(fail-closed): ① tools/v13_vol_run._logit_fit 재적합 max|Δβ| < 1e-10 ② 셀 정의 패리티 — 이 패키지의
  조건 마스크·피처·라벨이 rung-1/2 러너가 쓴 tools/v14_cond_diagnostics 정의와 비트 단위로 같아야 한다.
- 역할(champion/shadow)은 계약 live_pointer 에서 읽는다(데이터). champion 셀은 최신 rung 결과의 champion_rule 이
  conditional_persistence_pb 여야 한다 — rung 결과가 없으면(champion 미정) 거부.
- 산출물이 이미 있으면 **덮어쓰지 않는다**(exit 2, 아카이브를 읽기 전에). 계약은 수정하지 않는다 — sha256·content_hash 를
  인쇄하고 orchestrator 가 계약 frozen_coefficients 에 핀한다.

    PYTHONUTF8=1 python tools/v14_freeze_champion.py [--root PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from ai_fc.timeseries_v13 import features as F  # noqa: E402  (build_panel · logit_fit — 공유 구현)
from ai_fc.timeseries_v14 import contracts as C  # noqa: E402
from ai_fc.timeseries_v14 import pipeline as P  # noqa: E402  (condition_mask · level_series · labels_for)
from ai_fc.timeseries_v2.market_archive import read_market_observations  # noqa: E402
import v13_vol_run as R  # noqa: E402  (_logit_fit — 대사 기준)
import v14_cond_diagnostics as P0  # noqa: E402  (rung-1/2 러너의 셀 정의 — 패리티 기준)

RECON_TOL = 1e-10
MAX_RUNG = 4                     # development_protocol.maximum_development_evaluations


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def design_bounds(contract: dict[str, Any]) -> tuple[str, str, str]:
    """(lookback_start, design_start, design_end) — 계약 data_policy. 설계창 끝은 2014-12-31 이어야 한다."""
    policy = contract.get("data_policy") or {}
    window = [str(d) for d in (policy.get("design_window") or [])]
    lookback = str(policy.get("lookback_for_features") or window[0])
    if window != ["2007-01-01", "2014-12-31"]:
        raise C.TimeSeriesV14Error(f"data_policy.design_window {window} is not ['2007-01-01', '2014-12-31']")
    if lookback > window[0]:
        raise C.TimeSeriesV14Error("data_policy.lookback_for_features is after the design window start")
    return lookback, window[0], window[1]


def fit_panel(observations, contract: dict[str, Any]) -> dict[str, np.ndarray]:
    """설계창 끝에서 절단한 패널. 2015+ 날짜가 하나라도 남으면 raise (홀드아웃·봉인 바이트를 적합에 넣지 않는다)."""
    lookback, _, design_end = design_bounds(contract)
    panel = F.build_panel(observations, start=lookback, end=design_end)
    if len(panel["dates"]) and str(panel["dates"][-1]) > design_end:
        raise C.TimeSeriesV14Error("fit panel extends past the design window end")
    return panel


def rung_references(root: Path, contract: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """등록된 rung 의 사전등록 커밋·결과 파일 sha256 + 최신 rung 결과 경로. 결과 없는 rung 이 있으면 (None, 사유)."""
    refs: dict[str, Any] = {}
    latest: dict[str, Any] | None = None
    for n in range(1, MAX_RUNG + 1):
        key = f"rung{n}_conditional_blocks"
        spec = contract.get(key)
        if not isinstance(spec, dict):
            continue
        commit = spec.get("prereg_commit")
        results = root / str(spec.get("results_path") or "")
        if not commit:
            return {}, f"{key}.prereg_commit is null — the rung is not executed; the champion is undecided"
        if not spec.get("results_path") or not results.is_file():
            return {}, f"{key} results file is missing — the champion is decided only after that rung"
        refs[key] = {"prereg_commit": str(commit), "results_path": str(spec["results_path"]),
                     "results_sha256": _sha(results), "experiment_label": spec.get("experiment_label")}
        latest = {"key": key, "payload": json.loads(results.read_text(encoding="utf-8"))}
    if latest is None:
        return {}, "no rung{N}_conditional_blocks results are registered"
    refs["champion_source"] = latest["key"]
    refs["_latest_payload"] = latest["payload"]
    return refs, None


def champion_rule_problems(outcomes: dict[str, Any], champion_cells: list[str]) -> list[str]:
    problems = []
    for cell in champion_cells:
        champion = ((outcomes or {}).get(cell) or {}).get("champion")
        if champion != C.MODEL_NAME:
            problems.append(f"{cell}: latest rung champion_rule says {champion!r}, not {C.MODEL_NAME}")
    return problems


def definition_parity(contract: dict[str, Any], vix: np.ndarray, rv: np.ndarray) -> dict[str, Any]:
    """이 패키지의 조건·피처·라벨 == rung 러너(tools/v14_cond_diagnostics)의 정의 — 셀별 불일치 원점 수(0 이어야 한다)."""
    p0_specs = {s["name"]: s for s in P0.v14_cell_specs(contract)}
    out: dict[str, Any] = {}
    for spec in C.cell_specs():
        ref = p0_specs[spec["name"]]
        cond = P.condition_mask(spec, vix, rv); cond_ref = P0.conditional_subset(ref, vix, rv)
        y = P.labels_for(spec, vix, rv); y_ref = P0.full_labels(ref, vix, rv)
        lv = P.level_series(spec, vix, rv); lv_ref = P0.champion_feature(ref, vix, rv)
        out[spec["name"]] = {
            "condition_mismatch": int((cond != cond_ref).sum()),
            "label_mismatch": int((~((y == y_ref) | (np.isnan(y) & np.isnan(y_ref)))).sum()),
            "level_mismatch_on_subset": int((lv[cond] != lv_ref[cond]).sum()),
        }
    return out


def fit_cells(panel: dict[str, np.ndarray], *, design_start: str, roles: dict[str, str]) -> tuple[dict, dict]:
    dates = [str(d) for d in panel["dates"]]
    vix, rv = panel["vix"], panel["rv21"]
    design = np.array([d >= design_start for d in dates], bool)
    cells: dict[str, Any] = {}
    recon: dict[str, Any] = {}
    for spec in C.cell_specs():
        name = spec["name"]
        y = P.labels_for(spec, vix, rv)
        level = P.level_series(spec, vix, rv)
        m = design & P.condition_mask(spec, vix, rv) & np.isfinite(y) & np.isfinite(level)
        X, yf = level[m].reshape(-1, 1), y[m]
        if not len(yf):
            raise C.TimeSeriesV14Error(f"{name}: no condition-met design origins with a finite label")
        beta, mu, sd = F.logit_fit(X, yf)
        rb, rmu, rsd = R._logit_fit(X, yf)
        recon[name] = {"abs_beta_diff": float(np.abs(beta - rb).max()), "abs_mu_diff": float(np.abs(mu - rmu).max()),
                       "abs_sd_diff": float(np.abs(sd - rsd).max())}
        fit_dates = [d for d, keep in zip(dates, m) if keep]
        cells[name] = {
            "model": C.MODEL_NAME, "target": spec["target"], "h": spec["h"],
            **({"K": spec["K"]} if spec["target"] == "vix_conditional" else {"theta": spec["theta"]}),
            "condition": spec["condition"], "feature": spec["feature"], "role": roles[name],
            "beta": [float(v) for v in beta], "mu": [float(v) for v in mu], "sd": [float(v) for v in sd],
            "n_fit": int(m.sum()), "events_fit": int(yf.sum()), "clim_base_rate": float(yf.mean()),
            "fit_first_origin": fit_dates[0], "fit_last_origin": fit_dates[-1],
        }
    return cells, recon


def build_payload(root: Path, contract: dict[str, Any], observations, *, now: datetime) -> dict[str, Any]:
    cfg = C.live_pointer_config(contract)
    lookback, design_start, design_end = design_bounds(contract)
    refs, problem = rung_references(root, contract)
    if problem:
        raise C.TimeSeriesV14Error(problem)
    latest = refs.pop("_latest_payload")
    problems = champion_rule_problems(latest.get("champion_rule_outcomes") or {}, cfg["champion_cells"])
    if problems:
        raise C.TimeSeriesV14Error("champion cells are not conditional_persistence_pb in the latest rung: " + "; ".join(problems))
    panel = fit_panel(observations, contract)
    dates = [str(d) for d in panel["dates"]]
    parity = definition_parity(contract, panel["vix"], panel["rv21"])
    parity_ok = all(v == 0 for cell in parity.values() for v in cell.values())
    cells, recon = fit_cells(panel, design_start=design_start, roles=cfg["roles"])
    max_beta = max(v["abs_beta_diff"] for v in recon.values())
    max_other = max(max(v["abs_mu_diff"], v["abs_sd_diff"]) for v in recon.values())
    recon_pass = bool(max_beta < RECON_TOL and max_other < RECON_TOL and parity_ok)
    in_window = lambda series: [[d, float(v)] for d, v in zip(dates, series)]  # noqa: E731
    return {
        "schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "model": C.MODEL_NAME,
        "contract_id": C.CONTRACT_ID,
        "live_pointer": {"registered": cfg["registered"], "approval_receipt": cfg["approval_receipt"],
                         "champion_cells": cfg["champion_cells"], "shadow_cells": cfg["shadow_cells"]},
        "fit_window": [design_start, design_end], "panel_window": [lookback, design_end],
        "panel_first_date": dates[0], "panel_last_date": dates[-1], "n_panel": len(dates),
        "theta": C.THETA, "K": C.K, "vix_condition": C.VIX_CONDITION_TEXT, "rv_condition": C.RV_CONDITION_TEXT,
        "rv_definition": "log(NASDAQCOM).diff() rolling 21 sample std (ddof=1) * sqrt(252) — ai_fc.timeseries_v13.features.build_panel",
        "rv_nan_rule": ("RV21 NaN 원점(패널 첫 21세션·결측)은 crv 조건 부분집합 밖 — 채움 없음. lookback 2005-01-01 선행창이 "
                        "설계창 첫 원점의 RV21 을 정의한다(rung-1 러너와 같은 패널)."),
        "fit_subset_rule": "design_window ∧ condition_met ∧ finite label (i+1..i+h within the 2014-12-31 panel) ∧ finite level",
        "hyperparameters": {"fitter": "ai_fc.timeseries_v13.features.logit_fit", "iters": 200, "l2": 1e-3,
                            "zscore_ddof": 0, "sd_floor_rule": "sd<1e-9 -> 1.0", "clip": [1e-6, 1 - 1e-6],
                            "optimizer": "newton"},
        "prereg": refs,
        "inputs_sha256": {"VIX": C.canonical_hash(in_window(panel["vix"])),
                          "NASDAQCOM": C.canonical_hash(in_window(panel["ndx"]))},
        "knowledge_cutoff": now.isoformat(timespec="seconds"),
        "provenance": {"runner_sha256": _sha(Path(__file__)),
                       "features_sha256": _sha(ROOT / "src/ai_fc/timeseries_v13/features.py"),
                       "v14_pipeline_sha256": _sha(ROOT / "src/ai_fc/timeseries_v14/pipeline.py"),
                       "contract_sha256": _sha(root / C.CONTRACT_RELATIVE)},
        "cells": cells,
        "reconciliation": {"pass": recon_pass, "tolerance": RECON_TOL, "reference": "tools/v13_vol_run._logit_fit",
                           "max_abs_beta_diff": max_beta, "max_abs_mu_sd_diff": max_other, "cells": recon,
                           "definition_parity_reference": "tools/v14_cond_diagnostics (rung-1/2 runner cell definitions)",
                           "definition_parity_pass": parity_ok, "definition_parity": parity},
        "caveat": ("설계창 적합 — 홀드아웃 없음(C3)·라이브 전진 판정 전. θ·조건 20·창은 정점 지식을 간접 내포할 수 있다(CLAUDE.md "
                   "5원칙 명문화 예외 caveat). 참고 의견, 매매 신호 아님. 재적합 금지 — 라이브는 이 계수만 읽는다."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="저장소 루트(테스트용 임시 경로)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    out = root / C.COEFFICIENTS_RELATIVE
    if out.exists():
        print(f"REFUSED: {C.COEFFICIENTS_RELATIVE.as_posix()} already exists — 동결 계수는 덮어쓰지 않는다 "
              "(재동결은 사용자 결정 + 기존 파일 git 이력 보존 + 새 핀). 아무것도 쓰지 않았다.")
        return 2
    try:
        contract = C.load_contract_v14(root)
        C.live_pointer_config(contract)
        _, problem = rung_references(root, contract)
        if problem:
            print(f"REFUSED: {problem}. 아무것도 쓰지 않았다.")
            return 2
        payload = build_payload(root, contract, read_market_observations(root), now=datetime.now(timezone.utc))
    except C.TimeSeriesV14Error as exc:
        print(f"REFUSED: {exc}. 아무것도 쓰지 않았다.")
        return 2
    rec = payload["reconciliation"]
    for name, cell in payload["cells"].items():
        print(f"{name:11s} {cell['role']:8s} n_fit={cell['n_fit']:5d} events={cell['events_fit']:5d} "
              f"clim={cell['clim_base_rate']:.4f} beta=[{cell['beta'][0]:+.6f}, {cell['beta'][1]:+.6f}] "
              f"|Δβ|={rec['cells'][name]['abs_beta_diff']:.1e} parity={rec['definition_parity'][name]}")
    if not rec["pass"]:
        print(f"REFUSED: reconciliation failed — max|Δβ| {rec['max_abs_beta_diff']:.3e} (tol {RECON_TOL}) · "
              f"definition parity {rec['definition_parity_pass']}. 아무것도 쓰지 않았다.")
        return 1
    payload["content_hash"] = C.canonical_hash(payload)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:   # 'x' — 경합으로 생긴 파일도 덮어쓰지 않는다
        handle.write(text)
    print(f"\nwrote {C.COEFFICIENTS_RELATIVE.as_posix()} (panel {payload['panel_first_date']}..{payload['panel_last_date']})")
    print(f"sha256={_sha(out)}")
    print(f"content_hash={payload['content_hash']}")
    print(f"champion_cells={payload['live_pointer']['champion_cells']} shadow_cells={payload['live_pointer']['shadow_cells']} "
          f"reconciliation max|Δβ|={rec['max_abs_beta_diff']:.2e}")
    print("계약 frozen_coefficients.sha256 · content_hash 에 위 두 값을 핀하라(이 도구는 계약을 쓰지 않는다).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
