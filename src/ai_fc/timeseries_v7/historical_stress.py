"""Fixed open historical stress suite aggregation."""

from __future__ import annotations
from .gates import HISTORICAL_SUITES,RegimeScore,evaluate_historical_stress


def qualify(rows:dict[str,list[bool]],*,minimum_count:int=20)->dict[str,object]:
    scores={name:RegimeScore(len(values),sum(values)/len(values) if values else 0) for name,values in rows.items()}
    return evaluate_historical_stress(scores,minimum_count=minimum_count)
