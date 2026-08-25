from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

psycopg = pytest.importorskip("psycopg")

from ai_fc.timeseries_v7.dag import PROPAGATE_SQL
from ai_fc.timeseries_v7.budget import APPEND_BUDGET_SQL, durable_control_sql
from ai_fc.timeseries_v7.ralph_store import LeaseLost, RalphStore
from ai_fc.timeseries_v7.task_identity import TaskIdentity


DSN = os.environ.get("TSV7_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TSV7_TEST_DATABASE_URL not configured")
H64 = "a" * 64


def connection():
    return psycopg.connect(DSN)


def seed_task(identity: TaskIdentity, capability: str = "evaluator") -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO timeseries_v7.research_run(run_id,model_id,contract_hash,protected_predecessor_hash,state) VALUES(%s,%s,%s,%s,'running') ON CONFLICT DO NOTHING",
            (identity.run_id, "shadow.nasdaq_pit_hierarchical_distribution_v7", H64, H64),
        )
        conn.execute(
            "INSERT INTO timeseries_v7.data_cycle(run_id,cycle_id,knowledge_cutoff,trigger_reason,state) VALUES(%s,%s,clock_timestamp(),'test','ready') ON CONFLICT DO NOTHING",
            (identity.run_id, identity.cycle_id),
        )
        conn.execute(
            """INSERT INTO timeseries_v7.task(
              run_id,cycle_id,generation_id,task_key,task_type,required_capability,state,
              payload_hash,input_snapshot_hash,idempotency_key)
              VALUES(%s,%s,%s,%s,'fixture',%s,'ready',%s,%s,%s)
              ON CONFLICT DO NOTHING""",
            identity.as_tuple() + (capability, H64, H64, identity.idempotency_key(payload_hash=H64, input_snapshot_hash=H64)),
        )


def test_fencing_prevents_double_lease_and_stale_commit() -> None:
    identity = TaskIdentity("p006-run", "cycle", "gen", "task")
    seed_task(identity)
    store = RalphStore(connection)
    now = datetime.now(timezone.utc)
    first = store.lease("evaluator", "worker-a", now=now)
    assert first is not None and first.fencing_token == 1
    assert store.lease("evaluator", "worker-b", now=now) is None
    with connection() as conn:
        conn.execute(
            "UPDATE timeseries_v7.task SET lease_expires_at=%s WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)",
            (now - timedelta(seconds=1),) + identity.as_tuple(),
        )
    second = store.lease("evaluator", "worker-b", now=now)
    assert second is not None and second.fencing_token == 2
    store.start(second)
    with pytest.raises(LeaseLost):
        store.complete(first, result_uri="s3://stale", result_hash=H64)
    store.complete(second, result_uri="s3://valid", result_hash=H64)
    with connection() as conn:
        row = conn.execute(
            "SELECT state,fencing_token,result_artifact_uri FROM timeseries_v7.task WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)",
            identity.as_tuple(),
        ).fetchone()
    assert row == ("succeeded", 2, "s3://valid")


def test_dependency_terminal_state_is_propagated() -> None:
    parent = TaskIdentity("p009-run", "cycle", "gen", "parent")
    child = TaskIdentity("p009-run", "cycle", "gen", "child")
    seed_task(parent)
    seed_task(child)
    with connection() as conn:
        conn.execute(
            "UPDATE timeseries_v7.task SET state='failed' WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)",
            parent.as_tuple(),
        )
        conn.execute(
            "INSERT INTO timeseries_v7.task_dependency(run_id,cycle_id,generation_id,task_key,dependency_generation_id,dependency_task_key) VALUES(%s,%s,%s,%s,%s,%s)",
            child.as_tuple() + (parent.generation_id, parent.task_key),
        )
        rows = conn.execute(PROPAGATE_SQL).fetchall()
    assert (child.run_id, child.cycle_id, child.generation_id, child.task_key, "skipped_dependency") in rows


def test_restart_recovers_checkpoint_without_duplicate_task_side_effect() -> None:
    identity = TaskIdentity("p010-run", "cycle", "gen", "materialize")
    seed_task(identity)
    with connection() as conn:
        conn.execute(
            "UPDATE timeseries_v7.task SET checkpoint_uri='s3://checkpoint/1',checkpoint_hash=%s WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)",
            (H64,) + identity.as_tuple(),
        )
    seed_task(identity)
    with connection() as restarted:
        count = restarted.execute(
            "SELECT count(*) FROM timeseries_v7.task WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)", identity.as_tuple()
        ).fetchone()[0]
        checkpoint = restarted.execute(
            "SELECT checkpoint_uri,checkpoint_hash FROM timeseries_v7.task WHERE (run_id,cycle_id,generation_id,task_key)=(%s,%s,%s,%s)", identity.as_tuple()
        ).fetchone()
    assert count == 1 and checkpoint == ("s3://checkpoint/1", H64)


def test_budget_append_and_pause_abort_are_durable() -> None:
    identity = TaskIdentity("p012-run", "cycle", "", "budget")
    seed_task(identity)
    with connection() as conn:
        conn.execute(APPEND_BUDGET_SQL, identity.as_tuple() + ("experiment_count", 1))
        pause_sql, _ = durable_control_sql("PAUSE")
        conn.execute(pause_sql, (identity.run_id,))
    with connection() as restarted:
        assert restarted.execute("SELECT state FROM timeseries_v7.research_run WHERE run_id=%s", (identity.run_id,)).fetchone()[0] == "wait_data"
        abort_sql, _ = durable_control_sql("ABORT")
        restarted.execute(abort_sql, (identity.run_id,))
    with connection() as restarted:
        assert restarted.execute("SELECT state FROM timeseries_v7.research_run WHERE run_id=%s", (identity.run_id,)).fetchone()[0] == "cancelled"
        assert restarted.execute("SELECT sum(amount) FROM timeseries_v7.budget_ledger WHERE run_id=%s", (identity.run_id,)).fetchone()[0] == 1
