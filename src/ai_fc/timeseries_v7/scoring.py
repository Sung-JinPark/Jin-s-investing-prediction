"""Replayable distribution, direction, touch and drawdown metrics."""

from __future__ import annotations
import numpy as np


def crps_samples(samples:np.ndarray,actual:float)->float:
    values=np.sort(np.asarray(samples,float));n=len(values)
    first=np.mean(np.abs(values-actual));coeff=(2*np.arange(1,n+1)-n-1)
    second=float(np.sum(coeff*values)/(n*n))
    return float(first-second)


def pinball(prediction:float,actual:float,quantile:float)->float:
    residual=actual-prediction;return float(max(quantile*residual,(quantile-1)*residual))


def brier(probability:float,outcome:bool)->float:
    if not 0<=probability<=1:raise ValueError('probability must be fraction')
    return float((probability-int(outcome))**2)


def score_path(path_returns:np.ndarray)->dict[str,float]:
    levels=np.exp(np.cumsum(path_returns));running=np.maximum.accumulate(np.r_[1.,levels])[1:];dd=levels/running-1
    return {'max_drawdown':float(dd.min()),'touch_minus_05':float(np.any(dd<=-.05)),'touch_minus_10':float(np.any(dd<=-.1)),'touch_minus_15':float(np.any(dd<=-.15))}
