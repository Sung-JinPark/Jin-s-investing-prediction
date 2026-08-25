"""No-progress, repeated-blocker and governance stop rules."""

from __future__ import annotations
import hashlib,re


def blocker_fingerprint(message:str)->str:
    normalized=message.casefold();normalized=re.sub(r'[0-9a-f]{32,64}','<hash>',normalized);normalized=re.sub(r'\b\d+(?:\.\d+)?\b','<n>',normalized);normalized=re.sub(r'[a-z]:[/\\][^\s]+','<path>',normalized)
    return hashlib.sha256(' '.join(normalized.split()).encode()).hexdigest()


def stop_decision(*,new_evidence:bool,admissible_hypothesis:bool,blocker_repetitions:int,budget_ok:bool,prospective_reused:bool)->str:
    if prospective_reused:return 'BLOCKED_GOVERNANCE'
    if not budget_ok:return 'HOLD_BUDGET'
    if blocker_repetitions>=3:return 'HOLD_REPEATED_BLOCKER'
    if not new_evidence and not admissible_hypothesis:return 'WAIT_DATA'
    return 'CONTINUE'
