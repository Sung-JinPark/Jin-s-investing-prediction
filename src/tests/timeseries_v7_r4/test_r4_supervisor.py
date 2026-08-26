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
    validate_child_result,
    protected_manifest,
)
from ai_fc.timeseries_v7_r4.semantics import classify_outcome
from ai_fc.timeseries_v7_r4.router import GateDeficitRouter
from ai_fc.timeseries_v7_r4.specs import read_json, read_yaml, verify_delivery_spec, verify_pack
from ai_fc.timeseries_v7_r4.supervisor import Supervisor, SupervisorContext
from ai_fc.timeseries_v7_r4.control_plane import Lease

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
    assert retry.payload["retry_evidence"]["reason"] == "authoritative store mismatch"
    assert retry.payload["retry_evidence"]["evidence"] == {
        "expected": "postgresql", "observed": "sqlite",
    }


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
    assert retry.payload["retry_evidence"]["reason"] == "artifact is locally generatable"


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


def test_event_is_append_only(control):
    run_id = make_run(control)
    control.event(run_id, "ONE", {"x": 1})
    control.event(run_id, "TWO", {"x": 2})
    assert [event["event_type"] for event in control.list_events(run_id)] == ["ONE", "TWO"]


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
