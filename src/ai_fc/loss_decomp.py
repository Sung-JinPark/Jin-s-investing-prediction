"""T04 — 해소된 예측의 Brier 를 **세 조각으로 쪼갠다**.

## 왜 쪼개는가

`Brier = 0.4356` 이라는 숫자 하나로는 무엇이 잘못됐는지 알 수 없다. 질문을 잘못 고른 것인지,
운이 나빴던 것인지, 예측이 정직 확률에서 벗어난 것인지가 구별되지 않는다. 셋은 대응이 다르다.

- **질문 선택** — 등록에서만 고칠 수 있다(T02 계약). 사후에는 손댈 수 없다.
- **뽑기** — 고칠 수 없다. 기댓값 0 이므로 표본이 쌓이면 씻긴다.
- **앵커 초과** — 예측 절차에서 고칠 수 있다. 이것만이 '실력' 축이다.

## 항등식

정직 확률 `p`(등록 시점), 예측 확률 `q`(원장), 결과 `y ∈ {0,1}` 에 대해

    Brier = (q − y)²
          = p(1−p)                    ← 기대 바닥 (floor)
          + [(p − y)² − p(1−p)]       ← 뽑기 (draw)
          + [(q − y)² − (p − y)²]     ← 앵커 초과 (anchor excess)

세 항의 합은 항등적으로 `(q − y)²` 다. 두 번째 항은 `y ~ Bernoulli(p)` 하에서 기댓값 0 이다
(`E[(p−y)²] = p(1−p)`). 세 번째 항은 `(q−p)(q + p − 2y)` 로도 쓸 수 있고, 예측을 `p` 가 아닌
`q` 로 낸 대가다 — 부호가 음이면 그 회차에서 `q` 가 `p` 보다 나았다는 뜻이다.

## 정직 확률 `p` 를 어디서 가져오는가

**등록 시점에 고정된 값만 쓴다.** 성적을 보고 `p` 를 정하면 분해 전체가 사후 서사가 된다.

1. `prereg.honest_probability_estimate` — T02 이후 등록분
2. 레지스트리 `notes` 의 `예상확률 N%` — C5 사전등록 관례(첫 예측 전 고정)
3. 둘 다 없으면 **분해하지 않는다.** `floor`·`draw`·`anchor_excess` 는 `None` 이고
   사유를 남긴다. 없는 값을 지어내지 않는다.

`notes` 에 "리서치 이후 산정" 이 명기된 대체 질문은 **첫 예측 전 고정이 아니므로** 제외한다
(`c5_certificate.budget_reconciliation` 과 같은 규약).

## 이 모듈이 하지 않는 것

- 원장을 쓰지 않는다. 분해는 **읽어서 계산**하고 파일로 굳히지 않는다 —
  원장에 파생열을 붙이면 append-only 규약과 스키마가 충돌한다.
- 표본을 빼지 않는다. `research_status='failed'` 판정은 기존 규약 그대로 읽기만 한다.
- 예측 파일을 건드리지 않는다.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_EXPECTED_RE = re.compile(r"예상확률 (\d+)%")
_RESEARCH_INFORMED = "리서치 이후 산정"


@dataclass(frozen=True)
class LossDecomposition:
    question_id: str
    forecast_id: str
    outcome: int
    stated_probability: float          # q — 원장에 남은 확률
    brier: float
    honest_probability: float | None   # p — 등록 시점 고정값
    honest_source: str                 # 어디서 가져왔는가 (또는 왜 없는가)
    floor: float | None = None         # p(1−p)
    draw: float | None = None          # (p−y)² − p(1−p)
    anchor_excess: float | None = None # (q−y)² − (p−y)²
    primary: bool = True

    @property
    def decomposed(self) -> bool:
        return self.floor is not None

    def check_identity(self, tolerance: float = 1e-9) -> bool:
        """세 조각의 합이 Brier 와 같은가 — 분해가 항등식임을 매번 확인한다."""
        if not self.decomposed:
            return True
        total = float(self.floor) + float(self.draw) + float(self.anchor_excess)
        return abs(total - self.brier) < tolerance


def honest_probability_of(question: dict[str, Any]) -> tuple[float | None, str]:
    """등록 시점에 고정된 정직 확률. 없으면 `(None, 사유)`."""
    prereg = question.get("prereg")
    if isinstance(prereg, dict):
        value = prereg.get("honest_probability_estimate")
        if value is not None:
            return float(value), "prereg.honest_probability_estimate"

    notes = str(question.get("notes") or "")
    match = _EXPECTED_RE.search(notes)
    if match:
        if _RESEARCH_INFORMED in notes:
            return None, f"notes 예상확률이 '{_RESEARCH_INFORMED}' — 첫 예측 전 고정이 아니라 제외"
        return int(match.group(1)) / 100.0, "notes 예상확률 (첫 예측 전 고정)"
    return None, "등록 시점 정직 확률이 기록돼 있지 않다 — 분해하지 않는다"


def decompose_one(*, question_id: str, forecast_id: str, outcome: int,
                  stated_probability: float, brier: float,
                  honest_probability: float | None, honest_source: str,
                  primary: bool = True) -> LossDecomposition:
    if honest_probability is None:
        return LossDecomposition(
            question_id=question_id, forecast_id=forecast_id, outcome=outcome,
            stated_probability=stated_probability, brier=brier,
            honest_probability=None, honest_source=honest_source, primary=primary)
    p, q, y = float(honest_probability), float(stated_probability), int(outcome)
    floor = p * (1.0 - p)
    honest_brier = (p - y) ** 2
    return LossDecomposition(
        question_id=question_id, forecast_id=forecast_id, outcome=y,
        stated_probability=q, brier=brier, honest_probability=p,
        honest_source=honest_source, floor=floor,
        draw=honest_brier - floor, anchor_excess=(q - y) ** 2 - honest_brier,
        primary=primary)


def decompose_ledger(root: Path) -> list[LossDecomposition]:
    """원장 전량을 분해한다. primary 판정은 기존 규약을 그대로 읽는다."""
    from .c5_certificate import read_forecasts, read_ledger, read_overrides, read_registry

    questions = {str(q.get("id")): q for q in read_registry(root)}
    overrides = read_overrides(root)
    status = {f.forecast_id: f.research_status for f in read_forecasts(root)}

    out: list[LossDecomposition] = []
    for row in read_ledger(root):
        qid = str(row.get("question_id") or "")
        fid = str(row.get("forecast_id") or "")
        effective = overrides.get(fid, status.get(fid, "ok"))
        honest, source = honest_probability_of(questions.get(qid) or {})
        out.append(decompose_one(
            question_id=qid, forecast_id=fid, outcome=int(float(row["outcome"])),
            stated_probability=float(row["probability"]) / 100.0,
            brier=float(row["brier"]), honest_probability=honest,
            honest_source=source, primary=(effective != "failed")))
    return out


def summarize(rows: list[LossDecomposition], *, primary_only: bool = True) -> dict[str, Any]:
    """분해 가능한 행만 평균낸다 — 분해 불가 행 수를 함께 낸다(조용히 빼지 않는다)."""
    pool = [r for r in rows if r.primary] if primary_only else list(rows)
    usable = [r for r in pool if r.decomposed]
    summary: dict[str, Any] = {
        "n_rows": len(pool),
        "n_decomposed": len(usable),
        "n_undecomposable": len(pool) - len(usable),
        "undecomposable_reasons": sorted({r.honest_source for r in pool if not r.decomposed}),
        "mean_brier": round(statistics.mean([r.brier for r in pool]), 6) if pool else None,
    }
    if usable:
        summary.update({
            "mean_brier_decomposed": round(statistics.mean([r.brier for r in usable]), 6),
            "mean_floor": round(statistics.mean([float(r.floor) for r in usable]), 6),
            "mean_draw": round(statistics.mean([float(r.draw) for r in usable]), 6),
            "mean_anchor_excess": round(
                statistics.mean([float(r.anchor_excess) for r in usable]), 6),
        })
    summary["identity_holds"] = all(r.check_identity() for r in pool)
    return summary


def decomposition_lines(rows: list[LossDecomposition], summary: dict[str, Any]) -> list[str]:
    """사람이 읽을 요약. 판정 단어를 쓰지 않는다."""
    lines = [
        f"분해 가능 {summary['n_decomposed']}/{summary['n_rows']}행"
        + (f" · 분해 불가 {summary['n_undecomposable']}행" if summary["n_undecomposable"] else ""),
    ]
    if summary.get("mean_floor") is not None:
        lines.append(
            f"평균 Brier {summary['mean_brier_decomposed']:.5f} = "
            f"기대 바닥 {summary['mean_floor']:.5f} + 뽑기 {summary['mean_draw']:+.5f} + "
            f"앵커 초과 {summary['mean_anchor_excess']:+.5f}")
        lines.append("기대 바닥은 질문 선택의 값이라 등록에서만 고칠 수 있고, 뽑기는 기댓값 0 이며, "
                     "앵커 초과만 예측 절차로 고칠 수 있는 축이다.")
    for reason in summary.get("undecomposable_reasons") or []:
        lines.append(f"분해 불가 사유: {reason}")
    if not summary.get("identity_holds", True):
        lines.append("⚠ 항등식이 깨졌다 — 분해를 신뢰하지 말 것")
    return lines


def counterfactual_row_mean(root: Path, additions: list[tuple[float, int]]) -> dict[str, Any]:
    """가상의 해소 몇 건을 더했을 때 **행 평균 Brier** 가 어디로 가는지.

    게이트 판정을 예단하려는 것이 아니라, 예약된 손실의 크기를 먼저 말해두기 위한 계산이다.
    `additions` 는 `(예측확률, 결과)` 목록이며 실제 원장에 아무것도 쓰지 않는다.
    """
    from .gate_display import gate_display_facts

    facts = gate_display_facts(root)
    n = int(facts["n_rows_primary"])
    mean = float(facts["brier_primary_rows"])
    total = mean * n
    for q, y in additions:
        total += (float(q) - int(y)) ** 2
        n += 1
    return {"before_rows": int(facts["n_rows_primary"]),
            "before_mean": round(mean, 6),
            "after_rows": n, "after_mean": round(total / n, 6),
            "threshold": facts["threshold_brier"],
            "note": "행 평균은 게이트 정본 단위다. 이 계산은 원장에 아무것도 쓰지 않는다."}
