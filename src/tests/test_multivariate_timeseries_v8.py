from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries.backtest import sample_crps
from ai_fc.timeseries.model import fit_ridge_varx
from ai_fc.timeseries_v2.model import simulate_correlated_paths_v2
from ai_fc.timeseries_v2.backtest import walk_forward_backtest_v2
from ai_fc.timeseries_v8.artifact import (
    TimeSeriesV8ArtifactError,
    append_experiment,
    read_experiments,
)
from ai_fc.timeseries_v8.backtest import (
    dev_gate_proxy_report,
    paired_differences_vs_best,
    walk_forward_dev_backtest_v8,
)
from ai_fc.timeseries_v8.contracts import (
    DEVELOPMENT_TRUNCATION_AFTER,
    TimeSeriesV8ContractError,
    V2_RUN_RELATIVE,
    assert_development_cutoff,
    frozen_hash,
    load_contract_v8,
    verify_v2_benchmark,
)
from ai_fc.timeseries_v8.model import (
    DistributionConfigV8,
    bounded_location_shift,
    cramer_distance,
    fhs_horizon_samples,
    mixture_cdf_at,
    mixture_crps,
    mixture_quantile_function,
    mixture_quantiles,
    recalibration_levels,
    simulate_calibrated_paths_v8,
    volatility_term_structure,
)
from ai_fc.timeseries_v8.artifact import append_holdout_scoring
from ai_fc.timeseries_v8.pipeline import (
    SEALED_LEDGER_RELATIVE,
    TimeSeriesV8PipelineError,
    _sealed_preconditions,
    build_config_from_grids,
    verify_timeseries_v8,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _root(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    (target / "data/contracts").mkdir(parents=True)
    shutil.copy2(
        REPOSITORY_ROOT / "data/contracts/multivariate_timeseries_v8.yaml",
        target / "data/contracts/multivariate_timeseries_v8.yaml",
    )
    contract = load_contract_v8(target)
    benchmark = contract["v2_benchmark"]
    run_path = target / V2_RUN_RELATIVE
    run_path.parent.mkdir(parents=True)
    run_path.write_text(json.dumps({
        "run_id": benchmark["run_id"],
        "content_hash": benchmark["content_hash"],
        "contract_hash": benchmark["contract_hash"],
        "hashes": {"model_code": benchmark["model_code_hash"]},
    }), encoding="utf-8")
    return target


def _sessions(count: int, start: str = "2000-01-03") -> tuple[str, ...]:
    day = date.fromisoformat(start)
    sessions: list[str] = []
    while len(sessions) < count:
        if day.weekday() < 5:
            sessions.append(day.isoformat())
        day += timedelta(days=1)
    return tuple(sessions)


def _synthetic_market(count: int, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    endog = rng.normal(0.0002, 0.012, size=(count, 5))
    endog[:, 1] *= 3.0
    exog = rng.normal(0.0, 1.0, size=(count, 2))
    return endog, exog


# ── contract preregistration ────────────────────────────────────────────────

def test_v8_contract_is_preregistered_with_immutable_v2_predecessor(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v8(root)
    assert contract["model_id"] == "shadow.mf_dfm_varx_calibrated_v8"
    assert contract["model_version"] == 8
    assert contract["publication_gate"]["long_horizon_mean_crps_min_improvement"] == 0.02
    assert contract["publication_gate"]["p10_p90_coverage"] == [0.76, 0.84]
    assert contract["model"]["windows"]["design"] == ["2007-01-01", "2014-12-31"]
    assert contract["disclosure_caveat"]["v2_2019_scores_published_before_design"] is True
    observed = verify_v2_benchmark(root, contract)
    assert observed["run_id"] == "tsv2-backtest-f995c40e19ade197f3559b6e"


def test_v8_frozen_hash_changes_when_a_gate_coordinate_changes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v8(root)
    baseline = frozen_hash(contract)
    relaxed = json.loads(json.dumps(contract))
    relaxed["publication_gate"]["long_horizon_mean_crps_min_improvement"] = 0.01
    assert frozen_hash(relaxed) != baseline


def test_v8_contract_rejects_relaxed_gate_and_removed_prohibition(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = root / "data/contracts/multivariate_timeseries_v8.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["publication_gate"]["long_horizon_mean_crps_min_improvement"] = 0.01
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    with pytest.raises(TimeSeriesV8ContractError):
        load_contract_v8(root)
    payload["publication_gate"]["long_horizon_mean_crps_min_improvement"] = 0.02
    payload["prohibitions"].pop("sealed_2019_access_during_development")
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    with pytest.raises(TimeSeriesV8ContractError):
        load_contract_v8(root)


def test_v2_benchmark_tamper_is_rejected(tmp_path: Path) -> None:
    root = _root(tmp_path)
    run_path = root / V2_RUN_RELATIVE
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["content_hash"] = "0" * 64
    run_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TimeSeriesV8ContractError):
        verify_v2_benchmark(root)


def test_development_cutoff_is_structurally_2019_blind() -> None:
    assert assert_development_cutoff("2019-04-30") == "2019-04-30"
    assert assert_development_cutoff("2018-12-31") == "2018-12-31"
    with pytest.raises(TimeSeriesV8ContractError):
        assert_development_cutoff("2019-05-01")
    with pytest.raises(TimeSeriesV8ContractError):
        assert_development_cutoff("2026-01-01")
    assert DEVELOPMENT_TRUNCATION_AFTER == "2019-04-30"


# ── B1 volatility term structure ────────────────────────────────────────────

def test_volatility_term_structure_identity_and_mean_reversion() -> None:
    rng = np.random.default_rng(3)
    residuals = rng.normal(0.0, 0.01, size=(800, 5))
    residuals[-40:] *= 4.0  # current vol well above the long-run level
    identity = volatility_term_structure(residuals, decay=0.94, phi=None, horizon=63)
    np.testing.assert_array_equal(identity, np.ones((63, 5)))
    path = volatility_term_structure(
        residuals, decay=0.94, phi=0.94, horizon=63, unconditional_window_sessions=2520,
    )
    assert path.shape == (63, 5)
    # With v_now above vbar the projected multiplier decays monotonically below 1.
    assert float(path[0, 0]) < 1.0
    assert np.all(np.diff(path[:, 0]) <= 1e-12)
    fitted = volatility_term_structure(
        residuals, decay=0.94, phi="fitted_ar1", horizon=21,
    )
    assert fitted.shape == (21, 5)
    assert np.all(fitted > 0.0)


# ── E0 identity: neutral V8 == V2, bit for bit ─────────────────────────────

def _fits(count: int = 700) -> tuple:
    endog, exog = _synthetic_market(count)
    fit_a = fit_ridge_varx(
        endog, exog, lag=1, alpha=1.0,
        endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"),
    )
    fit_b = fit_ridge_varx(
        endog, exog, lag=2, alpha=0.1,
        endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"),
        train_start=100,
    )
    return (fit_a, fit_b), endog, exog


def test_simulator_neutral_configuration_reproduces_v2_exactly() -> None:
    fits, endog, exog = _fits()
    kwargs = dict(
        weights=(0.5, 0.5), endog_history=endog, exog_last=exog[-1], anchor=1.0,
        path_count=500, horizon=63, block_length=10, ewma_lambda=0.97, seed=20260828,
    )
    v2 = simulate_correlated_paths_v2(fits, **kwargs)
    v8 = simulate_calibrated_paths_v8(fits, step_scale=None, **kwargs)
    assert v8["path_hash"] == v2["path_hash"]
    np.testing.assert_array_equal(v8["log_returns"], v2["log_returns"])
    np.testing.assert_array_equal(v8["assignments"], v2["assignments"])


def test_simulator_step_scale_changes_dispersion_not_generator_order() -> None:
    fits, endog, exog = _fits()
    kwargs = dict(
        weights=(0.5, 0.5), endog_history=endog, exog_last=exog[-1], anchor=1.0,
        path_count=500, horizon=63, block_length=10, ewma_lambda=0.97, seed=20260828,
    )
    shrink = np.full((63, 5), 0.5)
    scaled = simulate_calibrated_paths_v8(fits, step_scale=shrink, **kwargs)
    neutral = simulate_calibrated_paths_v8(fits, step_scale=None, **kwargs)
    np.testing.assert_array_equal(scaled["assignments"], neutral["assignments"])
    assert float(np.std(scaled["log_returns"][:, 0])) < float(np.std(neutral["log_returns"][:, 0]))


def test_dev_walk_forward_neutral_configuration_equals_v2_walk_forward() -> None:
    sessions = 880
    dates = _sessions(sessions)
    endog, exog = _synthetic_market(sessions, seed=11)
    common = dict(
        dates=dates, endog=endog, exog=exog,
        endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"),
        model_id="shadow.mf_dfm_varx_calibrated_v8", model_version=8,
    )
    v2_scores, _ = walk_forward_backtest_v2(
        outer_start=dates[800], path_count=200, **common,
    )
    v8_scores, summary = walk_forward_dev_backtest_v8(
        config=DistributionConfigV8(), outer_start=dates[800], outer_end=dates[-1],
        path_count=200, collect_cramer_audit=False, **common,
    )
    assert len(v8_scores) == len(v2_scores) > 0
    assert v8_scores == v2_scores
    assert summary["config"]["phi"] is None


def test_dev_walk_forward_respects_the_window_end() -> None:
    sessions = 880
    dates = _sessions(sessions)
    endog, exog = _synthetic_market(sessions, seed=11)
    scores, summary = walk_forward_dev_backtest_v8(
        dates=dates, endog=endog, exog=exog,
        endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"),
        model_id="m", model_version=8,
        config=DistributionConfigV8(), outer_start=dates[800], outer_end=dates[805],
        path_count=200, collect_cramer_audit=False,
    )
    assert scores
    assert max(row.date for row in scores) <= dates[805]
    assert summary["window"]["outer_end"] == dates[805]


# ── B2 bounded location anchor ─────────────────────────────────────────────

def test_bounded_location_shift_identity_cap_and_targets() -> None:
    rng = np.random.default_rng(5)
    increments = rng.normal(-0.001, 0.01, size=(2000, 63))
    paths = np.cumsum(increments, axis=1)
    returns = rng.normal(0.0005, 0.01, size=3000)
    zero = bounded_location_shift(
        paths, training_returns=returns,
        omega_by_horizon={1: 0.0, 5: 0.0, 21: 0.0, 63: 0.0}, sigma_cap=0.25,
    )
    np.testing.assert_array_equal(zero, np.zeros(63))
    shift = bounded_location_shift(
        paths, training_returns=returns,
        omega_by_horizon={1: 0.0, 5: 0.25, 21: 0.5, 63: 1.0}, sigma_cap=0.25,
    )
    mu_hat = float(np.mean(returns))
    for horizon, omega in ((5, 0.25), (21, 0.5), (63, 1.0)):
        cumulative = float(np.sum(shift[:horizon]))
        mean_cum = float(np.mean(paths[:, horizon - 1]))
        sigma = float(np.std(paths[:, horizon - 1], ddof=1))
        target = float(np.clip(omega * (mu_hat * horizon - mean_cum), -0.25 * sigma, 0.25 * sigma))
        assert cumulative == pytest.approx(target, abs=1e-12)
        assert abs(cumulative) <= 0.25 * sigma + 1e-12


def test_bounded_location_shift_rejects_unbounded_parameters() -> None:
    paths = np.zeros((100, 63))
    returns = np.full(300, 0.001)
    with pytest.raises(Exception):
        bounded_location_shift(
            paths, training_returns=returns,
            omega_by_horizon={63: 1.5}, sigma_cap=0.25,
        )
    with pytest.raises(Exception):
        bounded_location_shift(
            np.ones((10, 63)), training_returns=returns[:10],
            omega_by_horizon={63: 1.0}, sigma_cap=0.25,
        )


# ── B3 blend: exact mixture identities ─────────────────────────────────────

def _direct_mixture_crps(x: np.ndarray, y: np.ndarray, w: float, actual: float) -> float:
    grid = np.sort(np.unique(np.concatenate((x, y, [actual]))))
    total = 0.0
    for left, right in zip(grid[:-1], grid[1:]):
        f_mix = w * np.mean(x <= left) + (1 - w) * np.mean(y <= left)
        heaviside = 1.0 if left >= actual else 0.0
        total += (f_mix - heaviside) ** 2 * (right - left)
    return float(total)


def test_mixture_crps_identity_matches_direct_integration() -> None:
    rng = np.random.default_rng(9)
    x = rng.normal(0.0, 1.0, size=60)
    y = rng.normal(0.5, 1.4, size=45)
    actual = 0.3
    for w in (1.0, 0.75, 0.5, 0.0):
        via_identity = mixture_crps(
            sample_crps(x, actual), sample_crps(y, actual),
            weight=w, distance=cramer_distance(x, y),
        )
        assert via_identity == pytest.approx(_direct_mixture_crps(x, y, w, actual), abs=1e-12)


def test_cramer_distance_properties() -> None:
    rng = np.random.default_rng(2)
    x = rng.normal(size=200)
    assert cramer_distance(x, x) == pytest.approx(0.0, abs=1e-15)
    y = x + 10.0
    assert cramer_distance(x, y) > 1.0
    assert cramer_distance(x, y) == pytest.approx(cramer_distance(y, x), rel=1e-12)


def test_mixture_quantiles_weighted_point_masses() -> None:
    x = np.asarray([0.0, 0.0])
    y = np.asarray([1.0, 1.0])
    values = mixture_quantiles(x, y, weight=0.75, quantiles=(0.5, 0.9))
    assert values[0] == 0.0 and values[1] == 1.0
    np.testing.assert_array_equal(
        mixture_quantiles(x, y, weight=1.0, quantiles=(0.5,)), np.asarray([0.0]),
    )


# ── B4 walk-forward PIT recalibration ──────────────────────────────────────

def test_recalibration_levels_identity_on_uniform_history() -> None:
    rng = np.random.default_rng(4)
    uniform = rng.uniform(0.0, 1.0, size=5000)
    targets = np.asarray([0.10, 0.25, 0.50, 0.75, 0.90])
    remapped = recalibration_levels(uniform, target_levels=targets, shrinkage=0.25)
    np.testing.assert_allclose(remapped, targets, atol=0.02)


def test_recalibration_sharpens_an_overdispersed_forecaster() -> None:
    rng = np.random.default_rng(6)
    # Forecaster claims N(0,2) while outcomes are N(0,1): PITs concentrate
    # around 0.5 and the recalibrated 10-90 band must shrink toward the truth.
    outcomes = rng.normal(0.0, 1.0, size=500)
    from scipy.stats import norm
    pits = norm.cdf(outcomes, scale=2.0)
    samples = rng.normal(0.0, 2.0, size=4000)
    midpoints = (np.arange(len(samples)) + 0.5) / len(samples)
    remapped = recalibration_levels(pits, target_levels=midpoints, shrinkage=0.25)
    recalibrated = np.quantile(np.sort(samples), remapped)
    original_width = np.quantile(samples, 0.90) - np.quantile(samples, 0.10)
    new_width = np.quantile(recalibrated, 0.90) - np.quantile(recalibrated, 0.10)
    true_width = 2 * norm.ppf(0.90)
    assert new_width < original_width
    assert abs(new_width - true_width) < abs(original_width - true_width)
    assert np.all(np.diff(np.sort(recalibrated)) >= 0.0)


def test_recalibration_levels_reject_bad_inputs() -> None:
    with pytest.raises(Exception):
        recalibration_levels(np.asarray([0.5, 1.5]), target_levels=np.asarray([0.5]), shrinkage=0.25)
    with pytest.raises(Exception):
        recalibration_levels(np.asarray([]), target_levels=np.asarray([0.5]), shrinkage=0.25)
    with pytest.raises(Exception):
        recalibration_levels(np.asarray([0.5]), target_levels=np.asarray([0.5]), shrinkage=1.5)


def test_mixture_quantile_function_and_cdf_are_consistent() -> None:
    rng = np.random.default_rng(8)
    x = rng.normal(0.0, 1.0, size=300)
    y = rng.normal(1.0, 2.0, size=200)
    levels = np.asarray([0.10, 0.50, 0.90])
    np.testing.assert_array_equal(
        mixture_quantile_function(x, y, weight=1.0, levels=levels),
        np.quantile(x, levels),
    )
    np.testing.assert_array_equal(
        mixture_quantile_function(x, y, weight=0.5, levels=levels),
        mixture_quantiles(x, y, weight=0.5, quantiles=(0.10, 0.50, 0.90)),
    )
    value = mixture_quantile_function(x, y, weight=0.5, levels=np.asarray([0.5]))[0]
    assert mixture_cdf_at(x, y, weight=0.5, value=value) == pytest.approx(0.5, abs=0.01)


def test_walk_forward_pit_warmup_below_minimum_is_identity() -> None:
    sessions = 880
    dates = _sessions(sessions)
    endog, exog = _synthetic_market(sessions, seed=11)
    common = dict(
        dates=dates, endog=endog, exog=exog,
        endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"),
        model_id="m", model_version=8,
        outer_start=dates[800], outer_end=dates[-1],
        path_count=200, collect_cramer_audit=False,
    )
    plain, _ = walk_forward_dev_backtest_v8(config=DistributionConfigV8(), **common)
    recal, summary = walk_forward_dev_backtest_v8(
        config=DistributionConfigV8(pit_recalibration_shrinkage=0.25), **common,
    )
    # Only a handful of origins exist, far below the 104-matured minimum:
    # the recalibration must not have fired and scores must be identical.
    assert summary["pit_recalibrated_origins"] == {"1": 0, "5": 0, "21": 0, "63": 0}
    assert recal == plain


# ── preregistered grid enforcement ─────────────────────────────────────────

def test_config_grid_accepts_registered_and_rejects_unregistered(tmp_path: Path) -> None:
    contract = load_contract_v8(_root(tmp_path))
    neutral = build_config_from_grids(contract, {})
    assert neutral.is_v2_identity()
    tuned = build_config_from_grids(contract, {
        "phi": 0.97,
        "omega_by_horizon": {21: 0.5, 63: 1.0},
        "sigma_cap": 0.35,
        "blend_weight_by_horizon": {21: 0.75, 63: 0.5},
        "pit_recalibration_shrinkage": 0.25,
    })
    assert tuned.phi == 0.97
    assert tuned.omega_by_horizon[63] == 1.0
    assert tuned.pit_recalibration_shrinkage == 0.25
    for bad in (
        {"phi": 0.5},
        {"omega_by_horizon": {63: 0.9}},
        {"sigma_cap": 0.5},
        {"blend_weight_by_horizon": {63: 0.25}},
        {"unconditional_window_sessions": 999},
        {"pit_recalibration_shrinkage": 0.75},
        {"unknown_key": 1},
    ):
        with pytest.raises(TimeSeriesV8ContractError):
            build_config_from_grids(contract, bad)


# ── B5 filtered-historical-simulation long-horizon reconstruction ──────────

def test_fhs_is_deterministic_and_recenters_on_the_pit_drift() -> None:
    rng = np.random.default_rng(12)
    returns = rng.normal(0.0006, 0.011, size=3000)
    first = fhs_horizon_samples(returns, horizon=63, ewma_lambda=0.97)
    second = fhs_horizon_samples(returns, horizon=63, ewma_lambda=0.97)
    np.testing.assert_array_equal(first, second)
    mu_hat = float(np.mean(returns))
    # Homoskedastic input: the reconstruction is a recentered historical
    # simulation, so its mean sits on the drift and its dispersion matches
    # the raw windows to within EWMA noise.
    assert float(np.mean(first)) == pytest.approx(mu_hat * 63, abs=5e-3)
    raw_windows = np.convolve(returns, np.ones(63), mode="valid")
    assert float(np.std(first)) == pytest.approx(float(np.std(raw_windows)), rel=0.25)


def test_fhs_width_conditions_on_current_volatility() -> None:
    rng = np.random.default_rng(13)
    calm = rng.normal(0.0004, 0.008, size=2600)
    stormy_tail = rng.normal(0.0, 0.030, size=120)
    calm_then_storm = np.concatenate((calm, stormy_tail))
    storm_then_calm = np.concatenate((stormy_tail, calm))
    wide = fhs_horizon_samples(calm_then_storm, horizon=21, ewma_lambda=0.97)
    narrow = fhs_horizon_samples(storm_then_calm, horizon=21, ewma_lambda=0.97)
    assert float(np.std(wide)) > 2.0 * float(np.std(narrow))


def test_fhs_tilt_is_bounded_and_requires_the_engine_mean() -> None:
    rng = np.random.default_rng(14)
    returns = rng.normal(0.0005, 0.012, size=2600)
    base = fhs_horizon_samples(returns, horizon=63, ewma_lambda=0.97)
    tilted = fhs_horizon_samples(
        returns, horizon=63, ewma_lambda=0.97,
        tilt_omega=0.5, tilt_cap_sigma=0.25, engine_mean=-0.50,
    )
    shift = float(np.mean(tilted) - np.mean(base))
    spread = float(np.std(base, ddof=1))
    assert shift < 0.0
    assert abs(shift) <= 0.25 * spread + 1e-12
    with pytest.raises(Exception):
        fhs_horizon_samples(returns, horizon=63, ewma_lambda=0.97, tilt_omega=0.5)


def test_walk_forward_fhs_replaces_only_registered_horizons() -> None:
    sessions = 880
    dates = _sessions(sessions)
    endog, exog = _synthetic_market(sessions, seed=11)
    common = dict(
        dates=dates, endog=endog, exog=exog,
        endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"),
        model_id="m", model_version=8,
        outer_start=dates[800], outer_end=dates[805],
        path_count=200, collect_cramer_audit=False,
    )
    plain, _ = walk_forward_dev_backtest_v8(config=DistributionConfigV8(), **common)
    fhs, _ = walk_forward_dev_backtest_v8(
        config=DistributionConfigV8(fhs_horizons=(21, 63)), **common,
    )
    plain_by = {(row.date, row.horizon): row for row in plain}
    fhs_by = {(row.date, row.horizon): row for row in fhs}
    assert set(plain_by) == set(fhs_by)
    for key, row in fhs_by.items():
        if key[1] in (1, 5):
            assert row == plain_by[key]
        else:
            assert row.model_crps != plain_by[key].model_crps


def test_fhs_grid_membership_is_enforced(tmp_path: Path) -> None:
    contract = load_contract_v8(_root(tmp_path))
    enabled = build_config_from_grids(contract, {
        "fhs_horizons": [21, 63], "fhs_vol_projection": "current_ewma",
        "fhs_tilt_omega": 0.25, "fhs_tilt_cap_sigma": 0.35,
    })
    assert enabled.fhs_horizons == (21, 63)
    assert not enabled.is_v2_identity()
    for bad in (
        {"fhs_horizons": [5]},
        {"fhs_vol_projection": "garch"},
        {"fhs_tilt_omega": 0.9},
        {"fhs_tilt_cap_sigma": 0.5},
    ):
        with pytest.raises(TimeSeriesV8ContractError):
            build_config_from_grids(contract, bad)


# ── ledgers and verification ───────────────────────────────────────────────

def _ledger_row(identity: str) -> dict:
    return {
        "schema_version": 1, "experiment_id": identity, "experiment_label": "E1",
        "parent_experiment_id": None, "window_role": "design",
        "window": {"outer_start": "2007-01-01", "outer_end": "2014-12-31"},
        "knowledge_cutoff": "2026-08-28T00:00:00+00:00",
        "model_id": "shadow.mf_dfm_varx_calibrated_v8", "model_version": 8,
        "contract_hash": "c" * 64, "model_code_hash": "d" * 64,
        "bundle_hash": "e" * 64, "config": {}, "path_count": 2000,
        "horizons": {}, "paired_long_horizon": {"origin_count": 1, "mean": -0.001,
                                                "ci90": {"lower": -0.002, "upper": -0.0005},
                                                "best_baselines": {}},
        "cramer_distance_mean": {}, "gfc_regime_coverage": None,
        "proxy": {"window_role": "design", "checks": {}, "pass": False},
    }


def test_experiment_ledger_is_append_only(tmp_path: Path) -> None:
    root = _root(tmp_path)
    row = _ledger_row("tsv8-exp-aaaaaaaaaaaaaaaaaaaa")
    assert append_experiment(root, row) is True
    assert append_experiment(root, row) is False  # identical replay is a no-op
    mutated = dict(row)
    mutated["experiment_label"] = "E1-modified"
    with pytest.raises(TimeSeriesV8ArtifactError):
        append_experiment(root, mutated)
    assert len(read_experiments(root)) == 1


def test_verify_flags_budget_ledger_and_premature_sealed_ledger(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert verify_timeseries_v8(root)["ok"] is True
    append_experiment(root, _ledger_row("tsv8-exp-bbbbbbbbbbbbbbbbbbbb"))
    result = verify_timeseries_v8(root)
    assert result["ok"] is True and result["experiments"] == 1
    ledger = root / "data/timeseries_v8/ledgers/development_experiments.jsonl"
    body = ledger.read_text(encoding="utf-8").replace("E1", "EX")
    ledger.write_text(body, encoding="utf-8")
    tampered = verify_timeseries_v8(root)
    assert tampered["ok"] is False
    assert any("hash mismatch" in error for error in tampered["errors"])
    sealed = root / SEALED_LEDGER_RELATIVE
    sealed.write_text("{}\n", encoding="utf-8")
    # The repo contract is frozen with the R8-D2 sign-off, so a sealed ledger
    # is legitimate; removing the freeze stamp must flag it again.
    frozen_ok = verify_timeseries_v8(root)
    assert not any("sealed" in error for error in frozen_ok["errors"])
    contract_path = root / "data/contracts/multivariate_timeseries_v8.yaml"
    payload = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    payload["freeze_note"]["frozen_on"] = None
    contract_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    premature = verify_timeseries_v8(root)
    assert any("sealed" in error for error in premature["errors"])


# ── sealed-evaluation preconditions ────────────────────────────────────────

def _passing_holdout_row(contract: dict) -> dict:
    manifest = build_config_from_grids(
        contract, json.loads(json.dumps(contract["frozen_winner"]["config_overrides"])),
    ).as_manifest()
    return {
        "schema_version": 1, "experiment_id": "tsv8-exp-holdoutpass000000000",
        "experiment_label": "E10_holdout_scoring", "parent_experiment_id": None,
        "window_role": "holdout",
        "window": {"outer_start": "2007-01-01", "outer_end": "2018-12-31"},
        "knowledge_cutoff": "2026-08-30T00:00:00+00:00",
        "model_id": "shadow.mf_dfm_varx_calibrated_v8", "model_version": 8,
        "contract_hash": "c" * 64, "model_code_hash": "d" * 64,
        "bundle_hash": "e" * 64, "config": manifest, "path_count": 20000,
        "horizons": {}, "paired_long_horizon": {"origin_count": 209, "mean": -0.0022,
                                                "ci90": {"lower": -0.0033, "upper": -0.0011},
                                                "best_baselines": {}},
        "cramer_distance_mean": {}, "gfc_regime_coverage": None,
        "proxy": {"window_role": "holdout", "checks": {}, "pass": True},
    }


def test_sealed_preconditions_enforce_every_gate(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v8(root)
    with pytest.raises(TimeSeriesV8PipelineError, match="sign-off"):
        _sealed_preconditions(root, contract, user_signoff="  ", path_count=20000)
    unfrozen = json.loads(json.dumps(contract))
    unfrozen["freeze_note"]["frozen_on"] = None
    with pytest.raises(TimeSeriesV8PipelineError, match="frozen"):
        _sealed_preconditions(root, unfrozen, user_signoff="R8-D2 approved", path_count=20000)
    with pytest.raises(TimeSeriesV8PipelineError, match="20000"):
        _sealed_preconditions(root, contract, user_signoff="R8-D2 approved", path_count=2000)
    with pytest.raises(TimeSeriesV8PipelineError, match="holdout"):
        _sealed_preconditions(root, contract, user_signoff="R8-D2 approved", path_count=20000)
    append_holdout_scoring(root, _passing_holdout_row(contract))
    ready = _sealed_preconditions(root, contract, user_signoff="R8-D2 approved", path_count=20000)
    assert ready["config"].fhs_horizons == (21, 63)
    (root / SEALED_LEDGER_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (root / SEALED_LEDGER_RELATIVE).write_text("{}\n", encoding="utf-8")
    with pytest.raises(TimeSeriesV8PipelineError, match="already disclosed"):
        _sealed_preconditions(root, contract, user_signoff="R8-D2 approved", path_count=20000)


def test_sealed_preconditions_reject_a_failed_or_mismatched_holdout(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v8(root)
    failed = _passing_holdout_row(contract)
    failed["proxy"] = {"window_role": "holdout", "checks": {}, "pass": False}
    append_holdout_scoring(root, failed)
    with pytest.raises(TimeSeriesV8PipelineError, match="holdout"):
        _sealed_preconditions(root, contract, user_signoff="R8-D2 approved", path_count=20000)
    mismatched = _passing_holdout_row(contract)
    mismatched["experiment_id"] = "tsv8-exp-holdoutother0000000"
    mismatched["config"] = {**mismatched["config"], "pit_recalibration_shrinkage": 0.25}
    append_holdout_scoring(root, mismatched)
    with pytest.raises(TimeSeriesV8PipelineError, match="holdout"):
        _sealed_preconditions(root, contract, user_signoff="R8-D2 approved", path_count=20000)


# ── dev-gate proxy report ──────────────────────────────────────────────────

def _proxy(tmp_path: Path) -> dict:
    return load_contract_v8(_root(tmp_path))["dev_gate_proxy"]


def test_dev_gate_proxy_report_passes_only_when_every_check_passes(tmp_path: Path) -> None:
    proxy = _proxy(tmp_path)
    summary = {
        "horizons": {
            "1": {"crps_improvement_vs_best": 0.03, "coverage_p10_p90": 0.80, "coverage_p25_p75": 0.50},
            "5": {"crps_improvement_vs_best": 0.02, "coverage_p10_p90": 0.80, "coverage_p25_p75": 0.50},
            "21": {"crps_improvement_vs_best": 0.05, "coverage_p10_p90": 0.79, "coverage_p25_p75": 0.51},
            "63": {"crps_improvement_vs_best": 0.04, "coverage_p10_p90": 0.78, "coverage_p25_p75": 0.49},
        },
        "regime_coverage": {"great_financial_crisis_2008": {"origins": 70, "coverage_p10_p90": 0.75}},
    }
    paired = {
        "mean": -0.0013, "origin_count": 417,
        "ci90": {"lower": -0.0026, "upper": -0.0001},
    }
    report = dev_gate_proxy_report(summary, paired, proxy=proxy, window_role="design")
    assert report["pass"] is True
    weak = json.loads(json.dumps(summary))
    weak["horizons"]["21"]["crps_improvement_vs_best"] = 0.02
    weak["horizons"]["63"]["crps_improvement_vs_best"] = 0.02  # mean below +2.5%
    report = dev_gate_proxy_report(weak, paired, proxy=proxy, window_role="design")
    assert report["pass"] is False
    assert report["checks"]["long_horizon_mean_improvement"]["pass"] is False
    noisy = {
        "mean": -0.0013, "origin_count": 417,
        "ci90": {"lower": -0.0060, "upper": 0.0034},  # se ~0.0029 > 0.001
    }
    report = dev_gate_proxy_report(summary, noisy, proxy=proxy, window_role="design")
    assert report["checks"]["paired_se"]["pass"] is False
    assert report["checks"]["projected_full_window_ci90_upper"]["pass"] is False


def test_dev_gate_proxy_holdout_checks(tmp_path: Path) -> None:
    proxy = _proxy(tmp_path)
    summary = {"horizons": {
        "21": {"crps_improvement_vs_best": 0.03},
        "63": {"crps_improvement_vs_best": 0.02},
    }}
    passing = dev_gate_proxy_report(
        summary, {"ci90": {"lower": -0.004, "upper": -0.0001}}, proxy=proxy, window_role="holdout",
    )
    assert passing["pass"] is True
    failing = dev_gate_proxy_report(
        summary, {"ci90": {"lower": -0.004, "upper": 0.0001}}, proxy=proxy, window_role="holdout",
    )
    assert failing["pass"] is False


def test_paired_differences_use_best_baseline_per_horizon() -> None:
    from ai_fc.timeseries.backtest import OriginScore

    rows = []
    for index in range(30):
        origin = f"2010-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}"
        for horizon in (21, 63):
            rows.append(OriginScore(
                date=origin, horizon=horizon, actual_log_return=0.0,
                model_crps=0.9, baseline_crps={"historical_simulation": 1.0, "random_walk": 2.0},
                median=0.0, p10=-1.0, p25=-0.5, p75=0.5, p90=1.0,
                direction_correct=True, first_touch_actual=False,
                first_touch_probability=0.0, expanding_crps=0.9, rolling_crps=0.9,
            ))
    paired = paired_differences_vs_best(rows)
    assert paired["origin_count"] == 30
    assert paired["best_baselines"] == {"21": "historical_simulation", "63": "historical_simulation"}
    assert paired["mean"] == pytest.approx(-0.1)
