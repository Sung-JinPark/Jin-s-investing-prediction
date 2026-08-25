"""Fresh source remediation and explicit degraded-model eligibility."""

from __future__ import annotations


def operational_decision(source_states:dict[str,str],*,degraded_model_preregistered:bool)->dict[str,object]:
    stale=sorted(name for name,state in source_states.items() if state!='fresh')
    if not stale:return {'state':'PASS','eligible':True,'stale_sources':[],'mode':'core'}
    if degraded_model_preregistered:return {'state':'PASS_DEGRADED','eligible':True,'stale_sources':stale,'mode':'preregistered_degraded'}
    return {'state':'WAIT_DATA','eligible':False,'stale_sources':stale,'mode':None}
