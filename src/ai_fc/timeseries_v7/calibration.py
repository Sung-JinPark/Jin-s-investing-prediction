"""Cross-fit quantile calibration on a dedicated matured calibration fold."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class CalibrationReceipt:
    quantiles:tuple[float,...]
    adjustments:np.ndarray
    calibration_fold_hash:str
    outer_scores_consumed:bool=False


def fit_quantile_adjustments(predicted:np.ndarray,actual:np.ndarray,quantiles:tuple[float,...],*,calibration_fold_hash:str,shrinkage:float=.5)->CalibrationReceipt:
    matrix=np.asarray(predicted,float);y=np.asarray(actual,float)
    if matrix.shape!=(len(y),len(quantiles)):raise ValueError('calibration shape mismatch')
    residual=y[:,None]-matrix
    adjustments=np.array([np.quantile(residual[:,i],q) for i,q in enumerate(quantiles)])*shrinkage
    return CalibrationReceipt(quantiles,adjustments,calibration_fold_hash,False)


def apply(receipt:CalibrationReceipt,predicted:np.ndarray)->np.ndarray:
    return np.sort(np.asarray(predicted,float)+receipt.adjustments,axis=-1)
