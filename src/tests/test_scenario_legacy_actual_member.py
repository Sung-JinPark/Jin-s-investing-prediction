from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ai_fc.scenario_shadow import legacy_actual_member
from ai_fc.scenario_shadow.legacy_actual_member import (
    ALL_QUANTILES,
    build_legacy_diagnostic_payload,
)
from ai_fc.scenario_shadow.legacy_reproduction import reproduce_legacy_snapshot
from ai_fc.scenario_shadow.representative import (
    RepresentativeSelectionError,
    select_actual_representative_path,
)


ROOT = Path(__file__).resolve().parents[2]


def _built() -> tuple[dict, object]:
    source_path = ROOT / "data/scenarios/nasdaq_latest.json"
    source_bytes = source_path.read_bytes()
    snapshot = json.loads(source_bytes.decode("utf-8"))
    reproduction = reproduce_legacy_snapshot(snapshot)
    payload = build_legacy_diagnostic_payload(
        root=ROOT,
        snapshot=snapshot,
        source_bytes=source_bytes,
        reproduction=reproduction,
    )
    return payload, reproduction


def test_conditional_quantiles_are_pointwise_and_monotone() -> None:
    payload, reproduction = _built()
    percentile = {"p05": 5, "p10": 10, "p25": 25, "p50": 50, "p75": 75, "p90": 90, "p95": 95}

    for scenario, mask in reproduction.masks.items():
        distribution = payload["scenario_distributions"][scenario]
        arrays = []
        for key in distribution["available_quantiles"]:
            expected = [
                int(round(float(value)))
                for value in np.percentile(
                    reproduction.sampled_weekly[mask], percentile[key], axis=0
                )
            ]
            assert distribution["quantiles"][key] == expected
            arrays.append(np.asarray(expected))
        for left, right in zip(arrays, arrays[1:]):
            assert np.all(left <= right)


def test_scenario_sample_gates_are_enforced() -> None:
    payload, _ = _built()
    assert payload["scenario_distributions"]["S1"]["available_quantiles"] == list(ALL_QUANTILES)
    assert payload["scenario_distributions"]["S2"]["available_quantiles"] == ["p50"]
    assert set(payload["scenario_distributions"]["S2"]["blocked_quantiles"]) == {
        "p25_p75",
        "p10_p90",
        "p05_p95",
    }
    assert payload["scenario_distributions"]["S3"]["available_quantiles"] == list(ALL_QUANTILES)


def test_unconditional_distribution_is_direct_full_joint_sample() -> None:
    payload, reproduction = _built()
    unconditional = payload["unconditional_distribution"]
    union = np.concatenate(
        [reproduction.sampled_weekly[reproduction.masks[key]] for key in ("S1", "S2", "S3")],
        axis=0,
    )
    assert len(union) == len(reproduction.sampled_weekly)
    for percentile, key in ((5, "p05"), (10, "p10"), (25, "p25"), (50, "p50"), (75, "p75"), (90, "p90"), (95, "p95")):
        expected = [int(round(float(value))) for value in np.percentile(union, percentile, axis=0)]
        assert unconditional["quantiles"][key] == expected
    assert payload["diagnostics"]["weighted_average_of_conditional_quantiles"] is False


def test_mixture_quantile_is_not_weighted_quantile_average() -> None:
    payload, _ = _built()
    weights = payload["candidate_implied_weights"]["values"]
    weighted_p50 = [
        int(
            round(
                sum(
                    weights[key]
                    * payload["scenario_distributions"][key]["quantiles"]["p50"][index]
                    for key in ("S1", "S2", "S3")
                )
            )
        )
        for index in range(len(payload["week_dates"]))
    ]
    assert weighted_p50 != payload["unconditional_distribution"]["quantiles"]["p50"]


def test_representatives_are_actual_rows_in_their_cohorts_and_pass_gates() -> None:
    payload, reproduction = _built()
    for scenario, representative in payload["representatives"].items():
        index = representative["original_global_path_index"]
        assert reproduction.masks[scenario][index]
        expected = [
            int(round(float(value))) for value in reproduction.sampled_weekly[index]
        ]
        assert representative["weekly_values"] == expected
        assert representative["candidate_gate_status"] == "pass"
        assert 35.0 <= representative["metric_percentiles"]["terminal_return"] <= 65.0
        for key in (
            "annualized_daily_volatility",
            "maximum_drawdown",
            "time_under_water_sessions",
            "weekly_direction_change_count",
        ):
            assert 10.0 <= representative["metric_percentiles"][key] <= 90.0


def test_probability_spaces_use_explicit_fraction_units() -> None:
    payload, _ = _built()
    assert payload["official_weights"] == {
        "unit": "fraction",
        "source": "official_snapshot_partition",
        "values": {"S1": 0.83, "S2": 0.02, "S3": 0.15},
    }
    assert payload["candidate_implied_weights"]["unit"] == "fraction"
    assert sum(payload["candidate_implied_weights"]["values"].values()) == pytest.approx(1.0)


def test_representative_tie_break_uses_lowest_global_path_index() -> None:
    future = np.full((4, 6), 100.0)
    weekly = np.full((4, 3), 100.0)
    selected = select_actual_representative_path(
        future_daily=future,
        sampled_weekly=weekly,
        mask=np.asarray([False, True, True, False]),
        trading_days=tuple(f"2026-01-{day:02d}" for day in range(2, 8)),
    )
    assert selected["original_global_path_index"] == 1


def test_representative_is_hidden_when_no_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_path = ROOT / "data/scenarios/nasdaq_latest.json"
    source_bytes = snapshot_path.read_bytes()
    snapshot = json.loads(source_bytes.decode("utf-8"))
    reproduction = reproduce_legacy_snapshot(snapshot)

    def no_candidate(**_: object) -> dict:
        raise RepresentativeSelectionError("no actual path satisfies centrality gates")

    monkeypatch.setattr(
        legacy_actual_member,
        "select_actual_representative_path",
        no_candidate,
    )
    payload = build_legacy_diagnostic_payload(
        root=ROOT,
        snapshot=snapshot,
        source_bytes=source_bytes,
        reproduction=reproduction,
    )
    assert payload["representatives"] == {}
    assert all(
        row["status"] == "representative_hidden_no_candidate"
        and row["representative_path_id"] is None
        for row in payload["scenario_distributions"].values()
    )
