"""Targeted, read-only research tests; no durable model/DB writes."""
import copy
import unittest

import numpy as np

import build_analytics as m


class PairResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = m.read(m.ROOT / "analysis_assumptions.json")
        cls.result = m.read(m.ROOT / "analytical_results.json")

    def test_explicit_weight_unit_no_inference(self):
        with self.assertRaises(ValueError):
            m.weights_checked({"bull": .3, "base": .45, "bear": .25}, "percent")

    def test_weights_not_normalized(self):
        with self.assertRaises(ValueError):
            m.weights_checked({"bull": .3, "base": .45, "bear": .3}, "fraction")

    def test_interaction_term_required(self):
        self.assertAlmostEqual(m.total_return(.12, .1, 0, 0), .232)
        self.assertNotAlmostEqual(m.total_return(.12, .1, 0, 0), .22)

    def test_economic_support_rejected_without_clipping(self):
        with self.assertRaises(ValueError):
            m.total_return(-1, 0, 0, 0)
        with self.assertRaises(ValueError):
            m.total_return(float("nan"), 0, 0, 0)

    def test_all_state_software_multiple_shift_exact_tie(self):
        shift = self.result["pair_analysis"]["software_extra_multiple_to_tie"]
        sw = self.a["assets"]["IGV"]
        weighted = sum(self.a["weights"][s] * m.total_return(sw["cases"][s]["g"], sw["cases"][s]["m"] + shift,
                       sw["dividend_remaining"], sw["fee_annual"]) for s in m.STATES)
        self.assertAlmostEqual(weighted, self.result["summary"]["semi_expected_assumption"], places=12)

    def test_growth_shift_exact_tie(self):
        shift = self.result["pair_analysis"]["software_extra_growth_to_tie"]
        sw = self.a["assets"]["IGV"]
        weighted = sum(self.a["weights"][s] * m.total_return(sw["cases"][s]["g"] + shift, sw["cases"][s]["m"],
                       sw["dividend_remaining"], sw["fee_annual"]) for s in m.STATES)
        self.assertAlmostEqual(weighted, self.result["summary"]["semi_expected_assumption"], places=12)

    def test_fixed_centers_do_not_prove_range_dominance(self):
        self.assertTrue(self.result["pair_analysis"]["fixed_center_dominance"])
        self.assertFalse(self.result["pair_analysis"]["range_robust_dominance"])
        self.assertTrue(all(x["spread_possible_low"] < 0 for x in self.result["scenarios"]))

    def test_relative_wealth_is_not_percentage_point_difference(self):
        row = self.result["scenarios"][0]
        self.assertAlmostEqual(row["relative_wealth_return"], (1+row["semi"]["return"])/(1+row["software"]["return"])-1)
        self.assertNotAlmostEqual(row["relative_wealth_return"], row["spread"])

    def test_triangle_inverse_endpoints_and_median(self):
        np.testing.assert_allclose(m.triangular_ppf(np.array([0., .5, 1.]), .1, .03), [.07, .1, .13])
        with self.assertRaises(ValueError):
            m.triangular_ppf([1.01], .1, .03)

    def test_correlation_outside_contract_is_rejected(self):
        with self.assertRaises(ValueError):
            m.paired_uniforms(np.random.default_rng(1), 10, 1.2)

    def test_zero_width_simulation_obeys_center_dominance(self):
        a = copy.deepcopy(self.a)
        for asset in a["assets"].values():
            for c in asset["cases"].values():
                c["g_width"] = c["m_width"] = 0.
        result = m.simulate(a, n=1000)
        self.assertEqual(result["semi_superiority_frequency"], 1)
        self.assertEqual(sum(result["histogram"]["counts"]), 1000)

    def test_frequency_role_never_promoted(self):
        self.assertIsNone(self.result["summary"]["calibrated_winner_probability"])
        self.assertFalse(self.result["official_forecast"])
        self.assertEqual(self.result["monte_carlo"]["frequency_unit"], "fraction")
        self.assertFalse(self.result["validation"]["assumption_frequency_is_forecast_probability"])

    def test_previous_study_midpoints_preserved(self):
        self.assertLessEqual(self.result["validation"]["max_midpoint_difference"], 1e-12)


if __name__ == "__main__":
    unittest.main()
