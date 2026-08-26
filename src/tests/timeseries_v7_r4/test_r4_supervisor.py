from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from ai_fc.timeseries_v7_r4.control_plane import PostgresControlPlane
from ai_fc.timeseries_v7_r4.collectors import collect_nasdaqcom
from ai_fc.timeseries_v7_r4.dispatcher import CodexDispatcher, DEFAULT_ALLOWED_PATHS
from ai_fc.timeseries_v7_r4.integrity import (
    canonical_json,
    safe_zip_inventory,
    sanitized_environment,
    scan_secret_bytes,
    sha256_bytes,
    sha256_file,
    validate_child_result,
    protected_manifest,
)
from ai_fc.timeseries_v7_r4.semantics import classify_outcome
from ai_fc.timeseries_v7_r4.router import GateDeficitRouter
from ai_fc.timeseries_v7_r4.specs import read_json, read_yaml, verify_delivery_spec, verify_pack
from ai_fc.timeseries_v7_r4.supervisor import (
    R4_EXACT_E0_ARTIFACT_SHA256,
    R4_EXACT_E0_MEAN_CRPS,
    R4_QUALIFIED_SNAPSHOT_HASH,
    Supervisor,
    SupervisorContext,
)
from ai_fc.timeseries_v7_r4.control_plane import Lease
from ai_fc.timeseries_v7_r4.runtime_snapshot_export import export_runtime_snapshot

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "migrations/timeseries_v7_r4/001_control_plane.sql"
ADMIN_URL = os.getenv(
    "RALPH_V7_R4_TEST_ADMIN_URL",
    "postgresql://postgres@127.0.0.1:55432/postgres",
)


@pytest.fixture(scope="module")
def postgres_url():
    name = "v7r4_test_" + uuid.uuid4().hex[:12]
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as exc:
        pytest.skip(f"disposable PostgreSQL unavailable: {exc}")
    url = f"postgresql://postgres@127.0.0.1:55432/{name}"
    try:
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (name,))
            conn.execute(f'DROP DATABASE "{name}"')


@pytest.fixture()
def control(postgres_url):
    value = PostgresControlPlane(postgres_url)
    value.migrate(MIGRATION)
    return value


def make_run(control: PostgresControlPlane, suffix: str = "") -> str:
    run_id = "test-run-" + uuid.uuid4().hex[:10] + suffix
    control.create_run(run_id=run_id, config_hash="a" * 64,
                       backlog_hash="b" * 64, review_pack_hash="c" * 64)
    return run_id


def result(lease, **overrides):
    value = {
        "run_id": lease.run_id, "cycle_id": lease.run_id + "-c001",
        "task_key": lease.task_key, "attempt_id": lease.attempt_id,
        "status": "SUCCEEDED", "protected_non_mutation": True,
        "secret_scan_pass": True, "child_worker_started_another_task": False,
        "supervisor_should_continue": True,
    }
    value.update(overrides)
    return value


def test_gate_failure_is_normal_replan():
    assert classify_outcome("HOLD_RESEARCH_GATE") == ("RESEARCH_GATE_FAILED_REPLAN", 0, True)


def test_security_is_hard_stop():
    assert classify_outcome("BLOCKED_SECRET_LEAK") == ("BLOCKED_SECRET_LEAK", 2, False)


def test_wait_data_is_normal_terminal():
    assert classify_outcome("WAIT_DATA") == ("WAIT_DATA", 0, False)


def test_wait_execution_permission_is_normal_terminal():
    assert classify_outcome("WAIT_EXECUTION_PERMISSION") == (
        "WAIT_EXECUTION_PERMISSION", 0, False,
    )


def test_unknown_state_fails_closed():
    assert classify_outcome("invented")[0] == "CONTROLLER_BUG"


def test_canonical_json_is_deterministic():
    assert canonical_json({"b": 2, "a": 1}) == b'{"a":1,"b":2}'


def test_sha256_bytes():
    assert sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_safe_zip(tmp_path):
    path = tmp_path / "safe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a/b.txt", "ok")
    assert safe_zip_inventory(path)[0]["path"] == "a/b.txt"


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:\\drive.txt"])
def test_zip_path_escape_rejected(tmp_path, name):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "bad")
    with pytest.raises(ValueError):
        safe_zip_inventory(path)


def test_zip_case_collision_rejected(tmp_path):
    path = tmp_path / "collision.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("A.txt", "one")
        archive.writestr("a.txt", "two")
    with pytest.raises(ValueError):
        safe_zip_inventory(path)


def test_secret_scan_finds_credential():
    assert scan_secret_bytes(b"api_key=" + b"x" * 32)


def test_secret_scan_allows_secret_name_only():
    assert not scan_secret_bytes(b'{"secret_name":"FRED_API_KEY"}')


def test_sanitized_environment(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    monkeypatch.setenv("RALPH_V7_R4_DATABASE_URL", "postgresql://private")
    monkeypatch.setenv("R4_ALLOW_CODEX_CHILD", "1")
    monkeypatch.setenv("R4_PUBLIC_SETTING", "yes")
    env = sanitized_environment()
    assert "FRED_API_KEY" not in env
    assert "RALPH_V7_R4_DATABASE_URL" not in env
    assert "R4_ALLOW_CODEX_CHILD" not in env
    assert env["R4_PUBLIC_SETTING"] == "yes"


def test_valid_child_result():
    payload = {"run_id": "r", "cycle_id": "c", "task_key": "t", "attempt_id": "a",
               "status": "SUCCEEDED", "protected_non_mutation": True,
               "secret_scan_pass": True, "child_worker_started_another_task": False,
               "supervisor_should_continue": True}
    assert validate_child_result(payload) == []


def test_child_cannot_start_another_task():
    payload = {"run_id": "r", "cycle_id": "c", "task_key": "t", "attempt_id": "a",
               "status": "SUCCEEDED", "protected_non_mutation": True,
               "secret_scan_pass": True, "child_worker_started_another_task": True,
               "supervisor_should_continue": True}
    assert "child_started_another_task" in validate_child_result(payload)


def test_successful_child_requires_independent_evidence():
    payload = {"run_id": "r", "cycle_id": "c", "task_key": "t", "attempt_id": "a",
               "status": "SUCCEEDED", "protected_non_mutation": True,
               "secret_scan_pass": True, "child_worker_started_another_task": False,
               "supervisor_should_continue": True, "commands": [], "tests": [],
               "acceptance_results": []}
    errors = validate_child_result(payload, require_evidence=True)
    assert {"missing_command_evidence", "missing_test_evidence",
            "missing_acceptance_evidence"}.issubset(errors)


def test_expected_red_test_is_valid_command_evidence():
    payload = {"run_id": "r", "cycle_id": "c", "task_key": "t", "attempt_id": "a",
               "status": "SUCCEEDED", "protected_non_mutation": True,
               "secret_scan_pass": True, "child_worker_started_another_task": False,
               "supervisor_should_continue": True,
               "commands": [
                   {"command": "pytest missing", "return_code": 1, "phase": "red_test",
                    "expected_failure": "ModuleNotFoundError"},
                   {"command": "pytest fixed", "return_code": 0},
               ],
               "tests": [{"name": "fixed", "passed": True}],
               "acceptance_results": [{"criterion": "fixed", "passed": True}]}
    assert validate_child_result(payload, require_evidence=True) == []


def test_red_then_green_same_command_is_valid_evidence():
    payload = {"run_id": "r", "cycle_id": "c", "task_key": "t", "attempt_id": "a",
               "status": "SUCCEEDED", "protected_non_mutation": True,
               "secret_scan_pass": True, "child_worker_started_another_task": False,
               "supervisor_should_continue": True,
               "commands": [
                   {"command": "pytest targeted", "return_code": 1},
                   {"command": "pytest targeted", "return_code": 0},
                   {"command": "pytest suite", "return_code": 0},
               ],
               "tests": [{"name": "suite", "passed": True}],
               "acceptance_results": [{"criterion": "fixed", "passed": True}]}
    assert validate_child_result(payload, require_evidence=True) == []


def test_dispatch_allowlist_is_r4_only():
    allowed = list(DEFAULT_ALLOWED_PATHS)
    assert CodexDispatcher._path_allowed(
        "src/ai_fc/timeseries_v7_r4/calendar.py", allowed,
    )
    assert CodexDispatcher._path_allowed(
        "data/timeseries_v7_r4/contracts/pit.json", allowed,
    )
    assert not CodexDispatcher._path_allowed(
        "data/timeseries_v7/official_ledger.jsonl", allowed,
    )
    assert not CodexDispatcher._path_allowed(
        "data/timeseries_v7_r4/ralph/spec/frozen.yaml", allowed,
    )


def test_read_specs():
    spec = ROOT / "data/timeseries_v7_r4/ralph/spec"
    config = read_yaml(spec / "NASDAQ_V7_R3_RALPH_R4_CONFIG_20260826.yaml")
    backlog = read_json(spec / "NASDAQ_V7_R3_RALPH_R4_BOOTSTRAP_BACKLOG_20260826.json")
    assert config["controller"]["authoritative_store"] == "postgresql"
    assert backlog["task_count"] == len(backlog["tasks"]) == 45


def test_verify_current_r4_pack():
    pack = Path(r"C:\Users\91ssj\Downloads\NASDAQ_V7_R3_RALPH_R4_SELF_DRIVING_GATE_PASS_PACK_20260826 (1).zip")
    if not pack.exists():
        pytest.skip("delivery pack is host-local")
    assert verify_pack(pack)["entry_count"] == 10


def test_delivery_manifest_matches_all_payloads():
    spec = ROOT / "data/timeseries_v7_r4/ralph/spec"
    result = verify_delivery_spec(spec)
    assert result["file_hashes_pass"] is True
    assert result["backlog_internal_pass"] is True


def test_postgres_migration_and_run(control):
    run_id = make_run(control)
    assert control.status(run_id)["state"] == "BOOTSTRAPPED"


def test_priority_claim(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [
        {"task_id": "late", "title": "late", "priority": 20},
        {"task_id": "first", "title": "first", "priority": 1},
    ])
    assert control.claim(run_id, "worker", 30).task_key == "first"


def test_imported_dependencies_block_claim_until_parent_succeeds(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [
        {"task_id": "parent", "title": "parent", "priority": 2},
        {"task_id": "child", "title": "child", "priority": 1,
         "dependencies": ["parent"]},
    ])
    parent = control.claim(run_id, "worker", 30)
    assert parent.task_key == "parent"
    assert control.finish(parent, "worker", result(parent), "SUCCEEDED")
    assert control.claim(run_id, "worker", 30).task_key == "child"


def test_reconcile_dependencies_repairs_preexisting_run(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [
        {"task_id": "parent", "title": "parent", "priority": 2},
        {"task_id": "child", "title": "child", "priority": 1},
    ])
    with control.connect() as conn:
        conn.execute(
            "UPDATE timeseries_v7_r4.tasks SET payload=%s::jsonb"
            " WHERE run_id=%s AND task_key='child'",
            (json.dumps({"task_id": "child", "title": "child", "priority": 1,
                         "dependencies": ["parent"]}), run_id),
        )
        conn.commit()
    repaired = control.reconcile_dependencies(run_id)
    assert repaired["inserted"] == [("child", "parent")]
    assert control.reconcile_dependencies(run_id)["inserted_count"] == 0
    assert control.claim(run_id, "worker", 30).task_key == "parent"
    assert "DEPENDENCY_GRAPH_CORRECTION_APPENDED" in {
        event["event_type"] for event in control.list_events(run_id)
    }


def test_permission_wait_correction_preserves_attempt_and_wakes(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [{"task_id": "t", "title": "t", "priority": 1}])
    lease = control.claim(run_id, "worker", 30)
    wait_result = result(
        lease,
        status="WAIT_DATA",
        blocker_signature="CODEX_CHILD_EXECUTION_NOT_ENABLED_IN_HOST",
        supervisor_should_continue=False,
    )
    assert control.finish(lease, "worker", wait_result, "WAIT_DATA")
    with control.connect() as conn:
        before = conn.execute(
            "SELECT state,result_hash,result FROM timeseries_v7_r4.attempts"
            " WHERE run_id=%s AND attempt_id=%s",
            (run_id, lease.attempt_id),
        ).fetchone()

    corrections = control.correct_execution_permission_waits(run_id)
    assert corrections[0]["supersedes_attempt_id"] == lease.attempt_id
    assert corrections[0]["supersedes_result_hash"] == before[1]
    with control.connect() as conn:
        task_state = conn.execute(
            "SELECT state FROM timeseries_v7_r4.tasks WHERE run_id=%s AND task_key='t'",
            (run_id,),
        ).fetchone()[0]
        after = conn.execute(
            "SELECT state,result_hash,result FROM timeseries_v7_r4.attempts"
            " WHERE run_id=%s AND attempt_id=%s",
            (run_id, lease.attempt_id),
        ).fetchone()
    assert task_state == "WAIT_EXECUTION_PERMISSION"
    assert after == before
    assert control.correct_execution_permission_waits(run_id) == []

    assert control.wake_execution_permission(run_id) == ["t"]
    with control.connect() as conn:
        task = conn.execute(
            "SELECT state,blocker_signature FROM timeseries_v7_r4.tasks"
            " WHERE run_id=%s AND task_key='t'", (run_id,),
        ).fetchone()
    assert task == ("PENDING", None)
    assert [event["event_type"] for event in control.list_events(run_id)] == [
        "TASK_STATE_CORRECTION_APPENDED",
        "TASK_EXECUTION_PERMISSION_GRANTED",
    ]


def test_acceptance_correction_preserves_success_and_requeues(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [{"task_id": "t", "title": "t", "priority": 1}])
    lease = control.claim(run_id, "worker", 30)
    success = result(lease)
    assert control.finish(lease, "worker", success, "SUCCEEDED")
    with control.connect() as conn:
        before = conn.execute(
            "SELECT state,result_hash,result FROM timeseries_v7_r4.attempts"
            " WHERE run_id=%s AND attempt_id=%s", (run_id, lease.attempt_id),
        ).fetchone()

    correction = control.correct_task_acceptance(
        run_id, "t", reason="authoritative store mismatch",
        evidence={"expected": "postgresql", "observed": "sqlite"},
    )
    assert correction["supersedes_attempt_id"] == lease.attempt_id
    assert correction["supersedes_result_hash"] == before[1]
    assert control.correct_task_acceptance(
        run_id, "t", reason="authoritative store mismatch",
        evidence={"expected": "postgresql", "observed": "sqlite"},
    ) == correction
    with control.connect() as conn:
        after = conn.execute(
            "SELECT state,result_hash,result FROM timeseries_v7_r4.attempts"
            " WHERE run_id=%s AND attempt_id=%s", (run_id, lease.attempt_id),
        ).fetchone()
    assert after == before
    retry = control.claim(run_id, "worker", 30)
    assert retry.task_key == "t"
    assert retry.payload["retry_blocker"] == "AUTHORITATIVE_POSTGRES_ACCEPTANCE_FAILED"
    assert retry.payload["acceptance_correction_history"]["reason"] == "authoritative store mismatch"
    assert retry.payload["acceptance_correction_history"]["evidence"] == {
        "expected": "postgresql", "observed": "sqlite",
    }
    assert retry.payload["retry_evidence"]["blocker_signature"] is None
    assert retry.payload["retry_attempt_history"][0]["attempt_id"] == lease.attempt_id


def test_implementable_wait_data_is_corrected_to_replan(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [{"task_id": "t", "title": "t", "priority": 1}])
    lease = control.claim(run_id, "worker", 30)
    wait = result(
        lease, status="WAIT_DATA", blocker_signature="MISSING_GENERATED_ARTIFACT",
        supervisor_should_continue=False,
    )
    assert control.finish(lease, "worker", wait, "WAIT_DATA")

    correction = control.correct_wait_data_to_replan(
        run_id, "t", reason="artifact is locally generatable",
        evidence={"source_data_present": True},
    )

    assert correction["original_state"] == "WAIT_DATA"
    assert correction["corrected_state"] == "RETRY_WAIT"
    retry = control.claim(run_id, "worker", 30)
    assert retry.payload["retry_blocker"] == "MISCLASSIFIED_WAIT_DATA_REPLAN"
    assert retry.payload["acceptance_correction_history"]["reason"] == "artifact is locally generatable"
    assert retry.payload["retry_evidence"]["blocker_signature"] == "MISSING_GENERATED_ARTIFACT"
    assert retry.payload["retry_attempt_history"][0]["blocker_signature"] == (
        "MISSING_GENERATED_ARTIFACT"
    )


def test_lease_fencing(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [{"task_id": "t", "title": "t", "priority": 1}])
    lease = control.claim(run_id, "worker", 30)
    forged = type(lease)(lease.run_id, lease.task_key, lease.attempt_id,
                         "forged", lease.title, lease.payload)
    assert not control.finish(forged, "worker", result(lease), "SUCCEEDED")
    assert control.finish(lease, "worker", result(lease), "SUCCEEDED")


def test_heartbeat_fencing(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [{"task_id": "t", "title": "t", "priority": 1}])
    lease = control.claim(run_id, "worker", 30)
    assert control.heartbeat(lease, "worker", 60)
    assert not control.heartbeat(lease, "other", 60)


def test_retry_backoff_is_not_reported_as_missing_data(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [{"task_id": "t", "title": "t", "priority": 1}])
    lease = control.claim(run_id, "worker", 30)
    retry = result(lease, status="RETRY_WAIT", blocker_signature="REPLAN")
    assert control.finish(lease, "worker", retry, "RETRY_WAIT")

    seconds = control.retry_backoff_seconds(run_id)

    assert seconds is not None
    assert 0 < seconds <= 60


def test_runtime_snapshot_export_is_credential_free(control, tmp_path):
    control.migrate(ROOT / "migrations/timeseries_v7_r4/002_pit_snapshots.sql")
    snapshot_hash = "d" * 64
    payload = {
        "feature_rows": [{"origin_session": "2020-01-02", "x": 1.0}],
        "labels": [{"origin_session": "2020-01-02", "horizon_sessions": 1,
                    "value": 0.01}],
    }
    with control.connect() as connection:
        connection.execute(
            "INSERT INTO timeseries_v7_r4.pit_snapshots "
            "(snapshot_hash,as_of,calendar_version,payload) VALUES (%s,%s,%s,%s::jsonb)",
            (snapshot_hash, datetime(2020, 1, 3, tzinfo=timezone.utc),
             "xnas-test", json.dumps(payload)),
        )
        connection.commit()

    output = tmp_path / "runtime-input.json"
    receipt = export_runtime_snapshot(
        control.database_url, snapshot_hash=snapshot_hash, output=output,
    )
    exported = json.loads(output.read_text(encoding="utf-8"))

    assert receipt["feature_rows"] == 1 and receipt["label_rows"] == 1
    assert receipt["credential_fields"] == 0
    assert exported["snapshot_hash"] == snapshot_hash
    assert "database_url" not in output.read_text(encoding="utf-8").lower()
    assert "postgresql://" not in output.read_text(encoding="utf-8").lower()


def test_five_role_export_has_nonempty_roles_and_session_gaps():
    from ai_fc.timeseries_v7_r4.runtime_snapshot_export import (
        FIVE_ROLE_RETAINED_COUNTS, _five_role_plan,
    )

    total = sum(FIVE_ROLE_RETAINED_COUNTS.values()) + 525
    origins = [f"{2000 + index // 360:04d}-{index % 12 + 1:02d}-{index % 28 + 1:02d}"
               for index in range(total)]
    # The helper requires unique ordered session identifiers; synthetic ordinal
    # prefixes make the ordering contract explicit without a market calendar.
    origins = [f"{index:05d}" for index in range(total)]
    features = [{"origin_session": origin} for origin in origins]
    labels = [{"origin_session": origin, "horizon_sessions": horizon}
              for origin in origins for horizon in (1, 5, 21, 63)]

    plan = _five_role_plan(features, labels)

    assert plan is not None
    assert plan["role_counts"] == FIVE_ROLE_RETAINED_COUNTS
    assert all(plan["role_origins"][role] for role in plan["role_order"])
    assert min(plan["gap_counts"]) >= plan["purge_sessions"] + plan["embargo_sessions"]
    assert plan["excluded_count"] == 525
    assert len(plan["plan_hash"]) == 64


def test_d1_006_rejects_single_feature_snapshot_as_multivariate_pit(
    control, tmp_path,
):
    artifact = tmp_path / "outputs/timeseries_v7_r4/R4-D1-006"
    artifact.mkdir(parents=True)
    (artifact / "data_pit_qualification.json").write_text(
        json.dumps({
            "source_snapshot_hash": "a" * 64,
            "r4_snapshot_hash": "b" * 64,
            "source_snapshot_rows": 7712,
            "source_label_rows": 30758,
            "active_feature_value_count": 7712,
            "qualified_feature_count": 1,
            "target_price_rows": 0,
            "core_missingness_2007_plus": 1.0,
            "alfred_series_covered": 1,
            "release_native_feature_count": 1,
            "calendar_version_hash": "c" * 64,
            "canonical_early_close_checks": 69,
            "r4_snapshot_rematerialized": True,
            "canonical_xnas_cutoff_proof": True,
            "feature_value_provenance_pass": True,
            "release_native_features_pass": True,
            "postgres_snapshot_persisted": True,
            "legacy_runtime_defects_acknowledged": True,
        }),
        encoding="utf-8",
    )
    context = SupervisorContext(
        repo=tmp_path,
        output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip",
        r3_design_pack=None,
        predecessor_repo=None,
        config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    )
    supervisor = Supervisor(control, context)
    lease = Lease(
        "run", "R4-D1-006", "attempt", "token", "qualify", {},
    )
    child_result = {
        "status": "SUCCEEDED",
        "acceptance_results": [],
        "unresolved_blockers": [],
        "recommended_router_deficits": [],
    }

    checked = supervisor._validate_task_semantics(lease, child_result)

    assert checked["status"] == "RETRY_WAIT"
    assert checked["blocker_signature"] == "R4_FULL_REMATERIALIZATION_EVIDENCE_MISSING"
    evidence = checked["acceptance_results"][-1]["evidence"]
    assert evidence["usable_multivariate_feature_set"] is False
    assert evidence["target_price_complete"] is False
    assert evidence["all_alfred_series_covered"] is False


def test_v2_002_rejects_a_new_block_bootstrap_comparator(control, tmp_path):
    module = tmp_path / "src/ai_fc/timeseries_v7_r4"
    module.mkdir(parents=True)
    (module / "e0_empirical_samples.py").write_text(
        'E0_BLOCK_BOOTSTRAP_CONTRACT={"algorithm":"historical_moving_block_bootstrap"}\n'
        'def from_quantiles(): raise ValueError("quantiles cannot reconstruct")\n',
        encoding="utf-8",
    )
    supervisor = Supervisor(
        control,
        SupervisorContext(
            repo=tmp_path,
            output_root=tmp_path / "outputs/timeseries_v7_r4",
            review_pack=tmp_path / "review.zip",
            r3_design_pack=None,
            predecessor_repo=None,
            config={"controller": {"lease_seconds": 30}},
            auto_codex=False,
        ),
    )
    lease = Lease("run", "R4-V2-002", "attempt", "token", "E0", {})
    child_result = {
        "status": "SUCCEEDED", "acceptance_results": [],
        "unresolved_blockers": [], "recommended_router_deficits": [],
    }

    checked = supervisor._validate_task_semantics(lease, child_result)

    assert checked["status"] == "RETRY_WAIT"
    assert checked["blocker_signature"] == "FROZEN_E0_COMPARATOR_MISMATCH"
    evidence = checked["acceptance_results"][-1]["evidence"]
    assert evidence["frozen_exact_empirical_anchor"] is False
    assert evidence["no_comparator_block_bootstrap"] is False


def test_v2_003_rejects_quadratic_pairwise_broadcast_without_final_guard(
    control, tmp_path,
):
    module = tmp_path / "src/ai_fc/timeseries_v7_r4"
    module.mkdir(parents=True)
    (module / "empirical_mixture.py").write_text(
        "pairwise = abs(left_values[:, None] - right_values[None, :])\n",
        encoding="utf-8",
    )
    supervisor = Supervisor(
        control,
        SupervisorContext(
            repo=tmp_path,
            output_root=tmp_path / "outputs/timeseries_v7_r4",
            review_pack=tmp_path / "review.zip",
            r3_design_pack=None,
            predecessor_repo=None,
            config={"controller": {"lease_seconds": 30}},
            auto_codex=False,
        ),
    )
    lease = Lease("run", "R4-V2-003", "attempt", "token", "mixture", {})
    checked = supervisor._validate_task_semantics(
        lease,
        {"status": "SUCCEEDED", "acceptance_results": [],
         "unresolved_blockers": [], "recommended_router_deficits": []},
    )

    assert checked["status"] == "RETRY_WAIT"
    assert checked["blocker_signature"] == "EMPIRICAL_MIXTURE_SCALE_OR_GUARD_MISSING"


def test_m3_006_rejects_point_mae_and_asserted_five_role_proof(control, tmp_path):
    artifact = tmp_path / "outputs/timeseries_v7_r4/R4-M3-006"
    artifact.mkdir(parents=True)
    (artifact / "g1_screen.json").write_text(json.dumps({
        "candidate_families": ["E1", "E2", "E3", "E4"],
        "candidate_counts": {"smoke": 4, "inner_screen": 4, "robust_inner": 4,
                             "full_nested": 4, "qualification": 1},
        "candidates": [{"candidate_id": family, "hypothesis_hash": "a" * 64,
                         "exposure_hash": "b" * 64, "underperforms_e0": True,
                         "weight": 0.0} for family in ("E1", "E2", "E3", "E4")],
        "five_role_validation_proof": True,
        "source": {
            "r4_snapshot_hash": "cdddba1e32a4bdb3aebc98ec676c81744085a2a5952d4014807f0feb78140fc2",
            "e0_artifact_sha256": "0653be032bcc8d0a4bf743967be3f21611a148aa9a12e11b1cb152f4aa2ca6ec",
            "evaluation_origin_grid_hash": "e9657818bc2693c0788d4c509b4bf08b4456e7ca6c8f149028788ee845947135",
            "model_score_rows": 24480, "legacy_precomputed_score_rows_used": 0,
            "outer_rows_used": 0, "score_metric": "mae",
        },
    }), encoding="utf-8")
    supervisor = Supervisor(control, SupervisorContext(
        repo=tmp_path, output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip", r3_design_pack=None,
        predecessor_repo=None, config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    ))
    checked = supervisor._validate_task_semantics(
        Lease("run", "R4-M3-006", "attempt", "token", "screen", {}),
        {"status": "SUCCEEDED", "acceptance_results": [],
         "unresolved_blockers": [], "recommended_router_deficits": []},
    )

    assert checked["status"] == "RETRY_WAIT"
    evidence = checked["acceptance_results"][-1]["evidence"]
    assert evidence["distribution_crps_scoring"] is False
    assert evidence["five_role_partition_bound"] is False
    assert evidence["frozen_candidate_coordinates_preserved"] is False


def test_m3_006_rejects_rounded_e0_comparator_value(control, tmp_path):
    artifact = tmp_path / "outputs/timeseries_v7_r4/R4-M3-006"
    artifact.mkdir(parents=True)
    role_counts = {role: 1 for role in ("train", "selection", "stacking",
                                        "calibration", "outer")}
    role_hashes = {role: "a" * 64 for role in role_counts}
    score_receipts = [{"family": family, "metric": "crps", "score_rows": 4,
                       "predictive_distribution_hash": "b" * 64}
                      for family in ("E1", "E2", "E3", "E4")]
    (artifact / "g1_screen.json").write_text(json.dumps({
        "candidate_families": ["E1", "E2", "E3", "E4"],
        "candidate_counts": {"smoke": 4, "inner_screen": 4, "robust_inner": 4,
                             "full_nested": 4, "qualification": 1},
        "candidates": [{"candidate_id": family, "hypothesis_hash": "c" * 64,
                         "exposure_hash": "d" * 64, "underperforms_e0": True,
                         "weight": 0.0} for family in ("E1", "E2", "E3", "E4")],
        "five_role_validation_proof": True, "score_receipts": score_receipts,
        "source": {
            "r4_snapshot_hash": "cdddba1e32a4bdb3aebc98ec676c81744085a2a5952d4014807f0feb78140fc2",
            "e0_artifact_sha256": "0653be032bcc8d0a4bf743967be3f21611a148aa9a12e11b1cb152f4aa2ca6ec",
            "e0_mean_crps": 0.03,
            "evaluation_origin_grid_hash": "e9657818bc2693c0788d4c509b4bf08b4456e7ca6c8f149028788ee845947135",
            "model_score_rows": 16, "legacy_precomputed_score_rows_used": 0,
            "outer_rows_used": 0, "score_metric": "distribution_crps",
            "frozen_candidate_coordinates_preserved": True,
            "optimizer_convergence_required": True,
            "five_role_receipt": {"role_counts": role_counts, "role_hashes": role_hashes,
                                  "plan_hash": "e" * 64, "excluded_count": 1,
                                  "interval_overlap_count": 0,
                                  "purge_unit": "xnas_sessions",
                                  "outer_exposed_during_screen": False},
        },
    }), encoding="utf-8")
    supervisor = Supervisor(control, SupervisorContext(
        repo=tmp_path, output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip", r3_design_pack=None,
        predecessor_repo=None, config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    ))
    checked = supervisor._validate_task_semantics(
        Lease("run", "R4-M3-006", "attempt", "token", "screen", {}),
        {"status": "SUCCEEDED", "acceptance_results": [],
         "unresolved_blockers": [], "recommended_router_deficits": []},
    )

    assert checked["status"] == "RETRY_WAIT"
    assert checked["acceptance_results"][-1]["evidence"]["uses_exact_e0_full_grid"] is False


def test_m3_007_rejects_raw_sample_checkpoints_and_accepts_compact_receipts(control, tmp_path):
    g1_folder = tmp_path / "outputs/timeseries_v7_r4/R4-M3-006"
    g2_folder = tmp_path / "outputs/timeseries_v7_r4/R4-M3-007"
    g1_folder.mkdir(parents=True)
    g2_folder.mkdir(parents=True)
    role_hashes = {role: role[0] * 64 for role in
                   ("train", "selection", "stacking", "calibration", "outer")}
    g1 = {
        "candidates": [{"candidate_id": family, "weight": 0.0}
                       for family in ("E1", "E2", "E3", "E4")],
        "five_role_receipt": {"role_hashes": role_hashes},
    }
    g1_path = g1_folder / "g1_screen.json"
    g1_path.write_text(json.dumps(g1), encoding="utf-8")
    five_role = {
        "role_counts": {"train": 4458, "selection": 634, "stacking": 634,
                        "calibration": 634, "outer": 765},
        "role_hashes": role_hashes,
        "outer_exposed_during_screen": False,
    }
    horizons = {
        str(horizon): {
            "weights": {"E0": 1.0, "E1": 0.0, "E2": 0.0, "E3": 0.0, "E4": 0.0},
            "weight_fit_role": "stacking", "stacking_case_count": 634,
            "stacking_crps": .02, "stacking_e0_crps": .02,
            "calibration_fit_role": "calibration", "cross_fit_case_count": 634,
            "cross_fit_calibration_applied": True, "e0_no_regret_pass": True,
            "sample_set_hash": str(horizon)[0] * 64,
        }
        for horizon in (1, 5, 21, 63)
    }
    artifact_path = g2_folder / "stacking_calibration.json"
    artifact_path.write_text(json.dumps({
        "schema": "r4_learned_stacking_cross_fit_calibration_v1",
        "horizons": horizons, "outer_rows_used": 0,
        "source": {
            "r4_snapshot_hash": R4_QUALIFIED_SNAPSHOT_HASH,
            "e0_artifact_sha256": R4_EXACT_E0_ARTIFACT_SHA256,
            "e0_mean_crps": R4_EXACT_E0_MEAN_CRPS,
            "g1_artifact_sha256": sha256_file(g1_path),
            "five_role_receipt": five_role,
            "git_embedded_raw_samples": False,
        },
    }), encoding="utf-8")
    supervisor = Supervisor(control, SupervisorContext(
        repo=tmp_path, output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip", r3_design_pack=None,
        predecessor_repo=None, config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    ))
    lease = Lease("run", "R4-M3-007", "attempt", "token", "stack", {})
    base = {"status": "SUCCEEDED", "acceptance_results": [],
            "unresolved_blockers": [], "recommended_router_deficits": []}

    checked = supervisor._validate_task_semantics(lease, dict(base))
    assert checked["status"] == "SUCCEEDED"
    assert checked["acceptance_results"][-1]["passed"] is True

    (g2_folder / "raw-samples.json").write_bytes(b"x" * 1_000_001)
    rejected = supervisor._validate_task_semantics(lease, dict(base))
    assert rejected["status"] == "RETRY_WAIT"
    assert rejected["acceptance_results"][-1]["evidence"][
        "artifact_present_and_compact"
    ] is False


def test_m3_008_rejects_self_report_without_frozen_methodology_revision(control, tmp_path):
    folder = tmp_path / "outputs/timeseries_v7_r4/R4-M3-008"
    folder.mkdir(parents=True)
    (folder / "qualification_revision_2.json").write_text(
        json.dumps({"schema": "r4_core_qualification_v1_revision_2"}),
        encoding="utf-8",
    )
    supervisor = Supervisor(control, SupervisorContext(
        repo=tmp_path, output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip", r3_design_pack=None,
        predecessor_repo=None, config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    ))
    checked = supervisor._validate_task_semantics(
        Lease("run", "R4-M3-008", "attempt", "token", "qualification", {}),
        {"status": "SUCCEEDED", "acceptance_results": [],
         "unresolved_blockers": [], "recommended_router_deficits": []},
    )
    assert checked["status"] == "RETRY_WAIT"
    assert checked["blocker_signature"] == "CORE_QUALIFICATION_GATE_METHOD_MISMATCH"
    assert checked["acceptance_results"][-1]["passed"] is False


def test_s4_001_rejects_predecessor_score_calibration_without_r4_role_receipt(control, tmp_path):
    folder = tmp_path / "outputs/timeseries_v7_r4/R4-S4-001/r4_calibration"
    folder.mkdir(parents=True)
    (folder / "acceptance_summary.json").write_text(
        json.dumps({"source_sha256": "a" * 64,
                    "families": [{"family": f"h{horizon}"}
                                 for horizon in (1, 5, 21, 63)]}), encoding="utf-8",
    )
    supervisor = Supervisor(control, SupervisorContext(
        repo=tmp_path, output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip", r3_design_pack=None,
        predecessor_repo=None, config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    ))
    checked = supervisor._validate_task_semantics(
        Lease("run", "R4-S4-001", "attempt", "token", "p-up", {}),
        {"status": "SUCCEEDED", "acceptance_results": [],
         "unresolved_blockers": [], "recommended_router_deficits": []},
    )
    assert checked["status"] == "RETRY_WAIT"
    assert checked["blocker_signature"] == "P_UP_CALIBRATION_ROLE_LEAKAGE"


def test_s4_001_accepts_explicit_pass_with_recomputed_fraction_bounds(control, tmp_path):
    folder = tmp_path / "outputs/timeseries_v7_r4/R4-S4-001/r4_calibration"
    folder.mkdir(parents=True)
    source = {
        "r4_snapshot_hash": R4_QUALIFIED_SNAPSHOT_HASH,
        "r4_snapshot_artifact_sha256":
            "e86687d2cb8daa77375546d049877f353cd7046969cead19ec8b9b9b6f1102ff",
        "g2_artifact_sha256":
            "3e19f5dc4360b0a74de41a7d4c54967597853b12c81689c57fbc34c281972523",
        "calibration_role_hash":
            "0f96b564e45155f90819c050f6435e964f8707989a67b5ba1f3da897c7b95fa2",
        "legacy_review_pack_score_rows_used": 0,
        "qualification_score_rows_used": 0, "outer_rows_used": 0,
        "outer_origin_intersection": 0,
    }
    family = lambda horizon: {
        "horizon": horizon, "calibration_role_origin_count": 634,
        "fit_role": "calibration_temporal_cross_fit",
        "evaluation_role": "calibration_cross_fit_holdout",
        "brier": .2, "base_rate_brier": .25, "balanced_brier": .21,
        "probability_unit": "fraction", "probability_bounds": "PASS",
        "probability_min": 0.0, "probability_max": 1.0,
    }
    (folder / "acceptance_summary.json").write_text(json.dumps({
        "schema": "r4_probability_up_calibration_v2", "source": source,
        "families": [family(horizon) for horizon in (1, 5, 21, 63)],
        "supersedes_sha256": "a" * 64,
    }), encoding="utf-8")
    supervisor = Supervisor(control, SupervisorContext(
        repo=tmp_path, output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip", r3_design_pack=None,
        predecessor_repo=None, config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    ))
    checked = supervisor._validate_task_semantics(
        Lease("run", "R4-S4-001", "attempt", "token", "p-up", {}),
        {"status": "SUCCEEDED", "acceptance_results": [],
         "unresolved_blockers": [], "recommended_router_deficits": []},
    )
    assert checked["status"] == "SUCCEEDED"
    assert checked["acceptance_results"][-1]["passed"] is True


def test_s4_002_rejects_predecessor_scale_fit_without_r4_role_receipt(control, tmp_path):
    folder = tmp_path / "outputs/timeseries_v7_r4/R4-S4-002/r4_calibration"
    folder.mkdir(parents=True)
    (folder / "acceptance_summary.json").write_text(
        json.dumps({
            "source_sha256": "a" * 64,
            "families": [
                {
                    "family": f"h{horizon}", "calibration_rows": 634,
                    "normal_sharpness": {"ratio": 1.0},
                    "scales": {
                        "normal": {"volatility_scale": 1.0},
                        "stress": {"volatility_scale": 1.1},
                    },
                }
                for horizon in (1, 5, 21, 63)
            ],
        }), encoding="utf-8",
    )
    supervisor = Supervisor(control, SupervisorContext(
        repo=tmp_path, output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip", r3_design_pack=None,
        predecessor_repo=None, config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    ))
    checked = supervisor._validate_task_semantics(
        Lease("run", "R4-S4-002", "attempt", "token", "scale", {}),
        {"status": "SUCCEEDED", "acceptance_results": [],
         "unresolved_blockers": [], "recommended_router_deficits": []},
    )
    assert checked["status"] == "RETRY_WAIT"
    assert checked["blocker_signature"] == "CONDITIONAL_SCALE_ROLE_LEAKAGE"


@pytest.mark.parametrize(("task_key", "blocker"), [
    ("R4-S4-003", "ASYMMETRIC_EVT_ROLE_OR_GUARD_FAILURE"),
    ("R4-S4-004", "REGIME_ROLE_OR_FEATURE_LEAKAGE"),
    ("R4-S4-005", "ANALOG_TRAJECTORY_IDENTITY_OR_ROLE_FAILURE"),
])
def test_s4_mechanisms_fail_closed_without_registered_receipt(
    control, tmp_path, task_key, blocker,
):
    supervisor = Supervisor(control, SupervisorContext(
        repo=tmp_path, output_root=tmp_path / "outputs/timeseries_v7_r4",
        review_pack=tmp_path / "review.zip", r3_design_pack=None,
        predecessor_repo=None, config={"controller": {"lease_seconds": 30}},
        auto_codex=False,
    ))
    checked = supervisor._validate_task_semantics(
        Lease("run", task_key, "attempt", "token", "mechanism", {}),
        {"status": "SUCCEEDED", "acceptance_results": [],
         "unresolved_blockers": [], "recommended_router_deficits": []},
    )
    assert checked["status"] == "RETRY_WAIT"
    assert checked["blocker_signature"] == blocker


def test_event_is_append_only(control):
    run_id = make_run(control)
    control.event(run_id, "ONE", {"x": 1})
    control.event(run_id, "TWO", {"x": 2})
    assert [event["event_type"] for event in control.list_events(run_id)] == ["ONE", "TWO"]


def test_blocked_execution_correction_preserves_attempt_and_only_requeues(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [{"id": "task", "title": "task"}])
    lease = control.claim(run_id, "worker", 30)
    assert lease is not None
    blocked = {
        "schema_version": 1, "run_id": run_id, "cycle_id": f"{run_id}-c001",
        "task_key": "task", "attempt_id": lease.attempt_id, "status": "BLOCKED",
        "blocker_signature": "INVALID_CHILD_RESULT:missing:run_id",
    }
    assert control.finish(lease, "worker", blocked, "BLOCKED") is True

    correction = control.correct_blocked_execution_to_retry(
        run_id, "task", reason="mechanical envelope identity omission",
        evidence={"model_gate_executed": False, "artifact_preserved": True},
    )

    status = control.status(run_id)
    with control.connect() as connection:
        task_state = connection.execute(
            "SELECT state FROM timeseries_v7_r4.tasks WHERE run_id=%s AND task_key='task'",
            (run_id,),
        ).fetchone()[0]
    assert correction["original_state"] == "BLOCKED"
    assert correction["corrected_state"] == "RETRY_WAIT"
    assert correction["supersedes_attempt_id"] == lease.attempt_id
    assert task_state == "RETRY_WAIT"
    assert status["state"] == "REPLAN"


def test_catalog_deduplicates(control):
    task = {"task_id": "catalog-task", "title": "catalog"}
    assert control.import_catalog("catalog-test", [task]) == 1
    assert control.import_catalog("catalog-test", [task]) == 0


def test_run_state_update(control):
    run_id = make_run(control)
    control.set_run_state(run_id, "WAIT_DATA", {"current": 0, "required": 1})
    status = control.status(run_id)
    assert status["state"] == "WAIT_DATA" and status["terminal_reason"]["required"] == 1


def test_finished_task_not_reclaimed(control):
    run_id = make_run(control)
    control.import_tasks(run_id, [{"task_id": "t", "title": "t", "priority": 1}])
    lease = control.claim(run_id, "worker", 30)
    assert control.finish(lease, "worker", result(lease), "SUCCEEDED")
    assert control.claim(run_id, "worker", 30) is None


def test_official_collector_is_session_aware(tmp_path):
    payload = (b"observation_date,NASDAQCOM\n"
               b"2026-08-21,26180.450\n2026-08-24,25980.190\n")
    receipt = collect_nasdaqcom(
        tmp_path,
        now=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
        payload=payload,
    )
    assert receipt["target_completed_xnas_session"] == "2026-08-25"
    assert receipt["missing_completed_sessions"] == 1
    assert receipt["freshness_pass"] is True
    assert "api_key" not in receipt["request_url"]


def test_official_collector_appends_without_duplicate(tmp_path):
    payload = b"observation_date,NASDAQCOM\n2026-08-24,25980.190\n"
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    first = collect_nasdaqcom(tmp_path, now=now, payload=payload)
    second = collect_nasdaqcom(tmp_path, now=now, payload=payload)
    assert first["new_rows"] == 1 and second["new_rows"] == 0


def test_protected_manifest_changes_on_protected_file(tmp_path):
    target = tmp_path / "data/timeseries_v7"
    target.mkdir(parents=True)
    item = target / "sealed.json"
    item.write_text("one", encoding="utf-8")
    before = protected_manifest(tmp_path)
    item.write_text("two", encoding="utf-8")
    after = protected_manifest(tmp_path)
    assert before["manifest_sha256"] != after["manifest_sha256"]


def test_codex_dispatcher_contract_is_available():
    assert CodexDispatcher.contract_ready() is True


def test_codex_dispatch_requires_explicit_enable(tmp_path, monkeypatch):
    monkeypatch.delenv("R4_ALLOW_CODEX_CHILD", raising=False)
    dispatcher = CodexDispatcher(repo=ROOT, output_root=tmp_path,
                                 central_worktree_root=tmp_path / "worktrees")
    with pytest.raises(PermissionError):
        dispatcher.dispatch({"task_key": "t", "attempt_id": "a"})


def test_codex_dispatch_prompt_requires_exact_identity_list_tests_and_retry_receipt():
    envelope = {
        "run_id": "run-1", "cycle_id": "cycle-2", "task_key": "R4-M3-007",
        "attempt_id": "attempt-4",
        "execution_replan_history": [{
            "evidence": {
                "required_changed_path":
                    "outputs/timeseries_v7_r4/R4-M3-007/verification_receipt.json",
            },
        }],
    }
    prompt = CodexDispatcher._build_prompt(envelope)
    assert '"run_id":"run-1"' in prompt
    assert '"cycle_id":"cycle-2"' in prompt
    assert '"task_key":"R4-M3-007"' in prompt
    assert '"attempt_id":"attempt-4"' in prompt
    assert "tests field must be a JSON array" in prompt
    assert "outputs/timeseries_v7_r4/R4-M3-007/verification_receipt.json" in prompt
    assert "successful verification-only retry therefore still has a real changed path" in prompt


def test_codex_dispatch_prompt_freezes_one_time_core_qualification_contract():
    prompt = CodexDispatcher._build_prompt({
        "run_id": "r", "cycle_id": "c", "task_key": "R4-M3-008",
        "attempt_id": "a",
    })
    assert "all 4,082 coordinates" in prompt
    assert "unchanged 1,025-origin weekly grid" in prompt
    assert "qualification_count=1" in prompt
    assert "complete machine-readable deficit vector" in prompt
    assert "never alter scores or claim PASS" in prompt
    assert "seed 20260825" in prompt
    assert "1,000 moving-block replications of length 13" in prompt
    assert "append a revision with an explicit supersedes SHA-256" in prompt


def test_codex_dispatch_prompt_isolates_s4_001_from_qualification_outer():
    prompt = CodexDispatcher._build_prompt({
        "run_id": "r", "cycle_id": "c", "task_key": "R4-S4-001",
        "attempt_id": "a",
    })
    assert "fixed calibration role (634 origins)" in prompt
    assert "qualification_score_rows_used=0" in prompt
    assert "outer_rows_used=0" in prompt
    assert "diagnostic evidence only" in prompt
    assert "phase=red_test" in prompt
    assert "expected_failure" in prompt
    assert "schema=r4_probability_up_calibration_v2" in prompt
    assert "evaluation_role=calibration_cross_fit_holdout" in prompt


def test_codex_dispatch_prompt_requires_s4_002_corrected_receipt_schema():
    prompt = CodexDispatcher._build_prompt({
        "run_id": "run", "cycle_id": "cycle", "task_key": "R4-S4-002",
        "attempt_id": "attempt",
    })
    assert "schema=r4_conditional_scale_v2" in prompt
    assert "calibration_role_origin_count=634" in prompt
    assert "normal_width_ratio<=1.10" in prompt
    assert "supersedes_sha256" in prompt


@pytest.mark.parametrize(("task_key", "required"), [
    ("R4-S4-003", "schema=r4_asymmetric_evt_v1"),
    ("R4-S4-004", "schema=r4_learned_regime_partial_pool_v1"),
    ("R4-S4-005", "schema=r4_full_analog_trajectories_v1"),
])
def test_codex_dispatch_prompt_registers_s4_mechanism_receipt(task_key, required):
    prompt = CodexDispatcher._build_prompt({
        "run_id": "run", "cycle_id": "cycle", "task_key": task_key,
        "attempt_id": "attempt",
    })
    assert required in prompt
    assert "qualification/outer outcomes are diagnostic evidence only" in prompt


def test_gate_deficit_router_is_deterministic():
    router = GateDeficitRouter.from_yaml(
        ROOT / "data/timeseries_v7_r4/ralph/spec/NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml")
    first = router.route(["h21_skill_negative", "coverage50_low"],
                         dataset_snapshot_hash="d" * 64, code_hash="c" * 64,
                         runtime_hash="r" * 64)
    second = router.route(["coverage50_low", "h21_skill_negative"],
                          dataset_snapshot_hash="d" * 64, code_hash="c" * 64,
                          runtime_hash="r" * 64)
    assert first == second
    assert "E0_ONLY_FALLBACK" in [item.action for item in first]
    assert "CROSS_FIT_LOCATION_SCALE_CALIBRATION" in [item.action for item in first]
