"""Ex-ante soft regimes with partial pooling."""

from __future__ import annotations

import numpy as np


def softmax(scores: np.ndarray) -> np.ndarray:
    shifted = scores - scores.max(axis=1, keepdims=True); exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def pooled_component_means(target: np.ndarray, probabilities: np.ndarray, *, minimum_ess: float) -> tuple[np.ndarray, np.ndarray]:
    y=np.asarray(target,float); p=np.asarray(probabilities,float); global_mean=float(y.mean())
    ess=np.square(p.sum(axis=0))/np.maximum(np.square(p).sum(axis=0),1e-12)
    local=(p.T@y)/np.maximum(p.sum(axis=0),1e-12)
    strength=np.minimum(1,ess/minimum_ess)
    return strength*local+(1-strength)*global_mean,ess
