"""Horizon-specific non-negative stacking on an isolated stacking fold."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class StackReceipt:
    weights:np.ndarray
    horizon_sessions:int
    stacking_fold_hash:str
    anchor_floor:float


def fit_weights(losses:np.ndarray,*,horizon_sessions:int,stacking_fold_hash:str,anchor_floor:float,previous:np.ndarray|None=None,turnover_penalty:float=.001,complexity_penalty:float=.0001)->StackReceipt:
    matrix=np.asarray(losses,float);components=matrix.shape[1];initial=np.full(components,1/components);initial[0]=max(initial[0],anchor_floor);initial[1:]*=(1-initial[0])/max(initial[1:].sum(),1e-12)
    def objective(w):
        value=float(np.mean(matrix@w))+complexity_penalty*float(np.square(w).sum())
        if previous is not None:value+=turnover_penalty*float(np.abs(w-previous).sum())
        return value
    result=minimize(objective,initial,method='SLSQP',bounds=[(anchor_floor,1)]+[(0,1)]*(components-1),constraints={'type':'eq','fun':lambda w:w.sum()-1})
    if not result.success:raise RuntimeError(result.message)
    return StackReceipt(result.x,horizon_sessions,stacking_fold_hash,anchor_floor)
