"""Manual review proposal only—never promotion/publication/trading."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewProposal:
    proposal_id:str;generation_id:str;gate_bundle_hash:str;owner_signature:str;status:str='proposed'


def create_proposal(*,proposal_id:str,generation_id:str,gate_bundle_hash:str,owner_signature:str,gates:dict[str,bool])->ReviewProposal:
    required=('integrity','qualification','operational','prospective')
    if not all(gates.get(name) is True for name in required):raise ValueError('all gates must pass before proposal')
    if not owner_signature:raise ValueError('manual owner signature required')
    return ReviewProposal(proposal_id,generation_id,gate_bundle_hash,owner_signature)
