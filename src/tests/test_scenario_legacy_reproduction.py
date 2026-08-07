from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_fc.scenario_shadow.legacy_reproduction import (
    LegacyReproductionError,
    reproduce_legacy_snapshot,
)


ROOT = Path(__file__).resolve().parents[2]


def _official() -> dict:
    return json.loads(
        (ROOT / "data/scenarios/nasdaq_latest.json").read_text(encoding="utf-8")
    )


def test_legacy_reproduction_counts_and_daily_quantiles_are_exact() -> None:
    result = reproduce_legacy_snapshot(_official())

    assert result.future_daily.shape == (20000, 252)
    assert result.sampled_weekly.shape == (20000, 52)
    assert result.counts == {"S1": 16702, "S2": 302, "S3": 2996}
    assert result.probability_percent == {"S1": 83, "S2": 2, "S3": 15}
    rounding = result.verification["probability_percent_rounding_receipt"]
    assert rounding["raw_percent"] == pytest.approx(
        {"S1": 83.51, "S2": 1.51, "S3": 14.98}
    )
    assert {key: value for key, value in rounding.items() if key != "raw_percent"} == {
        "method": "nearest_integer_then_largest_share_receives_residual",
        "independently_rounded_percent": {"S1": 84, "S2": 2, "S3": 15},
        "residual_percentage_points": -1,
        "adjusted_scenario": "S1",
        "final_percent": {"S1": 83, "S2": 2, "S3": 15},
    }
    assert result.verification["quantile_cells_checked"] == 1764
    assert result.verification["quantile_mismatches"] == 0
    assert result.verification["retained_member_mismatches"] == 0
    assert result.verification["passed"] is True


def test_legacy_reproduction_seed_change_is_detected() -> None:
    changed = reproduce_legacy_snapshot(_official(), seed_override=43, require_exact=False)
    assert changed.verification["passed"] is False
    assert changed.verification["seed_matches_snapshot"] is False
    with pytest.raises(LegacyReproductionError, match="legacy reproduction failed"):
        reproduce_legacy_snapshot(_official(), seed_override=43)
