import csv
import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("price_analytics", Path(__file__).parent / "prices" / "analytics.py")
PA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PA)


def rows(prices, start=dt.date(2025, 1, 1)):
    return [{"date": start+dt.timedelta(days=i), "close": value, "symbol": "KOSPI", "currency": "KRW", "source_id": "fixture", "price_type": "unadjusted_index_close"}
            for i, value in enumerate(prices)]


class PriceAnalyticsTests(unittest.TestCase):
    def load_fixture(self, observations):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"prices.csv"
            with path.open("w",newline="",encoding="utf-8") as handle:
                writer=csv.DictWriter(handle,fieldnames=["date","close","symbol","currency","source_id","price_type"])
                writer.writeheader()
                writer.writerows(observations)
            return PA.load_prices(path)

    def test_duplicates_rejected(self):
        observations=rows([100]); observations.append(observations[0].copy())
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            self.load_fixture(observations)

    def test_invalid_prices_rejected(self):
        for value in (0,-1,float("nan"),float("inf")):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.load_fixture(rows([value]))

    def test_after_cutoff_rejected(self):
        with self.assertRaisesRegex(ValueError,"After-cutoff"):
            self.load_fixture(rows([100],dt.date(2026,10,16)))

    def test_missing_provenance_rejected(self):
        observations=rows([100]);observations[0]["source_id"]=""
        with self.assertRaisesRegex(ValueError,"provenance"):
            self.load_fixture(observations)

    def test_missing_currency_rejected(self):
        observations=rows([100]);observations[0]["currency"]=""
        with self.assertRaises(ValueError):
            self.load_fixture(observations)

    def test_constant_and_small_samples_not_false_correlations(self):
        self.assertIsNone(PA.pearson([1,1,1],[1,2,3]))
        self.assertIsNone(PA.pearson([1,2],[1,2]))

    def test_rank_ties_are_averaged(self):
        self.assertEqual(PA.ranks([30,10,10,20]),[4,1.5,1.5,3])

    def test_known_opposite_correlation(self):
        self.assertAlmostEqual(PA.pearson([1,2,3,4],[4,3,2,1]),-1)

    def test_missing_month_not_filled(self):
        observations=[{"date":dt.date(2025,1,31),"close":100},
                      {"date":dt.date(2025,3,31),"close":120}]
        self.assertEqual(PA.period_returns(observations,"monthly"),{})

    def test_missing_week_not_filled(self):
        observations=[{"date":dt.date(2025,1,3),"close":100},
                      {"date":dt.date(2025,1,17),"close":120}]
        self.assertEqual(PA.period_returns(observations,"weekly"),{})

    def test_n_returns_require_n_plus_one_closes(self):
        self.assertEqual(PA.age_comparison(rows([100]*252),rows([100]*253),252)["status"],"unavailable")

    def test_summary_has_true_path_drawdown(self):
        result=PA.summarize(rows([100,150,100]))
        self.assertEqual(result["return_fraction"],0)
        self.assertAlmostEqual(result["max_drawdown_fraction"],-1/3)

    def test_fx_quotation_direction(self):
        result=PA.usd_global_comparison(rows([100,110]),rows([200,100]),rows([100,120]),benchmark_verified=True)
        self.assertAlmostEqual(result["usd_return_fraction"],1.2)
        self.assertAlmostEqual(result["world_price_return_fraction"],.2)

    def test_fx_no_same_date_is_unavailable(self):
        result=PA.usd_global_comparison(rows([100,110]),rows([200,100],dt.date(2025,2,1)),rows([100,120]))
        self.assertEqual(result["status"],"unavailable")

    def test_unverified_global_benchmark_is_suppressed(self):
        result=PA.usd_global_comparison(rows([100,110]),rows([200,100]),rows([100,120]))
        self.assertAlmostEqual(result["usd_return_fraction"],1.2)
        self.assertIsNone(result["world_price_return_fraction"])
        self.assertIsNone(result["usd_minus_world_log_return"])

    def test_wrong_currency_and_adjustment_rejected(self):
        for field,value in [("currency","USD"),("price_type","adjusted_total_return")]:
            observations=rows([100]);observations[0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.load_fixture(observations)

    def test_fixed_calendar_shift(self):
        self.assertEqual(PA.calendar_shift(dt.date(2007,10,15)),dt.date(2026,10,15))


if __name__ == "__main__":
    unittest.main()
