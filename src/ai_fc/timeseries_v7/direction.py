"""Dedicated calibrated probability-of-positive-return head."""

from __future__ import annotations
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, matthews_corrcoef


class DirectionHead:
    def __init__(self): self.model=LogisticRegression(max_iter=2000,class_weight='balanced')
    def fit(self,values:np.ndarray,returns:np.ndarray):self.model.fit(values,(returns>0).astype(int));return self
    def predict_probability(self,values:np.ndarray)->np.ndarray:return self.model.predict_proba(values)[:,1]


def metrics(probability:np.ndarray,outcome:np.ndarray)->dict[str,float]:
    p=np.asarray(probability,float);y=np.asarray(outcome,int);prediction=(p>=.5).astype(int)
    return {'balanced_accuracy':float(balanced_accuracy_score(y,prediction)),'mcc':float(matthews_corrcoef(y,prediction)),'brier':float(np.mean((p-y)**2))}
