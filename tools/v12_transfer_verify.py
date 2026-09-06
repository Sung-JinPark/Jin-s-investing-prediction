#!/usr/bin/env python
"""tools/v12_transfer_verify.py — S3-1 산출물 독립 재대사 (읽기 전용).

``transfer_results.json`` 이 주장하는 것을 **다른 경로로 다시 계산해** 대사한다. 특히 본 검정의
속도는 "Brier(θ) 가 θ 의 2차식" 이라는 항등식에 의존하므로, 검증기는 그 항등식을 쓰지 않고
격자 101점마다 p′ 배열을 만들어 전수 Brier 를 계산하는 무식한 방법으로 λ̂·ŵ 를 재적합한다.

검사 항목
---------
C1  전제  — V8 run·원장·봉인 해시, 등록부 sha256 이 S3-0 result 와 일치
C2  적합  — 격자 전수 재적합(2차식 미사용)으로 λ̂·ŵ 재현
C3  누락모수 — τ = 학습창 p 의 80분위, b = 학습창 터치율. 평가창 값과 다름을 명시 확인
C4  전이  — 평가창 p′ 재구성 → Δ = BS(p) − BS(p′) 항등식
C5  CI    — draws 를 새로 만들어 부트스트랩 CI90·se 재현
C6  집중도·MDE — 상위 5% 정의·부호·MDE 재계산
C7  A2    — p_reflect 대비 Δ_ref·CI 재현
C8  T4    — 단조 위반 수·p′=p 항등
C9  판정  — A1/A2 불리언, 셀 롤업, k_obs 가 레코드에서 유도됨
C10 귀무  — 순열 20회 재실행이 k_samples_head 를 재현(결정성) + T5 통과율 산식
C11 완결성 — 16 레코드·8 셀·생략 0, 홀드아웃(2015+) 미접촉
C12 전 지평 — h21·h63 만 평가, h1/h5 부재
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_first_touch_diag as ft      # noqa: E402
import v12_transfer_test as tt         # noqa: E402

RESULT = "data/timeseries_v12/diagnostics/transfer_results.json"
S3_0_RESULT = "outputs/timeseries_v12/loop/results/S3-0.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def brute_fit(p_t: np.ndarray, y_t: np.ndarray, kind: str,
              tau: float | None, b: float | None,
              pr_t: np.ndarray | None) -> tuple[float, list[float]]:
    """격자 101점 전수 재적합 — 2차식 항등식을 쓰지 않는다(검정 코드와 독립 경로)."""
    best_theta, best_bs, curve = None, None, []
    for theta in np.round(np.linspace(0.0, 1.0, 101), 2):
        if kind == "shrink":
            pp = np.array([pi - theta * (pi - b) if pi > tau else pi for pi in p_t])
        else:
            pp = np.array([(1.0 - theta) * pi + theta * ri for pi, ri in zip(p_t, pr_t)])
        bs = float(np.mean((pp - y_t) ** 2))
        curve.append(bs)
        if best_bs is None or bs < best_bs - 1e-15:      # 동점이면 갱신하지 않음 → 최소 θ
            best_bs, best_theta = bs, float(theta)
    return float(best_theta), curve


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", default=RESULT)
    ap.add_argument("--perm-recheck", type=int, default=20)
    args = ap.parse_args()

    res = json.loads((ROOT / args.result).read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []

    def add(cid: str, name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"id": cid, "name": name, "pass": bool(ok), "detail": detail})

    # ---------------------------------------------------------------- C1 전제
    seal = json.loads(subprocess.run(
        [sys.executable, str(ROOT / "tools/v12_seal_check.py")],
        capture_output=True, text=True, cwd=str(ROOT)).stdout)
    add("C1-a", "V8/V2 봉인 해시 baseline 일치", seal["sealed_match"], seal["sealed"])
    add("C1-b", "calibration 원장 해시 baseline 일치", seal["ledger_match"], seal["ledger"])

    s30 = json.loads((ROOT / S3_0_RESULT).read_text(encoding="utf-8"))
    prereg_sha = _sha256(ROOT / "data/timeseries_v12/prereg/hypotheses.json")
    add("C1-c", "등록부 sha256 이 S3-0 result 의 아티팩트 해시와 동일 (등록 후 무수정)",
        prereg_sha == s30["artifacts"]["data/timeseries_v12/prereg/hypotheses.json"]
        == res["prereg"]["sha256"], prereg_sha)

    sample = tt.build_sample()
    add("C1-d", "V8 run sha256 = 38dde7a8… (봉인 대상 무수정)",
        sample["run"]["run_sha256"] == tt.RUN_SHA256, sample["run"]["run_sha256"])
    add("C1-e", "p_reflect 가 S2-2 산출물과 바이트 동일",
        all(v["identical"] for v in sample["reflect_reconciliation"].values()),
        sample["reflect_reconciliation"])

    win = tt.split_windows(sample)
    add("C1-f", "분할 209/208 · 경계 2010-12-31",
        win["n"] == {"early": 209, "late": 208}, win["n"])

    # ---------------------------------------------------------------- 레코드 순회
    draws = {w: tt.draws_matrix(win["n"][w]) for w in tt.WINDOWS}
    fit_fail: list[str] = []
    tau_b_fail: list[str] = []
    delta_fail: list[str] = []
    ci_fail: list[str] = []
    conc_fail: list[str] = []
    a2_fail: list[str] = []
    bool_fail: list[str] = []
    tau_equals_eval: list[str] = []

    for rec in res["records"]:
        h, ev, fw = rec["horizon"], rec["eval_window"], rec["fit_window"]
        tag = f"{rec['hypothesis_id']}/h{h}/{rec['direction']}"
        p_e, y_e, pr_e = win["p"][h][ev], win["y"][h][ev], win["p_reflect"][h][ev]

        # ---- C2·C3 적합 + 누락모수
        if rec["hypothesis_id"] in ("T1", "T2"):
            p_t, y_t = win["p"][h][fw], win["y"][h][fw]
            tau = float(np.percentile(p_t, 80.0))
            b = float(np.mean(y_t))
            if not (tau == rec["tau"] and b == rec["b"]):
                tau_b_fail.append(tag)
            tau_eval = float(np.percentile(p_e, 80.0))
            if tau == tau_eval:
                tau_equals_eval.append(tag)
            lam_hat, _ = brute_fit(p_t, y_t, "shrink", tau, b, None)
            if rec["hypothesis_id"] == "T1":
                if lam_hat != rec["fitted_parameter"]:
                    fit_fail.append(f"{tag}: brute={lam_hat} json={rec['fitted_parameter']}")
            else:
                lam_e, _ = brute_fit(win["p"][h]["early"], win["y"][h]["early"], "shrink",
                                     float(np.percentile(win["p"][h]["early"], 80.0)),
                                     float(np.mean(win["y"][h]["early"])), None)
                lam_l, _ = brute_fit(win["p"][h]["late"], win["y"][h]["late"], "shrink",
                                     float(np.percentile(win["p"][h]["late"], 80.0)),
                                     float(np.mean(win["y"][h]["late"])), None)
                if min(lam_e, lam_l) != rec["fitted_parameter"]:
                    fit_fail.append(f"{tag}: brute_min={min(lam_e, lam_l)} json={rec['fitted_parameter']}")
            theta = rec["fitted_parameter"]
            pp = np.array([pi - theta * (pi - b) if pi > tau else pi for pi in p_e])
        elif rec["hypothesis_id"] == "T3":
            p_t, y_t, pr_t = win["p"][h][fw], win["y"][h][fw], win["p_reflect"][h][fw]
            w_hat, _ = brute_fit(p_t, y_t, "anchor", None, None, pr_t)
            if w_hat != rec["fitted_parameter"]:
                fit_fail.append(f"{tag}: brute={w_hat} json={rec['fitted_parameter']}")
            theta = rec["fitted_parameter"]
            pp = np.array([(1.0 - theta) * pi + theta * ri for pi, ri in zip(p_e, pr_e)])
        else:                                            # T4
            p21, p63 = win["p"][21][ev], win["p"][63][ev]
            viol = int(np.sum(p21 > p63))
            if viol != rec["monotonicity_violations"]:
                fit_fail.append(f"{tag}: viol brute={viol} json={rec['monotonicity_violations']}")
            src = p21 if h == 21 else p63
            pp = np.array([0.5 * (a + c) if a > c else s
                           for a, c, s in zip(p21, p63, src)])

        # ---- C4 Δ 항등
        bs_p = float(np.mean((p_e - y_e) ** 2))
        bs_pp = float(np.mean((pp - y_e) ** 2))
        d = (p_e - y_e) ** 2 - (pp - y_e) ** 2
        if not (abs(bs_p - rec["brier_p"]) < 1e-15 and abs(bs_pp - rec["brier_p_prime"]) < 1e-15
                and abs(float(d.mean()) - rec["delta"]) < 1e-15
                and abs((bs_p - bs_pp) - rec["delta"]) < 1e-12):
            delta_fail.append(f"{tag}: {bs_p - bs_pp:.3e} vs {rec['delta']:.3e}")

        # ---- C5 CI 재현 (draws 재생성)
        boot = d[draws[ev]].mean(axis=1)
        ci = ft.ci90([float(v) for v in boot])
        if not (abs(ci["ci90_lower"] - rec["ci90_lower"]) < 1e-15
                and abs(ci["ci90_upper"] - rec["ci90_upper"]) < 1e-15
                and abs(ci["bootstrap_se"] - rec["bootstrap_se"]) < 1e-15):
            ci_fail.append(tag)

        # ---- C6 집중도·MDE
        abs_d = np.abs(d)
        k5 = max(1, int(round(0.05 * d.size)))
        order = np.argsort(-abs_d, kind="mergesort")
        share = float(abs_d[order[:k5]].sum() / abs_d.sum()) if abs_d.sum() > 0 else None
        drop_mean = float(np.delete(d, order[:k5]).mean())
        mde = 1.6448536269514722 * rec["bootstrap_se"]
        sgn = int(np.sign(drop_mean))
        ok = (k5 == rec["top5pct_origins"]
              and (share is None or abs(share - rec["top5_abs_share"]) < 1e-12)
              and abs(drop_mean - rec["delta_after_top5pct_drop"]) < 1e-15
              and abs(mde - rec["mde_1645se"]) < 1e-15
              and rec["inconclusive_by_mde"] == bool(abs(rec["delta"]) < mde)
              and rec["sign_after_top5pct_drop"] == sgn
              and rec["concentration_fragile"] == bool(rec["delta"] != 0.0
                                                       and sgn != int(np.sign(rec["delta"])))
              and rec["concentration_sign_reversed"] == bool(rec["delta"] != 0.0
                                                             and sgn * np.sign(rec["delta"]) < 0)
              and rec["concentration_sign_vanishes"] == bool(rec["delta"] != 0.0
                                                             and drop_mean == 0.0))
        if not ok:
            conc_fail.append(tag)

        # ---- C7 A2
        d_ref = (pr_e - y_e) ** 2 - (pp - y_e) ** 2
        ci_ref = ft.ci90([float(v) for v in d_ref[draws[ev]].mean(axis=1)])
        if not (abs(float(d_ref.mean()) - rec["delta_vs_reflection"]) < 1e-15
                and abs(ci_ref["ci90_lower"] - rec["ci90_lower_vs_reflection"]) < 1e-15
                and rec["A2_pass"] == bool(ci_ref["ci90_lower"] > 0)):
            a2_fail.append(tag)

        # ---- C9 불리언
        if rec["A1_pass"] != bool(rec["ci90_lower"] > 0.0):
            bool_fail.append(tag)

    add("C2", "λ̂·ŵ 격자 전수 재적합(2차식 미사용)으로 재현", not fit_fail, fit_fail or "16/16 일치")
    add("C3-a", "τ·b 가 학습창 값과 일치", not tau_b_fail, tau_b_fail or "일치")
    add("C3-b", "학습창 τ ≠ 평가창 τ (평가창 재계산이 아님을 확인)",
        not tau_equals_eval, tau_equals_eval or "8/8 방향에서 상이")
    add("C4", "Δ = BS(p) − BS(p′) 항등 + 재구성 p′ 일치", not delta_fail, delta_fail or "16/16 일치")
    add("C5", "draws 재생성 부트스트랩 CI90·se 재현", not ci_fail, ci_fail or "16/16 일치")
    add("C6", "상위5%·MDE 재계산 일치", not conc_fail, conc_fail or "16/16 일치")
    add("C7", "A2(p_reflect 대비) 재현", not a2_fail, a2_fail or "16/16 일치")
    add("C9-a", "A1_pass = (CI90 하한 > 0)", not bool_fail, bool_fail or "16/16 일치")

    # ---------------------------------------------------------------- C8 T4
    p21f, p63f = sample["horizons"][21]["p"], sample["horizons"][63]["p"]
    viol_full = int(np.sum(p21f > p63f))
    t4_recs = [r for r in res["records"] if r["hypothesis_id"] == "T4"]
    add("C8-a", "T4 단조 위반 풀표본 0건 (S2-1 horizon_monotonicity 와 일치)",
        viol_full == 0, viol_full)
    add("C8-b", "T4 네 레코드 모두 Δ=0 (위반 0 → p′=p)",
        all(r["delta"] == 0.0 for r in t4_recs), [r["delta"] for r in t4_recs])

    # ---------------------------------------------------------------- C9 롤업·k_obs
    cells = res["cells"]
    rollup_ok = True
    for c in cells:
        rows = [r for r in res["records"]
                if r["hypothesis_id"] == c["hypothesis_id"] and r["horizon"] == c["horizon"]]
        if len(rows) != 2 or c["A1_cell_adopted"] != all(r["A1_pass"] for r in rows):
            rollup_ok = False
    add("C9-b", "셀 롤업 = 두 방향 AND", rollup_ok, len(cells))
    k_from_records = sum(1 for c in cells if c["A1_cell_adopted"])
    add("C9-c", "k_obs 가 레코드에서 유도됨",
        k_from_records == res["adoption"]["k_obs"] == res["multiplicity_null"]["k_obs"],
        k_from_records)

    # ---------------------------------------------------------------- C10 귀무 결정성
    recheck = tt.permutation_null(win, draws, count=args.perm_recheck, verbose_every=0)
    head = res["multiplicity_null"]["k_samples_head"][:args.perm_recheck]
    got = [int(v) for v in recheck["k_samples_head"][:args.perm_recheck]]
    add("C10-a", f"순열 {args.perm_recheck}회 재실행이 같은 k 열 재현 (seed 결정성)",
        head == got, {"json": head, "recheck": got})
    null = res["multiplicity_null"]
    n_perm = null["replicates"]
    t5 = res["t5_negative_control"]
    pooled = sum(null["t1_cell_pass_counts"].values()) / (2.0 * n_perm)
    add("C10-b", "T5 통과율 = T1 두 셀 A1 통과수 / (2 × 순열수)",
        abs(pooled - t5["pass_rate_pooled"]) < 1e-12,
        {"pooled": pooled, "by_cell": t5["pass_rate_by_cell"]})
    add("C10-c", "T5 판정 = 통과율 > 10% (pooled 또는 셀별)",
        t5["failed"] == bool(pooled > 0.10 or any(v > 0.10 for v in t5["pass_rate_by_cell"].values())),
        t5["failed"])
    dist = null["k_distribution"]
    add("C10-d", "k 분포 합 = 순열수", sum(dist.values()) == n_perm, sum(dist.values()))
    p_ge = sum(dist[str(j)] for j in range(int(null["k_obs"]), 9)) / n_perm
    add("C10-e", "P(k ≥ k_obs) 재계산 일치",
        abs(p_ge - null["p_k_ge_kobs"]) < 1e-12, p_ge)

    # ---------------------------------------------------------------- C11·C12 완결성
    add("C11-a", "레코드 16개 (4가설 × 2지평 × 2방향), 생략 0",
        len(res["records"]) == 16, len(res["records"]))
    add("C11-b", "셀 8개", len(cells) == 8, len(cells))
    keys = {(r["hypothesis_id"], r["horizon"], r["direction"]) for r in res["records"]}
    add("C11-c", "중복 레코드 없음", len(keys) == 16, len(keys))
    dates = sample["dates"]
    add("C11-d", "홀드아웃 무접촉 — 평가 원점 최대 날짜 ≤ 2014-12-31",
        max(dates) <= "2014-12-31", [min(dates), max(dates)])
    add("C12", "h21·h63 만 평가 (h1/h5 부재)",
        {r["horizon"] for r in res["records"]} == {21, 63},
        sorted({r["horizon"] for r in res["records"]}))

    # ---------------------------------------------------------------- C13 상단집합 구조
    us = res["upper_set_transfer_structure"]
    us_fail = []
    for rec in res["records"]:
        if rec["hypothesis_id"] != "T1":
            continue
        row = us[f"h{rec['horizon']}_{rec['direction']}"]
        p_e = win["p"][rec["horizon"]][rec["eval_window"]]
        if not (row["eval_upper_set_n"] == int(np.sum(p_e > rec["tau"]))
                == rec["eval_upper_set_n"]
                and abs(row["eval_upper_share"] - row["eval_upper_set_n"] / row["eval_n"]) < 1e-15):
            us_fail.append(f"h{rec['horizon']}_{rec['direction']}")
    add("C13", "상단집합 전이 구조가 레코드·원자료에서 재계산됨", not us_fail, us_fail or us)

    mandatory = ["hypothesis_id", "horizon", "direction", "n_eval", "touches_eval",
                 "fitted_parameter", "tau", "b", "brier_p", "brier_p_prime", "delta",
                 "ci90_lower", "ci90_upper", "bootstrap_se", "mde_1645se", "mde_share_of_brier",
                 "top5_abs_share", "sign_after_top5pct_drop", "concentration_fragile",
                 "delta_vs_reflection", "ci90_lower_vs_reflection", "A1_pass", "A2_pass"]
    missing = sorted({f"{r['hypothesis_id']}/{r['direction']}:{k}"
                      for r in res["records"] for k in mandatory if k not in r})
    add("C11-e", "등록부 mandatory_fields_per_cell 23개 전부 존재", not missing, missing or "23/23")

    failed = [c for c in checks if not c["pass"]]
    print(json.dumps({"checks": len(checks), "failed": len(failed),
                      "items": checks}, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
