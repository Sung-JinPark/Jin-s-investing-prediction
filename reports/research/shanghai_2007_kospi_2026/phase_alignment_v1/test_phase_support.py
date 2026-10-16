import math
import unittest
from phase_support import consecutive


class PriceGateTests(unittest.TestCase):
    def test_single_close_is_not_five_day_confirmation(self):
        self.assertEqual(consecutive([101,100,99],100,"below"),1)

    def test_only_trailing_run_counts(self):
        self.assertEqual(consecutive([99,98,101,99],100,"below"),1)

    def test_equal_price_does_not_count_as_reclaim_or_break(self):
        self.assertEqual(consecutive([101,100],100,"above"),0)
        self.assertEqual(consecutive([99,100],100,"below"),0)

    def test_five_actual_observations_count(self):
        self.assertEqual(consecutive([99,101,102,101,103,105],100,"above"),5)

    def test_invalid_prices_are_rejected(self):
        for values in ([],[0],[-1],[math.nan]):
            with self.subTest(values=values),self.assertRaises(ValueError):consecutive(values,100,"above")


if __name__=="__main__":unittest.main()
