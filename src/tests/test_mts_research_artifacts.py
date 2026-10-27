"""mts_research 원자 발행·체인·CAS·복구 테스트 — T47·T51·T52·T57·T58·T60.

전부 합성 tmp_path 루트. 실제 원장은 건드리지 않는다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ai_fc.mts_research import artifacts
from ai_fc.mts_research.artifacts import (
    ATTEMPT_LEDGER,
    FORECAST_LEDGER,
    MtsArtifactError,
    append_event,
    artifact_id,
    commit_forecast,
    fail_attempt,
    logical_forecast_key,
    read_chain,
    recover,
    start_attempt,
    update_latest_pointer,
    write_immutable_json,
)
from mts_research_fixtures import make_ready_draft, make_spec, utc


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "data/mts_research/ledgers").mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
# 체인 append
# ---------------------------------------------------------------------------


def test_chain_append_idempotent_and_collision(tmp_path: Path):
    root = _root(tmp_path)
    rel = artifacts.EVENT_LEDGER
    row1 = append_event(root, rel, {"event_id": "e1", "value": 1})
    again = append_event(root, rel, {"event_id": "e1", "value": 1})
    assert again == row1  # 동일 바이트 재append 는 no-op
    with pytest.raises(MtsArtifactError):
        append_event(root, rel, {"event_id": "e1", "value": 2})  # 충돌
    row2 = append_event(root, rel, {"event_id": "e2", "value": 2})
    assert row2["previous_hash"] == row1["content_hash"]
    assert len(read_chain(root, rel)) == 2


def test_chain_tamper_detected(tmp_path: Path):
    root = _root(tmp_path)
    rel = artifacts.EVENT_LEDGER
    append_event(root, rel, {"event_id": "e1", "value": 1})
    append_event(root, rel, {"event_id": "e2", "value": 2})
    path = root / rel
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["value"] = 999
    lines[0] = json.dumps(tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(MtsArtifactError):
        read_chain(root, rel)


def test_writer_assigns_hashes(tmp_path: Path):
    root = _root(tmp_path)
    with pytest.raises(MtsArtifactError):
        append_event(root, artifacts.EVENT_LEDGER, {"event_id": "e1", "content_hash": "x"})


# ---------------------------------------------------------------------------
# T60 — issued_at 은 commit 에서만; T57 — 실패는 FAILED + 사유
# ---------------------------------------------------------------------------


def _commit(root: Path, *, now, run_id="run-1", draft=None, started=None,
            evidence_track="historical_research", reconstruction_of=None):
    draft = draft or make_ready_draft()
    started = started or start_attempt(
        root,
        attempt_id=f"att-{run_id}",
        attempted_at=now,
        intended_origin_session=draft.spec.origin_session,
        contract_hash="ch",
        stage="forecast",
    )
    return commit_forecast(
        root,
        draft,
        started=started,
        now=now,
        experiment_id="exp-1",
        run_id=run_id,
        evidence_track=evidence_track,
        replay_mode="historical_information_set_reconstruction",
        contract_hash="ch",
        issuance_policy_id="first_issue_v1",
        model_version="mts.synthetic.1",
        reconstruction_of_forecast_id=reconstruction_of,
    )


def test_t60_issued_only_at_commit(tmp_path: Path):
    root = _root(tmp_path)
    draft = make_ready_draft()
    assert read_chain(root, FORECAST_LEDGER) == []  # draft 계산만으로는 ISSUED 없음
    now = utc(2026, 10, 21, 9)
    artifact = _commit(root, now=now, draft=draft)
    rows = read_chain(root, FORECAST_LEDGER)
    assert len(rows) == 1
    assert rows[0]["status"] == "ISSUED"
    from datetime import datetime

    assert datetime.fromisoformat(rows[0]["issued_at"].replace("Z", "+00:00")) == now
    assert artifact.issued_at == now


def test_t57_failed_attempt_leaves_no_artifact(tmp_path: Path):
    root = _root(tmp_path)
    now = utc(2026, 10, 21, 9)
    started = start_attempt(
        root,
        attempt_id="att-fail",
        attempted_at=now,
        intended_origin_session=date(2026, 10, 20),
        contract_hash="ch",
        stage="snapshot",
    )
    fail_attempt(root, started, attempted_at=now, reason_codes=("DATA_INVALID",))
    attempts = read_chain(root, ATTEMPT_LEDGER)
    assert [row["status"] for row in attempts] == ["STARTED", "FAILED"]
    assert attempts[1]["reason_codes"] == ["DATA_INVALID"]
    assert read_chain(root, FORECAST_LEDGER) == []
    # 종결된 attempt 로는 commit 불가
    with pytest.raises(MtsArtifactError):
        _commit(root, now=now, started=started)


def test_hold_draft_commits_without_payload(tmp_path: Path):
    """HOLD 는 수치 0 없이 사유만 가진 artifact 로 발행된다 (§17.3-3)."""
    root = _root(tmp_path)
    from ai_fc.mts_research.records import ForecastDraft

    hold = ForecastDraft(
        model_id="m",
        spec=make_spec(),
        state_id=None,
        calibration_state_id=None,
        prediction_status="HOLD",
        payload_ref=None,
        payload_hash=None,
        capabilities=(),
        reason_codes=("DFM_NOT_CONVERGED",),
    )
    artifact = _commit(root, now=utc(2026, 10, 21, 9), draft=hold)
    assert artifact.status == "HOLD" and artifact.payload_ref is None


# ---------------------------------------------------------------------------
# T47 / T58 — 논리 키 vs 저장 ID
# ---------------------------------------------------------------------------


def test_t47_t58_logical_key_stable_artifact_id_distinct(tmp_path: Path):
    root = _root(tmp_path)
    now = utc(2026, 10, 21, 9)
    live = _commit(root, now=now, run_id="run-live")
    recon = _commit(
        root,
        now=utc(2026, 10, 25, 9),
        run_id="run-recon",
        evidence_track="legacy_reproduction",
        reconstruction_of=live.forecast_id,
    )
    # 같은 논리 키 (중복 표본 차단의 축) — 저장 ID 는 서로 다름 (저장 충돌 없음)
    assert live.logical_forecast_key == recon.logical_forecast_key
    assert live.forecast_id != recon.forecast_id
    assert recon.reconstruction_of_forecast_id == live.forecast_id
    rows = read_chain(root, FORECAST_LEDGER)
    assert len(rows) == 2
    distinct_logical = {row["logical_forecast_key"] for row in rows}
    assert len(distinct_logical) == 1  # 독립 표본 수는 1 (T47/T58)


def test_legacy_reproduction_requires_original_reference(tmp_path: Path):
    root = _root(tmp_path)
    with pytest.raises(MtsArtifactError):
        _commit(root, now=utc(2026, 10, 21, 9), evidence_track="legacy_reproduction")


def test_artifact_id_axes():
    base = dict(
        evidence_track="historical_research",
        replay_mode="operational_replay",
        experiment_id="e",
        run_id="r",
        payload_hash="p",
    )
    assert artifact_id(**base) != artifact_id(**{**base, "run_id": "r2"})
    assert artifact_id(**base) == artifact_id(**base)


# ---------------------------------------------------------------------------
# T51 — crash 복구 / 불완전 commit 비노출
# ---------------------------------------------------------------------------


def test_t51_recover_incomplete_attempts(tmp_path: Path):
    root = _root(tmp_path)
    now = utc(2026, 10, 21, 9)
    start_attempt(
        root,
        attempt_id="att-crash",
        attempted_at=now,
        intended_origin_session=date(2026, 10, 20),
        contract_hash="ch",
        stage="snapshot",
    )
    recovered = recover(root, now=utc(2026, 10, 21, 10))
    assert len(recovered) == 1
    assert recovered[0]["reason_codes"] == ["RECOVERED_INCOMPLETE_ATTEMPT"]
    assert recover(root, now=utc(2026, 10, 21, 11)) == []  # idempotent
    assert read_chain(root, FORECAST_LEDGER) == []


def test_t51_interrupted_immutable_write_not_exposed(tmp_path: Path):
    """tmp 파일 단계 crash 는 대상 경로를 오염시키지 않는다."""
    root = _root(tmp_path)
    rel = Path("data/mts_research/experiments/exp-1/run-1/out.json")
    # crash 시뮬레이션: tmp 만 남은 상태
    target = root / rel
    target.parent.mkdir(parents=True)
    target.with_suffix(".json.tmp").write_text("partial", encoding="utf-8")
    assert not target.is_file()
    write_immutable_json(root, rel, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    with pytest.raises(MtsArtifactError):
        write_immutable_json(root, rel, {"ok": False})  # 불변 충돌


# ---------------------------------------------------------------------------
# T52 — latest pointer CAS
# ---------------------------------------------------------------------------


def test_t52_stale_job_cannot_roll_back_pointer(tmp_path: Path):
    root = _root(tmp_path)
    rel = Path("data/mts_research/derived/latest_pointer.json")
    newer = {"origin_session": "2026-10-21", "issued_at": "2026-10-21T09:00:00+00:00", "v": 2}
    older = {"origin_session": "2026-10-20", "issued_at": "2026-10-20T09:00:00+00:00", "v": 1}
    assert update_latest_pointer(root, rel, newer) is True
    assert update_latest_pointer(root, rel, older) is False  # 과거로 롤백 차단
    current = json.loads((root / rel).read_text(encoding="utf-8"))
    assert current["v"] == 2
    same_origin_later = {**newer, "issued_at": "2026-10-21T10:00:00+00:00", "v": 3}
    assert update_latest_pointer(root, rel, same_origin_later) is True


def test_pointer_must_stay_inside_namespace(tmp_path: Path):
    root = _root(tmp_path)
    with pytest.raises(MtsArtifactError):
        update_latest_pointer(
            root,
            Path("data/timeseries_v8/multivariate_v8_latest.json"),
            {"origin_session": "2026-10-21", "issued_at": "2026-10-21T09:00:00+00:00"},
        )
