"""tools/v13_vol_rung4_macro.py — rung-4: 봉인 아카이브 내 매크로 피처블록 vs PB (설계창 한정).

계약 `rung4_macro_blocks` 사전등록(결과 전 커밋 7a868424). 표적 K·θ·h 무변경, 적재·비용 0.

블록: F1 기간스프레드(DGS10−DGS2, PIT 실측 검증) · F2 달러(DTWEXBGS 21세션 변화율, 10세션 보수 지연)
      F3 EBP(월간, 42세션 보수 지연). 후보 = logit[PB 피처 + β·F_k], 피처당 파라미터 1개 추가.
게이트: 셀별 쌍대 Brier(PB − 후보) 양방향 CI90 하한 > 0 ∧ 증분 y-block(ℓ=13) 귀무 ≤ 0.10.
family: binomial P(k >= k_obs | n=27, p=0.05).

    PYTHONUTF8=1 python tools/v13_vol_rung4_macro.py
"""
from __future__ import annotations

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

SPLIT = "2011-01-01"
EXPERIMENT_LABEL = "V13VOL_rung4_macro"
OUT = ROOT / "data/timeseries_v13/vol/ladder_rung4_macro.json"
LEDGER = ROOT / "data/timeseries_v13/ledgers/vol_experiments.jsonl"
NULL_DRAWS = 120


def _series_by_date(observations, series_id: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for obs in observations:
        row = obs.model_dump(mode="json") if hasattr(obs, "model_dump") else obs
        if row["series_id"] == series_id:
            out[str(row["observation_time"])[:10]] = float(row["value"])
    return out


def _align(dates, values: dict[str, float], *, lag_sessions: int) -> np.ndarray:
    """패널 날짜에 맞춰 '해당 일자 이하의 마지막 관측'을 채우고, 지연 세션만큼 뒤로 민다.

    지연은 발행 지체를 덮는 보수적 장치다 — 지연 후 값이 없으면 NaN 으로 두고 해당 원점을 제외한다.
    """
    keys = sorted(values)
    aligned = np.full(len(dates), np.nan)
    j = 0
    last = np.nan
    for i, d in enumerate(dates):
        while j < len(keys) and keys[j] <= str(d):
            last = values[keys[j]]
            j += 1
        aligned[i] = last
    if lag_sessions:
        shifted = np.full(len(dates), np.nan)
        shifted[lag_sessions:] = aligned[:-lag_sessions]
        aligned = shifted
    return aligned


def build_blocks(observations, dates) -> dict[str, dict]:
    dgs2 = _series_by_date(observations, "DGS2")
    dgs10 = _series_by_date(observations, "DGS10")
    dollar = _series_by_date(observations, "DTWEXBGS")
    ebp = _series_by_date(observations, "FED_EBP")

    spread_by_date = {d: dgs10[d] - dgs2[d] for d in dgs10 if d in dgs2}
    f1 = _align(dates, spread_by_date, lag_sessions=0)

    dollar_level = _align(dates, dollar, lag_sessions=10)
    f2 = np.full(len(dates), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        f2[21:] = np.log(dollar_level[21:] / dollar_level[:-21])

    f3 = _align(dates, ebp, lag_sessions=42)
    return {
        "F1_term_spread": {"values": f1, "pit_grade": "archive_verified", "lag_sessions": 0},
        "F2_dollar": {"values": f2, "pit_grade": "assumed_lag", "lag_sessions": 10},
        "F3_ebp": {"values": f3, "pit_grade": "assumed_lag", "lag_sessions": 42},
    }


def main() -> int:
    contract = C.load_contract_v13(ROOT)
    spec_block = contract["rung4_macro_blocks"]
    if LEDGER.exists() and any(
            json.loads(line).get("experiment_label") == EXPERIMENT_LABEL
            for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()):
        print(f"{EXPERIMENT_LABEL} already in ledger — evaluation budget is single-use; refusing to re-run.")
        return 2

    observations = list(read_market_observations(ROOT))
    panel = F.build_panel(observations, start=C.DESIGN_WINDOW[0], end=C.DESIGN_WINDOW[1])
    dates = [str(d) for d in panel["dates"]]
    vix, rv = panel["vix"], panel["rv21"]
    frozen_median = 0.1694207105468098
    rv_f = F.fill_rv_nan(rv, frozen_median)
    early = np.array([d < SPLIT for d in dates])
    late = ~early
    blocks = build_blocks(observations, dates)
    guard = contract["degeneracy_guard"]["rules"]

    results: dict[str, dict] = {}
    k_obs = 0
    tested = 0
    print(f"{'셀':11s} {'블록':16s} {'e2l 쌍대[CI90]':>28s} {'l2e 쌍대[CI90]':>28s} {'귀무':>6s} 채택")
    for spec in C.cell_specs():
        name = spec["name"]
        if spec["target"] == "vix_touch":
            y = F.labels_vix(vix, spec["K"], spec["h"]); level = vix
        else:
            y = F.labels_rv(rv, spec["theta"], spec["h"]); level = rv_f
        pb_feat = F.feature_matrix("persistence_pb", level, None)
        for block_name, block in blocks.items():
            values = block["values"]
            usable = np.isfinite(y) & np.isfinite(values)
            me, ml = early & usable, late & usable
            cand = np.column_stack([level, values])
            entry: dict = {"pit_grade": block["pit_grade"], "lag_sessions": block["lag_sessions"],
                           "n_early": int(me.sum()), "n_late": int(ml.sum())}
            g_early = S.degeneracy_report(np.where(me, y, np.nan), min_events=guard["min_events_per_half_per_class"],
                                          min_episodes=guard["min_episodes_per_half_per_class"])
            g_late = S.degeneracy_report(np.where(ml, y, np.nan), min_events=guard["min_events_per_half_per_class"],
                                         min_episodes=guard["min_episodes_per_half_per_class"])
            entry["degeneracy"] = {"early": g_early["verdict"], "late": g_late["verdict"],
                                   "min_episodes": min(g_early["min_episodes"], g_late["min_episodes"])}
            if g_early["verdict"] == "untestable_by_construction" or g_late["verdict"] == "untestable_by_construction":
                entry["verdict"] = "untestable_by_construction"
                results[f"{name}|{block_name}"] = entry
                continue
            tested += 1
            paired = PB3.paired_model_ci(pb_feat, cand, np.where(usable, y, 0.0), me, ml, R.SEED)
            entry["paired"] = paired
            adopted_ci = bool(paired["ewma_beats_pb_both"])   # 후보(b)가 PB(a) 를 양방향으로 이김
            entry["bidirectional_ci_pass"] = adopted_ci
            if adopted_ci:
                null_rate = PB3.neg_control_increment(pb_feat, cand, np.where(usable, y, 0.0), me, ml,
                                                      R.SEED, draws=NULL_DRAWS)
                entry["neg_control_pass_rate"] = null_rate
                adopted = bool(null_rate <= 0.10)
            else:
                entry["neg_control_pass_rate"] = None
                adopted = False
            entry["adopted"] = adopted
            entry["verdict"] = ("adopted" if adopted else
                                ("measured_zero" if not adopted_ci else "null_leak"))
            if adopted:
                k_obs += 1
                if entry["degeneracy"]["min_episodes"] < guard["min_episodes_per_half_per_class"]:
                    entry["verdict"] = "adopted_episode_thin"
            results[f"{name}|{block_name}"] = entry
            e, l = paired["early_to_late"], paired["late_to_early"]  # noqa: E741
            print(f"{name:11s} {block_name:16s} "
                  f"{e['paired_mean_pb_minus_ewma']:+.5f}[{e['ci90'][0]:+.5f},{e['ci90'][1]:+.5f}] "
                  f"{l['paired_mean_pb_minus_ewma']:+.5f}[{l['ci90'][0]:+.5f},{l['ci90'][1]:+.5f}] "
                  f"{(entry['neg_control_pass_rate'] if entry['neg_control_pass_rate'] is not None else float('nan')):6.3f} "
                  f"{entry['verdict']}", flush=True)

    family_p = S.family_p_binomial(k_obs, max(tested, 1))
    payload = {
        "schema": "v13_vol_rung4_macro", "prereg_commit": spec_block.get("prereg_commit"),
        "window": list(C.DESIGN_WINDOW), "split": SPLIT, "n_panel": len(dates),
        "blocks": {k: {"pit_grade": v["pit_grade"], "lag_sessions": v["lag_sessions"],
                       "finite": int(np.isfinite(v["values"]).sum())} for k, v in blocks.items()},
        "tests_run": tested, "k_obs_adopted": k_obs, "family_p_binomial": family_p,
        "adopted": sorted(k for k, v in results.items() if v.get("adopted")),
        "cells": results,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    payload["content_hash"] = C.canonical_hash(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8", newline="\n")
    row = {"schema_version": 1, "experiment_label": EXPERIMENT_LABEL,
           "model": "event_probability.volatility_v13", "rung": "macro_blocks_vs_pb",
           "window_role": "design", "window": list(C.DESIGN_WINDOW),
           "prereg_commit": spec_block.get("prereg_commit"), "evaluation_index": 4,
           "backtest_windows_opened": 0,
           "gate": "셀별 쌍대 Brier(PB−후보) 양방향 CI90 하한>0 ∧ 증분 y-block ≤0.10 · family binomial",
           "blocks": payload["blocks"], "tests_run": tested, "k_obs_adopted": k_obs,
           "family_p_binomial": family_p, "adopted": payload["adopted"],
           "results_sha256": __import__("hashlib").sha256(OUT.read_bytes()).hexdigest(),
           "caveat": "설계창 한정·홀드아웃 미열람. F2·F3 는 PIT 증거 없이 보수 지연을 가정한 블록.",
           "knowledge_cutoff": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    row["content_hash"] = PB3.content_hash(row)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n검정 {tested}건 · 채택 {k_obs}건 · family P(k>={k_obs}|n={tested}) = {family_p:.4f}")
    print(f"채택: {payload['adopted'] or 'none'}")
    print(f"wrote {OUT.relative_to(ROOT)} · 원장 행 {row['content_hash'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
