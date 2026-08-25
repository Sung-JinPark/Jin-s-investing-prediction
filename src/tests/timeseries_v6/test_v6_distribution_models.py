import numpy as np

from ai_fc.timeseries_v6.distribution_models import (
    E0ExactAnchor,
    E1QuantileElasticNet,
    E2StudentT,
    E3QuantileHGB,
    E4BayesianDynamicLinear,
    E5SoftRegimePartialPooling,
    E6AsymmetricEVTTail,
    E7PITAnalogTrajectory,
    convex_sample_mixture,
    empirical_crps,
)
from ai_fc.timeseries_v6.research_backtest import candidate_grid


def _data(seed=7):
    rng = np.random.default_rng(seed); x = rng.normal(size=(260, 4)); scale = np.exp(0.2 * x[:, 1]); y = 0.02 * x[:, 0] + scale * rng.standard_t(6, size=len(x)) * 0.01
    return x, y


def test_e0_exact_samples_and_crps_identity() -> None:
    _, y = _data(); model = E0ExactAnchor.fit(y); forecast = model.predict()
    assert np.array_equal(forecast.samples, np.sort(y))
    assert empirical_crps(forecast.samples, 0.0) == empirical_crps(np.sort(y), 0.0)


def test_direct_candidates_recover_location_and_monotone_distribution() -> None:
    x, y = _data()
    models = [
        E1QuantileElasticNet.fit(x, y, alpha=0.0001, l1_ratio=0.1, max_iter=1000),
        E2StudentT.fit(x, y, degrees_of_freedom=6, ridge_alpha=0.1),
        E3QuantileHGB.fit(x, y, learning_rate=0.03, max_leaf_nodes=7, max_iter=100, l2_regularization=0.0, min_samples_leaf=20),
    ]
    forecasts = [model.predict(x[-1]) for model in models]
    assert all(np.all(np.diff(item.quantiles) >= 0) for item in forecasts)
    mixture = convex_sample_mixture([E0ExactAnchor.fit(y).predict(), forecasts[1]], np.asarray([0.5, 0.5]))
    assert len(mixture.samples) == 4000
    assert mixture.runtime_parameters["weights"] == [0.5, 0.5]


def test_preregistered_e4_e7_challengers_are_deterministic_and_monotone() -> None:
    rng = np.random.default_rng(11)
    x = rng.normal(size=(700, 4))
    y = 0.02 * x[:, 0] + np.exp(0.2 * x[:, 1]) * rng.standard_t(6, size=len(x)) * 0.01
    models = [
        E4BayesianDynamicLinear.fit(x, y, state_discount=0.98, prior_variance=1.0),
        E5SoftRegimePartialPooling.fit(x, y, global_shrinkage=0.5),
        E6AsymmetricEVTTail.fit(x, y, threshold_quantile=0.90),
        E7PITAnalogTrajectory.fit(x, y, neighbor_count=10),
    ]
    for model in models:
        first = model.predict(x[-1])
        second = model.predict(x[-1])
        assert np.array_equal(first.samples, second.samples)
        assert np.all(np.diff(first.quantiles) >= 0)
        assert 0 <= first.up_probability <= 1


def test_e5_rebalances_tiny_kmeans_regime_without_lowering_frozen_ess_floor() -> None:
    rng = np.random.default_rng(260824)
    z = rng.normal(size=(180, 3))
    labels = np.r_[np.zeros(100, dtype=int), np.ones(75, dtype=int), np.full(5, 2, dtype=int)]
    centers = np.vstack([z[labels == index].mean(axis=0) for index in range(3)])
    balanced, changed = E5SoftRegimePartialPooling._rebalance_labels(z, labels, centers, 50)
    assert changed is True
    assert np.bincount(balanced, minlength=3).min() >= 50


def test_e7_rejects_infeasible_temporally_spaced_neighbor_count() -> None:
    x, y = _data()
    import pytest

    with pytest.raises(Exception, match="temporal-spacing"):
        E7PITAnalogTrajectory.fit(x, y, neighbor_count=40)


def test_e4_e7_runtime_grids_match_frozen_coordinates() -> None:
    assert candidate_grid("E4") == [
        {"state_discount": discount, "prior_variance": prior}
        for discount in (0.98, 0.995)
        for prior in (1.0, 10.0)
    ]
    assert [row["global_shrinkage"] for row in candidate_grid("E5")] == [0.25, 0.5, 0.75]
    assert [row["threshold_quantile"] for row in candidate_grid("E6")] == [0.9, 0.95]
    assert [row["neighbor_count"] for row in candidate_grid("E7")] == [10, 20, 40]
