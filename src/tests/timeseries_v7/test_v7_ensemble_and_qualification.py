from __future__ import annotations

from datetime import datetime,timedelta,timezone
import numpy as np
import pytest

from ai_fc.timeseries_v7.calibration import apply,fit_quantile_adjustments
from ai_fc.timeseries_v7.direction import DirectionHead,metrics as direction_metrics
from ai_fc.timeseries_v7.freshness import operational_decision
from ai_fc.timeseries_v7.historical_stress import qualify as stress_qualify
from ai_fc.timeseries_v7.paths import path_metrics,sample_paths
from ai_fc.timeseries_v7.prospective import AppendOnlyForecastLedger,ProspectiveForecast
from ai_fc.timeseries_v7.prospective_score import assert_not_training_input,matured_only
from ai_fc.timeseries_v7.qualification import evaluate as qualify
from ai_fc.timeseries_v7.scoring import brier,crps_samples,pinball,score_path
from ai_fc.timeseries_v7.stacking import fit_weights


RNG=np.random.default_rng(11);UTC=timezone.utc


def test_direction_head_improves_over_always_up_fixture() -> None:
    x=RNG.normal(size=(300,2));returns=x[:,0]+RNG.normal(scale=.2,size=300);split=200
    head=DirectionHead().fit(x[:split],returns[:split]);p=head.predict_probability(x[split:]);result=direction_metrics(p,(returns[split:]>0).astype(int))
    assert result['balanced_accuracy']>.8 and result['brier']<.25


def test_stacking_nonnegative_sum_one_and_anchor_floor() -> None:
    losses=np.c_[np.full(100,.9),np.full(100,.5),np.full(100,.7)]
    receipt=fit_weights(losses,horizon_sessions=63,stacking_fold_hash='a'*64,anchor_floor=.5)
    assert np.all(receipt.weights>=0) and np.isclose(receipt.weights.sum(),1) and receipt.weights[0]>=.5


def test_calibration_uses_separate_fold_and_monotone_rearrangement() -> None:
    q=(.1,.5,.9);pred=np.tile(np.array([-.1,0,.1]),(100,1));actual=RNG.normal(.05,.1,100)
    receipt=fit_quantile_adjustments(pred,actual,q,calibration_fold_hash='b'*64)
    output=apply(receipt,pred[:2]);assert np.all(np.diff(output,axis=1)>=0) and not receipt.outer_scores_consumed


def test_joint_path_sampler_matches_every_endpoint_and_is_reproducible() -> None:
    analog=RNG.normal(0,.01,size=(200,63));endpoints={h:RNG.normal(0,.02*np.sqrt(h),size=500) for h in (1,5,21,63)}
    first=sample_paths(analog,endpoints,sample_count=1000,seed=7);second=sample_paths(analog,endpoints,sample_count=1000,seed=7)
    assert np.array_equal(first.log_return_paths,second.log_return_paths)
    cumulative=np.cumsum(first.log_return_paths,axis=1)
    for h in endpoints:assert np.allclose(cumulative[:,h-1],first.endpoint_targets[h])
    report=path_metrics(first);assert 0<=report['first_touch_minus_10']<=1


def test_scoring_metrics_have_known_values() -> None:
    assert crps_samples(np.array([-1.,0.,1.]),0)==pytest.approx(2/9)
    assert pinball(0,1,.5)==.5 and brier(.75,True)==.0625
    assert score_path(np.array([-.2,.1]))['touch_minus_10']==1


def test_historical_suites_and_research_qualification_are_separate_from_prospective() -> None:
    names={'gfc','pandemic','tightening_2022','rebound_2009','rebound_2020','bull_2023','absolute_return_q4','high_volatility_q4'}
    stress=stress_qualify({name:[True]*20 for name in names});assert stress['pass']
    good={'long_horizon_mean_crps_skill':.03,'h21_skill':.01,'h63_skill':.02,'paired_ci_upper':-.001,'coverage80':.8,'coverage50':.5,'balanced_direction_accuracy':.55,'brier':.2,'base_rate_brier':.25,'extreme_q4_coverage':.65,'catastrophic_underperformance':.05}
    assert qualify(good,True)['pass']
    with pytest.raises(ValueError,match='prospective'):qualify(good,True,prospective_scores=[1])


def test_prospective_forecast_is_post_freeze_and_append_only() -> None:
    frozen=datetime(2026,1,1,tzinfo=UTC);issued=frozen+timedelta(days=1)
    row=ProspectiveForecast('p',issued,issued-timedelta(hours=1),'a'*64,'b'*64,'c'*64,frozen)
    ledger=AppendOnlyForecastLedger();ledger.append(row)
    with pytest.raises(ValueError,match='already'):ledger.append(row)


def test_prospective_scoring_requires_maturity_and_never_enters_fit() -> None:
    now=datetime(2026,8,25,tzinfo=UTC);rows=[{'mature_at':now-timedelta(seconds=1),'actual':1},{'mature_at':now+timedelta(days=1),'actual':2}]
    assert len(matured_only(rows,now))==1
    with pytest.raises(ValueError):assert_not_training_input('stacking')


def test_stale_sources_require_preregistered_degraded_model_or_wait_data() -> None:
    assert operational_decision({'OFR':'stale'},degraded_model_preregistered=False)['state']=='WAIT_DATA'
    assert operational_decision({'OFR':'stale'},degraded_model_preregistered=True)['state']=='PASS_DEGRADED'
