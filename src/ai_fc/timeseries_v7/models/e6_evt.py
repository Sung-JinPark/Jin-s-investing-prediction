"""Asymmetric empirical EVT tail calibrator."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from scipy.stats import genpareto


@dataclass(frozen=True)
class TailFit:
    side: str
    threshold: float
    exceedance_count: int
    shape: float | None
    scale: float | None
    eligible: bool


def fit_tails(residuals: np.ndarray, *, threshold_quantile: float, minimum_exceedances: int) -> dict[str, TailFit]:
    values=np.asarray(residuals,float); upper=float(np.quantile(values,threshold_quantile)); lower=float(np.quantile(values,1-threshold_quantile))
    results={}
    for side, threshold, excess in (
        ("upper",upper,values[values>upper]-upper),
        ("lower",lower,lower-values[values<lower]),
    ):
        eligible=len(excess)>=minimum_exceedances
        if eligible:
            shape,_,scale=genpareto.fit(excess,floc=0); results[side]=TailFit(side,threshold,len(excess),float(shape),float(scale),True)
        else: results[side]=TailFit(side,threshold,len(excess),None,None,False)
    return results
