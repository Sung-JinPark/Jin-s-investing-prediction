"""원장 미터링이 실청구 항목을 전부 세는지 고정한다 (2026-10-28 실측 결함).

2026-10-26 Console 청구 대조: cost_log $14.89 vs 실청구 $29.43 (토큰 $27.20 +
웹서치 $2.23). 월 상한($50) 가드가 실지출의 51%만 보고 있었다. 누락 항목:
  (a) 웹서치 건당 요금 $10/1k — usage.server_tool_use.web_search_requests 가 정본
  (b) 캐시 쓰기 1.25x 할증 — 1.0x 로 세고 있었다
여기서 그 재발을 막는다. 질문·예측·판정 로직은 건드리지 않는다 (미터링 전용).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_fc import config, llm
from ai_fc.llm import PipelineBudget


def _usage_ns(**over) -> SimpleNamespace:
    base = {"input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    base.update(over)
    return SimpleNamespace(**base)


def test_web_search_fee_is_charged_per_billed_request() -> None:
    usage = _usage_ns(input_tokens=1_000_000,
                      server_tool_use=SimpleNamespace(web_search_requests=8,
                                                      web_fetch_requests=0))
    resp = SimpleNamespace(usage=usage, id="msg_ws")
    u = llm._usage_of(resp, "claude-opus-4-8")
    assert u.web_search_calls == 8
    assert u.cost_usd == pytest.approx(5.00 + 8 * config.WEB_SEARCH_COST_PER_CALL)


def test_cache_write_surcharge_and_read_discount_match_list_price() -> None:
    usage = _usage_ns(cache_creation_input_tokens=1_000_000,
                      cache_read_input_tokens=1_000_000)
    resp = SimpleNamespace(usage=usage, id="msg_cache")
    u = llm._usage_of(resp, "claude-opus-4-8")
    # 쓰기 1.25x($6.25) + 읽기 0.1x($0.50)
    assert u.cost_usd == pytest.approx(6.25 + 0.50)
    # ledger input_tokens 열의 블렌드 의미(쓰기 1x + 읽기 //10)는 소급 변경하지 않는다.
    assert u.input_tokens == 1_000_000 + 100_000
    assert u.cached_input_tokens == 1_000_000


def test_usage_without_server_tool_use_still_reads_zero() -> None:
    """구형 응답/테스트 스텁(server_tool_use 없음)에서도 예외 없이 0."""
    resp = SimpleNamespace(usage=_usage_ns(input_tokens=100, output_tokens=7), id=None)
    u = llm._usage_of(resp, "claude-opus-4-8")
    assert u.web_search_calls == 0
    assert u.cost_usd == pytest.approx(100 / 1e6 * 5 + 7 / 1e6 * 25)


def test_research_call_accumulates_search_fees_across_pause_turns() -> None:
    """pause_turn 재개가 몇 번이든 검색 건수·비용은 전부 합산돼 예산에 가산된다."""
    responses = [
        SimpleNamespace(
            usage=_usage_ns(input_tokens=10_000,
                            server_tool_use=SimpleNamespace(web_search_requests=3)),
            id="msg_1", stop_reason="pause_turn",
            content=[SimpleNamespace(type="web_search_tool_result", content=[1, 2, 3])],
        ),
        SimpleNamespace(
            usage=_usage_ns(input_tokens=20_000, output_tokens=500,
                            server_tool_use=SimpleNamespace(web_search_requests=2)),
            id="msg_2", stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="보고서")],
        ),
    ]
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: responses.pop(0)))
    budget = PipelineBudget(limit_usd=10.0)

    text, n_sources, total = llm.research_call(client, "system", "user", budget)

    assert text == "보고서"
    assert n_sources == 3
    assert total.web_search_calls == 5
    assert budget.spent_usd == pytest.approx(total.cost_usd)
    assert total.cost_usd == pytest.approx(
        30_000 / 1e6 * 5 + 500 / 1e6 * 25 + 5 * config.WEB_SEARCH_COST_PER_CALL)
