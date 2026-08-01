from __future__ import annotations

from ai_fc import llm
from ai_fc.llm_provider import AnthropicProvider, LLMProvider


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

