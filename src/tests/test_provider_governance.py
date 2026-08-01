from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.db import ingest, queries
from ai_fc.provider_governance import (
    APPROVAL_HEADER,
    ProviderApprovalError,
    assert_official_provider_allowed,
)


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

