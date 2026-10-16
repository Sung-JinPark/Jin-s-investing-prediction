"""tools/v13_ta_null_repair.py — T-A 검정 기계 수리: 블록 보존 대안 귀무 3종.

정본 사전등록: docs/design/v13_next_design_prereg_260907.md §1.
0 백테스트 — S3 원장(first_touch p/y)의 재분석. 기존 S3 기계(tools/v12_transfer_test.py)를 그대로
재사용하고 귀무 생성기만 교체한다. N1(창내 i.i.d. p 순열)이 파괴하는 지역 자기상관 구조를
블록(ℓ=13)으로 보존하는 3종:
  N-p-block : p 블록 순열(y 고정)          — N1 의 블록판(구조 보존)
  N-y-block : y 블록 순열(p 고정)          — 맵이 진짜 p→y 관계를 쓰는지
  N-blk-pair: (p,y) 쌍 블록 순열(동시)      — 시간 구조 파괴 하 우연 통과율
수리 판정 = 세 귀무 모두 T1 pooled 통과율 ≤ 0.10. 하나라도 초과 → 미수리 → 재개 금지.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import v12_transfer_test as S3  # noqa: E402  (build_sample/split_windows/evaluate_family/count_adopted 재사용)

BLOCK = 13
THRESHOLD = 0.10
SEED_BASE = 730000


def _block_perm_index(n: int, rng: np.random.Generator, block: int = BLOCK) -> np.ndarray:
    """길이 n 을 연속 블록(ℓ)으로 나눠 블록 순서를 순열한 뒤 이어붙여 n 으로 자른다."""
    starts = list(range(0, n, block))
    order = rng.permutation(len(starts))
    idx: list[int] = []
    for k in order:
        s = starts[k]
        idx.extend(range(s, min(s + block, n)))
    return np.asarray(idx[:n], dtype=int)


def _run_null(win, draws, *, kind: str, count: int, verbose_every: int = 0) -> dict:
    FOCUS, HYP, WIN = S3.FOCUS, S3.HYPOTHESES, S3.WINDOWS
    t1_cell_pass = {f"h{h}": 0 for h in FOCUS}
    cell_pass = {f"{hyp}_h{h}": 0 for hyp in HYP for h in FOCUS}
    k_counts: list[int] = []
    t0 = time.time()
    for i in range(count):
        rng = np.random.default_rng(SEED_BASE + i)
        if kind == "N-p-block":
            pw = {h: {w: win["p"][h][w][_block_perm_index(win["p"][h][w].size, rng)] for w in WIN}
                  for h in FOCUS}
            yw = win["y"]
        elif kind == "N-y-block":
            pw = win["p"]
            yw = {h: {w: win["y"][h][w][_block_perm_index(win["y"][h][w].size, rng)] for w in WIN}
                  for h in FOCUS}
        elif kind == "N-blk-pair":
            pw = {h: {} for h in FOCUS}; yw = {h: {} for h in FOCUS}
            for h in FOCUS:
                for w in WIN:
                    idx = _block_perm_index(win["p"][h][w].size, rng)
                    pw[h][w] = win["p"][h][w][idx]; yw[h][w] = win["y"][h][w][idx]
        else:
            raise ValueError(kind)
        recs = S3.evaluate_family(pw, yw, win["p_reflect"], draws, detail=False)
        k, per_cell = S3.count_adopted(recs)
        k_counts.append(k)
        for key, val in per_cell.items():
            if val:
                cell_pass[key] += 1
        for h in FOCUS:
            if per_cell[f"T1_h{h}"]:
                t1_cell_pass[f"h{h}"] += 1
        if verbose_every and (i + 1) % verbose_every == 0:
            el = time.time() - t0
            print(f"    {kind} {i+1}/{count} el={el:.0f}s proj={el/(i+1)*count:.0f}s "
                  f"t1_pool={sum(t1_cell_pass.values())/(2.0*(i+1)):.3f}", flush=True)
    arr = np.asarray(k_counts)
    return {
        "kind": kind, "replicates": count, "elapsed_sec": round(time.time() - t0, 1),
        "t1_cell_pass_counts": t1_cell_pass,
        "t1_pass_rate_pooled": sum(t1_cell_pass.values()) / (2.0 * count),
        "t1_pass_rate_by_cell": {k: v / count for k, v in t1_cell_pass.items()},
        "cell_pass_rate": {k: v / count for k, v in cell_pass.items()},
        "k_mean": float(arr.mean()), "k_max": int(arr.max()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--out", default="data/timeseries_v13/prereg/ta_null_repair.json")
    args = ap.parse_args()
    sample = S3.build_sample()
    win = S3.split_windows(sample)
    draws = {w: S3.draws_matrix(win["n"][w]) for w in S3.WINDOWS}
    results = {}
    for kind in ("N-p-block", "N-y-block", "N-blk-pair"):
        print(f"== {kind} (count={args.count}) ==", flush=True)
        results[kind] = _run_null(win, draws, kind=kind, count=args.count,
                                  verbose_every=max(1, args.count // 5))
        print(f"   -> T1 pooled pass rate = {results[kind]['t1_pass_rate_pooled']:.4f}", flush=True)
    rates = {k: v["t1_pass_rate_pooled"] for k, v in results.items()}
    repaired = all(r <= THRESHOLD for r in rates.values())
    out = {
        "schema": "v13_ta_null_repair", "prereg": "docs/design/v13_next_design_prereg_260907.md §1",
        "block": BLOCK, "threshold": THRESHOLD, "count": args.count,
        "n1_baseline_t5_pooled": 0.254,
        "nulls": results, "t1_pooled_pass_rates": rates,
        "repaired": repaired,
        "verdict": ("REPAIRED — 세 블록 귀무 모두 통과율 ≤ 0.10" if repaired
                    else "NOT_REPAIRED — 하나 이상 초과, 재개 금지"),
    }
    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"\nVERDICT: {out['verdict']}")
    print(f"rates: {json.dumps(rates)}  wrote {args.out}")


if __name__ == "__main__":
    main()
