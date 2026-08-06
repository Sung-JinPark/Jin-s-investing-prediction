from __future__ import annotations

import numpy as np

from ai_fc.shadow_models import (
    breeden_litzenberger_density, ewma_variance, fit_garch11, regime_block_bootstrap,
)


def test_volatility_shadows_and_bootstrap_are_deterministic() -> None:
    rng = np.random.default_rng(1)
    returns = rng.normal(0, .01, 400)
    assert ewma_variance(returns) > 0
    fit = fit_garch11(returns)
    assert fit.omega > 0 and fit.alpha >= 0 and fit.beta >= 0 and fit.alpha + fit.beta < 1
    one = regime_block_bootstrap(returns, horizon=20, n_paths=10, seed=4)
    two = regime_block_bootstrap(returns, horizon=20, n_paths=10, seed=4)
    assert np.array_equal(one, two)


def test_breeden_litzenberger_is_explicitly_risk_neutral() -> None:
    strikes = np.linspace(80, 120, 41)
    calls = np.maximum(100 - strikes, 0) + 5 * np.exp(-((strikes - 100) / 12) ** 2)
    result = breeden_litzenberger_density(
        strikes, calls, risk_free_rate=.04, maturity_years=.25)
    assert result["probability_space"] == "risk_neutral_terminal"
    np.testing.assert_allclose(
        np.trapezoid(result["density"], result["strikes"]), 1.0, atol=1e-8)
