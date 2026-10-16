"""Meaningful unit/availability/corporate-action checks; no durable writes."""
import math
import unittest
from calculations import (check_available, fx_return, scenario_return,
                          split_economic_return, validate_weights, weighted_return)

class ResearchArithmeticTests(unittest.TestCase):
    def test_multiplicative_earnings_and_multiple_changes(self):
        self.assertAlmostEqual(scenario_return(.1, -.1, 0, 0), -.01)

    def test_dividend_and_expense_are_distinct_cash_terms(self):
        self.assertAlmostEqual(scenario_return(0, 0, .003, .001), .002)

    def test_loss_is_not_clipped_to_probability_bounds(self):
        self.assertAlmostEqual(scenario_return(-.2, -.1, 0, 0), -.28)

    def test_percent_unit_is_rejected_even_when_magnitude_looks_fractional(self):
        with self.assertRaises(ValueError):
            validate_weights({"bull":.3,"base":.45,"bear":.25}, "percent")

    def test_weights_are_not_silently_normalized(self):
        with self.assertRaises(ValueError):
            validate_weights({"bull":.2,"base":.2,"bear":.2}, "fraction")

    def test_weight_bounds_are_not_silently_clipped(self):
        with self.assertRaises(ValueError):
            validate_weights({"bull":1.1,"base":.1,"bear":-.2}, "fraction")

    def test_missing_case_is_rejected(self):
        with self.assertRaises(ValueError):
            weighted_return({"bull":.1,"base":.03}, {"bull":.3,"base":.45,"bear":.25})

    def test_nonfinite_assumption_is_rejected(self):
        with self.assertRaises(ValueError):
            scenario_return(math.nan, 0, 0, 0)

    def test_economic_value_cannot_be_negative(self):
        with self.assertRaises(ValueError):
            scenario_return(-.99, -.99, 0, .01)

    def test_new_cpi_result_after_cutoff_is_rejected(self):
        with self.assertRaises(ValueError):
            check_available("2026-10-14T08:30:00-04:00", "2026-10-12T09:16:14+09:00")

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            check_available("2026-10-09T16:00:00", "2026-10-12T09:16:14+09:00")

    def test_prior_us_close_uses_timezone_in_cutoff(self):
        self.assertEqual(check_available("2026-10-09T16:00:00-04:00", "2026-10-12T09:16:14+09:00"),
                         "dated_release_precedes_cutoff")

    def test_unknown_publication_time_remains_unverified(self):
        self.assertIn("unverified", check_available(None, "2026-10-12T09:16:14+09:00"))

    def test_three_for_one_split_is_not_a_two_thirds_loss(self):
        self.assertAlmostEqual(split_economic_return(600, 200, 3), 0)
        self.assertAlmostEqual(split_economic_return(600, 220, 3, 6), .11)

    def test_fx_conversion_includes_cross_term(self):
        self.assertAlmostEqual(fx_return(.1, .05), .155)
        self.assertAlmostEqual(fx_return(.1, -.05), .045)

if __name__ == "__main__":
    unittest.main()
