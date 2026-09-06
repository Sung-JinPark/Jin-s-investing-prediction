#!/usr/bin/env python
"""tools/v12_probe_align.py — S1-3 사전 정합 확인 (읽기 전용, 산출 없음).

트랙 간 origin 축이 실제로 겹치는지, V10 축별 실험이 h21/h63 스코어를 갖는지만 확인한다.
쓰기 0 — stdout 만. 판정·수치 인용은 본 스크립트가 아니라 v12_lowcost_options.py 산출물에서 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ledger(track: str) -> list[dict]:
    path = ROOT / f"data/timeseries_{track}/ledgers/development_experiments.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def run(track: str, exp_id: str) -> dict:
    return json.loads((ROOT / f"data/timeseries_{track}/runs/dev_{exp_id}.json").read_text(encoding="utf-8"))


def summarize(track: str) -> dict[str, dict]:
    out = {}
    for row in ledger(track):
        label = row["experiment_label"]
        r = run(track, row["experiment_id"])
        horizons = sorted({int(s["horizon"]) for s in r["scores"]})
        dates_long = sorted({s["date"] for s in r["scores"] if int(s["horizon"]) in (21, 63)})
        out[label] = {
            "horizons": horizons,
            "n_long_origins": len(dates_long),
            "first": dates_long[0] if dates_long else None,
            "last": dates_long[-1] if dates_long else None,
            "degenerate": row.get("degenerate"),
            "config_keys_nonnull": sorted(k for k, v in (row.get("config") or {}).items() if v not in (None, 0.0)),
        }
    return out


def main() -> None:
    v10 = summarize("v10")
    v9 = summarize("v9")
    print("=== V10 ===")
    for label, info in v10.items():
        print(f"{label:32s} h={info['horizons']} n={info['n_long_origins']:4d} "
              f"[{info['first']}..{info['last']}] degen={info['degenerate']}")
    print("\n=== V9 ===")
    for label, info in v9.items():
        print(f"{label:36s} h={info['horizons']} n={info['n_long_origins']:4d} "
              f"[{info['first']}..{info['last']}] degen={info['degenerate']}")

    e10 = run("v10", next(r["experiment_id"] for r in ledger("v10") if r["experiment_label"] == "V10_E0_identity"))
    e9 = run("v9", next(r["experiment_id"] for r in ledger("v9")
                        if r["experiment_label"] == "V9_E0_identity_no_new_features"))
    d10 = {s["date"] for s in e10["scores"] if int(s["horizon"]) in (21, 63)}
    d9 = {s["date"] for s in e9["scores"] if int(s["horizon"]) in (21, 63)}
    print(f"\nV10 origins={len(d10)}  V9 origins={len(d9)}  교집합={len(d10 & d9)}  "
          f"V10-only={len(d10 - d9)}  V9-only={len(d9 - d10)}")

    frame = json.loads((ROOT / "data/timeseries_v11/diagnostics/aligned_origin_frame.json")
                       .read_text(encoding="utf-8"))
    print("v11 frame keys:", sorted(frame.keys()))
    for h in ("21", "63"):
        f = frame["horizons"][h]
        print(f"  h{h}: cols={sorted(f.keys())} n={len(f['date'])} "
              f"[{min(f['date'])}..{max(f['date'])}] ∩V10={len(set(f['date']) & d10)}")

    # V10 축별 config 차이 확인 (조합 격자의 '축' 정의 근거)
    print("\n=== V10 config (E0 대비 차이 나는 키) ===")
    base_cfg = next(r["config"] for r in ledger("v10") if r["experiment_label"] == "V10_E0_identity")
    for row in ledger("v10"):
        if row["experiment_label"] == "V10_E0_identity":
            continue
        diff = {k: (base_cfg.get(k), v) for k, v in row["config"].items() if base_cfg.get(k) != v}
        print(f"{row['experiment_label']:32s} {diff}")


if __name__ == "__main__":
    main()
