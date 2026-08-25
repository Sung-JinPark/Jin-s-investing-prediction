from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ai_fc.timeseries_v7.budget import durable_control_sql, preflight_budget
from ai_fc.timeseries_v7.scheduler import GenerationEvidence, decide_generation, generation_input_hash, task_blueprint
from ai_fc.timeseries_v7.security import SecurityBoundaryError, assert_write_paths, sanitized_environment, secret_name_matches


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def test_wait_data_is_nonfailure_without_new_evidence() -> None:
    decision = decide_generation(GenerationEvidence(), now=NOW, last_generation_at=None, input_hash="a", prior_input_hashes=set())
    assert decision.state == "WAIT_DATA" and decision.create_generation is False


def test_generation_requires_trigger_interval_and_novel_snapshot() -> None:
    evidence = GenerationEvidence(matured_weekly_origins=4)
    assert decide_generation(evidence, now=NOW, last_generation_at=NOW - timedelta(days=27), input_hash="a", prior_input_hashes=set()).state == "WAIT_DATA"
    assert decide_generation(evidence, now=NOW, last_generation_at=NOW - timedelta(days=28), input_hash="a", prior_input_hashes=set()).create_generation
    assert decide_generation(evidence, now=NOW, last_generation_at=None, input_hash="a", prior_input_hashes={"a"}).reason == "same_input_hash_duplicate_generation"


def test_task_blueprint_is_complete_ordered_and_restart_stable() -> None:
    first = task_blueprint("run", "cycle", "gen")
    second = task_blueprint("run", "cycle", "gen")
    assert first == second and len(first) == 19
    assert first[0]["dependency_task_key"] is None
    assert first[-1]["stage"] == "REVIEW_PROPOSAL"


def test_generation_input_hash_is_canonical() -> None:
    assert generation_input_hash({"b": 2, "a": 1}) == generation_input_hash({"a": 1, "b": 2})


def test_noncollector_workers_cannot_see_provider_secrets() -> None:
    source = {"PATH": "x", "FRED_API_KEY": "secret", "CUSTOM_PROVIDER_TOKEN": "secret", "GITHUB_TOKEN": "secret"}
    for capability in ("materializer", "trainer_cpu", "evaluator", "codex_worker"):
        environment = sanitized_environment(capability, source)
        assert secret_name_matches(environment) == []
        assert environment["PATH"] == "x"


def test_collector_cannot_modify_code_and_no_worker_touches_secrets_file() -> None:
    with pytest.raises(SecurityBoundaryError, match="collector cannot modify code"):
        assert_write_paths("collector", ["src/ai_fc/timeseries_v7/foo.py"])
    with pytest.raises(SecurityBoundaryError, match=".secrets"):
        assert_write_paths("codex_worker", [".secrets/provider.env"])


def test_budget_exhaustion_blocks_before_launch() -> None:
    decision = preflight_budget({"experiment_count": 750}, {"experiment_count": 1})
    assert decision.allowed is False and decision.state == "HOLD_BUDGET"
    assert decision.exhausted_resources == ("experiment_count",)


def test_zero_paid_api_budget_allows_no_positive_spend() -> None:
    assert preflight_budget({}, {"api_cost_usd": Decimal("0")}).allowed
    assert preflight_budget({}, {"api_cost_usd": Decimal("0.01")}).state == "HOLD_BUDGET"


def test_pause_and_abort_are_durable_states() -> None:
    assert durable_control_sql("PAUSE")[1] == "wait_data"
    assert durable_control_sql("ABORT")[1] == "cancelled"
