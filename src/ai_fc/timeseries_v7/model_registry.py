"""Immutable generation lineage; historical winner is never auto-promoted."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationRecord:
    generation_id:str;parent_generation_id:str|None;contract_hash:str;code_hash:str;runtime_hash:str;snapshot_hash:str;gate_decision_hash:str


class Registry:
    def __init__(self):self._records={}
    def register(self,row:GenerationRecord):
        if row.generation_id in self._records:raise ValueError('generation is immutable')
        self._records[row.generation_id]=row
    def historical_winner(self,generation_id:str)->dict[str,object]:
        if generation_id not in self._records:raise KeyError(generation_id)
        return {'generation_id':generation_id,'status':'historical_challenger','automatic_promotion':False}
