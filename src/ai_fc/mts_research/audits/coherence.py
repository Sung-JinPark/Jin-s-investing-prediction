"""정합성 감사 (§9.1, §14 JOINT_EVAL 의 전단) — 표시 체인 재계산, 보고만.

- V8: tier-1 replay(adapters.v8)가 이미 grid 단조·p_up 동일 artifact·pointer 투영을
  검사한다. 여기서는 그 결과를 정합성 관점으로 집계하고, 격자 라벨 정밀도 관찰
  (중점레벨 격자에서 grid[int(0.1*200)]=grid[20] 은 0.1025-분위)을 공시한다.
- V13: 라이브 원장 전 행의 h/K 단조성을 **측정해 보고만** 한다 — 사후 '정합화'로
  셀을 공개하는 경로는 없다 (§9.6). V14 조건부 표면과는 결합하지 않는다 (T27).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...timeseries_v13 import contracts as C13

REPORT_RELATIVE = Path("data/mts_research/derived/coherence_audit.json")

GRID_LABEL_OBSERVATION = (
    "V8 quantile_grid 는 중점 레벨 (i+0.5)/200 — pointer 투영 grid[int(q*200)] 의 p10 은 "
    "정확히는 0.1025-분위 수준이다. 수학적 모순이 아니라 라벨 정밀도 관찰이며, 동결 "
    "좌표이므로 수정 대상이 아니다 (공시만)."
)


def v13_monotonicity_report(root: Path) -> dict[str, Any]:
    """vol_live 전 행의 지평·임계 단조성 측정 (같은 발행·같은 표면 안에서만)."""
    path = root / C13.LIVE_LEDGER_RELATIVE
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    horizon_violations: list[dict[str, Any]] = []
    threshold_violations: list[dict[str, Any]] = []
    checked = 0
    for row in rows:
        cells = row.get("cells") or {}
        probabilities = {name: float(cell["p"]) for name, cell in cells.items()}
        if not probabilities:
            continue
        checked += 1
        # 같은 사건의 지평 단조: within-horizon 이므로 p(h5) <= p(h21) <= p(h63) 이 기대
        for family in ("vix25", "vix30", "rv"):
            chain = [f"{family}_h{h}" for h in (5, 21, 63)]
            for ca, cb in zip(chain, chain[1:]):
                a, b = probabilities.get(ca), probabilities.get(cb)
                if a is None or b is None:
                    continue  # 쌍 단위 검사 — 체인 일부 결측이 검사를 통째로 막지 않는다
                if a > b + 1e-12:
                    horizon_violations.append(
                        {"as_of": row.get("as_of"), "pair": [ca, cb], "p": [a, b]}
                    )
        # 같은 지평의 임계 단조: p(vix30) <= p(vix25)
        for h in (5, 21, 63):
            p25 = probabilities.get(f"vix25_h{h}")
            p30 = probabilities.get(f"vix30_h{h}")
            if p25 is not None and p30 is not None and p30 > p25 + 1e-12:
                threshold_violations.append(
                    {"as_of": row.get("as_of"), "h": h, "p": [p25, p30]}
                )
    return {
        "rows_checked": checked,
        "horizon_monotonicity_violations": horizon_violations,
        "threshold_monotonicity_violations": threshold_violations,
        "note": (
            "보고 전용 — 위반이 있어도 사후 projection 으로 '정합화해 공개' 하지 않는다 "
            "(§9.6). V14 조건부 표면과의 순서 제약은 걸지 않는다 (T27)."
        ),
    }


def build_report(root: Path) -> dict[str, Any]:
    from ..adapters.v8 import tier1_replay

    v8 = tier1_replay(root)
    v13 = v13_monotonicity_report(root)
    report = {
        "schema_version": 1,
        "v8_single_artifact_derivation": {
            "grid_monotone_and_p_up_same_artifact": v8["forecast_pass"] == v8["forecast_rows"],
            "pointer_projection": v8["pointer"],
            "resolution_consistency": {
                "pass": v8["resolution_pass"], "rows": v8["resolution_rows"],
                "grid_skip_rows": v8.get("grid_skip_rows", 0),
            },
            "grid_label_observation": GRID_LABEL_OBSERVATION,
            "grid_dependent_label_finding": (
                "bundle grid 가 국채 휴장 주식 거래일을 제외해 h세션 누적수익 라벨이 "
                "해당 일 수익을 누락한다 (2026-10-12 실측 2행) — grid-종속 표적. "
                "동결 코드: 수정이 아니라 공시·후속 계약 설계의 입력."
            ),
        },
        "v13_surface": v13,
        "gate_e2_input": {
            "pass": (
                v8["ok"]
                and not v13["horizon_monotonicity_violations"]
                and not v13["threshold_monotonicity_violations"]
            ),
            "evidence_refs": ["baseline_identity.json", "coherence_audit.json"],
        },
    }
    out = root / REPORT_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    return report
