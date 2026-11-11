"""V15 운영 단계(tmp 사본) — 수집·identity·제외·해소·A5 마감·계획·health·상태·원자 쓰기 (spec_U3 §8 P1~P17).

모든 쓰기는 tmp_path 사본 저장소에만 한다. 네트워크 0. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v8.contracts import canonical_hash
from ai_fc.timeseries_v15 import pipeline as p
from ai_fc.timeseries_v15.contracts import ATTEMPTS_LEDGER, ISSUANCE_LEDGER, RESOLUTION_LEDGER, SHADOW_LEDGER
from ai_fc.timeseries_v15.plan import plan_run
from v15_coherence_fixtures import (
    make_root, nasdaq_observations, set_track_open, stage_payload, v8_row, write_stage, write_v8_rows,
)

ARMS5 = ["A0", "A1", "A2", "A3", "A4"]
COLLECT_NOW = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)


@pytest.fixture()
def opened(tmp_path: Path):
    root = make_root(tmp_path, track_open=True)
    reference = v8_row("2026-11-06", "2026-11-10T11:04:48+00:00")
    write_v8_rows(root, [reference])
    return root, reference, tmp_path / "staging"


def _stage_all(root, reference, staging, **overrides) -> None:
    for arm in ARMS5:
        kwargs = overrides.get(arm, {})
        if kwargs is None:
            continue
        write_stage(staging, arm, stage_payload(root, arm, reference, **kwargs))


def _collect(root, reference, staging, now=COLLECT_NOW):
    return p.collect_staged(root, staging=staging, expected_arms=ARMS5, v8_forecast_id=reference["forecast_id"], now=now)


def test_p1_collect_identity_pass_appends_five_rows_in_order(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging)
    result = _collect(root, reference, staging)
    assert result["identity"]["status"] == "PASS" and result["appended"] == ARMS5
    rows = p.read_ledger(root, SHADOW_LEDGER)
    assert [row["arm"] for row in rows] == ARMS5
    for row in rows:
        for key in ("runtime_manifest", "exchange_calendars_version", "calendar_hash", "snapshot_method",
                    "post_dated", "issued_at", "kernel_code_hash", "seed"):
            assert key in row
        assert row["excluded_reasons"] == []
        assert row["post_dated"]["1"] is True and row["post_dated"]["63"] is False
    assert rows[0]["identity_vs_v8"]["status"] == "PASS"
    assert p.verify_v15(root)["ok"] is True


def test_p2_identity_failure_excludes_all_arms_but_rows_commit(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging, A0={"shift": 2e-12})
    result = _collect(root, reference, staging)
    assert result["identity"]["status"] == "FAIL"
    rows = p.read_ledger(root, SHADOW_LEDGER)
    assert len(rows) == 5 and all(row["excluded_reasons"] == ["a0_identity_fail"] for row in rows)
    attempts = p.read_ledger(root, ATTEMPTS_LEDGER)
    assert [row["kind"] for row in attempts] == ["a0_identity_fail"]
    assert p.verify_v15(root)["ok"] is True  # identity 는 무결성이 아니다


def test_p3_recollect_skips_existing_forecast_ids(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging)
    _collect(root, reference, staging)
    again = _collect(root, reference, staging, now=COLLECT_NOW + timedelta(hours=1))
    assert again["appended"] == [] and again["skipped"] == ARMS5
    assert len(p.read_ledger(root, SHADOW_LEDGER)) == 5


def test_p4_missing_arm_records_compute_failed(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging, A2=None)
    result = _collect(root, reference, staging)
    assert result["appended"] == ["A0", "A1", "A3", "A4"]
    kinds = [(row["arm"], row["kind"]) for row in p.read_ledger(root, ATTEMPTS_LEDGER)]
    assert kinds == [("A2", "compute_failed")]


def test_p5_missing_a0_excludes_all(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging, A0=None)
    _collect(root, reference, staging)
    rows = p.read_ledger(root, SHADOW_LEDGER)
    assert [row["arm"] for row in rows] == ["A1", "A2", "A3", "A4"]
    assert all(row["excluded_reasons"] == ["a0_missing"] for row in rows)


def test_p6_seed_mismatch_is_crn_violation(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging, A3={"seed": 999})
    _collect(root, reference, staging)
    rows = {row["arm"]: row for row in p.read_ledger(root, SHADOW_LEDGER)}
    assert rows["A3"]["excluded_reasons"] == ["crn_violation"] and rows["A1"]["excluded_reasons"] == []


def test_p7_kernel_drift_refused_and_verify_fails_on_changed_kernel(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging, A4={"kernel": "0" * 64})
    result = _collect(root, reference, staging)
    assert "A4" not in result["appended"]
    assert [(r["arm"], r["kind"]) for r in p.read_ledger(root, ATTEMPTS_LEDGER)] == [("A4", "kernel_hash_drift")]
    kernel = root / "src/ai_fc/timeseries_v15/vol.py"
    kernel.write_text(kernel.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8", newline="\n")
    verdict = p.verify_v15(root)
    assert verdict["ok"] is False and any("kernel_code_hash" in error for error in verdict["errors"])


def _a5_payload(root, reference) -> dict:
    payload = stage_payload(root, "A5", reference)
    payload.pop("content_hash")
    payload.update({"v8_forecast_id": None, "snapshot_method": "main_at_issue",
                    "issuance": {"next_session": "2026-11-09", "deadline_utc": "2026-11-09T14:25:00+00:00",
                                 "expected_origin": "2026-11-06",
                                 "tail_rows_structural": ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"],
                                 "tail_rows_asof": ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"],
                                 "dollar_last_obs_asof": "2026-10-30"}})
    payload["content_hash"] = canonical_hash(payload)
    return payload


def test_p8_a5_deadline(opened, tmp_path: Path) -> None:
    root, reference, staging = opened
    write_stage(staging, "A5", _a5_payload(root, reference))
    deadline = datetime(2026, 11, 9, 14, 25, tzinfo=timezone.utc)
    late = p.collect_a5(root, staging=staging, now=deadline + timedelta(seconds=1))
    assert late["appended"] is False and late["status"] == "a5_deadline_missed"
    assert p.read_ledger(root, ISSUANCE_LEDGER) == []
    assert [row["kind"] for row in p.read_ledger(root, ATTEMPTS_LEDGER)] == ["a5_deadline_missed"]
    early = p.collect_a5(root, staging=staging, now=deadline - timedelta(seconds=1))
    assert early["appended"] is True
    row = p.read_ledger(root, ISSUANCE_LEDGER)[0]
    assert row["issuance"]["issued_before_open"] is True and row["v8_forecast_id"] is None
    assert row["post_dated"]["1"] is False  # A5 h1 은 prospective
    again = p.collect_a5(root, staging=staging, now=deadline - timedelta(seconds=1))
    assert again["appended"] is False


def test_p9_resolve_scores_matured_horizons(opened) -> None:
    from ai_fc.timeseries.backtest import sample_crps
    from ai_fc.timeseries_v15.labels import pit_mid

    root, reference, staging = opened
    _stage_all(root, reference, staging)
    _collect(root, reference, staging)
    observations = nasdaq_observations("2026-10-01", "2026-11-16", step=0.002)
    result = p.resolve_v15(root, now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc), observations=observations)
    assert result["resolved"] == 10  # h1(11-09)·h5(11-13) × 5팔
    for row in p.read_ledger(root, RESOLUTION_LEDGER):
        forecast = next(f for f in p.read_ledger(root, SHADOW_LEDGER) if f["forecast_id"] == row["forecast_id"])
        grid = np.asarray(forecast["horizons"][str(row["horizon"])]["quantile_grid"])
        assert abs(row["crps_model"] - float(sample_crps(grid, row["y"]))) <= 1e-12
        assert row["pit"] == pit_mid(grid, row["y"])
        assert row["cov80"] == bool(grid[20] <= row["y"] <= grid[180])
        assert row["calendar_hash"] == forecast["calendar_hash"] and row["label_basis"] == "xnas_v1"
        assert abs(row["y"] - 0.002 * row["horizon"]) <= 1e-12


def test_p10_p14_plan_targets_snapshot_and_catch_up_window(tmp_path: Path) -> None:
    root = make_root(tmp_path, track_open=True)
    rows = [v8_row(origin, cutoff, number=n) for n, (origin, cutoff) in enumerate((
        ("2026-10-23", "2026-10-27T03:10:00+00:00"),
        ("2026-10-30", "2026-11-03T11:00:00+00:00"),
        ("2026-11-06", "2026-11-10T11:04:48+00:00")))]
    write_v8_rows(root, rows)
    calls: list = []

    def runner(args):
        calls.append(list(args))
        return "b" * 40

    now = datetime(2026, 11, 10, 14, 15, tzinfo=timezone.utc)
    scheduled = plan_run(root, event="schedule", schedule="15 14 * * 2-6", now=now, git_runner=runner)
    assert scheduled["pending"] is True and scheduled["v8_forecast_id"] == rows[2]["forecast_id"]
    assert scheduled["arms"] == ARMS5 and scheduled["snapshot_sha"] == "b" * 40
    assert calls[-1] == ["rev-list", "-1", "--first-parent", "--before=2026-11-10T11:04:48+00:00", "origin/main"]
    staging = tmp_path / "staging"
    for arm in ARMS5:
        write_stage(staging, arm, stage_payload(root, arm, rows[2]))
    result = p.collect_staged(root, staging=staging, expected_arms=ARMS5, v8_forecast_id=rows[2]["forecast_id"],
                              now=now)
    assert result["gaps_recorded"] == 5  # 창 밖(3번째 이전) 원점 10-23 의 5팔 — 계산하지 않음
    gaps = [row for row in p.read_ledger(root, ATTEMPTS_LEDGER) if row["kind"] == "gap_outside_catchup"]
    assert {row["origin"] for row in gaps} == {"2026-10-23"}
    assert p.record_catch_up_gaps(root, contract=p.load_contract_v15(root), now=now) == 0  # 1회만
    # P14: 같은 상태 — schedule 은 직전 원점(10-30)까지, workflow_dispatch(auto)는 최신 원점만
    scheduled = plan_run(root, event="schedule", schedule="15 14 * * 2-6", now=now, git_runner=runner)
    assert scheduled["pending"] is True and scheduled["v8_forecast_id"] == rows[1]["forecast_id"]
    dispatched = plan_run(root, event="workflow_dispatch", mode="auto", now=now, git_runner=runner)
    assert dispatched["pending"] is False
    run = plan_run(root, event="workflow_run", now=now, git_runner=runner)
    assert run["v8_forecast_id"] == rows[1]["forecast_id"]


def _write_a0_rows(root: Path, statuses: list[tuple[str, str]]) -> None:
    contract = p.load_contract_v15(root)
    kernel = contract["fork"]["frozen_kernel_code_hash"]
    for origin, status in statuses:
        body = {"forecast_id": f"tsv15-A0-{origin}", "arm": "A0", "origin": origin, "v8_forecast_id": f"v8-{origin}",
                "kernel_code_hash": kernel, "contract_hash": p.frozen_hash(contract),
                "issued_at": f"{origin}T00:00:00+00:00",
                "excluded_reasons": ["a0_identity_fail"] if status == "FAIL" else []}
        p._chain_append(root, SHADOW_LEDGER, body, key="forecast_id")


def test_p11_identity_streak_health_after_commit(tmp_path: Path) -> None:
    root = make_root(tmp_path, track_open=True)
    _write_a0_rows(root, [("2026-11-20", "FAIL"), ("2026-11-27", "FAIL"), ("2026-12-04", "FAIL")])
    assert p.verify_v15(root)["ok"] is True
    health = p.health_v15(root)
    assert health["identity_streak"] is True and health["alert"] is True
    before = (root / SHADOW_LEDGER).read_bytes()
    p.ack_identity_streak(root, reason="스냅숏 경합 확인", now=datetime(2026, 12, 9, tzinfo=timezone.utc))
    assert p.health_v15(root)["alert"] is False
    assert (root / SHADOW_LEDGER).read_bytes() == before  # ack 는 제외 행을 바꾸지 않는다
    other = make_root(tmp_path / "second", track_open=True)
    _write_a0_rows(other, [("2026-11-20", "FAIL"), ("2026-11-27", "FAIL"), ("2026-12-04", "FAIL"),
                           ("2026-12-11", "PASS")])
    assert p.health_v15(other)["alert"] is False  # PASS 1회로 자동 해제


def test_p12_status_has_counts_only(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging)
    _collect(root, reference, staging)
    payload = p.write_status(root)
    text = json.dumps(payload, ensure_ascii=False)
    for forbidden in ('"mean_d"', '"ci90"', '"delta_rel"', '"crps_model"', '"p"'):
        assert forbidden not in text
    assert payload["counts"]["shadow_forecasts"] == 5
    assert set(payload["families"]) == {"superiority", "noninferiority"}


def test_p13_calendar_drift_excluded_and_health_warns(opened) -> None:
    from ai_fc.timeseries_v15 import verdict as v

    root, reference, staging = opened
    _stage_all(root, reference, staging)
    _collect(root, reference, staging)
    rows = p.read_ledger(root, SHADOW_LEDGER)
    for row in rows:
        body = {"resolution_id": f"{row['forecast_id']}-h5-xnas_v1", "forecast_id": row["forecast_id"], "horizon": 5,
                "label_basis": "xnas_v1", "crps_model": 0.01, "resolved_at": "2026-11-14T03:10:00+00:00",
                "calendar_hash": "drifted" if row["arm"] == "A1" else row["calendar_hash"], "supersedes": None}
        p._chain_append(root, RESOLUTION_LEDGER, body, key="resolution_id")
    candidates = v.build_candidate_pairs(rows, [], p.read_ledger(root, RESOLUTION_LEDGER))
    stats = v._pairs_at_cut(candidates[("A1", 5)], v.parse_utc("2027-01-01T00:00:00Z"))
    assert stats["calendar_drift"] == 1 and stats["d"] == []
    assert len(v._pairs_at_cut(candidates[("A2", 5)], v.parse_utc("2027-01-01T00:00:00Z"))["d"]) == 1
    health = p.health_v15(root)
    assert health["alert"] is False and any("calendar_drift" in warning for warning in health["warnings"])


def _identity_stage(path: Path, status: str, computed_at: str) -> Path:
    payload = {"schema_version": 1, "kind": "v15_a0_live_identity_attempt", "v8_forecast_id": "v8-x",
               "v8_origin": "2026-11-06", "status": status, "max_abs_diff": 0.0, "mismatched_fields": [],
               "computed_at": computed_at}
    payload["content_hash"] = canonical_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_p15_identity_attempt_files_are_write_once_and_drive_identity_due(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_v8_rows(root, [v8_row("2026-11-06", "2026-11-10T11:04:48+00:00")])
    runner = lambda args: "c" * 40  # noqa: E731
    assert plan_run(root, mode="a0_identity", git_runner=runner)["identity_due"] is True
    first = p.record_identity_attempt(root, staged=_identity_stage(tmp_path / "s1.json", "FAIL", "2026-11-12T01:00:00+00:00"))
    assert first["written"].endswith("a0_live_identity_2026-11-06_a1.json")
    snapshot = (root / first["written"]).read_bytes()
    assert plan_run(root, mode="a0_identity", git_runner=runner)["identity_due"] is True
    second = p.record_identity_attempt(root, staged=_identity_stage(tmp_path / "s2.json", "PASS", "2026-11-12T03:00:00+00:00"))
    assert second["written"].endswith("_a2.json") and (root / first["written"]).read_bytes() == snapshot
    assert plan_run(root, mode="a0_identity", git_runner=runner)["identity_due"] is False
    assert plan_run(root, mode="mde_replay", git_runner=runner)["identity_due"] is False  # mde_v1 유무와 무관
    assert p.verify_v15(root)["ok"] is True


def test_p16_mde_summary_is_all_or_nothing(tmp_path: Path) -> None:
    from ai_fc.timeseries_v15.contracts import TimeSeriesV15ContractError
    from ai_fc.timeseries_v15.mde import MDE_ARMS, write_mde_prereg

    root = make_root(tmp_path)
    staging = tmp_path / "mde"
    staging.mkdir()
    for arm in MDE_ARMS[:-1]:
        payload = {"arm": arm, "rows": [], "kernel_code_hash": "k", "data_snapshot_sha": "s"}
        payload["content_hash"] = canonical_hash(payload)
        (staging / f"mde_{arm}.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TimeSeriesV15ContractError):
        write_mde_prereg(root, staging=staging, trials=5)
    prereg = root / "data/timeseries_v15/prereg"
    assert sorted(path.name for path in prereg.iterdir()) == ["fork_patch_v1.json"]
    (prereg / "mde_replay_A0.json").write_text("{}", encoding="utf-8")
    with pytest.raises(TimeSeriesV15ContractError):
        write_mde_prereg(root, staging=staging, trials=5)


def test_p17_first_origin_not_before_rule() -> None:
    rows = [
        {"origin": "2026-11-20", "knowledge_cutoff": "2026-11-24T11:00:00+00:00"},
        {"origin": "2026-11-27", "knowledge_cutoff": "2026-12-01T11:00:00+00:00"},
        {"origin": "2026-11-13", "knowledge_cutoff": "2026-11-17T11:00:00+00:00"},
    ]
    # r3 머지가 11-20(금) 뒤·V8 행(11-24 화) 앞이면 원점 11-20 이 첫 원점(원점은 T_r3 이전 금요일)
    assert p.first_origin_not_before(rows, r3_committed_at="2026-11-22T05:00:00Z") == "2026-11-20"
    assert p.first_origin_not_before(rows, r3_committed_at="2026-11-24T12:00:00Z") == "2026-11-27"
    assert p.first_origin_not_before(rows, r3_committed_at="2026-12-02T00:00:00Z") is None


# ── 리뷰 반영(w1-u3 fix) ─────────────────────────────────────────────────────


def _plan_next_day(root):
    return plan_run(root, event="schedule", schedule="15 14 * * 2-6", mode="auto",
                    now=COLLECT_NOW + timedelta(days=1), git_runner=lambda args: "a" * 40)


def test_p18_single_arm_retry_inherits_ledger_a0_pass(opened) -> None:
    """차단 B2: A0 PASS 뒤 실패 팔만 재시도하면 그 행은 제외 없이 쌍이 된다(a0_missing 금지)."""
    root, reference, staging = opened
    _stage_all(root, reference, staging, A2=None)
    _collect(root, reference, staging)
    plan = _plan_next_day(root)
    assert plan["pending"] is True and plan["arms"] == ["A2"]
    retry = staging.parent / "retry"
    write_stage(retry, "A2", stage_payload(root, "A2", reference))
    result = p.collect_staged(root, staging=retry, expected_arms=plan["arms"], v8_forecast_id=reference["forecast_id"],
                              now=COLLECT_NOW + timedelta(days=1))
    assert result["appended"] == ["A2"] and result["a0_source"] == "ledger"
    assert result["identity"]["status"] == "PASS"
    rows = {row["arm"]: row["excluded_reasons"] for row in p.read_ledger(root, SHADOW_LEDGER)}
    assert rows == {"A0": [], "A1": [], "A2": [], "A3": [], "A4": []}
    kinds = [(row["arm"], row["kind"]) for row in p.read_ledger(root, ATTEMPTS_LEDGER)]
    assert kinds == [("A2", "compute_failed")]  # a0_missing 행 없음
    assert _plan_next_day(root)["pending"] is False
    assert p.verify_v15(root)["ok"] is True


def test_p19_single_arm_retry_inherits_identity_fail_and_ledger_seed(opened) -> None:
    root, reference, staging = opened
    _stage_all(root, reference, staging, A0={"shift": 2e-12}, A2=None, A3=None)
    _collect(root, reference, staging)
    retry = staging.parent / "retry"
    write_stage(retry, "A2", stage_payload(root, "A2", reference))
    write_stage(retry, "A3", stage_payload(root, "A3", reference, seed=999))  # 원장 A0 시드(1234)와 다름
    result = p.collect_staged(root, staging=retry, expected_arms=["A2", "A3"], v8_forecast_id=reference["forecast_id"],
                              now=COLLECT_NOW + timedelta(days=1))
    assert result["appended"] == ["A2", "A3"] and result["attempts"] == []
    rows = {row["arm"]: row["excluded_reasons"] for row in p.read_ledger(root, SHADOW_LEDGER)}
    assert rows["A2"] == ["a0_identity_fail"]
    assert rows["A3"] == ["a0_identity_fail", "crn_violation"]
    kinds = [row["kind"] for row in p.read_ledger(root, ATTEMPTS_LEDGER)]
    assert kinds.count("a0_identity_fail") == 1 and "a0_missing" not in kinds


def test_p20_late_a0_does_not_rewrite_earlier_a0_missing_rows(opened) -> None:
    """역방향(공시 한계): A0 만 늦게 성공해도 먼저 쓰인 팔 행의 a0_missing 은 append-only 라 남는다."""
    root, reference, staging = opened
    _stage_all(root, reference, staging, A0=None)
    _collect(root, reference, staging)
    retry = staging.parent / "retry"
    write_stage(retry, "A0", stage_payload(root, "A0", reference))
    result = p.collect_staged(root, staging=retry, expected_arms=["A0"], v8_forecast_id=reference["forecast_id"],
                              now=COLLECT_NOW + timedelta(days=1))
    assert result["appended"] == ["A0"] and result["a0_source"] == "staging"
    rows = {row["arm"]: row["excluded_reasons"] for row in p.read_ledger(root, SHADOW_LEDGER)}
    assert rows["A0"] == [] and rows["A1"] == ["a0_missing"]


def test_p21_track_open_requires_r3_preconditions(tmp_path: Path) -> None:
    """비차단 1: track_open true 면 로더가 첫 원점·MDE 기입·mde_v1 핀·identity PASS·armed 를 요구한다."""
    from ai_fc.timeseries_v15.contracts import TimeSeriesV15ContractError, load_contract_v15

    bare = make_root(tmp_path / "bare")
    set_track_open(bare, True, preconditions=False)
    with pytest.raises(TimeSeriesV15ContractError) as caught:
        load_contract_v15(bare)
    message = str(caught.value)
    for fragment in ("first_origin_not_before", "mde.status", "mde_v1.json", "a0_live_identity", "gates.armed"):
        assert fragment in message, fragment
    assert p.verify_v15(bare)["ok"] is False
    good = make_root(tmp_path / "good", track_open=True)
    assert load_contract_v15(good)["live"]["first_origin_not_before"] == "2026-01-02"
    summary = good / "data/timeseries_v15/prereg/mde_v1.json"
    summary.write_text(summary.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(TimeSeriesV15ContractError, match="summary_sha256"):
        load_contract_v15(good)
    failing = make_root(tmp_path / "failing", track_open=True)
    later = {"schema_version": 1, "kind": "v15_a0_live_identity_attempt", "v8_forecast_id": "v8-x",
             "v8_origin": "2026-01-09", "status": "FAIL", "max_abs_diff": 1.0, "mismatched_fields": ["origin"],
             "computed_at": "2026-01-13T00:00:00+00:00"}
    later["content_hash"] = canonical_hash(later)
    target = failing / "data/timeseries_v15/prereg/a0_live_identity_2026-01-09_a1.json"
    target.write_text(json.dumps(later), encoding="utf-8")
    with pytest.raises(TimeSeriesV15ContractError, match="a0_live_identity"):
        load_contract_v15(failing)


def test_p22_verify_pins_contract_hash_after_live_rows(opened) -> None:
    """비차단 2: 라이브 행 뒤 r3 허용 키(first_origin_not_before)를 바꿔도 rule_hash 는 같지만 verify 가 잡는다."""
    root, reference, staging = opened
    _stage_all(root, reference, staging)
    _collect(root, reference, staging)
    assert p.verify_v15(root)["ok"] is True
    path = root / "data/contracts/multivariate_timeseries_v15_coherence.yaml"
    text = path.read_text(encoding="utf-8")
    old = "first_origin_not_before: '2026-01-02'"
    assert text.count(old) == 1
    path.write_text(text.replace(old, "first_origin_not_before: '2026-11-06'"), encoding="utf-8", newline="\n")
    p.load_contract_v15(root)  # rule_hash 는 그대로(허용 목록)
    verdict = p.verify_v15(root)
    assert verdict["ok"] is False and any("contract_hash" in error for error in verdict["errors"])


def test_p23_identity_tolerance_comes_from_contract(opened, monkeypatch) -> None:
    """비차단 4: identity 허용오차는 계약 arms.A0.identity_tolerance 값 — 코드 상수와 다르면 verify 실패."""
    root, reference, staging = opened
    _stage_all(root, reference, staging)
    result = _collect(root, reference, staging)
    assert result["identity"]["tolerance"] == 1e-12
    assert p.contract_identity_tolerance(p.load_contract_v15(root)) == p.IDENTITY_TOLERANCE
    monkeypatch.setattr(p, "IDENTITY_TOLERANCE", 1e-9)
    verdict = p.verify_v15(root)
    assert verdict["ok"] is False and any("identity_tolerance" in error for error in verdict["errors"])


def test_p24_a5_source_delay_is_origin_unavailable_and_scheduled_retry_skips(opened) -> None:
    """비차단 3: 월요일 원천 지연으로 원점이 목요일이면 a5_origin_unavailable(마감 검사보다 먼저),
    06:40Z 예약 재시도는 같은 ISO 주 기록이 있으면 건너뛴다. 수동 a5_issue 는 허용."""
    root, reference, staging = opened
    payload = _a5_payload(root, reference)
    payload.pop("content_hash")
    payload.update({"origin": "2026-11-05", "iso_week": "2026-W45"})
    payload["content_hash"] = canonical_hash(payload)
    write_stage(staging, "A5", payload)
    monday = datetime(2026, 11, 9, 5, 20, tzinfo=timezone.utc)  # 03:40Z 계산 뒤, 마감(14:25Z) 전
    result = p.collect_a5(root, staging=staging, now=monday)
    assert result["status"] == "a5_origin_unavailable"
    assert [row["kind"] for row in p.read_ledger(root, ATTEMPTS_LEDGER)] == ["a5_origin_unavailable"]

    def runner(args):
        return "a" * 40

    at_0640 = datetime(2026, 11, 9, 6, 40, tzinfo=timezone.utc)
    retry = plan_run(root, event="schedule", schedule="40 6 * * 1", now=at_0640, git_runner=runner)
    assert retry["a5_due"] is False and "a5_origin_unavailable_this_iso_week" in retry["reasons"]
    manual = plan_run(root, event="workflow_dispatch", mode="a5_issue", now=at_0640, git_runner=runner)
    assert manual["a5_due"] is True
