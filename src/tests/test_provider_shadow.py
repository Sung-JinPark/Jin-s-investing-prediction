from __future__ import annotations

from datetime import date
from pathlib import Path

from ai_fc.llm import PipelineBudget, Usage
from ai_fc.llm_provider import ProviderIdentity
from ai_fc.models import Question
from ai_fc.provider_shadow import append_shadow, read_shadow, run_shadow
from ai_fc.schemas import ForecastResult


class FakeProvider:
    identity = ProviderIdentity(
        provider="openai",
        model="gpt-test-2026-08-01",
        snapshot="gpt-test-2026-08-01",
        version="reasoning_core_v1",
        role="shadow",
    )

    def research(self, system, user, budget: PipelineBudget, max_search_uses=None):
        usage = Usage(100, 50, 0.1)
        budget.add(usage)
        return "evidence", 2, usage

    def reasoning(self, system, user, budget: PipelineBudget):
        usage = Usage(100, 50, 0.2)
        budget.add(usage)
        return ForecastResult(
            question_check="ok",
            reference_class="base",
            base_rates=["a", "b", "c"],
            anchor_pct=50,
            adjustments=[],
            decomposition="tree",
            premortem=["a", "b", "c"],
            probability=61,
            ci80_lo=45,
            ci80_hi=74,
            key_reasons=["a", "b", "c"],
            observables=["a", "b"],
            snapshots_filled=[],
            unverified_notes=[],
        ), usage

    def structured(self, *args, **kwargs):
        raise NotImplementedError


def _question() -> Question:
    return Question(
        question_id="future-question",
        title="Future",
        question="Will it happen?",
        deadline_kind="fixed",
        deadline=date(2099, 12, 31),
        rolling_days=None,
        resolution="yes if true",
        resolution_source="official",
        domain="macro",
        cadence_raw="manual",
        schedule=[],
        action_link="",
        status="active",
        created=date(2099, 1, 1),
        notes="",
        required_snapshots=[],
        src_hash="fixture",
    )


def test_shadow_is_separate_and_append_only(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "reasoning_core_v1.md").write_text("system", encoding="utf-8")
    observation = run_shadow(
        FakeProvider(),
        _question(),
        "2099-08-01_future-question_r1",
        prompts,
        date(2099, 8, 1),
        date(2099, 12, 31),
        n_agents=2,
        budget_usd=2,
    )

    assert observation.probability == 61
    assert observation.status == "shadow"
    assert observation.cost_usd == 0.4
    ledger = tmp_path / "calibration" / "provider_shadow_ledger.csv"
    append_shadow(ledger, observation)
    append_shadow(ledger, observation)
    rows = read_shadow(ledger)
    assert len(rows) == 2
    assert all(row["provider"] == "openai" for row in rows)
    assert all("결합하지 않음" in row["notes"] for row in rows)
