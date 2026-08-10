"""Append-only provider shadow observations for future, newly-run forecasts only."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from . import config
from .agents.base import run_research
from .aggregator import SingleRun
from .llm import PipelineBudget
from .llm_provider import LLMProvider
from .models import Question


SHADOW_HEADER = [
    "forecast_id",
    "forecast_date",
    "question_id",
    "provider",
    "model",
    "snapshot",
    "prompt_version",
    "probability",
    "ci80_lo",
    "ci80_hi",
    "sources_count",
    "cost_usd",
    "status",
    "notes",
]


@dataclass(frozen=True)
class ShadowObservation:
    forecast_id: str
    forecast_date: str
    question_id: str
    provider: str
    model: str
    snapshot: str
    prompt_version: str
    probability: int
    ci80_lo: int
    ci80_hi: int
    sources_count: int
    cost_usd: float
    status: str = "shadow"
    notes: str = "별도 benchmark 관측; 공식 확률과 결합하지 않음"


def should_run_shadow(question_id: str) -> bool:
    """Shadow is opt-in by both a dated model and an explicit question allowlist."""
    return bool(
        config.OPENAI_SHADOW_MODEL
        and question_id in config.OPENAI_SHADOW_QUESTION_IDS
    )


def run_shadow(
    provider: LLMProvider,
    question: Question,
    official_forecast_id: str,
    prompts_dir: Path,
    today: date,
    window_end: date | None,
    *,
    n_agents: int,
    budget_usd: float | None = None,
    aux_context: str | None = None,
) -> ShadowObservation:
    """Run a fully separate provider path without changing the official result."""
    budget = PipelineBudget(
        limit_usd=budget_usd or config.OPENAI_SHADOW_PIPELINE_BUDGET
    )
    briefs = run_research(provider, question, n_agents, budget, today)
    estimate = SingleRun().estimate(
        provider,
        question,
        briefs,
        prompts_dir,
        budget,
        today,
        window_end,
        aux_context=aux_context,
    )
    identity = provider.identity
    return ShadowObservation(
        forecast_id=f"{official_forecast_id}__{identity.provider}__{identity.snapshot}",
        forecast_date=today.isoformat(),
        question_id=question.question_id,
        provider=identity.provider,
        model=identity.model,
        snapshot=identity.snapshot,
        prompt_version=identity.version,
        probability=estimate.probability,
        ci80_lo=estimate.ci80_lo,
        ci80_hi=estimate.ci80_hi,
        sources_count=sum(item.sources_count for item in briefs),
        cost_usd=round(budget.spent_usd, 6),
    )


def append_shadow(path: Path, observation: ShadowObservation) -> None:
    """Append one immutable provider observation, creating only a new ledger header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with open(path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHADOW_HEADER)
        if not exists:
            writer.writeheader()
        writer.writerow(asdict(observation))


def read_shadow(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SHADOW_HEADER:
            raise ValueError(f"provider shadow ledger header mismatch: {reader.fieldnames}")
        return list(reader)

