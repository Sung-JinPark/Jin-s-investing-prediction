"""Evidence-triggered, finite V7 experiment planning."""

from __future__ import annotations
from dataclasses import dataclass
from .scheduler import GenerationEvidence,decide_generation,generation_input_hash


@dataclass(frozen=True)
class ExperimentPlan:
    generation_state:str
    input_hash:str
    candidate_ids:tuple[str,...]
    reason:str


def plan(snapshot:dict,evidence:GenerationEvidence,*,now,last_generation_at,prior_hashes:set[str],candidate_ids:tuple[str,...])->ExperimentPlan:
    digest=generation_input_hash(snapshot);decision=decide_generation(evidence,now=now,last_generation_at=last_generation_at,input_hash=digest,prior_input_hashes=prior_hashes)
    return ExperimentPlan(decision.state,digest,candidate_ids if decision.create_generation else (),decision.reason)
