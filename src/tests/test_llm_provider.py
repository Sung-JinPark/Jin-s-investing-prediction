from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai_fc import llm
from ai_fc.llm_provider import (
    AnthropicProvider,
    LLMProvider,
    OpenAIResponsesProvider,
    ProviderOutputError,
    SnapshotRequiredError,
)


def test_anthropic_adapter_preserves_existing_research_call(monkeypatch) -> None:
    marker = ("evidence", 3, llm.Usage(11, 7, 0.25))

    def fake(client, system, user, budget, max_search_uses=None):
        assert client == "client"
        assert max_search_uses == 4
        return marker

    monkeypatch.setattr(llm, "research_call", fake)
    provider = AnthropicProvider("client")

    assert isinstance(provider, LLMProvider)
    assert provider.research("system", "user", llm.PipelineBudget(4), 4) == marker
    assert provider.identity.provider == "anthropic"
    assert provider.identity.role == "official"


def test_provider_identity_is_registry_ready() -> None:
    identity = AnthropicProvider("client").identity.as_registry_params()

    assert set(identity) == {"provider", "model", "snapshot", "version", "role"}
    assert identity["model"] == identity["snapshot"]


def _forecast_payload(probability: int = 63) -> dict:
    return {
        "question_check": "판정 가능",
        "reference_class": "동일 유형 사건",
        "base_rates": ["a", "b", "c"],
        "anchor_pct": 55,
        "adjustments": [],
        "decomposition": "분해",
        "premortem": ["a", "b", "c"],
        "probability": probability,
        "ci80_lo": 45,
        "ci80_hi": 75,
        "key_reasons": ["a", "b", "c"],
        "observables": ["a", "b"],
        "snapshots_filled": [],
        "unverified_notes": [],
    }


class _FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        annotation = SimpleNamespace(type="url_citation", url="https://example.test/source")
        part = SimpleNamespace(text=self.output_text, annotations=[annotation])
        return SimpleNamespace(
            id="resp_test_123",
            output_text=self.output_text,
            output=[SimpleNamespace(content=[part])],
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=50,
                input_tokens_details=SimpleNamespace(cached_tokens=20),
            ),
        )


def test_openai_adapter_accepts_explicit_tier_and_rejects_family_alias() -> None:
    provider = OpenAIResponsesProvider(model="gpt-5.6-terra", client=object())
    assert provider.identity.snapshot == "gpt-5.6-terra"

    with pytest.raises(SnapshotRequiredError):
        OpenAIResponsesProvider(model="gpt-5.6", client=object())


def test_openai_responses_research_uses_web_search() -> None:
    fake = _FakeResponses("evidence")
    provider = OpenAIResponsesProvider(
        model="gpt-5.6-terra-2026-08-01",
        client=SimpleNamespace(responses=fake),
    )

    text, sources, usage = provider.research("system", "user", llm.PipelineBudget(2), 3)

    assert text == "evidence"
    assert sources == 1
    assert usage.cost_usd > 0
    assert usage.request_id == "resp_test_123"
    assert usage.cached_input_tokens == 20
    assert fake.kwargs["tools"] == [{"type": "web_search"}]
    assert fake.kwargs["model"].endswith("2026-08-01")


def test_openai_tier_pricing_does_not_fall_back_to_sol() -> None:
    fake = _FakeResponses("evidence")
    provider = OpenAIResponsesProvider(
        model="gpt-5.6-terra",
        client=SimpleNamespace(responses=fake),
    )

    _text, _sources, usage = provider.research(
        "system", "user", llm.PipelineBudget(2), 3
    )

    expected = ((100 - 20) * 2.0 + 20 * 2.0 * 0.1 + 50 * 12.0) / 1e6
    assert usage.cost_usd == pytest.approx(expected)


def test_openai_reasoning_enforces_common_output_contract() -> None:
    fake = _FakeResponses(json.dumps(_forecast_payload()))
    provider = OpenAIResponsesProvider(
        model="gpt-5.6-sol-2026-08-01",
        client=SimpleNamespace(responses=fake),
    )

    result, _usage = provider.reasoning("system", "user", llm.PipelineBudget(4))

    assert result.probability == 63
    assert fake.kwargs["text"]["format"]["strict"] is True
    schema = fake.kwargs["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Adjustment"]["additionalProperties"] is False
    assert schema["$defs"]["SnapshotItem"]["additionalProperties"] is False


def test_openai_reasoning_rejects_probability_outside_1_to_99() -> None:
    fake = _FakeResponses(json.dumps(_forecast_payload(100)))
    provider = OpenAIResponsesProvider(
        model="gpt-5.6-sol-2026-08-01",
        client=SimpleNamespace(responses=fake),
    )

    with pytest.raises(ProviderOutputError):
        provider.reasoning("system", "user", llm.PipelineBudget(4))
