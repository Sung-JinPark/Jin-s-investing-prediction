from __future__ import annotations

import numpy as np
import pytest
import yaml
from pathlib import Path
from scipy.optimize import approx_fprime

from ai_fc.timeseries_v7.models.e1_quantile_linear import fit as fit_e1, rearrange
from ai_fc.timeseries_v7.models.e2_student_t import fit as fit_e2, nll_and_gradient
from ai_fc.timeseries_v7.models.e3_boosting import compile_grid, verify_estimator_params
from ai_fc.timeseries_v7.models.e4_dlm import filter_states
from ai_fc.timeseries_v7.models.e5_regime import pooled_component_means, softmax
from ai_fc.timeseries_v7.models.e6_evt import fit_tails
from ai_fc.timeseries_v7.models.e7_analog_paths import retrieve
from ai_fc.timeseries_v7.models.e8_events import eligibility
from ai_fc.timeseries_v7.models.e9_market_implied import PhysicalCalibrator
from ai_fc.timeseries_v7.models.e10_foundation import FoundationReceipt


REPO=Path(__file__).resolve().parents[3]
CONTRACT=yaml.safe_load((REPO/'data/contracts/multivariate_timeseries_v7.yaml').read_text(encoding='utf-8'))
RNG=np.random.default_rng(7)


def test_e1_direct_quantile_uses_training_scaler_and_rearranges() -> None:
    x=RNG.normal(size=(120,2)); y=1+2*x[:,0]+RNG.normal(scale=.2,size=120)
    model=fit_e1(x,y,quantile=.5,alpha=.001,l1_ratio=.5,max_iter=2000)
    assert np.corrcoef(model.predict(x),y)[0,1]>.95
    values=np.array([[3,1,2],[0,-1,4]])
    assert np.all(np.diff(rearrange(values),axis=1)>=0)


def test_e2_student_t_analytic_gradient_matches_finite_difference() -> None:
    x=RNG.normal(size=(30,2)); y=RNG.standard_t(5,size=30); params=np.zeros(6)
    value,gradient=nll_and_gradient(params,x,y,5)
    numeric=approx_fprime(params,lambda p:nll_and_gradient(p,x,y,5)[0],1e-6)
    assert np.max(np.abs(gradient-numeric))<1e-4
    model=fit_e2(x,y,degrees_of_freedom=5,ridge_alpha=.01)
    location,scale,df=model.parameters(x[:3]);assert len(location)==3 and np.all(scale>0) and df==5


def test_e3_grid_is_compiled_from_contract_and_offgrid_fails() -> None:
    spec=CONTRACT['candidates']['E3'];grid=compile_grid(spec)
    assert len(grid)==32
    verify_estimator_params(spec,grid[0])
    with pytest.raises(ValueError,match='off-grid'):verify_estimator_params(spec,{**grid[0],'learning_rate':.05})


def test_e4_filtered_dlm_recovers_time_varying_coefficient() -> None:
    x=np.ones((200,1)); beta=np.linspace(-1,1,200);y=beta+RNG.normal(scale=.05,size=200)
    model=filter_states(x,y,process_variance=.002,observation_variance=.0025)
    assert np.corrcoef(model.states[:,0],beta)[0,1]>.95


def test_e5_soft_regime_probabilities_and_partial_pooling() -> None:
    probabilities=softmax(np.array([[2,0],[0,2],[1,1]],float))
    assert np.allclose(probabilities.sum(axis=1),1)
    means,ess=pooled_component_means(np.array([1,-1,0]),probabilities,minimum_ess=40)
    assert np.all(np.isfinite(means)) and np.all(ess>0)


def test_e6_fits_positive_and_negative_tails_separately() -> None:
    residuals=RNG.standard_t(3,size=2000)
    fits=fit_tails(residuals,threshold_quantile=.9,minimum_exceedances=40)
    assert fits['upper'].eligible and fits['lower'].eligible
    assert fits['upper'].threshold>fits['lower'].threshold


def test_e7_returns_complete_paths_and_proves_spacing() -> None:
    states=np.arange(500,dtype=float)[:,None];paths=RNG.normal(size=(500,63))
    values=retrieve(states,paths,np.array([250.]),neighbor_count=3,minimum_spacing=126)
    assert all(len(row.returns)==63 for row in values)
    assert all(abs(left.origin_index-right.origin_index)>=126 for i,left in enumerate(values) for right in values[i+1:])
    with pytest.raises(ValueError,match='full'):retrieve(states,paths[:,:1],np.array([0.]),neighbor_count=1)


def test_e8_event_weight_is_zero_before_sixty_independent_events() -> None:
    assert eligibility(59)['ensemble_weight']==0 and eligibility(60)['eligible']


def test_e9_refuses_uncalibrated_risk_neutral_probability() -> None:
    calibrator=PhysicalCalibrator()
    with pytest.raises(RuntimeError):calibrator.predict(np.array([.5]))
    with pytest.raises(ValueError):calibrator.fit(np.full(125,.5),np.arange(125)%2)
    p=np.linspace(.1,.9,126);y=(p+RNG.normal(scale=.2,size=126)>.5).astype(int)
    assert np.all((calibrator.fit(p,y).predict(p[:3])>=0)&(calibrator.predict(p[:3])<=1))


def test_e10_default_weight_remains_zero_without_both_receipts_gates() -> None:
    receipt=FoundationReceipt('a'*64,'b'*64,'c'*64,nested_oos_pass=True,calibration_pass=False)
    assert receipt.weight==0
