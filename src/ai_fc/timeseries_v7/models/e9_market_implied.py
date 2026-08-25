"""Physical calibration boundary for risk-neutral probabilities."""

from __future__ import annotations
import numpy as np
from sklearn.linear_model import LogisticRegression


class PhysicalCalibrator:
    def __init__(self): self.model=None
    def fit(self,risk_neutral_probability:np.ndarray,outcomes:np.ndarray):
        p=np.asarray(risk_neutral_probability,float)
        if len(p)<126: raise ValueError("minimum 126 captured origins required")
        logits=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1)
        self.model=LogisticRegression().fit(logits,np.asarray(outcomes,int));return self
    def predict(self,p:np.ndarray)->np.ndarray:
        if self.model is None: raise RuntimeError("risk-neutral probabilities are not physically calibrated")
        values=np.clip(np.asarray(p,float),1e-6,1-1e-6);return self.model.predict_proba(np.log(values/(1-values)).reshape(-1,1))[:,1]
