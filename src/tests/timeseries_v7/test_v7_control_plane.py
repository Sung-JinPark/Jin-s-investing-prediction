from __future__ import annotations


import pytest

from ai_fc.timeseries_v7.dag import downstream_terminal_state
from ai_fc.timeseries_v7.ralph_store import HEARTBEAT_SECONDS, LEASE_SECONDS, LEASE_SQL
from ai_fc.timeseries_v7.task_identity import TaskIdentity, TaskIdentityError


HASH_A = "a" * 64
HASH_B = "b" * 64


def test_same_task_key_in_distinct_cycles_has_distinct_identity() -> None:
    first = TaskIdentity("run", "cycle-a", "gen", "collect")
    second = TaskIdentity("run", "cycle-b", "gen", "collect")
    assert first != second
    assert first.idempotency_key(payload_hash=HASH_A, input_snapshot_hash=HASH_B) != second.idempotency_key(payload_hash=HASH_A, input_snapshot_hash=HASH_B)


def test_replay_same_cycle_is_idempotent() -> None:
    identity = TaskIdentity("run", "cycle", "gen", "train")
    assert identity.idempotency_key(payload_hash=HASH_A, input_snapshot_hash=HASH_B) == identity.idempotency_key(payload_hash=HASH_A, input_snapshot_hash=HASH_B)


def test_invalid_coordinate_and_hash_fail_closed() -> None:
    with pytest.raises(TaskIdentityError):
        TaskIdentity("../run", "cycle", "", "task")
    with pytest.raises(TaskIdentityError):
        TaskIdentity("run", "cycle", "", "task").idempotency_key(payload_hash="bad", input_snapshot_hash=HASH_B)


def test_lease_sql_uses_skip_locked_and_fencing() -> None:
    normalized = " ".join(LEASE_SQL.lower().split())
    assert "for update skip locked" in normalized
    assert "fencing_token=task.fencing_token + 1" in normalized
    assert "lease_expires_at <" in normalized
    assert LEASE_SECONDS == 300
    assert HEARTBEAT_SECONDS == 30


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (["succeeded"], None),
        (["wait_data"], "wait_data"),
        (["failed"], "skipped_dependency"),
        (["hold", "succeeded"], "skipped_dependency"),
        (["cancelled"], "cancelled"),
    ],
)
def test_terminal_dependency_propagation(states: list[str], expected: str | None) -> None:
    assert downstream_terminal_state(states) == expected
