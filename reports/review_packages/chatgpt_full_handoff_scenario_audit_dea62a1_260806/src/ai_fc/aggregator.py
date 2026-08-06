"""ProbabilityAggregator — 앙상블 교체 지점 (P2에서 orchestrator 무수정 교체).

P1: SingleRun (추론 1회).
P2: MedianEnsemble (Claude+GPT x K=6, 중앙값, σ>8%p면 재조사 콜백) — 이 인터페이스에 구현.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

import anthropic

from .llm import PipelineBudget
from .models import EvidenceBrief, Question
from .reasoning_core import run_reasoning
from .schemas import ForecastResult


@dataclass
class AggregateResult:
    probability: int
    ci80_lo: int
    ci80_hi: int
    result: ForecastResult          # 대표 실행 (앙상블이면 중앙값에 가장 가까운 실행)
    runs: list[int] = field(default_factory=list)  # 개별 실행 확률들
    divergence: float | None = None  # 앙상블 σ (SingleRun은 None)


class ProbabilityAggregator(Protocol):
    def estimate(self, client: anthropic.Anthropic, q: Question,
                 briefs: list[EvidenceBrief], prompts_dir: Path,
                 budget: PipelineBudget, today: date,
                 window_end: date | None,
                 aux_context: str | None = None) -> AggregateResult: ...


class SingleRun:
    """P1: 추론 코어 1회 실행."""

    def estimate(self, client, q, briefs, prompts_dir, budget, today, window_end,
                 aux_context=None):
        result, _usage = run_reasoning(client, q, briefs, prompts_dir, budget,
                                       today, window_end, aux_context=aux_context)
        return AggregateResult(
            probability=result.probability,
            ci80_lo=result.ci80_lo,
            ci80_hi=result.ci80_hi,
            result=result,
            runs=[result.probability],
        )


class KRunMedian:
    """K회 독립 추론 → 고정 중앙값 (AIA·FutureSearch 'run twice' — ARCHITECTURE §2-④).

    고정 규칙 결합이라 ML 게이트 비저촉. 단 활성화(K>1)는 P2 게이트 후 사용자 결정 —
    기본 config.REASONING_RUNS=1이면 orchestrator가 SingleRun을 쓴다.
    대표 result는 중앙값에 가장 가까운 실행. divergence = (max-min)/100.
    """

    def __init__(self, k: int) -> None:
        self.k = max(2, k)

    def estimate(self, client, q, briefs, prompts_dir, budget, today, window_end,
                 aux_context=None):
        import statistics

        results = []
        for _ in range(self.k):
            r, _usage = run_reasoning(client, q, briefs, prompts_dir, budget,
                                      today, window_end, aux_context=aux_context)
            results.append(r)
        probs = [r.probability for r in results]
        med = int(round(statistics.median(probs)))
        rep = min(results, key=lambda r: abs(r.probability - med))
        return AggregateResult(
            probability=med,
            ci80_lo=int(round(statistics.median(r.ci80_lo for r in results))),
            ci80_hi=int(round(statistics.median(r.ci80_hi for r in results))),
            result=rep,
            runs=probs,
            divergence=(max(probs) - min(probs)) / 100.0,
        )
