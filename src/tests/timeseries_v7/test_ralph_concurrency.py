from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Effect:
    token:int=0
    owner:str|None=None
    committed_hash:str|None=None
    logical_effects:int=0
    def lease(self,owner):self.token+=1;self.owner=owner;return self.token
    def complete(self,owner,token,result_hash):
        if owner!=self.owner or token!=self.token:return False
        if self.committed_hash is None:self.committed_hash=result_hash;self.logical_effects+=1
        elif self.committed_hash!=result_hash:raise ValueError('conflicting duplicate completion')
        return True


def test_worker_crash_expired_lease_and_stale_fencing_token():
    effect=Effect();stale=effect.lease('worker-a');current=effect.lease('worker-b')
    assert not effect.complete('worker-a',stale,'a'*64)
    assert effect.complete('worker-b',current,'b'*64) and effect.logical_effects==1


def test_network_partition_duplicate_completion_is_exactly_once():
    effect=Effect();token=effect.lease('worker');assert effect.complete('worker',token,'a'*64)
    assert effect.complete('worker',token,'a'*64) and effect.logical_effects==1


def test_database_restart_preserves_fencing_and_effect_identity():
    before=Effect();token=before.lease('worker');before.complete('worker',token,'a'*64)
    after=Effect(before.token,before.owner,before.committed_hash,before.logical_effects)
    assert after.complete('worker',token,'a'*64) and after.logical_effects==1
