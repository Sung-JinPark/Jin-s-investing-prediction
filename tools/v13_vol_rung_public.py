"""tools/v13_vol_rung_public.py — rung-7 / rung-8: 공공영역 외부 정보집합 블록 vs PB (설계창 한정).

사전등록: `docs/design/v13_rung7_prereg_261021.md` + 계약 키 `rung7_public_blocks` / `rung8_public_blocks`(결과 전 커밋).
표적 K·θ·h 무변경 · 홀드아웃·봉인 미열람 · 블록 정의는 계약이 정본이며 여기서 바꾸지 않는다.
게이트: 셀별 쌍대 Brier(PB − 후보) 양방향 CI90 하한 > 0 ∧ 증분 y-block(ℓ=13) 귀무 ≤ 0.10 (rung-4~6 동일).
family: 대표값 binomial P(k >= k_obs | n=검정 수, p=0.05). 클래스별 k·가설 활성 셀 부분집합은 진단 병기.

    PYTHONUTF8=1 python tools/v13_vol_rung_public.py --rung 7
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from ai_fc.timeseries_v13 import contracts as C  # noqa: E402
from ai_fc.timeseries_v13 import features as F  # noqa: E402
from ai_fc.timeseries_v13 import scoring as S  # noqa: E402
from ai_fc.timeseries_v2.market_archive import read_market_observations  # noqa: E402
import v13_vol_run as R  # noqa: E402  (block_boot_ci·_boot_lower_fast 규칙 승계)
import v13_vol_rung3_pb as PB3  # noqa: E402  (paired_model_ci·neg_control_increment 재사용)
import v13_vol_rung7_diagnostics as D  # noqa: E402  (블록 빌더 — 진단과 같은 코드)

SPLIT = "2011-01-01"
LEDGER = ROOT / "data/timeseries_v13/ledgers/vol_experiments.jsonl"
NULL_DRAWS = 120
FROZEN_RV_MEDIAN = 0.1694207105468098


def build_block(name: str, *, dates, vix, rv, spec, marks, p1, p3, d2):
    h = spec["h"]
    if name == "E1_fomc_in_window":
        return D.window_count(marks["fomc_scheduled"], h)
    if name == "E2_macro_release_in_window":
        return D.window_count(marks["bls_empsit"] + marks["bls_cpi"], h)
    if name == "E3_log_sessions_to_next_fomc":
        return np.log1p(D.sessions_to_next(marks["fomc_scheduled"]))
    if name == "P1_vix_lev_net_oi":
        return p1
    if name == "P3_nq_lev_net_oi":
        return p3
    if name == "D1_log_sessions_since_event":
        if spec["target"] == "vix_touch":
            return np.log1p(D.sessions_since(vix >= float(spec["K"])))
        return np.log1p(D.sessions_since(rv > float(spec["theta"])))
    if name == "D2_log_sessions_since_any_vix25":
        return d2
    raise KeyError(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rung", type=int, required=True, choices=(7, 8))
    args = ap.parse_args()
    key = f"rung{args.rung}_public_blocks"
    contract = C.load_contract_v13(ROOT)
    spec = contract[key]
    label = spec["experiment_label"]
    out_path = ROOT / spec["results_path"]
    if LEDGER.exists() and any(
            json.loads(line).get("experiment_label") == label
            for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()):
        print(label + " already in ledger — 평가 예산은 1회용이다. 재실행 거부.")
        return 2
    if not spec.get("prereg_commit"):
        print("prereg_commit 이 계약에 없다 — 사전등록 커밋 뒤에만 실행한다.")
        return 2

    observations = list(read_market_observations(ROOT))
    # 패널은 D1 선행창을 위해 2005 부터 읽되, 적합·평가는 설계창 행만 쓴다 (2015+ 미열람: end 절단).
    panel = F.build_panel(observations, start=D.LOOKBACK_START, end=C.DESIGN_WINDOW[1])
    dates = [str(d) for d in panel["dates"]]
    vix = np.asarray(panel["vix"], float)
    rv_raw = np.asarray(panel["rv21"], float)
    rv_f = F.fill_rv_nan(rv_raw, FROZEN_RV_MEDIAN)
    design = np.array([C.DESIGN_WINDOW[0] <= d <= C.DESIGN_WINDOW[1] for d in dates])
    early = design & np.array([d < SPLIT for d in dates])
    late = design & ~np.array([d < SPLIT for d in dates])
    marks = D.event_index_sets(dates)
    p1 = D.positioning_series(dates, "1170E1", "lev_net_over_oi")
    p3 = D.positioning_series(dates, "209742", "lev_net_over_oi")
    d2 = np.log1p(D.sessions_since(vix >= 25.0))
    guard = contract["degeneracy_guard"]["rules"]
    excluded = {(e["cell"], e["block"]): e["reason"] for e in spec.get("excluded_cells", [])}

    results: dict = {}
    k_obs = 0
    tested = 0
    k_by_class: dict[str, int] = {}
    n_by_class: dict[str, int] = {}
    print("{:11s} {:30s} {:>28s} {:>28s} {:>6s} 판정".format("셀", "블록", "e2l 쌍대[CI90]", "l2e 쌍대[CI90]", "귀무"))
    for cell in C.cell_specs():
        name = cell["name"]
        if cell["target"] == "vix_touch":
            y_full = F.labels_vix(vix, cell["K"], cell["h"])
            level = vix
        else:
            y_full = F.labels_rv(rv_raw, cell["theta"], cell["h"])
            level = rv_f
        y = np.where(design, y_full, np.nan)
        pb_feat = F.feature_matrix("persistence_pb", level, None)
        for block in spec["blocks"]:
            bname = block["id"]
            klass = block["class"]
            entry: dict = {"class": klass}
            if (name, bname) in excluded:
                entry["verdict"] = "excluded_preregistered"
                entry["reason"] = excluded[(name, bname)]
                results[name + "|" + bname] = entry
                continue
            values = build_block(bname, dates=dates, vix=vix, rv=rv_f, spec=cell, marks=marks, p1=p1, p3=p3, d2=d2)
            usable = np.isfinite(y) & np.isfinite(values)
            me = early & usable
            ml = late & usable
            cand = np.column_stack([level, values])
            entry.update({"n_early": int(me.sum()), "n_late": int(ml.sum())})
            ge = S.degeneracy_report(np.where(me, y, np.nan), min_events=guard["min_events_per_half_per_class"],
                                     min_episodes=guard["min_episodes_per_half_per_class"])
            gl = S.degeneracy_report(np.where(ml, y, np.nan), min_events=guard["min_events_per_half_per_class"],
                                     min_episodes=guard["min_episodes_per_half_per_class"])
            entry["degeneracy"] = {"early": ge["verdict"], "late": gl["verdict"],
                                   "min_episodes": min(ge["min_episodes"], gl["min_episodes"])}
            if "untestable_by_construction" in (ge["verdict"], gl["verdict"]):
                entry["verdict"] = "untestable_by_construction"
                results[name + "|" + bname] = entry
                continue
            tested += 1
            n_by_class[klass] = n_by_class.get(klass, 0) + 1
            paired = PB3.paired_model_ci(pb_feat, cand, np.where(usable, y, 0.0), me, ml, R.SEED)
            entry["paired"] = paired
            ci_pass = bool(paired["ewma_beats_pb_both"])
            entry["bidirectional_ci_pass"] = ci_pass
            if ci_pass:
                rate = PB3.neg_control_increment(pb_feat, cand, np.where(usable, y, 0.0), me, ml, R.SEED, draws=NULL_DRAWS)
                entry["neg_control_pass_rate"] = rate
                adopted = bool(rate <= 0.10)
            else:
                entry["neg_control_pass_rate"] = None
                adopted = False
            entry["adopted"] = adopted
            if adopted:
                entry["verdict"] = "adopted"
                k_obs += 1
                k_by_class[klass] = k_by_class.get(klass, 0) + 1
                if entry["degeneracy"]["min_episodes"] < guard["min_episodes_per_half_per_class"]:
                    entry["verdict"] = "adopted_episode_thin"
            elif not ci_pass:
                entry["verdict"] = "measured_zero"
            else:
                entry["verdict"] = "null_leak"
            results[name + "|" + bname] = entry
            e2l, l2e = paired["early_to_late"], paired["late_to_early"]
            shown = entry["neg_control_pass_rate"] if entry["neg_control_pass_rate"] is not None else float("nan")
            print("{:11s} {:30s} {:+.5f}[{:+.5f},{:+.5f}] {:+.5f}[{:+.5f},{:+.5f}] {:6.3f} {}".format(
                name, bname, e2l["paired_mean_pb_minus_ewma"], e2l["ci90"][0], e2l["ci90"][1],
                l2e["paired_mean_pb_minus_ewma"], l2e["ci90"][0], l2e["ci90"][1], shown, entry["verdict"]), flush=True)

    family_p = S.family_p_binomial(k_obs, max(tested, 1))
    active = spec.get("hypothesis_active_cells") or {}
    active_summary = {}
    for block in spec["blocks"]:
        cells = active.get(block["id"])
        if not cells:
            continue
        sub = [results.get(c + "|" + block["id"], {}) for c in cells]
        n_sub = sum(1 for e in sub if e.get("verdict") not in (None, "excluded_preregistered", "untestable_by_construction"))
        k_sub = sum(1 for e in sub if e.get("adopted"))
        active_summary[block["id"]] = {"cells": cells, "n": n_sub, "k": k_sub,
                                       "family_p_binomial_diagnostic": S.family_p_binomial(k_sub, max(n_sub, 1))}
    payload = {
        "schema": f"v13_vol_rung{args.rung}_public",
        "prereg_commit": spec.get("prereg_commit"),
        "window": list(C.DESIGN_WINDOW),
        "split": SPLIT,
        "n_panel_design": int(design.sum()),
        "lookback_start": D.LOOKBACK_START,
        "blocks": {b["id"]: {"class": b["class"], "definition": b["definition"], "lag_sessions": b.get("lag_sessions"),
                             "pit_grade": b.get("pit_grade")} for b in spec["blocks"]},
        "excluded_cells": spec.get("excluded_cells", []),
        "tests_run": tested,
        "k_obs_adopted": k_obs,
        "family_p_binomial": family_p,
        "family_representative": spec["family"]["representative"],
        "by_class": {k: {"n": n_by_class.get(k, 0), "k": k_by_class.get(k, 0)} for k in n_by_class},
        "hypothesis_active_diagnostic": active_summary,
        "adopted": sorted(k for k, v in results.items() if v.get("adopted")),
        "cells": results,
        "holdout_read": False,
        "sealed_read": False,
        "new_data_ingested": True,
        "license_exposure": "none (US federal public domain: Fed Board, BLS, CFTC)",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    payload["content_hash"] = C.canonical_hash(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8", newline="\n")

    row = {
        "schema_version": 1,
        "experiment_label": label,
        "model": "event_probability.volatility_v13",
        "rung": spec["rung_name"],
        "window_role": "design",
        "window": list(C.DESIGN_WINDOW),
        "prereg_commit": spec.get("prereg_commit"),
        "evaluation_index": int(spec["evaluation_index"]),
        "backtest_windows_opened": 0,
        "holdout_slot_consumed": 0,
        "gate": "셀별 쌍대 Brier(PB−후보) 양방향 CI90 하한>0 ∧ 증분 y-block ≤0.10 · family binomial",
        "blocks": [b["id"] for b in spec["blocks"]],
        "tests_run": tested,
        "k_obs_adopted": k_obs,
        "family_p_binomial": family_p,
        "adopted": payload["adopted"],
        "results_sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
        "caveat": "설계창 한정·홀드아웃·봉인 미열람. 연방 공공영역 외부 적재(달력·CFTC TFF) — 라이선스 노출 0. 라이브 배치는 별도 결정.",
        "knowledge_cutoff": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    row["content_hash"] = PB3.content_hash(row)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("\n검정 {}건 · 채택 {}건 · family P(k>={}|n={}) = {:.4f} · 클래스별 {}".format(
        tested, k_obs, k_obs, tested, family_p, payload["by_class"]))
    print("채택: " + (", ".join(payload["adopted"]) if payload["adopted"] else "none"))
    print("wrote {} · 원장 행 {}…".format(out_path.relative_to(ROOT).as_posix(), row["content_hash"][:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
