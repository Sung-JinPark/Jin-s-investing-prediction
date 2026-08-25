"""PIT analog retrieval preserving complete 63-session paths."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class AnalogPath:
    origin_index: int
    distance: float
    returns: tuple[float, ...]


def retrieve(states: np.ndarray, paths: np.ndarray, query: np.ndarray, *, neighbor_count: int, minimum_spacing: int = 126) -> list[AnalogPath]:
    x=np.asarray(states,float); full=np.asarray(paths,float)
    if full.ndim != 2 or full.shape[1] != 63 or len(full) != len(x): raise ValueError("full 63-session trajectories required")
    median=np.median(x,axis=0); scale=np.subtract(*np.percentile(x,[75,25],axis=0)); scale[scale==0]=1
    distances=np.sqrt(np.square((x-query)/scale).sum(axis=1)); order=np.argsort(distances)
    selected=[]
    for index in order:
        if all(abs(int(index)-row.origin_index)>=minimum_spacing for row in selected):
            selected.append(AnalogPath(int(index),float(distances[index]),tuple(float(v) for v in full[index])))
        if len(selected)==neighbor_count: break
    return selected
