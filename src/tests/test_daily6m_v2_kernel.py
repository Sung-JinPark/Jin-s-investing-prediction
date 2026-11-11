"""daily6m v2 kernel: synthetic only (no network, no repository writes)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from ai_fc.timeseries.backtest import sample_crps
from ai_fc.timeseries.model import fit_ridge_varx
from ai_fc.timeseries_daily6m.contracts import ENDOGENOUS_NAMES, EXOGENOUS_NAMES
from ai_fc.timeseries_daily6m_v2 import kernel as K
from ai_fc.timeseries_daily6m_v2.contracts import Daily6mV2ContractError
from ai_fc.timeseries_v2.model import _ewma_scale, simulate_correlated_paths_v2

SMALL = {"selection": {"seed": 20261111, "replicates": 3, "paths": 200, "validation_horizon": 21,
                       "hysteresis_mc_sd": 1.0, "default_incumbent": [10, 0.97]}}


def residuals(rows=700, seed=3):
    rng = np.random.default_rng(seed)
    values = rng.standard_t(5, (rows, 5)) * 0.01
    values[-200:] *= 1.8
    return values


def test_fresh_scale_keeps_v1_lagged_denominator_and_constant_column_multiple():
    e = residuals()
    for decay in (0.94, 0.97):
        scale, fresh, lagged = K.fresh_ewma_scale(e, decay)
        v1 = _ewma_scale(e, decay)
        assert np.allclose(scale, v1 * np.sqrt(fresh / lagged)[None, :], rtol=0, atol=1e-12)
        assert np.allclose(fresh, decay * lagged + (1 - decay) * e[-1] ** 2, rtol=1e-15, atol=0)
        assert np.array_equal(K.lagged_ewma_scale(e, decay), v1)


def test_fresh_variance_reacts_to_the_origin_residual():
    e = residuals()
    shock = e.copy()
    shock[-1] = 0.2
    zero = e.copy()
    zero[-1] = 0.0
    _, fresh_shock, lagged = K.fresh_ewma_scale(shock, 0.97)
    assert np.all(fresh_shock > lagged)
    _, fresh_zero, lagged_zero = K.fresh_ewma_scale(zero, 0.97)
    assert np.allclose(fresh_zero, 0.97 * lagged_zero, rtol=1e-15)


def test_variance_term_structure_shape():
    fresh = np.array([4.0, 1.0, 2.0])
    long_run = np.array([1.0, 4.0, 2.0])
    g = K.variance_term_structure(fresh, long_run, np.array([0.9, 0.9, 0.9]), 200)
    assert np.all(g[0] == 1.0)
    assert np.all(np.diff(g[:, 0]) < 0) and abs(g[-1, 0] - np.sqrt(1 / 4)) < 1e-6
    assert np.all(np.diff(g[:, 1]) > 0) and abs(g[-1, 1] - 2.0) < 1e-6
    assert np.allclose(g[:, 2], 1.0)
    assert np.all(K.variance_term_structure(fresh, long_run, np.ones(3), 20) == 1.0)
    assert np.allclose(K.long_run_variance(residuals(), "slow_ewma_0.996"), K.fresh_ewma_scale(residuals(), 0.996)[1])
    with pytest.raises(Daily6mV2ContractError):
        K.long_run_variance(residuals(), "design_constant_level")


def test_crn_bootstrap_is_shared_across_blocks_and_restarts_at_one_over_block():
    rng = np.random.default_rng([20261111, 0, 0])
    starts, uniforms = K.crn_stationary_bootstrap(rng, rows=900, paths=4000, horizon=21)
    again = K.crn_stationary_bootstrap(np.random.default_rng([20261111, 0, 0]), rows=900, paths=4000, horizon=21)
    assert np.array_equal(starts, again[0]) and np.array_equal(uniforms, again[1])
    for block in (5, 10, 21):
        indexes = K.crn_bootstrap_indexes(starts, uniforms, rows=900, mean_block=block)
        restart = indexes[:, 1:] != (indexes[:, :-1] + 1) % 900
        assert abs(restart.mean() - 1 / block) < 0.01
        # restarts happen exactly where the shared uniform is below 1/block
        assert np.array_equal(indexes[:, 1:][uniforms[:, 1:] < 1 / block], starts[:, 1:][uniforms[:, 1:] < 1 / block])


def test_selection_is_deterministic_and_hysteresis_holds_small_margins():
    e = residuals(760)
    first = K.select_distribution_crn(e, previous=None, constants=SMALL)
    assert first == K.select_distribution_crn(e, previous=None, constants=SMALL)
    assert first["incumbent"] == [10, 0.97] and first["previous"] is None and first["validation_origins"] > 0
    assert set(first["scores"]) == {K.selection_key(b, d) for b in (5, 10, 21) for d in (0.94, 0.97)}
    if first["chosen"] != first["best"]:
        assert first["mean_margin"] <= first["mc_sd"]
    # an incumbent whose paired margin is within 1 MC SD is kept
    huge = {"selection": {**SMALL["selection"], "hysteresis_mc_sd": 1e9}}
    held = K.select_distribution_crn(e, previous=(21, 0.94), constants=huge)
    assert held["chosen"] == [21, 0.94] and held["switched"] is False
    switch = K.select_distribution_crn(e, previous=(21, 0.94), constants={"selection": {**SMALL["selection"], "hysteresis_mc_sd": -1e9}})
    assert switch["chosen"] == switch["best"]
    outside = K.select_distribution_crn(e, previous=(7, 0.5), constants=SMALL)
    assert outside["incumbent"] == [10, 0.97]
    fallback = K.select_distribution_crn(e[:499], previous=None, constants=SMALL)
    assert fallback["fallback"] is True and fallback["chosen"] == [10, 0.97]


def test_selection_shares_one_crn_draw_across_all_six_candidates(monkeypatch):
    """Review N8: spy inside select_distribution_crn instead of calling the index builder twice."""
    draws, uses = [], []
    real_draw, real_indexes = K.crn_stationary_bootstrap, K.crn_bootstrap_indexes

    def draw(rng, *, rows, paths, horizon):
        starts, uniforms = real_draw(rng, rows=rows, paths=paths, horizon=horizon)
        draws.append((starts.tobytes(), uniforms.tobytes()))
        return starts, uniforms

    def indexes(starts, uniforms, *, rows, mean_block):
        uses.append((len(draws) - 1, starts.tobytes(), uniforms.tobytes(), mean_block))
        return real_indexes(starts, uniforms, rows=rows, mean_block=mean_block)

    monkeypatch.setattr(K, "crn_stationary_bootstrap", draw)
    monkeypatch.setattr(K, "crn_bootstrap_indexes", indexes)
    settings = {"selection": {**SMALL["selection"], "replicates": 2, "paths": 20}}
    result = K.select_distribution_crn(residuals(rows=600), previous=None, constants=settings)
    origins = result["validation_origins"]
    assert origins > 0 and len(draws) == 2 * origins            # one draw per (replicate, origin), never per candidate
    assert len(uses) == 3 * len(draws)                           # each draw feeds the three blocks ...
    for position in range(len(draws)):
        group = [use for use in uses if use[0] == position]
        assert [use[3] for use in group] == list(K.BLOCK_CANDIDATES)
        assert all(use[1:3] == draws[position] for use in group)  # ... with the very same starts and uniforms
    assert len(result["scores"]) == 6                            # and both lambdas reuse the block's indexes


def test_anchored_grid_moves_once_in_21_sessions_in_the_real_batch_shape():
    lag = 2
    rolling_length = 2520 - lag
    base_expanding = 2900
    seen = []
    for day in range(22):
        expanding = base_expanding + day
        count = expanding + rolling_length
        origins = K.anchored_validation_origins(count)
        # map to calendar day labels: rolling block starts at row `expanding` with first date `day`
        labels = [origin - expanding + day for origin in origins]
        seen.append(tuple(labels))
    changes = sum(a != b for a, b in zip(seen, seen[1:]))
    assert changes == 1
    # disclosed case, not a stability claim: a lag change alters the rolling residual length and so the positions
    shifted = K.anchored_validation_origins(base_expanding + 2520 - 5)
    assert len(shifted) == len(K.anchored_validation_origins(base_expanding + rolling_length))


@pytest.fixture
def fits():
    rng = np.random.default_rng(75)
    y = rng.normal(0, 0.008, (800, 5))
    y[:, 0] += 0.0003
    x = rng.normal(0, 0.2, (800, 3))
    expanding = fit_ridge_varx(y, x, lag=1, alpha=1.0, endog_names=ENDOGENOUS_NAMES, exog_names=EXOGENOUS_NAMES)
    rolling = fit_ridge_varx(y, x, lag=1, alpha=1.0, endog_names=ENDOGENOUS_NAMES, exog_names=EXOGENOUS_NAMES, train_start=200)
    return y, x, expanding, rolling


def test_reduced_simulator_is_bit_identical_to_sealed_v2(fits):
    y, x, expanding, rolling = fits
    kwargs = dict(weights=(0.5, 0.5), endog_history=y, exog_last=x[-1], anchor=102.0, path_count=64, horizon=30,
                  block_length=10, ewma_lambda=0.97, seed=1234)
    sealed = simulate_correlated_paths_v2((expanding, rolling), **kwargs)
    reduced = K.simulate_paths_v2_arms((expanding, rolling), persistence=np.ones(5), anchor_rule="slow_ewma_0.996",
                                       arms=("main",), fresh=False, **kwargs)
    assert np.array_equal(reduced["main"]["log_returns"], sealed["log_returns"])
    assert np.array_equal(reduced["main"]["index_paths"], sealed["index_paths"])


def test_three_arms_share_random_numbers(fits):
    y, x, expanding, rolling = fits
    boosted = replace(expanding, coefficients=expanding.coefficients.copy())
    boosted.coefficients[0, 0] = 0.01
    boosted_rolling = replace(rolling, coefficients=rolling.coefficients.copy())
    boosted_rolling.coefficients[0, 0] = 0.01
    sims = K.simulate_paths_v2_arms((boosted, boosted_rolling), weights=(0.5, 0.5), endog_history=y, exog_last=x[-1],
                                    anchor=100.0, path_count=500, horizon=40, block_length=5, ewma_lambda=0.94, seed=9,
                                    persistence=np.full(5, 0.95), anchor_rule="slow_ewma_0.996")
    assert np.array_equal(sims["main"]["log_returns"][:, 0], sims["term_structure"]["log_returns"][:, 0])
    assert sims["zero_drift"]["log_returns"].mean() < sims["main"]["log_returns"].mean()
    assert not np.array_equal(sims["main"]["log_returns"], sims["term_structure"]["log_returns"])


def test_quantile_grid_matches_bands_and_crps39():
    rng = np.random.default_rng(1)
    paths = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (3000, 12)), axis=1))
    raw = K.quantile_grid_unrounded(paths, anchor=100.0)
    records = K.summarize_compact(paths, anchor=100.0, future_dates=[f"2027-01-{d:02d}" for d in range(1, 13)])
    for row, name in zip(K.BAND_ROWS, K.BAND_NAMES):
        expected = np.log(np.array([record["band_index"][name] for record in records]) / 100.0)
        assert np.max(np.abs(raw[row] - expected)) <= 1e-12
    grid = K.quantile_grid(paths, anchor=100.0)
    assert grid.shape == (39, 12) and np.all(np.diff(grid, axis=0) >= 0)
    assert len(K.GRID_LEVELS) == 39 and K.GRID_LEVELS[0] == 0.025 and K.GRID_LEVELS[-1] == 0.975


def test_crps39_hand_cases_and_convergence():
    q = [0.0] * 39
    # y=0.1 above every quantile: losses tau*0.1; 2*trapezoid = 2*0.1*int tau from .025 to .975 = 0.1*(0.975^2-0.025^2)
    assert abs(K.crps_grid39(0.1, q) - 0.1 * (0.975 ** 2 - 0.025 ** 2)) < 1e-12
    assert abs(K.crps_grid39(-0.1, q) - 0.1 * ((1 - 0.025) ** 2 - (1 - 0.975) ** 2)) < 1e-12
    from scipy.stats import norm
    grid = [norm.ppf(t) for t in K.GRID_LEVELS]
    values = [K.crps_grid39(y, grid) for y in (-0.5, 0.0, 0.5)]
    assert values[1] < values[0] and values[1] < values[2]
    samples = np.random.default_rng(0).normal(size=200000)
    for y in (-1.0, 0.3, 1.5):
        approx, exact = K.crps_grid39(y, grid), sample_crps(samples, y)
        assert approx < exact and (exact - approx) / exact < 0.03
    with pytest.raises(Daily6mV2ContractError):
        K.crps_grid39(0.0, [0.0] * 5)


def test_non_finite_or_non_positive_paths_fail_without_clipping():
    with pytest.raises(Daily6mV2ContractError):
        K.quantile_grid(np.array([[1.0, np.nan]]), anchor=1.0)
    with pytest.raises(Daily6mV2ContractError):
        K.summarize_compact(np.array([[1.0, -1.0]]), anchor=1.0, future_dates=["a", "b"])
    assert not hasattr(K, "lead_multipliers") and not hasattr(K, "apply_width_multipliers")


def _synthetic_observations(extra_2015: int = 0):
    from types import SimpleNamespace
    import exchange_calendars as xcals
    exchange = xcals.get_calendar("XNAS", start="2012-06-01", end="2015-03-31")
    days = [d.date().isoformat() for d in exchange.sessions if d.date().isoformat() >= "2012-07-02"]
    rng = np.random.default_rng(11)
    rows = []
    levels = {"NASDAQCOM": 3000.0, "VIX": 18.0, "DGS2": 0.3, "DGS10": 1.6, "DTWEXB": 100.0}
    post = 0
    for day in days:
        if day > "2014-12-31":
            if post >= extra_2015:
                break
            post += 1
        for series, level in levels.items():
            shock = rng.normal(0, 0.01 if series != "VIX" else 0.05)
            levels[series] = level * float(np.exp(shock)) if series in ("NASDAQCOM", "VIX", "DTWEXB") else level + shock
            rows.append(SimpleNamespace(series_id=series, observation_time=day, value=levels[series]))
    return rows, post * len(levels)


def test_design_generator_is_deterministic_and_skips_post_window_rows():
    from ai_fc.timeseries_daily6m_v2 import design as D
    plain, _ = _synthetic_observations()
    mixed, extra = _synthetic_observations(extra_2015=20)
    settings = dict(replicates=2, paths=100, step=60, first_origin=400)
    panel = D.design_panel(plain)
    first = D.constants_from_design(D.compute_design(panel, **settings))
    again = D.constants_from_design(D.compute_design(D.design_panel(plain), **settings))
    assert first == again
    mixed_panel = D.design_panel(mixed)
    assert mixed_panel["post_window_rows_skipped"] == extra > 0 and mixed_panel["post_window_rows_used"] == 0
    assert mixed_panel["dates"] == panel["dates"] and mixed_panel["dates"][-1] <= "2014-12-31"
    assert np.array_equal(mixed_panel["changes"], panel["changes"])
    assert first["long_run_rule"]["registered"] in ("slow_ewma_0.996", "sample_mean_square")
    assert "lead_multipliers" not in first and first["lead_width_multiplier"].startswith("rejected")
