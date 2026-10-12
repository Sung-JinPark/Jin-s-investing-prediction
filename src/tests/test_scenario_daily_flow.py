"""Daily member selection: independent exact distances, source and calendar gates."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.distance import cdist

from ai_fc import scenario_daily_flow as flow
from ai_fc import scenario
from ai_fc.quant import mc
from ai_fc.scenario import future_trading_days, load_calendar_contract


@pytest.fixture(scope="module")
def snapshot() -> dict:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "data/scenarios/archive/2026-10-09.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def payload(snapshot: dict) -> dict:
    root = Path(__file__).resolve().parents[2]
    return flow.build_daily_flow(snapshot, calendar=load_calendar_contract(root))


def _prices(n: int = 320) -> np.ndarray:
    rng = np.random.default_rng(971)
    increments = .0003 + rng.normal(0, .014, (n, 120))
    return 100 * np.exp(np.column_stack((np.zeros(n), np.cumsum(increments, axis=1))))


def _brute_selection(prices: np.ndarray, ids: np.ndarray, months: list[int]) -> tuple[int, float, int]:
    # Independent all-pairs reference with explicit scalar features and rank order.
    features = []
    for path in prices:
        log_changes = np.diff(np.log(path))
        features.append([math.log(path[t] / path[0]) for t in months] + [
            float(log_changes.std(ddof=1)),
            max(1 - value / max(path[:t + 1]) for t, value in enumerate(path)),
            sum(x * y < 0 for x, y in zip(log_changes, log_changes[1:])) / (len(log_changes) - 1),
        ])
    features = np.asarray(features)
    scales = np.percentile(features, 75, axis=0) - np.percentile(features, 25, axis=0)
    z = (features - np.median(features, axis=0)) / scales
    distance = cdist(z, z)
    np.fill_diagonal(distance, np.inf)
    k = math.ceil(math.sqrt(len(prices)))
    radii = np.sort(distance, axis=1)[:, k - 1]
    center = min(range(len(prices)), key=lambda i: (radii[i], ids[i]))
    neighbors = sorted((i for i in range(len(prices)) if i != center),
                       key=lambda i: (distance[center, i], ids[i]))[:k]
    cluster = [center] + neighbors
    eligible = []
    for candidate in cluster:
        allowed = True
        for column, (lo, hi) in ((6, (10, 90)), (7, (5, 95)), (8, (5, 95))):
            bounds = np.percentile(features[:, column], (lo, hi))
            allowed &= bounds[0] <= features[candidate, column] <= bounds[1]
        if allowed:
            eligible.append(candidate)
    logs = np.log(prices)
    daily_scales = np.percentile(logs, 75, axis=0) - np.percentile(logs, 25, axis=0)
    daily_scales[0] = 1  # anchor contributes exactly zero to every distance.
    costs = {i: sum(float(np.sum(np.abs(logs[i] - logs[j]) / daily_scales)) for j in cluster)
             for i in eligible}
    chosen = min(eligible, key=lambda i: (costs[i], ids[i]))
    return int(ids[chosen]), float(radii[center]), int(ids[center])


def test_exact_tree_density_and_daily_medoid_match_independent_brute_force() -> None:
    prices = _prices()
    ids = np.arange(len(prices)) * 3 + 7
    months = [20, 40, 60, 80, 100, 120]
    result = flow._select_member(prices, ids, months)
    expected_id, expected_radius, expected_center = _brute_selection(prices, ids, months)
    assert result["status"] == "ok"
    assert result["member_path_index"] == expected_id
    assert result["density_radius"] == pytest.approx(expected_radius, abs=1e-12)
    assert result["density_center_path_index"] == expected_center
    assert result["cluster_size"] == math.ceil(math.sqrt(len(prices))) + 1


def test_multimodal_density_selects_dense_cluster_instead_of_global_average(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = _prices()
    rng = np.random.default_rng(171)
    features = np.zeros((len(prices), 9))
    features[:100, :6] = rng.normal(0, .0002, (100, 6))
    features[100:, :6] = rng.normal(8, 4, (220, 6))
    monkeypatch.setattr(flow, "_features", lambda *_: features)
    result = flow._select_member(prices, np.arange(len(prices)), [20, 40, 60, 80, 100, 120])
    assert result["status"] == "ok"
    assert result["density_center_path_index"] < 100
    assert result["member_path_index"] < 100
    assert all(member < 100 for member in result["cluster_member_path_indexes"])


def test_member_ties_use_original_id_and_are_invariant_to_row_order(monkeypatch: pytest.MonkeyPatch) -> None:
    n = 220
    prices = np.tile(_prices(1), (n, 1))  # Every candidate has zero medoid cost.
    features = np.zeros((n, 9))
    features[:, 0] = np.arange(n) ** 1.2
    ids = np.arange(n)[::-1]
    monkeypatch.setattr(flow, "_features", lambda *_: features)
    result = flow._select_member(prices, ids, [20, 40, 60, 80, 100, 120])
    assert result["status"] == "ok"
    assert result["member_path_index"] == min(result["cluster_member_path_indexes"])
    permutation = np.random.default_rng(71).permutation(n)
    monkeypatch.setattr(flow, "_features", lambda *_: features[permutation])
    reordered = flow._select_member(prices[permutation], ids[permutation], [20, 40, 60, 80, 100, 120])
    assert result["member_path_index"] == reordered["member_path_index"]
    assert result["density_center_path_index"] == reordered["density_center_path_index"]


def test_small_condition_and_constant_density_are_explicitly_blocked() -> None:
    months = [20, 40, 60, 80, 100, 120]
    small = flow._select_member(_prices(199), np.arange(199), months)
    assert small["reason"] == "conditional_sample_below_200"
    constant = flow._select_member(np.full((220, 121), 100.), np.arange(220), months)
    assert constant["reason"] == "all_density_features_constant"
    assert len(constant["scaling"]["excluded_constant_features"]) == 9


def test_duplicate_cluster_zero_radius_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    features = np.zeros((220, 9))
    features[180:, 0] = np.arange(40) + 1
    monkeypatch.setattr(flow, "_features", lambda *_: features)
    result = flow._select_member(_prices(220), np.arange(220), [20, 40, 60, 80, 100, 120])
    assert result["reason"] == "degenerate_density_radius"
    assert result["density_radius"] == 0


def test_dense_cluster_with_ineligible_tail_is_blocked_without_relaxing_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    features = np.zeros((320, 9))
    features[:30, 0] = np.arange(30) * .00001
    features[30:, 0] = np.linspace(10, 500, 290)
    features[30:, 6] = 1
    monkeypatch.setattr(flow, "_features", lambda *_: features)
    result = flow._select_member(_prices(), np.arange(320), [20, 40, 60, 80, 100, 120])
    assert result["reason"] == "eligible_neighbors_below_9"
    assert result["eligible_neighbor_count"] == 0
    assert result["eligibility_gates"]["daily_realized_volatility"]["lower"] == 1


def test_zero_iqr_nonconstant_std_fallback_is_audited_and_constant_is_dropped() -> None:
    matrix = np.column_stack((np.ones(220), np.r_[np.zeros(200), np.arange(1, 21)]))
    scaled, diagnostics = flow._standardize(matrix, ("constant", "rare_nonconstant"))
    assert scaled.shape == (220, 1)
    assert diagnostics["excluded_constant_features"] == ["constant"]
    assert diagnostics["zero_iqr_std_fallback_features"] == ["rare_nonconstant"]
    assert diagnostics["scales"]["rare_nonconstant"] == pytest.approx(matrix[:, 1].std())


def test_latest_full_daily_grid_six_months_and_unchanged_source(snapshot: dict, payload: dict) -> None:
    before = deepcopy(snapshot)
    assert payload["status"] == "ok" and payload["shadow"]["passed"] is True
    assert all(row["passed"] for row in payload["shadow"]["checks"].values())
    assert payload["calendar_end"] == "2027-04-09"
    assert payload["default_end_index"] == 124
    assert len(payload["dates"][:payload["default_end_index"] + 1]) == 125
    assert len(payload["dates"]) == 253
    assert payload["dates"][1:] == snapshot["quantile_table"]["trading_days"]
    assert payload["probability_unit"] == "fraction"
    assert [payload["scenarios"][key]["probability"] for key in flow.SCENARIOS] == [.92, .02, .06]
    assert payload["provenance"]["source_probability_unit"] == "percent"
    assert payload["provenance"]["distribution_changed"] is False
    assert payload["provenance"]["official_snapshot_changed"] is False
    assert flow.validate_daily_flow(payload, snapshot) is payload
    assert snapshot == before


def test_selected_members_are_unchanged_whole_ensemble_paths_and_reproducible(snapshot: dict, payload: dict) -> None:
    inputs, _, _ = flow._source_inputs(snapshot, None)
    future, masks = flow._ensemble(inputs)
    root = Path(__file__).resolve().parents[2]
    rebuilt = flow.build_daily_flow(snapshot, calendar=load_calendar_contract(root))
    assert rebuilt == payload
    for key, row in payload["scenarios"].items():
        member = row["member_path_index"]
        assert masks[key][member]
        assert row["values"] == [snapshot["anchor"]] + future[member].tolist()
        assert row["end"] == future[member, payload["default_end_index"] - 1]
        assert row["selection"]["sensitivities"]["half_k"]["k"] == max(9, math.ceil(row["selection"]["k"] / 2))
        assert row["selection"]["sensitivities"]["double_k"]["k"] == min(len(future[masks[key]]) - 1, row["selection"]["k"] * 2)


def test_fraction_risk_uses_all_original_paths_not_representative_members(snapshot: dict, payload: dict) -> None:
    inputs, _, _ = flow._source_inputs(snapshot, None)
    future, _ = flow._ensemble(inputs)
    expected = np.maximum.accumulate(future <= snapshot["corr10"], axis=1).mean(axis=0)
    assert payload["risk"]["cumulative_touch"] == [0.] + expected.tolist()
    assert payload["risk"]["probability_space"] == "original_all_gbm_ensemble"
    assert max(payload["risk"]["cumulative_touch"]) <= 1


@pytest.mark.parametrize(("asof", "expected"), [
    (date(2026, 8, 31), date(2027, 2, 28)),
    (date(2023, 8, 31), date(2024, 2, 29)),
    (date(2026, 10, 9), date(2027, 4, 9)),
    (date(2026, 12, 30), date(2027, 6, 30)),
])
def test_calendar_month_end_leap_year_and_year_crossing(asof: date, expected: date) -> None:
    assert flow.add_calendar_months(asof, 6) == expected


def test_holiday_weekend_axis_end_has_no_artificial_price_point() -> None:
    root = Path(__file__).resolve().parents[2]
    calendar = load_calendar_contract(root)
    asof = date(2026, 8, 31)
    end = flow.add_calendar_months(asof, 6)
    days = [asof] + future_trading_days(asof, 252, calendar)
    last_index = max(i for i, day in enumerate(days) if day <= end)
    assert end == date(2027, 2, 28)  # Sunday is an axis date, not a price observation.
    assert days[last_index] == date(2027, 2, 26)
    assert date(2026, 12, 25) not in days
    assert date(2027, 1, 18) not in days


def test_declared_probability_units_and_invalid_fractions_are_rejected(snapshot: dict) -> None:
    assert flow._source_unit(snapshot)[0] == "percent"
    with pytest.raises(flow.DailyFlowError, match="unit metadata"):
        flow._source_unit({"paths": {"S1": {"prob": .92}}})
    wrong = deepcopy(snapshot)
    wrong["probability_unit"] = "fraction"
    with pytest.raises(flow.DailyFlowError, match="outside declared fraction"):
        flow.build_daily_flow(wrong)
    wrong["probability_unit"] = "unknown"
    with pytest.raises(flow.DailyFlowError, match="fraction or percent"):
        flow.build_daily_flow(wrong)
    wrong["probability_unit"] = "percent"
    wrong["model"]["probability_unit"] = "fraction"
    with pytest.raises(flow.DailyFlowError, match="metadata conflicts"):
        flow.build_daily_flow(wrong)


def test_missing_parameters_future_vintage_and_changed_calendar_are_rejected(snapshot: dict) -> None:
    wrong = deepcopy(snapshot)
    wrong["model"].pop("gbm_parameters")
    with pytest.raises(flow.DailyFlowError, match="retained champion"):
        flow.build_daily_flow(wrong)
    wrong = deepcopy(snapshot)
    wrong["model"]["gbm_parameters"]["estimation_end"] = "2026-10-10"
    with pytest.raises(flow.DailyFlowError, match="estimation_end"):
        flow.build_daily_flow(wrong)
    root = Path(__file__).resolve().parents[2]
    calendar = load_calendar_contract(root)
    calendar["registered_at"] = "2026-10-10"
    with pytest.raises(flow.DailyFlowError, match="registered after"):
        flow.build_daily_flow(snapshot, calendar=calendar)
    calendar["registered_at"] = "2026-08-03"
    calendar["one_off_closures"] = ["2026-10-12"]
    with pytest.raises(flow.DailyFlowError, match="calendar disagrees"):
        flow.build_daily_flow(snapshot, calendar=calendar)


def test_changed_distribution_explicitly_blocks_shadow_and_representatives(snapshot: dict) -> None:
    changed = deepcopy(snapshot)
    changed["quantile_table"]["quantiles"]["p50"][17] += 10
    blocked = flow.build_daily_flow(changed)
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "champion_shadow_reproduction_failed"
    assert blocked["shadow"]["checks"]["daily_quantiles"]["passed"] is False
    assert all(row["values"] == [] and row["reason"] == "champion_shadow_reproduction_failed"
               for row in blocked["scenarios"].values())


def test_future_source_retains_exact_replay_inputs_without_reestimating_or_changing_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate the already-existing structural subsystem, which reads repository
    # context. The pure numerical champion producer and its raw close inputs are
    # exercised here; no latest history is substituted into an archived vintage.
    monkeypatch.setattr(scenario, "build_structural_forecast", lambda _root, source: {
        "dates": source["week_dates"], "paths": source["paths"],
    })
    monkeypatch.setattr(scenario, "validate_scenario", lambda source: source)
    asof = date(2026, 10, 9)
    dates = [date.fromisoformat(str(value)) for value in np.busday_offset(
        np.datetime64(asof.isoformat()), np.arange(-252, 1))]
    x = np.arange(253)
    closes = (25_000.00039 * np.exp(.00065 * x + .025 * np.sin(x / 15))).tolist()
    source = scenario.build_scenario(dates, closes, n_paths=2_000, seed=19)
    source["snapshot_id"] = "synthetic-exact-replay:2026-10-09:r1"
    replay = source["model"]["gbm_parameters"]["replay_parameters"]
    assert replay["anchor"] == closes[-1] != source["anchor"]
    retained = deepcopy(source)
    inputs, _, _ = flow._source_inputs(source, None)
    reconstructed, _ = flow._ensemble(inputs)
    expected = mc.gbm_paths(closes, lookback=252, horizon=252, n=2_000, seed=19)
    assert np.array_equal(reconstructed, expected)
    result = flow.build_daily_flow(source)
    assert result["status"] == "ok"
    assert result["shadow"]["passed"] is True
    assert "full float replay_parameters" in result["shadow"]["parameter_precision"]
    assert source == retained
    assert result["risk"]["simulation_threshold"] == replay["corr10"]
    invalid = deepcopy(source)
    invalid["model"]["gbm_parameters"]["replay_parameters"]["sigma_daily_log_return"] *= 2
    with pytest.raises(flow.DailyFlowError, match="disagree with reported"):
        flow.build_daily_flow(invalid)


@pytest.mark.parametrize("corruption", ("artificial_value", "probability_percent", "risk_space", "source_hash", "calendar_end", "fake_shadow"))
def test_public_validator_rejects_semantic_corruption(snapshot: dict, payload: dict, corruption: str) -> None:
    invalid = deepcopy(payload)
    if corruption == "artificial_value":
        invalid["scenarios"]["S1"]["values"][-1] += .01
    elif corruption == "probability_percent":
        invalid["scenarios"]["S1"]["probability"] = 92
    elif corruption == "risk_space":
        invalid["risk"]["probability_space"] = "selected_member_paths"
    elif corruption == "source_hash":
        invalid["source_snapshot_sha256"] = "0" * 64
    elif corruption == "calendar_end":
        invalid["calendar_end"] = "2026-11-20"
    else:
        invalid["shadow"]["checks"]["daily_quantiles"]["passed"] = False
    with pytest.raises(flow.DailyFlowError):
        flow.validate_daily_flow(invalid, snapshot)


def test_cross_platform_member_tolerance_is_explicit_bounded_and_does_not_rewrite(snapshot: dict, payload: dict) -> None:
    perturbed = deepcopy(payload)
    perturbed["scenarios"]["S1"]["values"][-1] += 1e-9
    unchanged = deepcopy(perturbed)
    assert flow.validate_daily_flow(perturbed, snapshot) is perturbed
    assert perturbed == unchanged
    perturbed["scenarios"]["S1"]["values"][-1] += flow.PRICE_REPLAY_ABS_TOLERANCE * 2
    with pytest.raises(flow.DailyFlowError, match="actual unchanged source member"):
        flow.validate_daily_flow(perturbed, snapshot)
