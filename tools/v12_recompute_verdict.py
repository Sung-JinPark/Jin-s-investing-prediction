#!/usr/bin/env python
"""tools/v12_recompute_verdict.py — S1-1 세 동결 독립 재계산 (읽기 전용).

백테스트·홀드아웃·봉인 실행 0. 커밋된 run/ledger/diagnostic 아티팩트만 읽어 재계산한다.
쓰기는 ``--out`` 한 파일뿐(기본 ``docs/review/verdict_recompute.json``).

재계산 대상 (envelope S1-1 spec)
-------------------------------
A. **V10 GFC 인공물** — 챔피언 ``V10_W3_gamma_m010`` vs ``V10_E0_identity``
   ① 쌍대 평균·상대개선 ② GFC 원점 견인 비중 ③ 상위 5% 원점 제거 시 부호 ④ 블록부트 CI90.
B. **V11 전이 split 민감도** — 3 split(경계 ±1y) × 2 변형(P1 선형 조건부 / 저모멘텀 tertile 조건부),
   각 split 양방향(forward/reverse). 상수 recenter는 플라시보 대조로 병기.
C. **V9 쌍대 재계산** — E1~E4 vs E0, E6 vs E5(부분창 기준선) 쌍대 평균·CI90.

방법 정본 (원 구현과 동일해야 재현이 성립 — 출처는 코드 경로로 명기)
-------------------------------------------------------------------
* 쌍대 통계 = ``src/ai_fc/timeseries_v10/pipeline.py::_dual_vs_e0``
  origin별 d_i = mean_{h∈{21,63}}( crps_E0(i,h) − crps_exp(i,h) ), 양수 = 개선.
  CI90 = 정상 블록 부트스트랩(block=13 기하분포, B=2000, ``np.random.default_rng(20260902)``),
  percentile [5,95], se = std(ddof=1), mde50 = 1.645·se. RNG 호출 순서까지 그대로 복제한다.
* 상대개선 분모 = E0의 h21·h63 model_crps 전체 평균 (freeze 문서 "+0.64%" 재현용).
* GFC 국면 = ``src/ai_fc/timeseries/backtest.py`` 의 ``great_financial_crisis_2008``
  = origin date ∈ [2008-01-01, 2009-06-30]. 정의 폭 민감도로 넓은 창도 병기한다.
* V11 전이 = ``outputs/timeseries_v11/reports/CALM_SIGNAL_ADVERSARIAL_VERIFY_20260903.json`` 렌즈3 명세:
  z=Φ⁻¹(u), σ=crps/cs(z) (cs = 표준정규 CRPS), raw_err=σ·z, median 이동만 반영해 CRPS 재계산.
  cs(z) = z(2Φ(z)−1) + 2φ(z) − 1/√π.

주의: 이 스크립트는 수치를 만들 뿐 판정 문장을 만들지 않는다. 판정은 산출 JSON을 읽고 사람이 쓴다.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

LONG_HORIZONS = (21, 63)
GFC_CANONICAL = ("2008-01-01", "2009-06-30")   # backtest.py 정본
GFC_WIDE = ("2007-07-01", "2009-12-31")        # 정의 폭 민감도용(정본 아님)

DUAL_BLOCK = 13
DUAL_REPLICATES = 2000
DUAL_SEED = 20260902

_NORM = statistics.NormalDist()
_INV_SQRT_PI = 1.0 / math.sqrt(math.pi)


# --------------------------------------------------------------------------- 공통

def _load_run(track: str, experiment_id: str) -> dict[str, Any]:
    path = ROOT / f"data/timeseries_{track}/runs/dev_{experiment_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _ledger(track: str) -> list[dict[str, Any]]:
    path = ROOT / f"data/timeseries_{track}/ledgers/development_experiments.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _experiment_id(track: str, label: str) -> str:
    for row in _ledger(track):
        if row.get("experiment_label") == label:
            return str(row["experiment_id"])
    raise KeyError(f"{track}: experiment_label {label!r} not in ledger")


def _crps_map(run: dict[str, Any]) -> dict[tuple[str, int], float]:
    return {(s["date"], int(s["horizon"])): float(s["model_crps"]) for s in run["scores"]}


def per_origin_delta(base_run: dict[str, Any], exp_run: dict[str, Any]) -> tuple[list[str], np.ndarray]:
    """origin별 d_i = mean_h( base_crps − exp_crps ). 양수 = exp 개선. _dual_vs_e0 와 동일."""
    base = _crps_map(base_run)
    by_origin: dict[str, list[float]] = {}
    for score in exp_run["scores"]:
        horizon = int(score["horizon"])
        key = (score["date"], horizon)
        if horizon in LONG_HORIZONS and key in base:
            by_origin.setdefault(score["date"], []).append(base[key] - float(score["model_crps"]))
    origins = sorted(by_origin)
    return origins, np.array([float(np.mean(by_origin[o])) for o in origins])


def dual_ci90(per_origin: np.ndarray, *, seed: int = DUAL_SEED, block: int = DUAL_BLOCK,
              replicates: int = DUAL_REPLICATES) -> dict[str, float]:
    """pipeline.py::_dual_vs_e0 의 부트스트랩을 호출 순서까지 그대로 복제(비트 동일 목표)."""
    rng = np.random.default_rng(seed)
    n = len(per_origin)
    draws = []
    for _ in range(replicates):
        picks: list[float] = []
        while len(picks) < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(1.0 / block))
            picks.extend(per_origin[(start + np.arange(length)) % n])
        draws.append(float(np.mean(picks[:n])))
    lower, upper = np.percentile(draws, [5, 95])
    se = float(np.std(draws, ddof=1))
    return {"ci90_lower": float(lower), "ci90_upper": float(upper),
            "bootstrap_se": se, "mde50": 1.645 * se}


def mean_long_crps(run: dict[str, Any]) -> float:
    """h21·h63 model_crps 전체 평균 — 상대개선의 분모."""
    values = [float(s["model_crps"]) for s in run["scores"] if int(s["horizon"]) in LONG_HORIZONS]
    return float(np.mean(values))


# --------------------------------------------------------------------------- A. V10

def _share_in_window(origins: Sequence[str], deltas: np.ndarray,
                     window: tuple[str, str]) -> dict[str, Any]:
    start, end = window
    mask = np.array([start <= o <= end for o in origins])
    total = float(deltas.sum())
    inside = float(deltas[mask].sum())
    return {
        "window": [start, end],
        "origins_in_window": int(mask.sum()),
        "origin_share": float(mask.mean()),
        "delta_sum_in_window": inside,
        "delta_sum_total": total,
        "delta_share": (inside / total) if total else None,
        "mean_excluding_window": float(deltas[~mask].mean()) if (~mask).any() else None,
    }


def recompute_v10() -> dict[str, Any]:
    e0 = _load_run("v10", _experiment_id("v10", "V10_E0_identity"))
    champ_label = "V10_W3_gamma_m010"
    champ = _load_run("v10", _experiment_id("v10", champ_label))

    origins, deltas = per_origin_delta(e0, champ)
    n = len(origins)
    mean_delta = float(deltas.mean())
    denom = mean_long_crps(e0)
    ci = dual_ci90(deltas)

    # 상위 5% 원점 제거 — 이득 집중도(freeze 문서 L3: 21개 제거 시 부호 반전 주장)
    drop = math.ceil(0.05 * n)
    keep = np.sort(np.argsort(deltas)[: n - drop])
    trimmed = deltas[keep]
    ci_trimmed = dual_ci90(trimmed)

    top_sum = float(deltas[np.argsort(deltas)[n - drop:]].sum())

    return {
        "champion_label": champ_label,
        "baseline_label": "V10_E0_identity",
        "origin_count": n,
        "paired_mean_delta": mean_delta,
        "e0_mean_long_crps": denom,
        "relative_improvement": mean_delta / denom,
        "ci90": [ci["ci90_lower"], ci["ci90_upper"]],
        "bootstrap_se": ci["bootstrap_se"],
        "mde50": ci["mde50"],
        "gfc_canonical": _share_in_window(origins, deltas, GFC_CANONICAL),
        "gfc_wide_sensitivity": _share_in_window(origins, deltas, GFC_WIDE),
        "top5pct_removal": {
            "origins_dropped": drop,
            "top5pct_delta_sum": top_sum,
            "top5pct_share_of_net": (top_sum / float(deltas.sum())) if deltas.sum() else None,
            "mean_after_removal": float(trimmed.mean()),
            "sign_after_removal": "negative" if trimmed.mean() < 0 else "positive",
            "relative_after_removal": float(trimmed.mean()) / denom,
            "ci90_after_removal": [ci_trimmed["ci90_lower"], ci_trimmed["ci90_upper"]],
        },
        "ledger_recorded_dual_vs_e0": next(
            (r.get("dual_vs_e0") for r in _ledger("v10")
             if r.get("experiment_label") == champ_label), None,
        ),
    }


# --------------------------------------------------------------------------- B. V11

def _norm_crps_unit(z: float) -> float:
    """표준정규 예측분포의 CRPS(σ=1): z(2Φ(z)−1) + 2φ(z) − 1/√π."""
    return z * (2.0 * _NORM.cdf(z) - 1.0) + 2.0 * _NORM.pdf(z) - _INV_SQRT_PI


def _load_v11_frame(horizon: int) -> dict[str, list]:
    path = ROOT / "data/timeseries_v11/diagnostics/aligned_origin_frame.json"
    frame = json.loads(path.read_text(encoding="utf-8"))
    return frame["horizons"][str(horizon)]


def _v11_calm_rows(horizon: int, calm_pct: float = 80.0) -> list[dict[str, float | str]]:
    """calm(primary ≤ p80) origin만 남기고 σ·raw_err 를 역산 (렌즈3 재구성 절차)."""
    frame = _load_v11_frame(horizon)
    primary = np.array(frame["primary"], dtype=float)
    threshold = float(np.percentile(primary, calm_pct))
    rows: list[dict[str, float | str]] = []
    for i, date in enumerate(frame["date"]):
        if primary[i] > threshold:
            continue
        u = min(max(float(frame["u"][i]), 1e-6), 1.0 - 1e-6)
        z = _NORM.inv_cdf(u)
        crps = float(frame["crps"][i])
        sigma = crps / _norm_crps_unit(z)
        rows.append({
            "date": date, "z": z, "sigma": sigma, "crps": crps,
            "raw_err": sigma * z, "p1": float(frame["P1_ret_mom_21"][i]),
        })
    return rows


def _ols(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """절편 포함 단순 OLS → (a, b). 분산 0이면 (mean(y), 0)."""
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    var = float(((xa - xa.mean()) ** 2).sum())
    if var <= 0:
        return float(ya.mean()), 0.0
    b = float(((xa - xa.mean()) * (ya - ya.mean())).sum() / var)
    return float(ya.mean() - b * xa.mean()), b


def _crps_after_shift(rows: Iterable[dict], shifts: Sequence[float]) -> float:
    """median 이동만 반영한 CRPS 평균. σ 불변, z' = (raw_err − shift)/σ."""
    total = [
        row["sigma"] * _norm_crps_unit((row["raw_err"] - shift) / row["sigma"])
        for row, shift in zip(rows, shifts)
    ]
    return float(np.mean(total))


def _transfer_once(train: list[dict], test: list[dict], variant: str) -> dict[str, Any]:
    base = float(np.mean([r["crps"] for r in test]))
    a, b = _ols([r["p1"] for r in train], [r["raw_err"] for r in train])

    if variant == "p1_linear":                         # 변형1 — 렌즈3 명세 그대로
        shifts = [a + b * r["p1"] for r in test]
    elif variant == "low_mom_tertile":                 # 변형2 — 저모멘텀 tertile 조건부 상수 이동
        cut = float(np.percentile([r["p1"] for r in train], 100.0 / 3.0))
        low = [r["raw_err"] for r in train if r["p1"] <= cut]
        shift = float(np.mean(low)) if low else 0.0
        shifts = [shift if r["p1"] <= cut else 0.0 for r in test]
    elif variant == "constant_placebo":                # 플라시보 — 절편만
        shifts = [a for _ in test]
    else:
        raise ValueError(variant)

    after = _crps_after_shift(test, shifts)
    corr = (float(np.corrcoef([r["p1"] for r in train], [r["raw_err"] for r in train])[0, 1])
            if len(train) > 2 else None)
    return {
        "variant": variant,
        "train_n": len(train), "test_n": len(test),
        "fit_intercept": a, "fit_slope": b, "train_corr_p1_rawerr": corr,
        "crps_base": base, "crps_after": after,
        "crps_delta": after - base,
        "crps_relative_change": (after - base) / base if base else None,
        # 양수 = 악화. 전이 성공은 음수(개선)여야 한다.
        "improved": after < base,
    }


def recompute_v11(horizons: Sequence[int] = (21, 63),
                  boundaries: Sequence[str] = ("2009-12-31", "2010-12-31", "2011-12-31"),
                  variants: Sequence[str] = ("p1_linear", "low_mom_tertile", "constant_placebo"),
                  ) -> dict[str, Any]:
    """3 split(경계 ±1y) × 변형 × 양방향 전이. 경계 중앙값이 캠페인 정본(2007-10 / 2011-14)."""
    out: dict[str, Any] = {"boundaries": list(boundaries), "results": []}
    for horizon in horizons:
        rows = _v11_calm_rows(horizon)
        for boundary in boundaries:
            first = [r for r in rows if r["date"] <= boundary]
            second = [r for r in rows if r["date"] > boundary]
            if min(len(first), len(second)) < 30:
                out["results"].append({"horizon": horizon, "boundary": boundary,
                                       "skipped": "sub-window < 30 origins"})
                continue
            for variant in variants:
                for direction, (train, test) in (("forward", (first, second)),
                                                 ("reverse", (second, first))):
                    record = _transfer_once(train, test, variant)
                    record.update({"horizon": horizon, "boundary": boundary,
                                   "direction": direction})
                    out["results"].append(record)

    canonical = [r for r in out["results"]
                 if r.get("variant") in ("p1_linear", "low_mom_tertile") and "improved" in r]
    out["summary"] = {
        "cells": len(canonical),
        "cells_improved": sum(1 for r in canonical if r["improved"]),
        "both_directions_improved": [
            {"horizon": h, "boundary": bd, "variant": v}
            for h in horizons for bd in boundaries for v in ("p1_linear", "low_mom_tertile")
            if all(r["improved"] for r in canonical
                   if r["horizon"] == h and r["boundary"] == bd and r["variant"] == v)
            and any(r["horizon"] == h and r["boundary"] == bd and r["variant"] == v
                    for r in canonical)
        ],
    }
    return out


# --------------------------------------------------------------------------- C. V9

V9_PAIRS = [
    ("V9_E1_m2sl_liquidity", "V9_E0_identity_no_new_features"),
    ("V9_E2_totci_credit", "V9_E0_identity_no_new_features"),
    ("V9_E3_totll_credit", "V9_E0_identity_no_new_features"),
    ("V9_E4_wrmfns_mmf", "V9_E0_identity_no_new_features"),
    ("V9_E6_vxn_vix_spread", "V9_E5_subwindow_baseline"),   # 260원점 부분창 — E0와 창이 다름
]


def recompute_v9() -> dict[str, Any]:
    runs: dict[str, dict[str, Any]] = {}

    def run_for(label: str) -> dict[str, Any]:
        if label not in runs:
            runs[label] = _load_run("v9", _experiment_id("v9", label))
        return runs[label]

    rows = []
    for exp_label, base_label in V9_PAIRS:
        base, exp = run_for(base_label), run_for(exp_label)
        origins, deltas = per_origin_delta(base, exp)
        ci = dual_ci90(deltas)
        denom = mean_long_crps(base)
        rows.append({
            "experiment": exp_label, "baseline": base_label,
            "origin_count": len(origins),
            "paired_mean_delta": float(deltas.mean()),
            "abs_mean_delta": abs(float(deltas.mean())),
            "relative_improvement": float(deltas.mean()) / denom,
            "ci90": [ci["ci90_lower"], ci["ci90_upper"]],
            "bootstrap_se": ci["bootstrap_se"],
            "ci90_excludes_zero": ci["ci90_lower"] > 0 or ci["ci90_upper"] < 0,
        })
    return {
        "pairs": rows,
        "max_abs_mean_delta": max(r["abs_mean_delta"] for r in rows),
        "pairs_with_ci90_excluding_zero": [r["experiment"] for r in rows if r["ci90_excludes_zero"]],
    }


# --------------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description="S1-1 세 동결 독립 재계산 (읽기 전용)")
    parser.add_argument("--out", default="docs/review/verdict_recompute.json")
    parser.add_argument("--tracks", default="v10,v11,v9")
    args = parser.parse_args()

    wanted = {t.strip() for t in args.tracks.split(",") if t.strip()}
    payload: dict[str, Any] = {
        "schema": "v12_verdict_recompute_v1",
        "task": "S1-1",
        "read_only": True,
        "sources": {
            "v10": "data/timeseries_v10/{runs,ledgers}",
            "v11": "data/timeseries_v11/diagnostics/aligned_origin_frame.json",
            "v9": "data/timeseries_v9/{runs,ledgers}",
        },
        "method_refs": {
            "paired_statistic": "src/ai_fc/timeseries_v10/pipeline.py::_dual_vs_e0",
            "gfc_regime": "src/ai_fc/timeseries/backtest.py (great_financial_crisis_2008)",
            "v11_transfer": "outputs/timeseries_v11/reports/CALM_SIGNAL_ADVERSARIAL_VERIFY_20260903.json lens3",
        },
    }
    if "v10" in wanted:
        payload["v10"] = recompute_v10()
    if "v11" in wanted:
        payload["v11"] = recompute_v11()
    if "v9" in wanted:
        payload["v9"] = recompute_v9()

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    for track in ("v10", "v11", "v9"):
        if track in payload:
            print(f"  {track}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
