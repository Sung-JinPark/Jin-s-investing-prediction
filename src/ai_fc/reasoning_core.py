"""추론 코어 — prompts/reasoning_core_vN.md 로드 + 증거 합성 + structured output."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import anthropic

from . import config
from .llm import PipelineBudget, Usage, reasoning_call
from .models import EvidenceBrief, Question
from .schemas import ForecastResult

STRUCTURED_SUFFIX = """

---
[출력 형식]
위 절차 [0]~[5]를 수행한 뒤, 지정된 구조화 스키마로 출력하라.
- probability는 1~99 정수 (구간 표현 금지)
- required_snapshots의 각 항목은 snapshots_filled에 확정 값 또는 'NOT FOUND'로
- 증거에 없는 수치를 만들지 마라. 검증 못한 주장은 unverified_notes에
"""


def load_system_prompt(prompts_dir: Path) -> str:
    path = prompts_dir / f"{config.PROMPT_VERSION}.md"
    return path.read_text(encoding="utf-8") + STRUCTURED_SUFFIX


def build_user_prompt(q: Question, briefs: list[EvidenceBrief], today: date,
                      window_end: date | None, aux_context: str | None = None) -> str:
    evidence = "\n\n".join(
        f"### [{b.profile}] 리서치 보고 (출처 {b.sources_count}개)\n{b.text}"
        for b in briefs
    )
    snapshots = "\n".join(f"- {s}" for s in q.required_snapshots) or "- 없음"
    window = f"\n[rolling 윈도우 종료일] {window_end.isoformat()}" if window_end else ""
    # 정량 참조는 Outside view 보조 자료 — 질문별 ML 매핑 확률은 base_rates.ml_digest가
    # 의도적으로 제외한다 (앵커링 방지, divergence 트리거 보전)
    aux = (f"\n\n[정량·오픈웨이트 참조 — Outside view 보조 (base rate 참조일 뿐 매매 신호 아님)]\n"
           f"{aux_context}") if aux_context else ""
    return f"""오늘: {today.isoformat()} (KST)

[예측 질문]
{q.question}

[판정 기준] {q.resolution}
[판정 출처] {q.resolution_source}
[도메인] {q.domain}{window}

[확정 필요 스냅샷]
{snapshots}{aux}

[리서치 증거 패키지 — 아래 자료만 근거로 사용]
{evidence}
"""


def run_reasoning(client: anthropic.Anthropic, q: Question, briefs: list[EvidenceBrief],
                  prompts_dir: Path, budget: PipelineBudget, today: date,
                  window_end: date | None,
                  aux_context: str | None = None) -> tuple[ForecastResult, Usage]:
    system = load_system_prompt(prompts_dir)
    user = build_user_prompt(q, briefs, today, window_end, aux_context)
    return reasoning_call(client, system, user, budget)
