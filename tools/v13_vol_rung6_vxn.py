"""tools/v13_vol_rung6_vxn.py — rung-6: PIT VXN 교차지수 스프레드 vs PB (설계창 한정).

계약 `rung6_vxn_pit_spread` 사전등록(결과 전 커밋 f72895ba). 표적 K·θ·h 무변경.

블록: H2 = VXN_t − VIX_t (나스닥 초과 내재변동성). H1(VXN 수준)은 자동 기각 규칙으로 등록되지 않았다.
게이트: 셀별 쌍대 Brier(PB − 후보) 양방향 CI90 하한 > 0 ∧ 증분 y-block(ℓ=13) 귀무 ≤ 0.10.
family: 대표값 binomial P(k >= k_obs | n=9, p=0.05).

VXN 은 ALFRED 빈티지 PIT 계열을 쓴다 — 현재본이 아니다(2010-04-27 손상 회피).

    PYTHONUTF8=1 python tools/v13_vol_rung6_vxn.py
"""
from __future__ import annotations

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
import v13_vol_run as R  # noqa: E402
import v13_vol_rung3_pb as PB3  # noqa: E402

SPLIT = "2011-01-01"
LABEL = "V13VOL_rung6_vxn_pit"
OUT = ROOT / "data/timeseries_v13/vol/ladder_rung6_vxn.json"
LEDGER = ROOT / "data/timeseries_v13/ledgers/vol_experiments.jsonl"
EXOG = ROOT / "data/timeseries_v13/exog/vxn_vintage_observations.jsonl"
NULL_DRAWS = 120
FROZEN_RV_MEDIAN = 0.1694207105468098


def load_vxn() -> dict:
    out = {}
    for line in EXOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["observation_time"]] = float(row["value"])
    return out


def main() -> int:
    contract = C.load_contract_v13(ROOT)
    spec = contract["rung6_vxn_pit_spread"]
    if LEDGER.exists() and any(
            json.loads(line).get("experiment_label") == LABEL
            for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()):
        print(LABEL + " already in ledger — 평가 예산은 1회용이다. 재실행 거부.")
        return 2

    observations = list(read_market_observations(ROOT))
    panel = F.build_panel(observations, start=C.DESIGN_WINDOW[0], end=C.DESIGN_WINDOW[1])
    dates = [str(d) for d in panel["dates"]]
    vix, rv = panel["vix"], panel["rv21"]
    rv_f = F.fill_rv_nan(rv, FROZEN_RV_MEDIAN)

    vxn_map = load_vxn()
    vxn = np.array([vxn_map.get(d, np.nan) for d in dates])
    block = vxn - vix                       # H2 — 계약 정의 그대로
    print("VXN PIT 정합 {}/{}행 · 결측 {}".format(
        int(np.isfinite(vxn).sum()), len(dates), int(np.isnan(vxn).sum())))

    early = np.array([d < SPLIT for d in dates])
    late = ~early
    guard = contract["degeneracy_guard"]["rules"]

    results = {}
    k_obs = 0
    tested = 0
    print("{:11s} {:>28s} {:>28s} {:>6s} 판정".format(
        "셀", "e2l 쌍대[CI90]", "l2e 쌍대[CI90]", "귀무"))
    for cell in C.cell_specs():
        name = cell["name"]
        if cell["target"] == "vix_touch":
            y = F.labels_vix(vix, cell["K"], cell["h"])
            level = vix
        else:
            y = F.labels_rv(rv, cell["theta"], cell["h"])
            level = rv_f
        pb_feat = F.feature_matrix("persistence_pb", level, None)
        usable = np.isfinite(y) & np.isfinite(block)
        me = early & usable
        ml = late & usable
        cand = np.column_stack([level, block])
        entry = {"n_early": int(me.sum()), "n_late": int(ml.sum())}
        ge = S.degeneracy_report(np.where(me, y, np.nan),
                                 min_events=guard["min_events_per_half_per_class"],
                                 min_episodes=guard["min_episodes_per_half_per_class"])
        gl = S.degeneracy_report(np.where(ml, y, np.nan),
                                 min_events=guard["min_events_per_half_per_class"],
                                 min_episodes=guard["min_episodes_per_half_per_class"])
        entry["degeneracy"] = {"early": ge["verdict"], "late": gl["verdict"],
                               "min_episodes": min(ge["min_episodes"], gl["min_episodes"])}
        if "untestable_by_construction" in (ge["verdict"], gl["verdict"]):
            entry["verdict"] = "untestable_by_construction"
            results[name] = entry
            print("{:11s} {:>28s} {:>28s} {:>6s} untestable".format(name, "—", "—", "—"))
            continue
        tested += 1
        paired = PB3.paired_model_ci(pb_feat, cand, np.where(usable, y, 0.0), me, ml, R.SEED)
        entry["paired"] = paired
        ci_pass = bool(paired["ewma_beats_pb_both"])
        entry["bidirectional_ci_pass"] = ci_pass
        if ci_pass:
            rate = PB3.neg_control_increment(pb_feat, cand, np.where(usable, y, 0.0),
                                             me, ml, R.SEED, draws=NULL_DRAWS)
            entry["neg_control_pass_rate"] = rate
            adopted = bool(rate <= 0.10)
        else:
            entry["neg_control_pass_rate"] = None
            adopted = False
        entry["adopted"] = adopted
        if adopted:
            entry["verdict"] = "adopted"
        elif not ci_pass:
            entry["verdict"] = "measured_zero"
        else:
            entry["verdict"] = "null_leak"
        if adopted:
            k_obs += 1
            if entry["degeneracy"]["min_episodes"] < guard["min_episodes_per_half_per_class"]:
                entry["verdict"] = "adopted_episode_thin"
        results[name] = entry
        e2l = paired["early_to_late"]
        l2e = paired["late_to_early"]
        shown = entry["neg_control_pass_rate"]
        shown = shown if shown is not None else float("nan")
        print("{:11s} {:+.5f}[{:+.5f},{:+.5f}] {:+.5f}[{:+.5f},{:+.5f}] {:6.3f} {}".format(
            name,
            e2l["paired_mean_pb_minus_ewma"], e2l["ci90"][0], e2l["ci90"][1],
            l2e["paired_mean_pb_minus_ewma"], l2e["ci90"][0], l2e["ci90"][1],
            shown, entry["verdict"]), flush=True)

    family_p = S.family_p_binomial(k_obs, max(tested, 1))
    payload = {
        "schema": "v13_vol_rung6_vxn_pit",
        "prereg_commit": spec.get("prereg_commit"),
        "window": list(C.DESIGN_WINDOW),
        "split": SPLIT,
        "n_panel": len(dates),
        "block": {"name": "H2_vxn_vix_spread",
                  "definition": spec["blocks"]["H2_vxn_vix_spread"]["definition"],
                  "lag_sessions": spec["blocks"]["H2_vxn_vix_spread"]["lag_sessions"],
                  "finite": int(np.isfinite(block).sum())},
        "pit_source": "ALFRED vintage (earliest_available_vintage + initial_release)",
        "tests_run": tested,
        "k_obs_adopted": k_obs,
        "family_p_binomial": family_p,
        "family_representative": spec["family"]["representative"],
        "adopted": sorted(k for k, v in results.items() if v.get("adopted")),
        "cells": results,
        "holdout_read": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    payload["content_hash"] = C.canonical_hash(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8", newline="\n")

    row = {
        "schema_version": 1,
        "experiment_label": LABEL,
        "model": "event_probability.volatility_v13",
        "rung": "vxn_pit_spread_vs_pb",
        "window_role": "design",
        "window": list(C.DESIGN_WINDOW),
        "prereg_commit": spec.get("prereg_commit"),
        "evaluation_index": 6,
        "backtest_windows_opened": 0,
        "holdout_slot_consumed": 0,
        "gate": "셀별 쌍대 Brier(PB−후보) 양방향 CI90 하한>0 ∧ 증분 y-block ≤0.10 · family binomial n=9",
        "blocks": ["H2_vxn_vix_spread"],
        "tests_run": tested,
        "k_obs_adopted": k_obs,
        "family_p_binomial": family_p,
        "adopted": payload["adopted"],
        "results_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "caveat": ("설계창 한정·홀드아웃 미열람. VXN 은 ALFRED 빈티지 PIT 계열이며 "
                   "2007-2010 구간은 최초 가용 빈티지(2014-04-17)로 archive_verified 가 아니다."),
        "knowledge_cutoff": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    row["content_hash"] = PB3.content_hash(row)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("\n검정 {}건 · 채택 {}건 · family P(k>={}|n={}) = {:.4f}".format(
        tested, k_obs, k_obs, tested, family_p))
    print("채택: " + (", ".join(payload["adopted"]) if payload["adopted"] else "none"))
    print("wrote {} · 원장 행 {}…".format(OUT.relative_to(ROOT), row["content_hash"][:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
