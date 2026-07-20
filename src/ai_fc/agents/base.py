"""ResearchAgent — 프로필 프롬프트 + web_search 호출 → EvidenceBrief."""

from __future__ import annotations

from datetime import date

import anthropic

from .. import config
from ..llm import PipelineBudget, research_call
from ..models import EvidenceBrief, Question
from .profiles import PROFILE_SETS, get_profile


def _user_prompt(q: Question, today: date) -> str:
    snapshots = "\n".join(f"- {s}" for s in q.required_snapshots) or "- (명시된 필수 스냅샷 없음)"
    deadline = (
        q.deadline.isoformat() if q.deadline_kind == "fixed" and q.deadline
        else f"rolling {q.rolling_days}일" if q.deadline_kind == "rolling"
        else "미확정 — 발표/이벤트 일자를 반드시 확인해 보고할 것"
    )
    return f"""오늘: {today.isoformat()} (KST)

[예측 질문]
{q.question}

[판정 기준] {q.resolution}
[판정 출처] {q.resolution_source}
[기한] {deadline}
[도메인] {q.domain}

[반드시 확정해야 할 스냅샷 값]
{snapshots}

위 질문의 판정에 필요한 정보를 당신의 프로필 임무에 따라 조사해 보고하세요."""


def run_research(client: anthropic.Anthropic, q: Question, n_agents: int,
                 budget: PipelineBudget, today: date) -> list[EvidenceBrief]:
    profiles = PROFILE_SETS.get(n_agents, PROFILE_SETS[2])
    assert "devil" in profiles, "데블스 애드버킷 생략 금지"
    user = _user_prompt(q, today)

    # v3 WS-B lite 티어: 검색량·분량만 축소 — 프로필 구성(데블스 포함)은 불변 (헌법)
    lite = getattr(q, "tier", "standard") == "lite"
    words = config.LITE_RESEARCH_WORDS if lite else 900
    max_uses = config.LITE_SEARCH_MAX_USES if lite else None

    def one(profile: str) -> EvidenceBrief:
        text, n_sources, usage = research_call(
            client, get_profile(profile, words), user, budget,
            max_search_uses=max_uses)
        if not text:
            raise RuntimeError(f"{profile} 에이전트가 빈 보고서 반환")
        return EvidenceBrief(profile=profile, text=text, sources_count=n_sources,
                             cost_usd=usage.cost_usd,
                             input_tokens=usage.input_tokens,
                             output_tokens=usage.output_tokens)

    # 순차 실행 — 병렬 시 서버사이드 web_search 분당 한도를 버스트로 초과
    # ("Server tool use limit exceeded", 2026-07-15 실측). 벽시계보다 회수율 우선.
    return [one(p) for p in profiles]
