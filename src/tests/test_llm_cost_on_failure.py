"""추론 출력이 검증에서 떨어져도 그 호출의 비용은 원장에 남아야 한다.

배경(2026-09-11 실측): 추론 계약(`anchor_pct + Σdelta_pp == probability`)은 **교차 필드
항등식이라 JSON Schema 로 표현할 수 없다** — 서버가 못 막고 전량이 클라이언트 검증이다.
그 검증이 비용 계상보다 먼저 터지면 토큰은 청구됐는데 원장에는 0 원으로 남는다.
`asml-eps-beat-2026q3` 실패 2건의 추론 비용 $1.564 가 그렇게 사라졌다.

이 파일은 origin/main 의 `37ca3b66` 에서 왔고, 2026-09-11 병합(`17858ec2`)에서 통째로
삭제됐다 — 그 병합이 `messages.parse` + raw-response 헤더 경로를 버리고 `messages.create`
경로를 채택했기 때문이다. 경로와 함께 사라진 내부 헬퍼(`_raw_payload`·
`_reasoning_usage_from_raw`)의 테스트 3건은 되살리지 않는다: 읽지 않는 원시 페이로드의
접근자 모양을 지킬 이유가 없다.

되살리는 것은 **행동 테스트**다. `test_reasoning_contract.py` 가 같은 성질을 가짜 클라이언트
객체로 이미 덮지만, 여기서는 **실제 anthropic SDK 를 httpx MockTransport 위에 올린다** —
`resp.usage` 의 모양이나 SDK 의 응답 객체가 바뀌는 날을 잡는 것은 이쪽뿐이다. 네트워크도
API 키도 쓰지 않는다.
"""
from __future__ import annotations

import json

import anthropic
import anthropic._base_client as _base_client
import pytest

from ai_fc import config, llm

# anthropic 0.105 은 httpx, 1.5 는 httpx2 위에 올라간다(CI 가 후자를 설치한다).
# 둘 다 깔려 있을 수 있으므로 이름으로 고르지 않고 **SDK 가 실제로 쓰는 모듈**을 집는다 —
# http_client 타입이 어긋나면 SDK 가 조용히 자기 클라이언트를 새로 만든다.
_http = getattr(_base_client, "httpx", None) or getattr(_base_client, "httpx2", None)
pytestmark = pytest.mark.skipif(_http is None, reason="SDK 의 HTTP 모듈을 찾지 못함")


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
    transport = _http.MockTransport(lambda request: _http.Response(200, json=body))
    return anthropic.Anthropic(api_key="test-key",
                               http_client=_http.Client(transport=transport))


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
    # 교정 재시도도 실제로 과금된다 — 두 번 다 계상돼야 원장이 청구서와 맞는다.
    # (MockTransport 가 같은 위반 본문을 다시 주므로 재시도도 떨어진다)
    assert len(budget.calls) == 2


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
    assert usage.request_id == "msg_test"


def test_usage_reader_agrees_between_object_and_raw_json() -> None:
    """속성이 없어도 0 으로 읽어야 한다 — 여기서 터지면 비용이 통째로 사라진다.

    `_usage_of` 는 `budget.add` **전**에 호출된다. 예전 구현처럼 `u.input_tokens` 를 직접
    읽으면 SDK 가 필드 이름을 바꾸는 날 AttributeError 로 터지고, 2026-09-11 과 똑같이
    청구는 되고 기록은 0 원이 된다.
    """
    fields = {"input_tokens": 100, "cache_creation_input_tokens": 50,
              "cache_read_input_tokens": 200, "output_tokens": 7}

    class _Usage:
        pass

    obj = _Usage()
    for key, value in fields.items():
        setattr(obj, key, value)

    assert llm._usage_fields(obj) == llm._usage_fields(fields) == (170, 7)
    assert llm._usage_fields(_Usage()) == (0, 0), "필드가 없어도 예외 없이 0"
