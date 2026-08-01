"""Provider-neutral boundary for forecast research and structured reasoning.

The existing Anthropic implementation remains the official producer.  Additional
providers must implement this contract; provider outputs are never averaged or
otherwise combined here.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol, runtime_checkable

from . import config, llm
from .llm import PipelineBudget, Usage
from .schemas import ForecastResult


_DATED_SNAPSHOT = re.compile(r"^gpt-[a-z0-9.-]+-20\d{2}-\d{2}-\d{2}$")


class SnapshotRequiredError(ValueError):
    """Raised when a moving OpenAI alias is supplied to the forecast pipeline."""


class ProviderOutputError(RuntimeError):
    """Raised when a provider returns data outside the common output contract."""


def require_dated_openai_snapshot(model: str) -> str:
    """Fail closed on aliases so track-record identity cannot drift silently."""
    if not _DATED_SNAPSHOT.fullmatch(model):
        raise SnapshotRequiredError(
            "OpenAI forecast models require a verified dated snapshot id; "
            f"moving alias is not allowed: {model or '<empty>'}"
        )
    return model


def validate_forecast_output(value: Any) -> ForecastResult:
    """Enforce the provider-independent 1..99 probability result contract."""
    try:
        result = value if isinstance(value, ForecastResult) else ForecastResult.model_validate(value)
    except Exception as exc:  # Pydantic keeps the field-level detail in the cause.
        raise ProviderOutputError(f"forecast output schema mismatch: {exc}") from exc
    if not 1 <= result.probability <= 99:
        raise ProviderOutputError(f"probability must be an integer in 1..99: {result.probability}")
    if not (1 <= result.ci80_lo <= result.ci80_hi <= 99):
        raise ProviderOutputError(
            f"ci80 must satisfy 1 <= lo <= hi <= 99: {result.ci80_lo}, {result.ci80_hi}"
        )
    return result


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
        result, usage = llm.reasoning_call(self.client, system, user, budget)
        return validate_forecast_output(result), usage


class OpenAIResponsesProvider:
    """OpenAI Responses API adapter with built-in web search and strict snapshots.

    The SDK import is lazy so existing Anthropic-only installations and read-only
    dashboard jobs keep working.  Production construction requires the ``openai``
    project extra and ``OPENAI_API_KEY``; tests inject a deterministic fake client.
    """

    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        api_key: str | None = None,
        role: str = "shadow",
    ) -> None:
        snapshot = require_dated_openai_snapshot(model)
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - installation error path
                raise RuntimeError("OpenAI provider requires the 'openai' package") from exc
            key = api_key or config.get_openai_api_key()
            if not key:
                raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider")
            client = OpenAI(api_key=key)
        self.client = client
        self.identity = ProviderIdentity(
            provider="openai",
            model=model,
            snapshot=snapshot,
            version=config.PROMPT_VERSION,
            role=role,
        )

    def _create(self, **kwargs: Any) -> Any:
        last: Exception | None = None
        for attempt in range(config.LLM_MAX_RETRIES):
            try:
                return self.client.responses.create(**kwargs)
            except Exception as exc:  # SDK exception classes are intentionally optional.
                last = exc
                name = type(exc).__name__.lower()
                if not any(token in name for token in ("rate", "timeout", "connection", "server")):
                    raise
                if attempt + 1 < config.LLM_MAX_RETRIES:
                    time.sleep(2 ** attempt * 2)
        assert last is not None
        raise last

    def _usage(self, response: Any) -> Usage:
        raw = getattr(response, "usage", None)
        inp = int(getattr(raw, "input_tokens", 0) or 0)
        out = int(getattr(raw, "output_tokens", 0) or 0)
        details = getattr(raw, "input_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        # Cached tokens use the official 90% discount.  Unknown snapshots inherit
        # the base family price only after the operator maps it in config.PRICES.
        family = self.identity.model.rsplit("-", 3)[0]
        in_price, out_price = config.PRICES.get(family, (5.0, 30.0))
        cost = ((inp - cached) * in_price + cached * in_price * 0.1 + out * out_price) / 1e6
        return Usage(inp, out, cost)

    @staticmethod
    def _text(response: Any) -> str:
        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for part in getattr(item, "content", []) or []:
                value = getattr(part, "text", None)
                if isinstance(value, str):
                    chunks.append(value)
        return "\n".join(chunks).strip()

    @staticmethod
    def _citation_count(response: Any) -> int:
        urls: set[str] = set()
        for item in getattr(response, "output", []) or []:
            for part in getattr(item, "content", []) or []:
                for annotation in getattr(part, "annotations", []) or []:
                    if getattr(annotation, "type", "") == "url_citation":
                        url = getattr(annotation, "url", "")
                        if url:
                            urls.add(str(url))
        return len(urls)

    @staticmethod
    def _format(output_format: type) -> dict[str, Any]:
        schema = output_format.model_json_schema()
        return {
            "type": "json_schema",
            "name": output_format.__name__.lower(),
            "schema": schema,
            "strict": True,
        }

    def research(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
        max_search_uses: int | None = None,
    ) -> tuple[str, int, Usage]:
        budget.ensure_room("openai:research")
        limit = max_search_uses or config.WEB_SEARCH_MAX_USES
        response = self._create(
            model=self.identity.snapshot,
            instructions=system,
            input=(f"{user}\n\n[도구 예산] web_search 호출은 최대 {limit}회 이내로 제한하라."),
            tools=[{"type": "web_search"}],
            reasoning={"effort": config.OPENAI_REASONING_EFFORT},
            max_output_tokens=config.RESEARCH_MAX_TOKENS,
        )
        usage = self._usage(response)
        budget.add(usage)
        text = self._text(response)
        if not text:
            raise ProviderOutputError("OpenAI research returned empty output")
        return text, self._citation_count(response), usage

    def structured(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
        output_format: type,
        max_tokens: int = 2000,
    ) -> tuple[Any, Usage]:
        budget.ensure_room("openai:structured")
        response = self._create(
            model=self.identity.snapshot,
            instructions=system,
            input=user,
            text={"format": self._format(output_format)},
            reasoning={"effort": config.OPENAI_REASONING_EFFORT},
            max_output_tokens=max_tokens,
        )
        usage = self._usage(response)
        budget.add(usage)
        try:
            parsed = output_format.model_validate(json.loads(self._text(response)))
        except Exception as exc:
            raise ProviderOutputError(f"OpenAI structured output mismatch: {exc}") from exc
        return parsed, usage

    def reasoning(
        self,
        system: str,
        user: str,
        budget: PipelineBudget,
    ) -> tuple[ForecastResult, Usage]:
        parsed, usage = self.structured(
            system,
            user,
            budget,
            ForecastResult,
            max_tokens=config.REASONING_MAX_TOKENS,
        )
        return validate_forecast_output(parsed), usage
