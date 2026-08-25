"""Joint endpoint and full-path sampler with stochastic analog reconciliation."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np


HORIZONS=(1,5,21,63)


@dataclass(frozen=True)
class PathBundle:
    log_return_paths:np.ndarray
    endpoint_targets:dict[int,np.ndarray]
    seed:int


def sample_paths(analog_paths:np.ndarray,endpoint_samples:dict[int,np.ndarray],*,sample_count:int=20_000,seed:int=0)->PathBundle:
    source=np.asarray(analog_paths,float)
    if source.ndim!=2 or source.shape[1]!=63:raise ValueError('63-session analog paths required')
    if set(endpoint_samples)!=set(HORIZONS):raise ValueError('all direct endpoints required')
    rng=np.random.default_rng(seed);indices=rng.integers(0,len(source),size=sample_count);paths=source[indices].copy()
    targets={h:rng.choice(np.asarray(endpoint_samples[h],float),size=sample_count,replace=True) for h in HORIZONS}
    cumulative=np.cumsum(paths,axis=1);start=0;previous=np.zeros(sample_count)
    for horizon in HORIZONS:
        current=cumulative[:,horizon-1];delta=targets[horizon]-current
        width=horizon-start;paths[:,start:horizon]+=delta[:,None]/width
        cumulative=np.cumsum(paths,axis=1);previous=targets[horizon];start=horizon
    return PathBundle(paths,targets,seed)


def path_metrics(bundle:PathBundle)->dict[str,object]:
    cumulative=np.cumsum(bundle.log_return_paths,axis=1);levels=np.exp(cumulative);running=np.maximum.accumulate(np.c_[np.ones(len(levels)),levels],axis=1)[:,1:]
    drawdowns=levels/running-1;maximum=drawdowns.min(axis=1)
    return {'max_drawdown_mean':float(maximum.mean()),'first_touch_minus_05':float(np.mean(np.any(drawdowns<=-.05,axis=1))),'first_touch_minus_10':float(np.mean(np.any(drawdowns<=-.10,axis=1))),'first_touch_minus_15':float(np.mean(np.any(drawdowns<=-.15,axis=1))),'duplicate_trajectory_fraction':float(1-len(np.unique(bundle.log_return_paths,axis=0))/len(bundle.log_return_paths))}
