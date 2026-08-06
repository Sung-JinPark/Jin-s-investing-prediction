from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.db import ingest, queries
from ai_fc import files as F
from ai_fc.provider_governance import (
    APPROVAL_HEADER,
    ProviderApprovalError,
    assert_official_provider_allowed,
)
from ai_fc.llm import PipelineBudget, Usage
from ai_fc.llm_provider import ProviderIdentity
from ai_fc.orchestrator import _persist_failed_costs


def test_established_anthropic_provider_needs_no_new_approval(tmp_path: Path) -> None:
    assert_official_provider_allowed(tmp_path, "anthropic", "claude-opus-4-8")


def test_openai_official_switch_is_blocked_without_exact_approval(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration"
    calibration.mkdir()
    (calibration / "approvals.csv").write_text(
        ",".join(APPROVAL_HEADER) + "\n", encoding="utf-8"
    )
    with pytest.raises(ProviderApprovalError):
        assert_official_provider_allowed(
            tmp_path, "openai", "gpt-5.6-terra-2026-08-01"
        )


def test_openai_official_switch_requires_matching_snapshot_and_reviewer(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration"
    calibration.mkdir()
    (calibration / "approvals.csv").write_text(
        ",".join(APPROVAL_HEADER) + "\n"
        "2026-08-01,official_llm_provider_change,anthropic,"
        "openai:gpt-5.6-terra-2026-08-01,official_llm_provider,approved,"
        "human-owner,paired gate accepted,abc123\n",
        encoding="utf-8",
    )

    assert_official_provider_allowed(
        tmp_path, "openai", "gpt-5.6-terra-2026-08-01"
    )
    with pytest.raises(ProviderApprovalError):
        assert_official_provider_allowed(
            tmp_path, "openai", "gpt-5.6-sol-2026-08-01"
        )


def test_cost_log_keeps_provider_identity_separate(tmp_path: Path) -> None:
    conn = ingest.connect(tmp_path / "index.db")
    queries.log_cost(conn, "q", "reasoning", "claude", 10, 5, 0.1)
    queries.log_cost(
        conn, "q", "shadow:forecast", "gpt", 20, 8, 0.2,
        provider="openai", snapshot="gpt-test-2026-08-01",
        cached_input_tokens=4, web_search_calls=2,
    )

    rows = queries.provider_cost_summary(conn)
    assert {row["provider"] for row in rows} == {"anthropic", "openai"}
    openai = next(row for row in rows if row["provider"] == "openai")
    assert openai["cached_input_tokens"] == 4
    assert openai["web_search_calls"] == 2


def test_cost_log_survives_a_fresh_sqlite_index(tmp_path: Path) -> None:
    ledger = tmp_path / "calibration" / "cost_log.csv"
    first = ingest.connect(tmp_path / "first.db")
    queries.log_cost(
        first, "q", "research:general", "gpt-5.6-terra", 100, 20, 0.004,
        provider="openai", snapshot="gpt-5.6-terra", request_id="resp_1",
        cached_input_tokens=25, web_search_calls=1, ledger_path=ledger,
    )
    first.close()

    second = ingest.connect(tmp_path / "second.db")
    report = ingest.DriftReport()
    ingest._sync_cost_log(second, tmp_path, report)

    assert report.ok
    row = second.execute("SELECT * FROM cost_log").fetchone()
    assert row["request_id"] == "resp_1"
    assert row["cached_input_tokens"] == 25
    assert F.parse_cost_log(ledger)[0]["cost_usd"] == pytest.approx(0.004)


def test_failed_pipeline_usage_is_persisted_before_reraising(tmp_path: Path) -> None:
    conn = ingest.connect(tmp_path / "index.db")
    budget = PipelineBudget(1.5)
    budget.add(Usage(120, 30, 0.002, "resp_failed", 20, 1))
    identity = ProviderIdentity(
        provider="openai", model="gpt-5.6-terra", snapshot="gpt-5.6-terra",
        version="v1",
    )

    _persist_failed_costs(conn, tmp_path, "q", identity, budget)

    row = F.parse_cost_log(tmp_path / "calibration" / "cost_log.csv")[0]
    assert row["stage"] == "failed:pipeline:1"
    assert row["request_id"] == "resp_failed"
    assert row["web_search_calls"] == 1
