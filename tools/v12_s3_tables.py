#!/usr/bin/env python
"""tools/v12_s3_tables.py — S3 판정서(docs/design/v12_s3_verdict.md)의 표 렌더 (읽기 전용).

s3_verdict.json 필드만 읽어 마크다운 표를 표준출력으로 낸다. 판정서에 붙는 모든 표 행은
이 출력의 복사본이어야 하며 `tools/v12_s3_doc_check.py` 가 바이트 일치를 대사한다.
파일을 쓰지 않는다.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V = "data/timeseries_v12/diagnostics/s3_verdict.json"

DIRLABEL = {
    "early_to_late": "전→후",
    "late_to_early": "후→전",
    "early_window": "전반창",
    "late_window": "후반창",
}
WINLABEL = {"early": "전반", "late": "후반"}


def f6(x: float) -> str:
    return f"{x:+.6f}"


def pct(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def yn(b: bool) -> str:
    return "채택" if b else "미달"


def main() -> int:
    v = json.loads((ROOT / V).read_text(encoding="utf-8"))
    cells, dirs = v["cells"], v["directions"]

    # ---------------------------------------------------------------- 표 A 셀 판정
    print("### 표 A — 셀 판정 (채택 = 양방향 CI90 하한 > 0)\n")
    print("| 셀 | 지평 | 방향별 Δ | 방향별 CI90 하한 | 구속 방향 | 미달 양상 | A1 | A2 | 귀무 통과율 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        d0, d1 = c["directions"]
        deltas = f"{f6(c['delta_by_direction'][d0])} / {f6(c['delta_by_direction'][d1])}"
        lowers = f"{f6(c['ci90_lower_by_direction'][d0])} / {f6(c['ci90_lower_by_direction'][d1])}"
        print(f"| {c['hypothesis_id']} | h{c['horizon']} | {deltas} | {lowers} | "
              f"{DIRLABEL[c['binding_direction']]} | {c['binding_failure_mode']} | "
              f"{yn(c['A1_derived'])} | {yn(c['A2_derived'])} | {c['null_cell_pass_rate']:.3f} |")
    print()
    print(f"**k_obs = {v['verdict']['k_obs']}** · 채택 셀: "
          f"{'없음' if not v['verdict']['adopted_cells'] else ', '.join(v['verdict']['adopted_cells'])} "
          f"· A2 통과 셀: {'없음' if not v['verdict']['A2_cells'] else ', '.join(v['verdict']['A2_cells'])}")
    print()

    # ---------------------------------------------------------------- 표 B 방향 16
    print("### 표 B — 16 방향 전수 (생략 0 · 등록부 no_cell_dropping)\n")
    print("| 가설 | h | 방향 | 학습→평가 | n / 터치 | θ | BS(p) | BS(p′) | Δ | CI90 하한 | MDE | 하한 부족분(%BS) | A1 | A2 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for d in dirs:
        theta = "—" if d["fitted_parameter"] is None else f"{d['fitted_parameter']:.2f}"
        flow = (f"{WINLABEL[d['fit_window']]}→{WINLABEL[d['eval_window']]}"
                if d["fit_window"] else f"—→{WINLABEL[d['eval_window']]}")
        print(f"| {d['hypothesis_id']} | {d['horizon']} | {DIRLABEL[d['direction']]} | {flow} | "
              f"{d['n_eval']} / {d['touches_eval']} | {theta} | {d['brier_p']:.6f} | "
              f"{d['brier_p_prime']:.6f} | {f6(d['delta'])} | {f6(d['ci90_lower'])} | "
              f"{d['mde_1645se']:.6f} | {pct(d['shortfall_share_of_brier'], 2)} | "
              f"{yn(d['A1_derived'])} | {yn(d['A2_derived'])} |")
    print()

    # ---------------------------------------------------------------- 표 C 미달 양상
    fa = v["failure_analysis"]
    print("### 표 C — 미달의 두 양상 (16 방향)\n")
    print("| 양상 | 방향 수 | 뜻 |")
    print("|---|---|---|")
    print(f"| 하한 < 0 | {fa['by_failure_mode']['하한<0']} | 개선의 증거가 CI90 으로 지지되지 않음 |")
    print(f"| 하한 = 0 | {fa['by_failure_mode']['하한=0']} | 맵이 평가창에서 아무 일도 하지 않음 (p′=p, Δ=0) |")
    print(f"| 하한 > 0 | {fa['by_failure_mode']['하한>0']} | 채택 |")
    print()
    degen = [f"{d['cell']} {DIRLABEL[d['direction']]}" for d in dirs if d["degenerate"]]
    print(f"퇴화 방향 {len(degen)} 개: {', '.join(degen)}")
    print()
    print(f"|Δ| < MDE '결정적 증거 없음' = {fa['inconclusive_by_mde_directions']}/16 방향 · "
          f"{fa['inconclusive_by_mde_cells']}/8 셀에서 최소 한 방향 · "
          f"A2 통과 = {fa['a2_pass_directions']}/16 방향 · {fa['a2_pass_cells']}/8 셀")
    print()

    # ---------------------------------------------------------------- 표 D 귀무·다중검정
    m = v["multiplicity"]
    print("### 표 D — 순열 귀무 N1 (1000회) · 다중검정\n")
    ks = sorted(m["k_distribution"], key=int)
    print("| k (통과 셀 수) | " + " | ".join(ks) + " |")
    print("|---" * (len(ks) + 1) + "|")
    print("| 순열 수 | " + " | ".join(str(m["k_distribution"][k]) for k in ks) + " |")
    print("| P(k ≥ ·) | " + " | ".join(f"{m['p_k_ge'][k]:.4f}" for k in ks) + " |")
    print()
    print(f"평균 k = {m['k_mean']} · 최대 k = {m['k_max']} · "
          f"**P(k ≥ k_obs={v['verdict']['k_obs']}) = {m['p_k_ge_kobs']:.4f}** · "
          f"family 주장 = {'지지' if m['family_claim_supported'] else '미지지'}")
    print()

    nl = v["null_liberality"]
    print("### 표 E — 귀무 아래 셀별 통과율 (사후 진단 라벨 · 채택 요건 아님)\n")
    print("| 셀 | 귀무 통과율 | 명목 5% 대비 | 실측 A1 | 미달의 해석 |")
    print("|---|---|---|---|---|")
    for c in cells:
        regime = c["null_regime"]
        reading = ("검정력 부족으로 설명되지 않음" if regime == "관대"
                   else "검정력 부족과 구분 불가")
        print(f"| {c['cell']} | {c['null_cell_pass_rate']:.3f} | {regime} | "
              f"{yn(c['A1_derived'])} | {reading} |")
    print()
    print(f"관대 {len(nl['liberal_cells'])} 셀 · 보수 {len(nl['conservative_cells'])} 셀. {nl['caveat']}")
    print()

    # ---------------------------------------------------------------- 표 F T5
    print("### 표 F — T5 음성 대조\n")
    print("| 항목 | 값 |")
    print("|---|---|")
    print(f"| pooled 통과율 | {v['verdict']['T5_pass_rate_pooled']:.4f} |")
    print(f"| 문턱 | {v['verdict']['T5_threshold']:.2f} |")
    print(f"| 판정 | {'실패 (검정 기계 결함)' if v['verdict']['T5_failed'] else '통과'} |")
    print(f"| 발동 분기 | {v['verdict']['governing_branch']} |")
    print()

    # ---------------------------------------------------------------- 표 G S4 이월
    print("### 표 G — S4 이월 조항\n")
    print("| ID | 조항 |")
    print("|---|---|")
    for c in v["carry_to_s4"]:
        print(f"| `{c['id']}` | {c['rule']} |")
    print()
    return 0


def _cli() -> int:
    """`--out <path>` 를 주면 렌더 결과를 그 파일에도 저장한다 (판정서 첨부용 사본)."""
    if "--out" in sys.argv:
        target = ROOT / sys.argv[sys.argv.index("--out") + 1]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main()
        target.parent.mkdir(parents=True, exist_ok=True)
        header = ("# S3-2 — S3 판정 표 (자동 렌더)\n\n"
                  "> `tools/v12_s3_tables.py` 출력의 사본. 판정서의 표 행은 이 파일과 바이트 일치해야 하며\n"
                  "> `tools/v12_s3_doc_check.py` 가 대사한다. 수기 편집 금지.\n\n")
        target.write_text(header + buf.getvalue(), encoding="utf-8")
        sys.stdout.write(buf.getvalue())
        print(f"\n[wrote {target.relative_to(ROOT).as_posix()}]")
        return rc
    return main()


if __name__ == "__main__":
    raise SystemExit(_cli())
