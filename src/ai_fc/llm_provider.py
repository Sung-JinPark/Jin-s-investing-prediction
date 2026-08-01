"""Provider-neutral boundary for forecast research and structured reasoning.

The existing Anthropic implementation remains the official producer.  Additional
providers must implement this contract; provider outputs are never averaged or
otherwise combined here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol, runtime_checkable

from . import config, llm
from .llm import PipelineBudget, Usage
from .schemas import ForecastResult


@dataclass(frozen=True)
class ProviderIdentity:
    """Immutable identity stored with every new forecast or shadow observation."""

    provider: str
    model: str
    snapshot: str
    version: str
    role: str = "official"

    def as_registry_params(self) -> dict[str, str]:
        return asdict(self)


@runtime_checkable
class LLMProvider(Protocol):
    """Common provider contract used by research and forecast reasoning."""

    identity: ProviderIdentity

    def research(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
        max_search_uses: int | None = None,
    ) -> tuple[str, int, Usage]: ...

    def structured(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
        output_format: type,
        max_tokens: int = 2000,
    ) -> tuple[Any, Usage]: ...

    def reasoning(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
    ) -> tuple[ForecastResult, Usage]: ...


class AnthropicProvider:
    """Adapter that preserves the pre-abstraction Anthropic call path exactly."""

    def __init__(self, client: Any, *, role: str = "official") -> None:
        self.client = client
        self.identity = ProviderIdentity(
            provider="anthropic",
            model=config.REASONING_MODEL,
            snapshot=config.REASONING_MODEL,
            version=config.PROMPT_VERSION,
            role=role,
        )

    def research(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
        max_search_uses: int | None = None,
    ) -> tuple[str, int, Usage]:
        return llm.research_call(
            self.client,
            system,
            user,
            budget,
            max_search_uses=max_search_uses,
        )

    def structured(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
        output_format: type,
        max_tokens: int = 2000,
    ) -> tuple[Any, Usage]:
        return llm.structured_call(
            self.client,
            system,
            user,
            budget,
            output_format,
            max_tokens=max_tokens,
        )

    def reasoning(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
    ) -> tuple[ForecastResult, Usage]:
        return llm.reasoning_call(self.client, system, user, budget)

