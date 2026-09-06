#!/usr/bin/env python
"""tools/v12_s3_verdict.py — S3 판정 산출 (S3-2, 읽기 전용 재분석).

입력은 커밋된 산출물 두 개뿐이다:
  · `data/timeseries_v12/diagnostics/transfer_results.json` (S3-1 — 수치의 유일 원천)
  · `data/timeseries_v12/prereg/hypotheses.json`            (S3-0 — 규칙의 유일 원천, ec496463 커밋)

이 스크립트는 S3-1 의 롤업 필드(`adoption`·`verdict`)를 **믿지 않는다**. 16 개 `records` 의
`ci90_lower` 에서 A1·A2·셀 판정·k_obs 를 직접 재유도하고, 그 결과가 S3-1 롤업과 일치하는지
대사한다(`derivation.matches_transfer_rollup`). 불일치는 그 자체로 실패다.

판정 분기는 등록부 `pre_committed_interpretation` 의 문자열을 그대로 인용해 고른다 —
분기 선택을 스크립트가 하고, 판정문(docs/design/v12_s3_verdict.md)은 그 결과를 렌더한다.

산출: data/timeseries_v12/diagnostics/s3_verdict.json (이 파일 하나만 쓴다)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TR_REL = "data/timeseries_v12/diagnostics/transfer_results.json"
PR_REL = "data/timeseries_v12/prereg/hypotheses.json"
S2_REL = "data/timeseries_v12/diagnostics/s2_entry_verdict.json"
OUT_REL = "data/timeseries_v12/diagnostics/s3_verdict.json"

# 명목 단측 수준 — CI90 하한 > 0 은 단측 5% 검정이다. 귀무 통과율을 이 값과 대조해
# 셀이 관대(liberal)한지 보수적인지 분류한다. 채택 요건이 아니라 사후 진단 라벨이다.
NOMINAL_ONE_SIDED = 0.05

CELL_ORDER = ["T1_h21", "T1_h63", "T2_h21", "T2_h63", "T3_h21", "T3_h63", "T4_h21", "T4_h63"]


def sha256(rel: str) -> str:
    h = hashlib.sha256()
    with (ROOT / rel).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def build() -> dict:
    tr = load(TR_REL)
    pr = load(PR_REL)

    records = tr["records"]
    null = tr["multiplicity_null"]
    t5 = tr["t5_negative_control"]

    # ---------------------------------------------------------------- 1. 방향 단위 재유도
    directions: list[dict] = []
    for rec in records:
        cell = f"{rec['hypothesis_id']}_h{rec['horizon']}"
        lower = rec["ci90_lower"]
        # A1 은 **엄격 부등호**다. 퇴화(p′=p)로 CI 가 [0,0] 인 방향은 하한이 정확히 0 이라 미달.
        a1 = lower > 0.0
        a2 = rec["ci90_lower_vs_reflection"] > 0.0
        if lower < 0.0:
            mode = "하한<0"
        elif lower == 0.0:
            mode = "하한=0"
        else:
            mode = "하한>0"
        directions.append({
            "cell": cell,
            "hypothesis_id": rec["hypothesis_id"],
            "horizon": rec["horizon"],
            "direction": rec["direction"],
            "fit_window": rec["fit_window"],
            "eval_window": rec["eval_window"],
            "n_eval": rec["n_eval"],
            "touches_eval": rec["touches_eval"],
            "fitted_parameter": rec["fitted_parameter"],
            "parameter_name": rec["parameter_name"],
            "brier_p": rec["brier_p"],
            "brier_p_prime": rec["brier_p_prime"],
            "delta": rec["delta"],
            "ci90_lower": lower,
            "ci90_upper": rec["ci90_upper"],
            "mde_1645se": rec["mde_1645se"],
            "mde_share_of_brier": rec["mde_share_of_brier"],
            "inconclusive_by_mde": rec["inconclusive_by_mde"],
            "degenerate": rec["degenerate"],
            "delta_vs_reflection": rec["delta_vs_reflection"],
            "ci90_lower_vs_reflection": rec["ci90_lower_vs_reflection"],
            "concentration_fragile": rec["concentration_fragile"],
            "concentration_sign_reversed": rec["concentration_sign_reversed"],
            "concentration_sign_vanishes": rec["concentration_sign_vanishes"],
            "A1_derived": a1,
            "A2_derived": a2,
            "A1_reported": rec["A1_pass"],
            "A2_reported": rec["A2_pass"],
            "failure_mode": mode,
            # 채택까지 하한이 올라가야 할 폭 — 미달 방향에서만 의미가 있다.
            # 하한이 정확히 0 인 퇴화 방향은 부족분 0.0 (부호 없는 0 으로 정규화).
            "shortfall": None if a1 else (0.0 if lower == 0.0 else -lower),
            "shortfall_share_of_brier": None if a1 else (
                0.0 if lower == 0.0 else (-lower / rec["brier_p"] if rec["brier_p"] else None)),
            "null_direction_pass_rate": null["direction_pass_rate"].get(
                f"{rec['hypothesis_id']}_h{rec['horizon']}_{rec['direction']}"),
        })

    # ---------------------------------------------------------------- 2. 셀 단위 재유도
    cells: list[dict] = []
    for cell_id in CELL_ORDER:
        rows = [d for d in directions if d["cell"] == cell_id]
        assert len(rows) == 2, f"{cell_id}: 방향 {len(rows)} 개 (2 여야 한다)"
        binding = min(rows, key=lambda d: d["ci90_lower"])   # 채택을 막는 방향
        a1_cell = all(d["A1_derived"] for d in rows)
        a2_cell = all(d["A2_derived"] for d in rows)
        npr = null["cell_pass_rate"][cell_id]
        cells.append({
            "cell": cell_id,
            "hypothesis_id": rows[0]["hypothesis_id"],
            "horizon": rows[0]["horizon"],
            "directions": [d["direction"] for d in rows],
            "delta_by_direction": {d["direction"]: d["delta"] for d in rows},
            "ci90_lower_by_direction": {d["direction"]: d["ci90_lower"] for d in rows},
            "min_ci90_lower": binding["ci90_lower"],
            "binding_direction": binding["direction"],
            "binding_failure_mode": binding["failure_mode"],
            "binding_shortfall_share_of_brier": binding["shortfall_share_of_brier"],
            "A1_derived": a1_cell,
            "A2_derived": a2_cell,
            "A1_reported": tr["adoption"]["A1_by_cell"][cell_id],
            "A2_reported": tr["adoption"]["A2_by_cell"][cell_id],
            "degenerate_directions": [d["direction"] for d in rows if d["degenerate"]],
            "inconclusive_directions": [d["direction"] for d in rows if d["inconclusive_by_mde"]],
            "concentration_flagged_directions": [d["direction"] for d in rows
                                                 if d["concentration_fragile"]
                                                 or d["concentration_sign_reversed"]
                                                 or d["concentration_sign_vanishes"]],
            "null_cell_pass_rate": npr,
            # 사후 진단 라벨 — 채택 요건 아님.
            "null_regime": "관대" if npr > NOMINAL_ONE_SIDED else "보수",
        })

    adopted = [c["cell"] for c in cells if c["A1_derived"]]
    k_obs = len(adopted)
    a2_cells = [c["cell"] for c in cells if c["A2_derived"]]

    rollup_match = (
        adopted == list(tr["adoption"]["adopted_cells"])
        and k_obs == tr["adoption"]["k_obs"]
        and k_obs == null["k_obs"]
        and all(d["A1_derived"] == d["A1_reported"] for d in directions)
        and all(d["A2_derived"] == d["A2_reported"] for d in directions)
        and all(c["A1_derived"] == c["A1_reported"] for c in cells)
        and all(c["A2_derived"] == c["A2_reported"] for c in cells)
    )

    # ---------------------------------------------------------------- 3. 등록부 분기 선택
    interp = pr["pre_committed_interpretation"]
    t5_failed = t5["pass_rate_pooled"] > t5["threshold"]
    branches = []
    if t5_failed:
        branches.append("T5_fail")
    if k_obs == 0:
        branches.append("adopted_0")
    if k_obs >= 1:
        branches.append("adopted_ge_1")
    # 등록부: "이 경로가 adopted_0 보다 우선한다"
    governing = "T5_fail" if t5_failed else ("adopted_0" if k_obs == 0 else "adopted_ge_1")
    decision_code = "NEGATIVE_RESULT" if governing in ("T5_fail", "adopted_0") else "ADOPTED"

    p_k_ge_kobs = null["p_k_ge_kobs"]
    family_supported = p_k_ge_kobs <= null["family_claim_threshold"]

    # ---------------------------------------------------------------- 4. 실패 양상 집계
    modes = {"하한<0": 0, "하한=0": 0, "하한>0": 0}
    for d in directions:
        modes[d["failure_mode"]] += 1

    failure = {
        "directions_total": len(directions),
        "by_failure_mode": modes,
        "degenerate_directions": [f"{d['cell']}·{d['direction']}" for d in directions if d["degenerate"]],
        "inconclusive_by_mde_directions": sum(1 for d in directions if d["inconclusive_by_mde"]),
        "inconclusive_by_mde_cells": sum(1 for c in cells if c["inconclusive_directions"]),
        "a2_pass_directions": sum(1 for d in directions if d["A2_derived"]),
        "a2_pass_cells": len(a2_cells),
        "worst_binding_cell": min(cells, key=lambda c: c["min_ci90_lower"])["cell"],
        "closest_binding_cell_nondegenerate": max(
            [c for c in cells if not c["degenerate_directions"]],
            key=lambda c: c["min_ci90_lower"])["cell"],
        "note": ("A1 은 엄격 부등호이므로 하한이 정확히 0 인 방향도 미달이다. "
                 "하한<0 은 '증거 부족', 하한=0 은 '맵이 평가창에서 아무 일도 하지 않음'으로 성격이 다르다."),
    }

    liberal = [c["cell"] for c in cells if c["null_regime"] == "관대"]
    conservative = [c["cell"] for c in cells if c["null_regime"] == "보수"]

    verdict = {
        "decision": "전이 불가 (부정 결과 확정)",
        "decision_code": decision_code,
        "adopted_cells": adopted,
        "adopted_count": k_obs,
        "k_obs": k_obs,
        "A2_cells": a2_cells,
        "T5_failed": t5_failed,
        "T5_pass_rate_pooled": t5["pass_rate_pooled"],
        "T5_threshold": t5["threshold"],
        "governing_branch": governing,
        "branches_fired": branches,
        "branch_precedence": "T5_fail > adopted_0 (등록부 pre_committed_interpretation.T5_fail 원문)",
        "s4_contract": interp[governing],
        "s4_contract_source": f"prereg.pre_committed_interpretation.{governing}",
        "converges": len(branches) > 1,
        "family_claim_supported": family_supported,
        "p_k_ge_kobs": p_k_ge_kobs,
        "accept_line": (f"채택 목록: 없음 (0/8 셀) — 부정 결과 확정. "
                        f"k_obs={k_obs} · T5 실패={t5_failed}"),
    }

    scope = {
        "established": [
            "이 표본·이 창·이 분할에서, 사전등록된 네 파생층 맵(T1~T4) 중 어느 것도 두 방향 모두에서 "
            "Brier 개선의 CI90 하한을 0 위로 올리지 못했다 — 8 셀 전부 미달, k_obs=0.",
            "T3(반사 앵커 혼합)은 전→후 두 지평에서 CI90 **상한**이 0 미만이다 — 미달을 넘어 유의하게 악화다. "
            "S2-3 이 정정 등록한 기대(비GFC·calm 에서 w>0 은 악화 방향)와 일치한다.",
            "T4(지평 단조 제약)는 이 표본에서 위반이 0 건이라 교정할 것이 없다 — 무비용이자 무효과.",
            "음성 대조 T5 가 실패했다. 무작위로 짝지은 p 로도 T1 이 pooled 25.4% 확률로 채택 요건을 "
            "만족하므로, 이 검정 기계가 낸 '통과'는 증거로 쓸 수 없었다.",
        ],
        "not_established": [
            "'V8 first_touch 확률이 잘 보정돼 있다' 가 아니다 — S2-1 의 과신 구조와 S2-2 의 기준선 대비 "
            "결론은 그대로다.",
            "'어떤 재보정도 불가능하다' 가 아니다 — 부정된 것은 등록된 네 맵과 이 검정 절차이며, "
            "다른 맵·다른 표본·다른 분할은 검정되지 않았다.",
            "'V8 이 반사원리 기준선을 이긴다/진다' 를 새로 말하지 않는다 — S3 는 p′ vs p 검정이며, "
            "기준선 대비는 A2 로 기록만 했다(셀 단위 통과 0).",
            "2015+ 봉인창에 대한 어떤 주장도 아니다 — 홀드아웃 미계산.",
        ],
    }

    carry = [
        {"id": "C-S4-contract",
         "rule": "S4 는 등록부 분기 그대로 'V12 부정 결과 계약'으로 작성한다. 계약 draft 를 "
                 "'조건부 통과' 로 되살리는 서술은 등록부 위반."},
        {"id": "C-null-redesign",
         "rule": "N1 이 T1 류 수축 맵의 적법한 귀무가 아닐 가능성(S3-1 open_question)은 S4-2 재검토 "
                 "항목이다. 결과를 본 뒤 귀무를 갈아끼워 판정을 되살리는 것은 금지."},
        {"id": "C-gate-arith",
         "rule": "등록부 prohibitions.K-gate-arith 유지 — S4 에서 기준선을 바꿔 문턱을 낮추는 것은 "
                 "근거 명문화 없이 금지."},
        {"id": "C-split-contrast",
         "rule": "등록부 prohibitions.K-split-contrast 유지 — S2-3 분할창 대비를 S3/S4 근거로 인용 금지."},
        {"id": "C-holdout",
         "rule": "2015+ 봉인창 미계산 유지. 부정 결과라고 해서 홀드아웃을 여는 근거가 되지 않는다."},
    ]

    out = {
        "schema": "v12.s3_verdict/1",
        "task_id": "S3-2",
        "title": "S3 판정 — 사전등록 전이 가설 채택 여부",
        "generated_by": "tools/v12_s3_verdict.py",
        "read_only": True,
        "inputs": {
            TR_REL: {"sha256": sha256(TR_REL), "role": "수치 원천 (S3-1)"},
            PR_REL: {"sha256": sha256(PR_REL), "role": "규칙 원천 (S3-0, 커밋 "
                                                       f"{tr['prereg']['commit'][:8]})"},
            S2_REL: {"sha256": sha256(S2_REL), "role": "이월 제약 원천 (S2-3)"},
        },
        "rule": {
            "A1": pr["adoption"]["primary"]["rule"],
            "A1_source": pr["adoption"]["primary"]["source"],
            "A2": pr["adoption"]["secondary"]["rule"],
            "A2_status": pr["adoption"]["secondary"]["status"],
            "cell_definition": pr["adoption"]["cell_definition"],
            "no_pooling": pr["adoption"]["no_pooling"],
            "T5": t5["rule"],
            "T5_interpretation_limit": t5["interpretation_limit"],
            "family_claim_threshold": pr["multiplicity"]["family_claim_threshold"],
            "what_adoption_does_not_mean": interp["what_adoption_does_not_mean"],
        },
        "derivation": {
            "source": "transfer_results.records 16 건에서 직접 재유도 (롤업 필드 미사용)",
            "directions": len(directions),
            "cells": len(cells),
            "k_obs": k_obs,
            "adopted_cells": adopted,
            "matches_transfer_rollup": rollup_match,
        },
        "verdict": verdict,
        "failure_analysis": failure,
        "null_liberality": {
            "label": "[사후 관찰] 채택 요건이 아니며 판정을 바꾸지 않는다",
            "nominal_one_sided": NOMINAL_ONE_SIDED,
            "liberal_cells": liberal,
            "conservative_cells": conservative,
            "cell_pass_rate": {c["cell"]: c["null_cell_pass_rate"] for c in cells},
            "reading": ("귀무 통과율이 명목 5% 를 크게 넘는 셀에서는 무작위로 짝지은 p 가 실측 p 보다 "
                        "자주 채택 요건을 만족한다. 그 셀의 미달은 '검정력 부족' 으로 설명되지 않는다. "
                        "반대로 통과율이 5% 미만인 셀의 미달은 검정력 부족과 구분되지 않는다."),
            "caveat": "이 분류는 결과를 본 뒤 붙인 라벨이다. 등록부에 없으며 어떤 셀의 판정도 바꾸지 않는다.",
        },
        "multiplicity": {
            "k_distribution": null["k_distribution"],
            "k_mean": null["k_mean"],
            "k_max": null["k_max"],
            "p_k_ge": null["p_k_ge"],
            "p_k_ge_kobs": p_k_ge_kobs,
            "family_claim_supported": family_supported,
            "note": ("k_obs=0 이므로 P(k≥0)=1 은 자명하다. 정보는 귀무분포 자체에 있다 — "
                     "귀무 아래 평균 통과 셀 수가 2.764 인 검정 기계에서 실측이 0 이다."),
        },
        "cells": cells,
        "directions": directions,
        "scope": scope,
        "carry_to_s4": carry,
        "caveats_inherited": tr["caveats"],
        "open_questions": [
            "N1 이 T1 류 상단 수축 맵의 적법한 귀무인지 [미검증] — S3-1 이 특정한 기전(귀무 p 의 상단 "
            "과신)은 사후 관찰이고 정량 검증이 없다. S4-2 이월.",
            "귀무 통과율의 지평 간 100배 격차(h21 vs h63)의 기전 [미검증].",
            "T4 두 셀의 비독립성을 family 산술이 무시한다 [미검증] (S3-0 이월).",
            "S2-3 이월 유지 — 채택 규칙의 주체 선택(R2=표적 구조)이 옳은 독해인지는 사용자 판단(V12-D2).",
            "S2-3 이월 유지 — R3(로짓 기울기)과 상위분위 gap 이 갈리는 이유 [미검증].",
            "S2-3 이월 유지 — h21 후반창 집중도가 구조인지 표본 인공물인지 미확정.",
            "S1-3 이월 유지 — V10 조합 격자 재개 여부는 사용자 결정(V12-D5 제안).",
            "S1-1 이월 유지 — V11 CI 난수 규약 차(원본 seed 12345 vs 재계산 20260902) 병기 필요.",
        ],
        "not_done": [
            "대안 귀무(블록 순열·y 치환) 미계산 — 결과를 본 뒤 귀무 추가는 등록부 위반. S4-2 이월.",
            "국면(GFC/calm) 층화 CI 미산출 — S2 규약 승계.",
            "h1·h5 지평 미평가 — S2 에서 판정 제외.",
            "2015+ 봉인창 미계산 — 홀드아웃 보존.",
        ],
    }
    return out


def main() -> int:
    out = build()
    path = ROOT / OUT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT_REL}")
    print(f"  decision       = {out['verdict']['decision']}")
    print(f"  adopted_cells  = {out['verdict']['adopted_cells']} (k_obs={out['verdict']['k_obs']})")
    print(f"  governing      = {out['verdict']['governing_branch']} · branches={out['verdict']['branches_fired']}")
    print(f"  rollup match   = {out['derivation']['matches_transfer_rollup']}")
    print(f"  failure modes  = {out['failure_analysis']['by_failure_mode']}")
    print(f"  liberal cells  = {out['null_liberality']['liberal_cells']}")
    return 0 if out["derivation"]["matches_transfer_rollup"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
