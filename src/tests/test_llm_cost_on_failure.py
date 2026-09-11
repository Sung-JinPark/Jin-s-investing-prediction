"""추론 출력이 검증에서 떨어져도 그 호출의 비용은 원장에 남아야 한다.

배경(2026-09-11 실측): SDK 의 messages.parse 는 응답을 받은 직후 곧바로 스키마 검증을
돌린다. 검증이 실패하면 예외가 usage 를 들고 나가 버려, 토큰은 청구됐는데 로컬 원장에는
0 원으로 남았다 — asml-eps-beat-2026q3 실패 2건의 추론 비용이 통째로 누락됐다.

여기서는 실제 anthropic SDK 를 httpx MockTransport 위에 올려 검증한다. 응답 본문을
직접 만들어 주므로 네트워크도 API 키도 필요 없고, SDK 가 헤더를 무시하도록 바뀌면
(폴백 경로로 내려가면서) 검증 실패 케이스가 곧바로 빨간불이 된다.
"""
from __future__ import annotations

import json

import anthropic
import httpx
import pytest

from ai_fc import config, llm


def _message(payload: dict, *, input_tokens: int = 1000, output_tokens: int = 500) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": config.REASONING_MODEL,
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def _client(body: dict) -> anthropic.Anthropic:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    return anthropic.Anthropic(api_key="test-key",
                               http_client=httpx.Client(transport=transport))


def _forecast_payload(*, anchor: int, deltas: list[float], probability: int) -> dict:
    """anchor + Σ(조정) 과 최종 확률이 어긋나게도 만들 수 있는 스키마 준수 본문."""
    return {
        "question_check": "해소가능 — 기한·임계값 확정",
        "reference_class": "참조 클래스",
        "base_rates": ["base rate 1", "base rate 2", "base rate 3"],
        "anchor_pct": anchor,
        "adjustments": [
            {"evidence": f"근거 {index}", "direction": "up" if delta >= 0 else "down",
             "delta_pp": abs(delta)}
            for index, delta in enumerate(deltas)
        ],
        "decomposition": "분해 트리",
        "premortem": ["틀릴 이유 1", "틀릴 이유 2", "틀릴 이유 3"],
        "probability": probability,
        "ci80_lo": max(1, probability - 10),
        "ci80_hi": min(99, probability + 10),
        "key_reasons": ["근거 1", "근거 2", "근거 3"],
        "observables": ["지표 1", "지표 2"],
        "snapshots_filled": [],
        "unverified_notes": [],
    }


def test_arithmetic_violation_still_records_the_call_cost() -> None:
    """anchor 68 − 5 = 63 인데 최종 64 — 검증은 떨어지되 비용은 남아야 한다."""
    body = _message(_forecast_payload(anchor=68, deltas=[-5], probability=64))
    budget = llm.PipelineBudget(limit_usd=10.0)

    with pytest.raises(Exception) as caught:
        llm.reasoning_call(_client(body), "system", "user", budget)

    assert "anchor" in str(caught.value), "산술 정합성 가드가 사유여야 한다"
    assert budget.spent_usd > 0, "검증 실패 호출의 비용이 누락되면 월 예산이 실제보다 낮게 잡힌다"
    assert budget.calls and budget.calls[-1].output_tokens == 500


def test_successful_call_records_the_same_cost_as_before() -> None:
    """정상 경로의 비용 계산은 바뀌지 않는다 — 캐시 토큰 가중치 포함."""
    body = _message(_forecast_payload(anchor=60, deltas=[5, -5], probability=60))
    body["usage"]["cache_read_input_tokens"] = 2000
    budget = llm.PipelineBudget(limit_usd=10.0)

    parsed, usage = llm.reasoning_call(_client(body), "system", "user", budget)

    assert parsed.probability == 60
    # 1000 + 2000//10 = 1200
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 500
    assert budget.spent_usd == pytest.approx(usage.cost_usd)


def test_usage_reader_agrees_between_object_and_raw_json() -> None:
    """원시 JSON 경로와 SDK 객체 경로가 같은 토큰 수를 내야 한다."""
    fields = {"input_tokens": 100, "cache_creation_input_tokens": 50,
              "cache_read_input_tokens": 200, "output_tokens": 7}

    class _Usage:
        pass

    obj = _Usage()
    for key, value in fields.items():
        setattr(obj, key, value)

    assert llm._usage_fields(obj) == llm._usage_fields(fields) == (170, 7)


def test_unreadable_usage_does_not_mask_the_real_failure() -> None:
    """비용을 못 읽었다고 예측 실패의 진짜 사유가 가려지면 안 된다."""

    class _Broken:
        text = "본문이 JSON 이 아님"

    assert llm._reasoning_usage_from_raw(_Broken(), config.REASONING_MODEL).cost_usd == 0.0
