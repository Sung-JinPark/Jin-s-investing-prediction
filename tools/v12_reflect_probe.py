#!/usr/bin/env python
"""tools/v12_reflect_probe.py — S2-2 준비 탐색 (읽기 전용, stdout 만).

반사원리 기준선 p_reflect = 2Φ(−ln(S/K)/(σ√T)) 를 계산하려면 원점별 σ(EWMA λ=.97)가 필요하고,
그 σ 는 V8 이 실제로 본 학습 수익률(endog[:, 0] = nasdaq_return)에서 나와야 한다.

여기서 확인하는 것 하나뿐: **커밋된 features_C1.parquet 의 nasdaq_return 열이 V8 run 의
endog[:, 0] 과 동일한가**. 판정은 재구성 대사 — 각 원점에서
  actual_log_return(h) == sum(r[i+1 : i+1+h])
  first_touch_actual(h) == (min(exp(cumsum(r[i+1 : i+1+h]))) <= 0.90)
가 417×4 전부 일치하면 동일 계열로 확정한다. 불일치가 있으면 S2-2 는 차단.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/timeseries_v8/runs/dev_tsv8-exp-61cee7b7fb7c41399534.json"
HORIZONS = (1, 5, 21, 63)


def main() -> None:
    import pandas as pd

    for cand in ("C1", "C2", "C3"):
        path = ROOT / f"data/timeseries_v2/parquet/features_{cand}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        print(f"== {cand}: rows={len(frame)} cols={list(frame.columns)[:8]}")
        print(f"   index {frame.index[0]} .. {frame.index[-1]}")

    frame = pd.read_parquet(ROOT / "data/timeseries_v2/parquet/features_C1.parquet")
    dates = [d.date().isoformat() for d in frame.index]
    ret = frame["nasdaq_return"].to_numpy(dtype=float)
    pos = {d: i for i, d in enumerate(dates)}

    run = json.loads(RUN.read_text(encoding="utf-8"))
    rows = run["scores"]
    mism_ret = mism_touch = missing = 0
    worst = 0.0
    for s in rows:
        i = pos.get(str(s["date"]))
        if i is None:
            missing += 1
            continue
        h = int(s["horizon"])
        seg = ret[i + 1: i + 1 + h]
        if seg.size != h:
            missing += 1
            continue
        diff = abs(float(seg.sum()) - float(s["actual_log_return"]))
        worst = max(worst, diff)
        if diff > 1e-12:
            mism_ret += 1
        touch = bool(np.min(np.exp(np.cumsum(seg))) <= 0.90)
        if touch != bool(s["first_touch_actual"]):
            mism_touch += 1
    print(f"\n== 재구성 대사: rows={len(rows)} missing={missing} "
          f"ret_mismatch={mism_ret} touch_mismatch={mism_touch} max|Δ|={worst:.3e}")

    # 원점 인덱스 분포(주간 원점 간격) · 학습 길이 확인
    origin_dates = sorted({str(s["date"]) for s in rows})
    idxs = [pos[d] for d in origin_dates if d in pos]
    gaps = np.diff(idxs)
    print(f"   origins={len(idxs)} first_idx={idxs[0]} last_idx={idxs[-1]} "
          f"gap min/med/max={gaps.min()}/{np.median(gaps)}/{gaps.max()} series_len={len(ret)}")


if __name__ == "__main__":
    main()
