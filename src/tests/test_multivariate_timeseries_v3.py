from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v3.analyst_ledger import (
    ReportSignal, aggregate_report_signal, append_report_signal, read_report_signals,
)
from ai_fc.timeseries_v3.backtest import (
    OriginScore, empirical_crps, evaluate_research_gate, tail_weighted_crps,
)
from ai_fc.timeseries_v3.baselines import FixedAnchorDistribution
from ai_fc.timeseries_v3.calibration import monotone_quantiles, wilson_interval
from ai_fc.timeseries_v3.contracts import (
    MODEL_ID, WORKBOOK_RELATIVE, TimeSeriesV3ContractError, load_contract_v3,
    verify_v2_benchmark,
)
from ai_fc.timeseries_v3.dfm_alignment import DFMAlignmentError, align_factor, factor_features
from ai_fc.timeseries_v3.event_ledger import (
    EventSnapshot, append_event_snapshot, apply_local_event_shock,
    pre_event_branch_probabilities, snapshots_available_at,
)
from ai_fc.timeseries_v3.interfaces import ComponentForecast
from ai_fc.timeseries_v3.models.direct_location import AnalogQuantileModel, DirectHorizonModel
from ai_fc.timeseries_v3.models.regime_mixture import SoftRegimeModel
from ai_fc.timeseries_v3.monitoring import operational_monitor, source_freshness
from ai_fc.timeseries_v3.options_ledger import MarketImpliedSnapshot, PhysicalCalibration
from ai_fc.timeseries_v3.path_reconciler import (
    endpoint_errors, gaussian_copula_endpoints, path_duplicate_fraction, stochastic_bridge_paths,
)
from ai_fc.timeseries_v3.pipeline import _path_risk_audit
from ai_fc.timeseries_v3.snapshots import SnapshotFact, SnapshotLeakageError, pit_snapshot
from ai_fc.timeseries_v3.stacking import StackedDistribution, constrained_loss_weights
from ai_fc.timeseries_v3.targets import direct_log_return_targets, index_from_log_return


ROOT = Path(__file__).resolve().parents[2]


def test_v3_contract_is_new_and_v2_benchmark_is_byte_identified():
    contract = load_contract_v3(ROOT)
    assert contract["model_id"] == MODEL_ID
    assert contract["target"]["recursive_one_day_long_horizon"] == "prohibited"
    assert contract["baseline"]["row_wise_oracle"] == "prohibited"
    observed = verify_v2_benchmark(ROOT, contract)
    assert observed["run_id"] == "tsv2-backtest-f995c40e19ade197f3559b6e"


def test_direct_target_alignment_and_index_round_trip():
    prices = 100.0 * np.exp(np.arange(80) * 0.01)
    targets = direct_log_return_targets(prices)
    assert targets[1][0] == pytest.approx(0.01)
    assert targets[63][5] == pytest.approx(0.63)
    assert index_from_log_return(100.0, targets[21][0]) == pytest.approx(prices[21])


def test_snapshot_rejects_future_available_fact_and_feature():
    safe = SnapshotFact("X", "2020-01-01", "2020-01-02T00:00:00+00:00", 1.0, "fred", "a" * 64, "native_pit")
    future = replace(safe, available_at="2020-01-04T00:00:00+00:00")
    snapshot = pit_snapshot([safe, future], origin="2020-01-03", knowledge_cutoff="2020-01-03T00:00:00+00:00")
    assert snapshot.facts == (safe,)
    with pytest.raises(SnapshotLeakageError):
        pit_snapshot(
            [safe], origin="2020-01-03", knowledge_cutoff="2020-01-03T00:00:00+00:00",
            features={"bad": 1.0}, feature_available_at={"bad": "2020-01-04T00:00:00+00:00"},
        )


def test_direct_horizon_ridge_recovers_distinct_targets_and_bounds_correction():
    rng = np.random.default_rng(7)
    features = rng.normal(size=(700, 3))
    coefficients = {1: np.array([0.2, -0.1, 0.05]), 5: np.array([-0.1, 0.4, 0.2]), 21: np.array([0.3, 0.1, -0.2]), 63: np.array([0.5, -0.2, 0.1])}
    targets = {h: features @ beta + rng.normal(scale=0.01, size=len(features)) for h, beta in coefficients.items()}
    model = DirectHorizonModel.fit(features, targets, alpha=0.01, correction_sigma_bounds={h: 0.25 for h in coefficients})
    anchors = {h: rng.normal(scale=0.1, size=2000) for h in coefficients}
    corrections = model.location_corrections(np.array([10.0, 10.0, 10.0]), anchors)
    for horizon, correction in corrections.items():
        assert abs(correction) <= 0.25 * np.std(anchors[horizon], ddof=1) + 1e-12
    assert not np.allclose(model.coefficients[1], model.coefficients[63])


def test_analog_quantile_uses_only_fitted_rows_and_bounded_location():
    rng = np.random.default_rng(17)
    features = rng.normal(size=(600, 2))
    targets = {h: 0.01 * h * features[:, 0] + rng.normal(0, 0.01 * np.sqrt(h), 600) for h in (1, 5, 21, 63)}
    model = AnalogQuantileModel.fit(
        features, targets, neighbors=100, conditional_weight=0.5,
        correction_sigma_bounds={h: 0.25 for h in targets},
    )
    anchors = {h: rng.normal(0, 0.01 * np.sqrt(h), 1000) for h in targets}
    result = model.predict_samples(np.array([1.0, 0.0]), anchors, count=1000, rng=rng)
    assert set(result) == {1, 5, 21, 63}
    assert all(len(values) == 1000 for values in result.values())


def test_fixed_anchor_is_deterministic_and_not_rowwise_oracle():
    rng = np.random.default_rng(8)
    returns = rng.normal(0.0003, 0.01, 3000)
    states = rng.normal(size=(3000, 6))
    anchor = FixedAnchorDistribution({"historical_simulation": 0.5, "filtered_historical_simulation": 0.3, "stationary_block_bootstrap": 0.2}, sample_count=500)
    first = anchor.predict(returns=returns, state_history=states, origin_state=states[-1], horizons=(1, 5, 21, 63), seed=44, data_cutoff="2026-01-01")
    second = anchor.predict(returns=returns, state_history=states, origin_state=states[-1], horizons=(1, 5, 21, 63), seed=44, data_cutoff="2026-01-01")
    assert np.array_equal(first.horizon_samples[63], second.horizon_samples[63])


def test_dfm_alignment_anchors_reference_sign_scale_and_features():
    states = np.linspace(-2, 2, 100)
    aligned = align_factor(
        "growth", states, {"PAYEMS": -0.8, "INDPRO": -0.5, "RSAFS": -0.2},
        positive_references=("PAYEMS", "INDPRO", "RSAFS"), reference_slice=slice(0, 60),
    )
    assert aligned.sign == -1
    assert aligned.loadings["PAYEMS"] > 0
    features = factor_features(aligned, state_prediction=aligned.states - 0.1, age_since_release=np.arange(100))
    assert np.nanmedian(features["growth_innovation"]) == pytest.approx(0.1)
    with pytest.raises(DFMAlignmentError):
        align_factor("bad", states, {"X": 1.0}, positive_references=("PAYEMS",))


def _event(**changes):
    payload = dict(
        event_id="CPI-1", event_type="CPI", scheduled_at="2026-01-10T13:30:00+00:00",
        snapshot_at="2026-01-09T20:00:00+00:00", source_id="consensus",
        consensus_mean=2.5, consensus_median=2.5, consensus_dispersion=0.2,
        model_nowcast=2.6, prior_actual=2.4, market_implied_move=0.01,
        fedwatch_probability_vector=(0.2, 0.8), actual=None, actual_available_at=None,
        revision_of=None, raw_sha256="b" * 64,
    )
    payload.update(changes)
    return EventSnapshot(**payload)


def test_event_actual_leakage_revision_chain_and_local_path_effect(tmp_path):
    path = tmp_path / "events.jsonl"
    first = _event()
    assert append_event_snapshot(path, first)
    revision = _event(snapshot_at="2026-01-09T21:00:00+00:00", revision_of=first.snapshot_id)
    assert append_event_snapshot(path, revision)
    with pytest.raises(ValueError):
        append_event_snapshot(path, _event(revision_of="missing"))
    leaked = _event(actual=2.8, actual_available_at="2026-01-10T13:31:00+00:00")
    with pytest.raises(ValueError, match="future event actual"):
        snapshots_available_at([leaked], "2026-01-10T13:30:30+00:00")
    paths = np.zeros((100, 20))
    probabilities = pre_event_branch_probabilities(first)
    changed = apply_local_event_shock(
        paths, event_session=10, branch_probabilities=probabilities,
        mean_shocks={"soft_dovish": 0.02, "near_consensus": 0.0, "hot_hawkish": -0.02},
        volatility_multipliers={"soft_dovish": 1.1, "near_consensus": 1.0, "hot_hawkish": 1.2},
        effect_sessions=5, rng=np.random.default_rng(2),
    )
    assert np.array_equal(changed[:, :10], paths[:, :10])
    assert not np.array_equal(changed[:, 10:15], paths[:, 10:15])


def test_report_signals_are_timestamped_deduplicated_and_revision_linked(tmp_path):
    path = tmp_path / "reports.jsonl"
    row = ReportSignal(
        "r1", "bank", "2026-01-01T10:00:00+00:00", "2026-01-01T10:01:00+00:00",
        "NASDAQ", "3m", "return", 0.05, 0.04, "up", "moderate", "2025-12-31",
        "extractor", 1, "c" * 64, "cluster-1",
    )
    assert append_report_signal(path, row)
    duplicate = replace(row, report_id="r2", published_at="2026-01-01T11:00:00+00:00", available_at="2026-01-01T11:01:00+00:00")
    assert append_report_signal(path, duplicate)
    value, count = aggregate_report_signal(read_report_signals(path), cutoff="2026-01-02T00:00:00+00:00", provider_reliability={"bank": 0.7})
    assert value == pytest.approx(0.05)
    assert count == 1


def test_market_implied_probability_is_not_physical_without_60_outcomes():
    row = MarketImpliedSnapshot("2026-01-01", "cme", (0.4, 0.6), 3.5, 0.7, -0.1, 0.2, 0.01, "d" * 64)
    row.validate()
    with pytest.raises(ValueError):
        PhysicalCalibration(1.0, 0.0, 59).calibrate(0.6)
    assert 0 <= PhysicalCalibration(0.8, 0.1, 60).calibrate(0.6) <= 1


def test_stacking_enforces_anchor_floor_and_zeroes_absent_event():
    weights = constrained_loss_weights(
        {"anchor": 1.0, "direct_location": 0.8, "event": 0.1},
        anchor="anchor", anchor_floor=0.35,
    )
    assert weights["anchor"] >= 0.35
    forecasts = {
        name: ComponentForecast.from_samples(name, {21: np.full(100, value)}, data_cutoff="x", feature_hash=name)
        for name, value in {"anchor": 0.0, "direct_location": 0.1, "event": 10.0}.items()
    }
    stack = StackedDistribution({21: weights}, "anchor", 0.35)
    output = stack.combine(forecasts, count=1000, seed=1, event_present=False)
    assert np.max(output[21]) < 10


def test_joint_endpoint_bridge_is_exact_and_paths_are_diverse():
    rng = np.random.default_rng(3)
    samples = {h: rng.normal(0.0002 * h, 0.01 * np.sqrt(h), 1000) for h in (1, 5, 21, 63)}
    horizons, endpoints = gaussian_copula_endpoints(samples, correlation=np.eye(4), count=500, rng=rng)
    paths = stochastic_bridge_paths(endpoints, horizons, rng.normal(0, 0.01, 2000), rng=rng)
    assert np.max(np.abs(endpoint_errors(paths, endpoints, horizons))) < 1e-12
    assert path_duplicate_fraction(paths) < 0.01


def test_quantile_monotonicity_crps_and_wilson_are_independently_computable():
    result = monotone_quantiles(np.array([0.1, 0.5, 0.9]), np.array([1.0, 0.0, 2.0]))
    assert list(result.values()) == [1.0, 1.0, 2.0]
    assert empirical_crps(np.array([-1.0, 0.0, 1.0]), 0.0) >= 0
    low, high = wilson_interval(8, 10)
    assert low < 0.8 < high


def test_research_gate_uses_fixed_comparator_and_mandatory_conditional_tables():
    rows = []
    for index in range(80):
        for horizon in (21, 63):
            actual = 0.01 if index % 2 else -0.01
            rows.append(OriginScore(
                f"2020-{1 + index // 28:02d}-{1 + index % 28:02d}", horizon, actual,
                0.008, 0.010, -0.03, 0.03, -0.03, 0.03,
                ("bull" if actual > 0 else "bear"), "normal", "no_event",
                0.10 + index / 1000, "core_fresh_optional_components_absent",
                0.75 if actual > 0 else 0.25, 0.70 if actual > 0 else 0.30,
                0.004, 0.009, {"0.1": -0.03, "0.5": 0.0, "0.9": 0.03},
            ))
    gate = evaluate_research_gate(rows, leakage_count=0, lineage_linkage=1.0, bootstrap_iterations=200, seed=4)
    assert gate["fixed_comparator"] == "fixed_anchor_ensemble_v3"
    assert gate["row_wise_oracle_used"] is False
    assert "actual_sign" in gate["conditional_tables"][21]
    assert "absolute_move_quartile" in gate["conditional_tables"][63]
    assert "volatility_quartile" in gate["conditional_tables"][21]
    assert "component_staleness" in gate["conditional_tables"][63]
    assert gate["pit_histograms"]["21"]["sample_n"] == 80
    assert gate["direction_reliability"]["63"]
    assert gate["score_tables"]["21"]["mean_pinball"] == pytest.approx(0.004)


def test_tail_weighted_crps_and_path_risk_audit_are_finite():
    samples = np.linspace(-0.20, 0.20, 1001)
    assert tail_weighted_crps(samples, -0.05) >= 0
    paths = np.array([
        [0.01, -0.02, -0.03, 0.01],
        [-0.04, -0.04, -0.04, 0.01],
    ])
    audit = _path_risk_audit(paths)
    assert 0.0 <= audit["minus_10pct_first_touch_probability"] <= 1.0
    assert audit["max_drawdown_duration_sessions_quantiles"]["0.9"] >= 1


def test_monitoring_is_sample_aware_and_freshness_uses_release_calendar():
    provisional = operational_monitor(np.ones(20), np.ones(20), np.ones(20, dtype=bool))
    assert provisional["status"] == "provisional_monitor_only"
    weekly = source_freshness(
        observed_at="2026-01-02T00:00:00+00:00", expected_next_release="2026-01-09T00:00:00+00:00",
        knowledge_cutoff="2026-01-08T12:00:00+00:00", grace_hours=12,
    )
    assert weekly["status"] == "fresh"


def test_v3_workbook_path_is_isolated_from_v2_and_official_ledgers():
    assert WORKBOOK_RELATIVE.as_posix() == (
        "data/timeseries_v3/workbooks/multivariate_timeseries_v3_latest.xlsx"
    )
