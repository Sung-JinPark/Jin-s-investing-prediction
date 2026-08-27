import numpy as np

from ai_fc.timeseries_v7_r5.conditional_scale_selection import (
    _crps_scaled,
    _ewma_paths,
    _garch_scale,
    _garch_variance_path,
    _mature_training_labels,
    _rv_features,
    fit_garch_t,
    fit_har,
)


def test_har_recovers_positive_finite_direct_scale() -> None:
    rng = np.random.default_rng(7)
    features = np.column_stack([np.ones(500), rng.normal(size=(500, 3))])
    target = np.exp(features @ np.array([-5.0, 0.2, 0.1, 0.05]) + rng.normal(scale=0.1, size=500))
    fit = fit_har(features, target, horizon=21, alpha=1e-4)
    assert fit.forecast(features[-1]) > 0
    assert np.isfinite(fit.forecast(features[-1]))


def test_rv_and_ewma_are_past_only_and_positive() -> None:
    returns = np.linspace(-0.01, 0.01, 100)
    feature = _rv_features(returns, 50)
    changed_future = returns.copy()
    changed_future[51:] = 99
    assert np.array_equal(feature, _rv_features(changed_future, 50))
    assert all(np.all(path > 0) for path in _ewma_paths(returns).values())


def test_garch_t_fit_and_forecast_are_finite() -> None:
    rng = np.random.default_rng(11)
    returns = rng.standard_t(df=8, size=800) * 0.01
    fit = fit_garch_t(returns)
    path = _garch_variance_path(returns, fit)
    assert fit.alpha + fit.beta < 0.999
    assert fit.degrees_of_freedom > 2
    assert _garch_scale(returns, path, 700, 21, fit) > 0


def test_scaled_empirical_crps_prefers_matching_scale() -> None:
    samples = np.sort(np.linspace(-1.0, 1.0, 101))
    assert _crps_scaled(samples, 0.0, np.std(samples, ddof=1)) < _crps_scaled(samples, 0.0, 10.0)


def test_training_pool_excludes_labels_that_mature_after_role_cutoff() -> None:
    origins = {"2020-01-02", "2020-01-03"}
    lookup = {
        ("2020-01-02", 5): {"origin_session": "2020-01-02", "mature_at": "2020-01-03T21:00:00Z"},
        ("2020-01-03", 5): {"origin_session": "2020-01-03", "mature_at": "2020-01-10T21:00:00Z"},
    }
    rows = _mature_training_labels(lookup, origins, 5)
    assert [row["origin_session"] for row in rows] == ["2020-01-02"]
