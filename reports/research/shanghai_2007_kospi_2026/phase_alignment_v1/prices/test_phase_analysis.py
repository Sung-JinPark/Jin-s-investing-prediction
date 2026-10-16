import datetime as dt
import unittest

from phase_analysis import (EXTENDED_FEATURES,FEATURES,FLAGS,directional_events,
                            drawdown_excursions,historical_outcome,is_pareto,matches,phase_features)


def rows(values):
    return [dict(date=dt.date(2007,1,1)+dt.timedelta(days=i),close=float(v)) for i,v in enumerate(values)]


class PhaseMathTests(unittest.TestCase):
    def test_turn_is_not_known_before_confirmation(self):
        path=rows([100,80,87,88])
        self.assertEqual(directional_events(path[:3],.10)["events"],[])
        event=directional_events(path,.10)["events"][0]
        self.assertEqual(event["date"],path[1]["date"])
        self.assertEqual(event["confirmed_at"],path[3]["date"])
        self.assertEqual(directional_events(path,.15)["events"],[])

    def test_rebound_must_reverse_before_becoming_confirmed_peak(self):
        path=rows([100,80,92,110,94])
        self.assertEqual([e["kind"] for e in directional_events(path[:4],.10)["events"]],["trough"])
        self.assertEqual([e["kind"] for e in directional_events(path,.10)["events"]],["trough","peak"])

    def test_rebound_pair_does_not_use_later_trough(self):
        feature=phase_features(rows([100,80,90,96,85,70,80]),.10)
        self.assertEqual(feature["last_confirmed_trough_close"],70)
        self.assertEqual(feature["preceding_rebound_trough_close"],80)
        self.assertAlmostEqual(feature["preceding_rebound_gain_fraction"],.20)

    def test_whole_underwater_spell_keeps_later_lower_low(self):
        spells=drawdown_excursions(rows([100,80,95,75,100,110]))
        self.assertEqual(len(spells),1)
        self.assertEqual(spells[0]["trough_close"],75)
        self.assertEqual(spells[0]["peak_to_recovery_sessions"],4)
        self.assertTrue(spells[0]["threshold_20pct_eligible"])

    def test_unrecovered_spell_is_not_completed(self):
        self.assertEqual(drawdown_excursions(rows([100,80,90])),[])

    def test_rebound_shape_does_not_reset_at_new_low(self):
        feature=phase_features(rows([100,60,70,80,70,59]),.10)
        self.assertEqual(feature["bounce_from_running_trough_fraction"],0)
        self.assertEqual(feature["loss_recovered_from_running_trough_fraction"],0)
        self.assertAlmostEqual(feature["preceding_rebound_gain_fraction"],1/3)
        self.assertAlmostEqual(feature["preceding_rebound_prior_loss_recovered_fraction"],.5)
        self.assertTrue(feature["below_last_confirmed_trough"])
        self.assertTrue(feature["new_postpeak_low"])

    def test_future_horizon_counts_future_closes_not_origin(self):
        path=rows([100,150,100,80])
        outcome=historical_outcome(path,path[0]["date"],2)
        self.assertEqual(outcome["last_date"],path[2]["date"])
        self.assertEqual(outcome["end_return_fraction"],0)
        self.assertAlmostEqual(outcome["max_drawdown_fraction"],-1/3)
        self.assertFalse(outcome["additional_20pct_loss_event"])

    def test_bullish_future_has_zero_origin_inclusive_worst_return(self):
        path=rows([100,110,120])
        outcome=historical_outcome(path,path[0]["date"],2)
        self.assertEqual(outcome["worst_origin_return_fraction"],0)
        self.assertAlmostEqual(outcome["minimum_future_observed_return_fraction"],.1)

    def test_incomplete_future_is_explicitly_censored(self):
        path=rows([100,80])
        outcome=historical_outcome(path,path[0]["date"],2)
        self.assertEqual(outcome["status"],"right_censored")
        self.assertIsNone(outcome["end_return_fraction"])

    def test_extended_shape_can_reject_matching_zero_reset_features(self):
        original={name:0 for name in FEATURES+FLAGS}
        extended={name:0 for name in EXTENDED_FEATURES+FLAGS}
        extended["preceding_rebound_gain_fraction"]=.3
        self.assertTrue(matches(original,"loose"))
        self.assertFalse(matches(extended,"loose",EXTENDED_FEATURES))

    def test_pareto_keeps_tradeoff_without_scalar_score(self):
        first={name:0 for name in FEATURES+FLAGS};first["sessions_since_peak"]=10
        second={name:0 for name in FEATURES+FLAGS};second["peak_drawdown_fraction"]=.1
        worse={name:0 for name in FEATURES+FLAGS};worse["sessions_since_peak"]=20;worse["peak_drawdown_fraction"]=.2
        sample=[first,second,worse]
        self.assertTrue(is_pareto(first,sample));self.assertTrue(is_pareto(second,sample))
        self.assertFalse(is_pareto(worse,sample))


if __name__=="__main__":unittest.main()
