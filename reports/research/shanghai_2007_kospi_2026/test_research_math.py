import math
import unittest

from research_math import implied_pe_change, path_risks, profit_concentration, valuation_return


class ResearchMathTests(unittest.TestCase):
    def test_joint_eps_and_multiple_shock_is_multiplicative(self):
        self.assertAlmostEqual(valuation_return(-.2, -.2, unit="fraction"), -.36)

    def test_growth_can_coexist_with_price_loss(self):
        self.assertAlmostEqual(valuation_return(.2, -.3, unit="fraction"), -.16)

    def test_required_multiple_for_twenty_percent_loss(self):
        pe = implied_pe_change(.2, -.2, unit="fraction")
        self.assertAlmostEqual(pe, -1/3)
        self.assertAlmostEqual(valuation_return(.2, pe, unit="fraction"), -.2)

    def test_unit_is_not_inferred_from_magnitude(self):
        with self.assertRaises(ValueError):
            valuation_return(.2, .2, unit="percent")

    def test_invalid_inputs_are_rejected_not_clipped(self):
        for invalid in (-1, -1.01, math.nan, math.inf):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                valuation_return(invalid, 0, unit="fraction")

    def test_drawdown_is_distinct_from_origin_loss(self):
        result = path_risks(100, [150, 100], unit="index_points")
        self.assertAlmostEqual(result["max_drawdown_fraction"], -1/3)
        self.assertEqual(result["worst_origin_return_fraction"], 0)
        self.assertFalse(result["additional_20pct_loss_event"])

    def test_exact_twenty_percent_loss_counts(self):
        self.assertTrue(path_risks(100, [80], unit="index_points")["additional_20pct_loss_event"])

    def test_negative_or_empty_price_path_rejected(self):
        for prices in ([], [0], [-1], [math.nan]):
            with self.subTest(prices=prices), self.assertRaises(ValueError):
                path_risks(100, prices, unit="index_points")

    def test_profit_growth_concentration_not_market_contribution(self):
        result = profit_concentration(200, 80, 1, 0, unit="same_currency_and_scale;growth_fraction")
        self.assertAlmostEqual(result["current_leaders_share_fraction"], .6)
        self.assertAlmostEqual(result["previous_leaders_share_fraction"], .2)
        self.assertAlmostEqual(result["leaders_increment_share_fraction"], 1)

    def test_incompatible_profit_units_rejected(self):
        with self.assertRaises(ValueError):
            profit_concentration(200, 80, 1, 0, unit="KRW")


if __name__ == "__main__":
    unittest.main()
