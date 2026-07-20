"""Anthropic 래퍼: 재시도·토큰/검색 미터링·예산 중단.

- 리서치: messages.create + 서버사이드 web_search_20260209 (pause_turn 루프 처리)
- 추론: messages.parse + Pydantic (structured outputs)
- 모든 호출의 비용을 계산해 PipelineBudget에 가산. 초과 시 즉시 중단.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import anthropic

from . import config
from .schemas import ForecastResult


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class PipelineBudget:
    limit_usd: float
    spent_usd: float = 0.0
    calls: list[Usage] = field(default_factory=list)

    def add(self, usage: Usage) -> None:
        self.calls.append(usage)
        self.spent_usd += usage.cost_usd

    def ensure_room(self, stage: str) -> None:
        if self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(
                f"파이프라인 예산 초과: ${self.spent_usd:.2f} >= ${self.limit_usd:.2f} ({stage} 전 중단)")


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = config.PRICES.get(model, (5.0, 25.0))
    return input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price


def _usage_of(resp, model: str) -> Usage:
    u = resp.usage
    inp = (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) \
        + (getattr(u, "cache_read_input_tokens", 0) or 0) // 10  # 캐시 읽기는 ~0.1x
    out = u.output_tokens or 0
    return Usage(inp, out, _cost(model, inp, out))


def _with_retries(fn):
    last = None
    for attempt in range(config.LLM_MAX_RETRIES):
        try:
            return fn()
        except (anthropic.RateLimitError, anthropic.InternalServerError,
                anthropic.APIConnectionError) as exc:
            last = exc
            time.sleep(2 ** attempt * 2)
        # BadRequest 등 4xx는 재시도 없이 즉시 전파
    raise last


def research_call(client: anthropic.Anthropic, system: str, user: str,
                  budget: PipelineBudget,
                  max_search_uses: int | None = None) -> tuple[str, int, Usage]:
    """웹서치 리서치 1회. (본문 텍스트, 검색결과 블록 수, 사용량) 반환.

    max_search_uses: per-call 검색 상한 (v3 WS-B lite 티어) — None이면 전역 기본.
    검색이 전멸(성공 0건 + 오류 블록 존재 — 분당 검색 한도 초과 등)하면
    65초 냉각 후 1회 재실행한다. 재시도 비용도 예산에 정직하게 가산.
    """
    model = config.RESEARCH_MODEL
    search_limit = max_search_uses if max_search_uses is not None \
        else config.WEB_SEARCH_MAX_USES
    total = Usage()

    for search_attempt in range(2):
        budget.ensure_room("research")
        messages = [{"role": "user", "content": user}]
        text_parts: list[str] = []
        n_sources = 0
        n_search_errors = 0

        for _ in range(5):  # pause_turn 연속 재개 상한
            resp = _with_retries(lambda: client.messages.create(
                model=model,
                max_tokens=config.RESEARCH_MAX_TOKENS,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                tools=[{"type": "web_search_20260209", "name": "web_search",
                        "max_uses": search_limit}],
                messages=messages,
            ))
            u = _usage_of(resp, model)
            total = Usage(total.input_tokens + u.input_tokens,
                          total.output_tokens + u.output_tokens,
                          total.cost_usd + u.cost_usd)
            budget.add(u)

            for block in resp.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "web_search_tool_result":
                    content = block.content
                    if isinstance(content, list):  # 오류 시 객체, 성공 시 리스트
                        n_sources += len(content)
                    else:
                        n_search_errors += 1

            if resp.stop_reason == "pause_turn":
                messages = messages + [{"role": "assistant", "content": resp.content}]
                continue
            if resp.stop_reason == "refusal":
                raise RuntimeError("리서치 호출이 refusal로 종료됨")
            break

        if n_sources == 0 and n_search_errors > 0 and search_attempt == 0:
            time.sleep(65)  # 분당 검색 한도 냉각
            continue
        return "\n".join(text_parts).strip(), n_sources, total

    return "\n".join(text_parts).strip(), n_sources, total


def structured_call(client: anthropic.Anthropic, system: str, user: str,
                    budget: PipelineBudget, output_format,
                    max_tokens: int = 2000):
    """소형 구조화 호출 (WS6 divergence 사후 리뷰 등). 파싱 실패 시 예외."""
    budget.ensure_room("structured")
    model = config.REASONING_MODEL
    resp = _with_retries(lambda: client.messages.parse(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        output_format=output_format))
    usage = _usage_of(resp, model)
    budget.add(usage)
    parsed = resp.parsed_output
    if parsed is None:
        raise RuntimeError("structured 출력 파싱 실패")
    return parsed, usage


def reasoning_call(client: anthropic.Anthropic, system: str, user: str,
                   budget: PipelineBudget) -> tuple[ForecastResult, Usage]:
    """추론 코어 1회 — structured output 강제. 파싱 실패 시 예외 (숫자 추측 금지)."""
    budget.ensure_room("reasoning")
    model = config.REASONING_MODEL

    resp = _with_retries(lambda: client.messages.parse(
        model=model,
        max_tokens=config.REASONING_MAX_TOKENS,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],  # 다질문 연속 실행 시 캐시
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": user}],
        output_format=ForecastResult,
    ))
    usage = _usage_of(resp, model)
    budget.add(usage)

    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("추론 호출이 refusal로 종료됨")
    parsed = resp.parsed_output
    if parsed is None:
        raise RuntimeError("추론 출력 파싱 실패 — 기록하지 않고 중단")
    if not (1 <= parsed.probability <= 99) or parsed.ci80_lo > parsed.ci80_hi:
        raise RuntimeError(f"추론 출력 검증 실패: p={parsed.probability}, "
                           f"ci=[{parsed.ci80_lo},{parsed.ci80_hi}]")
    return parsed, usage
