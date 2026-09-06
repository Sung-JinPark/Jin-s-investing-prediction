#!/usr/bin/env python
"""tools/v12_transfer_tables.py — S3-1 결과 표 렌더 (JSON 필드만, 수기 전사 0).

등록부 reporting_contract.numbers_from_scripts_only 준수: 이 파일이 찍는 모든 수치는
``transfer_results.json`` 필드를 그대로 포맷한 것이다. 산문 해석은 붙이지 않는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULT = "data/timeseries_v12/diagnostics/transfer_results.json"


def f(v: Any, spec: str = "+.6f") -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", default=RESULT)
    ap.add_argument("--out", default="outputs/timeseries_v12/loop/_s3_1_tables.md")
    args = ap.parse_args()

    r = json.loads((ROOT / args.result).read_text(encoding="utf-8"))
    L: list[str] = []
    a = L.append

    a("# S3-1 — T1~T4 양방향 전이 + CI90 + 순열 귀무 (자동 렌더)")
    a("")
    a(f"등록부 `{r['prereg']['path']}` sha256 `{r['prereg']['sha256'][:16]}…` "
      f"(커밋 `{r['prereg']['commit'][:8]}`) · run sha256 `{r['target']['run_sha256'][:16]}…`")
    m = r["method"]
    a(f"분할 {m['split']['boundary']} → 전반 {m['split']['n']['early']} / 후반 {m['split']['n']['late']} · "
      f"격자 {m['grid']['points']}점(step {m['grid']['step']}, {m['grid']['tie_break']}) · "
      f"τ={int(m['tau_quantile'])}분위 · 블록부트 ℓ={m['bootstrap']['block']} B={m['bootstrap']['replicates']} "
      f"seed {m['bootstrap']['seed']} · 순열 {m['permutation_null']['replicates']}회")
    a("")

    a("## 1. 16 결과 (4가설 × 2지평 × 2방향 — 생략 0)")
    a("")
    a("| 가설 | h | 방향 | 학습→평가 | θ | BS(p) | BS(p′) | Δ | CI90 | MDE | A1 | A2 | 비고 |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for rec in r["records"]:
        ci = f"[{f(rec['ci90_lower'])}, {f(rec['ci90_upper'])}]"
        note = rec.get("degenerate") or ""
        if rec.get("inconclusive_by_mde"):
            note = (r"\|Δ\|<MDE 결정적 증거 없음" + (f" · {note}" if note else ""))
        if rec.get("concentration_sign_reversed"):
            note += " · 집중도 취약(부호 반전)"
        elif rec.get("concentration_sign_vanishes"):
            note += " · 집중도 취약(제거 후 Δ=0)"
        a(f"| {rec['hypothesis_id']} | {rec['horizon']} | {rec['direction']} | "
          f"{rec['fit_window'] or '—'}→{rec['eval_window']} | "
          f"{f(rec['fitted_parameter'], '.2f')} | {f(rec['brier_p'], '.6f')} | "
          f"{f(rec['brier_p_prime'], '.6f')} | {f(rec['delta'])} | {ci} | "
          f"{f(rec['mde_1645se'], '.6f')} | {'PASS' if rec['A1_pass'] else '미달'} | "
          f"{'PASS' if rec['A2_pass'] else '미달'} | {note or '—'} |")
    a("")

    a("## 2. 셀 판정 (채택 = 양방향 CI90 하한 > 0)")
    a("")
    a("| 셀 | 방향별 Δ | 방향별 CI90 하한 | A1 채택 | A2 | 결정적 증거 없음 | 부호 반전 | 제거 후 Δ=0 |")
    a("|---|---|---|---|---|---|---|---|")
    for c in r["cells"]:
        deltas = " / ".join(f(v) for v in c["delta_by_direction"].values())
        lowers = " / ".join(f(v) for v in c["ci90_lower_by_direction"].values())
        a(f"| {c['hypothesis_id']} h{c['horizon']} | {deltas} | {lowers} | "
          f"{'채택' if c['A1_cell_adopted'] else '미달'} | "
          f"{'통과' if c['A2_cell_pass'] else '미달'} | "
          f"{', '.join(c['inconclusive_by_mde']) or '—'} | "
          f"{', '.join(c['concentration_sign_reversed']) or '—'} | "
          f"{', '.join(c['concentration_sign_vanishes']) or '—'} |")
    a("")
    ad = r["adoption"]
    a(f"**k_obs = {ad['k_obs']}** · 채택 셀: {', '.join(ad['adopted_cells']) or '없음'}")
    a("")

    a("## 3. 집중도 (K-concentration) · 검정력 (K-power)")
    a("")
    a(r"| 가설 | h | 방향 | n | 터치 | 상위5%(개) | 상위5% \|d\| 비중 | 상위5개 비중 | "
      r"제거 후 Δ | 부호 | 반전 | Δ=0 | MDE/BS |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for rec in r["records"]:
        a(f"| {rec['hypothesis_id']} | {rec['horizon']} | {rec['direction']} | {rec['n_eval']} | "
          f"{rec['touches_eval']} | {rec['top5pct_origins']} | "
          f"{f(rec['top5_abs_share'], '.4f')} | {f(rec['top5count_abs_share'], '.4f')} | "
          f"{f(rec['delta_after_top5pct_drop'])} | {rec['sign_after_top5pct_drop']} | "
          f"{'예' if rec['concentration_sign_reversed'] else '아니오'} | "
          f"{'예' if rec['concentration_sign_vanishes'] else '아니오'} | "
          f"{f(rec['mde_share_of_brier'], '.4f')} |")
    a("")
    a("## 3-b. 상단집합 전이 구조 (T1·T2 맵이 평가창에서 건드리는 원점 수)")
    a("")
    a("| 지평·방향 | 학습창 τ | 학습창 상단 n | 평가창 상단 n | 평가창 n | 평가창 상단 비율 |")
    a("|---|---|---|---|---|---|")
    for key, row in r["upper_set_transfer_structure"].items():
        if key == "note":
            continue
        a(f"| {key} | {f(row['tau_from_training_window'], '.4f')} | {row['train_upper_n']}/"
          f"{row['train_n']} | {row['eval_upper_set_n']} | {row['eval_n']} | "
          f"{f(row['eval_upper_share'], '.4f')} |")
    a("")
    a(f"> {r['upper_set_transfer_structure']['note']}")
    a("")

    a("## 4. 순열 귀무 N1 (다중검정)")
    a("")
    n = r["multiplicity_null"]
    a(f"순열 {n['replicates']}회 · 내부 부트스트랩 복제 {m['permutation_null']['inner_bootstrap_replicates']} "
      f"(계산 예산 축소 사용: {'예' if m['permutation_null']['computational_fallback_used'] else '아니오'}) · "
      f"소요 {n['elapsed_sec']:.1f}s")
    a("")
    a("| k (통과 셀 수) | " + " | ".join(str(j) for j in range(9)) + " |")
    a("|---|" + "---|" * 9)
    a("| 순열 수 | " + " | ".join(str(n["k_distribution"][str(j)]) for j in range(9)) + " |")
    a("| P(k ≥ ·) | " + " | ".join(f(n["p_k_ge"][str(j)], ".4f") for j in range(9)) + " |")
    a("")
    a(f"평균 k = {n['k_mean']:.3f} · 최대 k = {n['k_max']} · "
      f"**P(k ≥ k_obs={n['k_obs']}) = {f(n['p_k_ge_kobs'], '.4f')}** · "
      f"family 주장 문턱 {n['family_claim_threshold']} → "
      f"{'충족' if n['family_claim_supported'] else '미충족'}")
    a("")
    a("귀무에서의 셀별 통과율:")
    a("")
    a("| 셀 | " + " | ".join(k for k in n["cell_pass_rate"]) + " |")
    a("|---|" + "---|" * len(n["cell_pass_rate"]))
    a("| 통과율 | " + " | ".join(f(v, ".3f") for v in n["cell_pass_rate"].values()) + " |")
    a("")

    a("## 5. T5 음성 대조")
    a("")
    t5 = r["t5_negative_control"]
    a(f"- 정의: {t5['definition']}")
    a(f"- 통과율 pooled = **{f(t5['pass_rate_pooled'], '.4f')}** · "
      f"셀별 = " + ", ".join(f"{k} {f(v, '.4f')}" for k, v in t5["pass_rate_by_cell"].items()))
    a(f"- 문턱 {t5['threshold']} · 판정 = **{'실패 (검정 기계 결함)' if t5['failed'] else '통과'}**")
    a(f"- 규칙: {t5['rule']}")
    a(f"- 해석 한계: {t5['interpretation_limit']}")
    a("")

    a("## 6. T4 풀표본 (보고 전용)")
    a("")
    a("| h | n | 단조 위반 | Δ | CI90 |")
    a("|---|---|---|---|---|")
    for key, row in r["t4_full_sample"].items():
        a(f"| {key} | {row['n']} | {row['monotonicity_violations']} | {f(row['delta'])} | "
          f"[{f(row['ci90_lower'])}, {f(row['ci90_upper'])}] |")
    a("")

    a("## 7. 판정")
    a("")
    v = r["verdict"]
    a(f"- T5 이전 채택: {', '.join(v['adopted_cells_before_T5']) or '없음'}")
    a(f"- T5 실패: {'예' if v['T5_failed'] else '아니오'}")
    a(f"- 최종 채택: {', '.join(v['adopted_cells_final']) or '없음'}")
    a(f"- S4 계약: **{v['s4_contract']}**")
    a("")
    a("## 8. Caveat (등록부 의무 + 본 태스크 관측)")
    a("")
    for c in r["caveats"]:
        a(f"- {c}")
    a("")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(L)} lines)")


if __name__ == "__main__":
    main()
