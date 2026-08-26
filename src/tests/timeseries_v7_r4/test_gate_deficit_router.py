from pathlib import Path

from ai_fc.timeseries_v7_r4.core_qualification import GATE_NAMES
from ai_fc.timeseries_v7_r4.router import GateDeficitRouter, HypothesisRegistry


ROOT = Path(__file__).resolve().parents[3]
ROUTER = ROOT / "data/timeseries_v7_r4/ralph/spec/NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml"


def test_every_frozen_gate_has_an_admissible_task_family():
    router = GateDeficitRouter.from_yaml(ROUTER)
    mapping = router.validate_gate_coverage(GATE_NAMES)
    assert set(mapping) == set(GATE_NAMES)
    assert all(mapping[gate] for gate in GATE_NAMES)


class _Result:
    def __init__(self, inserted):
        self._inserted = inserted

    def fetchone(self):
        return (1,) if self._inserted else None


class _Connection:
    def __init__(self):
        self.keys = set()

    def execute(self, sql, parameters):
        assert "ON CONFLICT DO NOTHING" in sql
        key = parameters[0]
        inserted = key not in self.keys
        self.keys.add(key)
        return _Result(inserted)


def test_hypothesis_registry_blocks_duplicate_frozen_combination():
    registry = HypothesisRegistry(_Connection())
    coordinates = dict(hypothesis_hash="h" * 64, dataset_snapshot_hash="d" * 64,
                       code_hash="c" * 64, runtime_hash="r" * 64)
    assert registry.register(deficit_family="R-LONG-NEGATIVE", action="E0_ONLY_FALLBACK",
                             **coordinates)
    assert not registry.register(deficit_family="R-LONG-NEGATIVE", action="NO_REGRET_STACKING",
                                 **coordinates)


def test_same_blocker_routes_to_alternate_family_at_contract_limit():
    router = GateDeficitRouter.from_yaml(ROUTER)
    history = [
        {"blocker_signature": "NO_IMPROVEMENT", "action": "COMPONENT_ABLATION"},
        {"blocker_signature": "NO_IMPROVEMENT", "action": "COMPONENT_ABLATION"},
        {"blocker_signature": "NO_IMPROVEMENT", "action": "COMPONENT_ABLATION"},
    ]
    routed = router.route(["h21_skill_negative"], dataset_snapshot_hash="d" * 64,
                          code_hash="c" * 64, runtime_hash="r" * 64,
                          blocker_signature="NO_IMPROVEMENT", blocker_history=history)
    assert routed
    assert all(task.action != "COMPONENT_ABLATION" for task in routed)
