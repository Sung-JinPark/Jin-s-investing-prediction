"""Small structural integrity checks; never mutate durable records."""
from __future__ import annotations
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
import relative_ml as ml


class RelativeMLTests(unittest.TestCase):
    def panel(self, n=220):
        dates = pd.bdate_range("2020-01-01", periods=n).strftime("%Y-%m-%d")
        rng = np.random.default_rng(5)
        return pd.DataFrame(np.exp(np.cumsum(rng.normal(.0001, .01, (n, 3)), axis=0))*100,
                            columns=["SOXX", "IGV", "SPY"], index=dates)

    def test_feature_causality(self):
        panel = self.panel()
        first = ml.make_features(panel)
        changed = panel.copy(); changed.iloc[180:] *= [2, .1, 3]
        pd.testing.assert_frame_equal(first.iloc[:180], ml.make_features(changed).iloc[:180])

    def test_target_is_gross_return_ratio(self):
        panel = pd.DataFrame({"SOXX": [100., 120.], "IGV": [100., 110.], "SPY": [100., 105.]})
        target = ml.relative_target(panel, 1)
        self.assertAlmostEqual(np.expm1(target.iloc[0]), 1.2/1.1-1)
        self.assertTrue(pd.isna(target.iloc[1]))

    def test_strict_embargo(self):
        for horizon in [21, 57]:
            indices = ml.purged_training_indices(200, horizon, np.ones(300, dtype=bool))
            self.assertEqual(indices[-1]+horizon, 199)
            self.assertTrue(np.all(indices+horizon < 200))

    def test_unmatured_labels_not_training(self):
        valid = np.ones(300, dtype=bool); valid[:126] = False
        indices = ml.purged_training_indices(200, 57, valid)
        self.assertTrue(np.all((indices >= 126) & (indices <= 142)))

    def test_scaler_is_train_only(self):
        estimator = ml.models()["ridge"]
        train = np.array([[1., 2.], [3., 4.], [5., 6.]])
        estimator.fit(train, np.array([0., 1., 2.]))
        estimator.predict(np.array([[1000., 1000.]]))
        np.testing.assert_array_equal(estimator[0].mean_, [3., 4.])

    def test_invalid_price_rejected(self):
        for value in [np.nan, 0., -1., np.inf]:
            with self.assertRaises(ValueError):
                ml.finite_positive(pd.Series([1., value]), "fixture")

    def test_historical_split_scaling_invariant(self):
        panel = self.panel()
        original = ml.relative_target(panel, 21)
        scaled = panel.copy(); scaled.SOXX /= 3
        np.testing.assert_allclose(original, ml.relative_target(scaled, 21), equal_nan=True, atol=1e-14)

    def test_price_session_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)/"price_inputs"; directory.mkdir()
            for symbol in ["SOXX", "IGV", "SPY"]:
                pd.DataFrame({"date": ["2026-10-08", "2026-10-09" if symbol != "IGV" else "2026-10-07"],
                              "adj_close": [100., 101.]}).to_csv(directory/f"{symbol}_adjusted_history.csv", index=False)
            with self.assertRaises(ValueError):
                ml.load_prices(Path(folder))

    def test_declared_end_of_year_session_horizon(self):
        import exchange_calendars as xcals
        self.assertEqual(len(xcals.get_calendar("XNYS").sessions_in_range("2026-10-12", "2026-12-31")), 57)

    def test_bootstrap_deterministic(self):
        values = np.linspace(-.02, .03, 300)
        self.assertEqual(ml.block_bootstrap_interval(values, 21), ml.block_bootstrap_interval(values, 21))


if __name__ == "__main__":
    unittest.main()
