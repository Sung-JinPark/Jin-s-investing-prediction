from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_fc.scenario_v4_shadow import (
    ScenarioV4ShadowError,
    build_shadow_payload,
    validate_shadow_payload,
)


ROOT = Path(__file__).resolve().parents[2]


def test_v4_shadow_uses_actual_member_paths_and_blocks_promotion() -> None:
    repo = ROOT
    official = json.loads((repo / "data/scenarios/nasdaq_latest.json").read_text(encoding="utf-8"))
    shadow = build_shadow_payload(official)

    assert shadow["status"] == "shadow_only"
    assert shadow["dashboard_toggle_default"] == "off"
    assert shadow["promotion_state"] == "blocked_pending_rolling_origin_validation"
    assert shadow["source_snapshot_id"] == official["snapshot_id"]
    assert shadow["official_weighted_mixture_fan"]["probability_space"] == (
        "official_weighted_mixture"
    )
    assert shadow["guardrails"]["conditional_fan_distinct_from_official_weighted_mixture"]
    assert shadow["guardrails"]["calendar_year_state_reset_2026_to_2027"] is False
    assert [row["year"] for row in official["structural_forecast"]["years"]] == [2026, 2027]

    for key in ("S1", "S2", "S3"):
        median_sample = next(
            row for row in official["path_realism"][key]["sample_paths"]
            if row["terminal_percentile"] == 50
        )
        assert shadow["paths"][key]["values"] == median_sample["values"]
        assert shadow["paths"][key]["member_path_index"] == median_sample["path_index"]
        assert shadow["scenario_conditional_fans"][key]["status"] == (
            "coarse_member_sample_only"
        )
        assert "not_confirmed" in shadow["scenario_conditional_fans"][key]


def test_v4_shadow_rejects_forbidden_guardrail_drift() -> None:
    repo = ROOT
    official = json.loads((repo / "data/scenarios/nasdaq_latest.json").read_text(encoding="utf-8"))
    shadow = build_shadow_payload(official)
    shadow["guardrails"]["endpoint_forcing"] = True

    with pytest.raises(ScenarioV4ShadowError, match="endpoint_forcing"):
        validate_shadow_payload(shadow)
