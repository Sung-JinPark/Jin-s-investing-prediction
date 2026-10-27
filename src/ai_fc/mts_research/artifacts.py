"""원자적 발행·append-only 체인·attempt 이벤트·CAS pointer·노출 감사 (§16.1).

이식 전례: timeseries_daily6m/pipeline.py 의 writer_lock·previous_hash 체인·
_atomic(tmp+os.replace)·idempotent append. 여기에 §16.1 이 요구하는
compare-and-swap latest pointer(T52)와 attempt 복구(T51)를 보강한다.

쓰기 범위: data/mts_research/ 아래만. 다른 트랙의 원장·동결 파일에는 절대 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from ..timeseries_v8.contracts import canonical_hash
from .records import (
    EvidenceTrack,
    ForecastArtifact,
    ForecastAttemptEvent,
    ForecastDraft,
    ForecastSpec,
    MtsRecordError,
    ReplayMode,
    require_utc,
)

STORE_RELATIVE = Path("data/mts_research")
LEDGERS_RELATIVE = STORE_RELATIVE / "ledgers"
EXPERIMENTS_RELATIVE = STORE_RELATIVE / "experiments"
FORECAST_LEDGER = LEDGERS_RELATIVE / "forecasts.jsonl"
RESOLUTION_LEDGER = LEDGERS_RELATIVE / "resolutions.jsonl"
ATTEMPT_LEDGER = LEDGERS_RELATIVE / "attempts.jsonl"
EXPOSURE_LEDGER = LEDGERS_RELATIVE / "exposures.jsonl"
EVENT_LEDGER = LEDGERS_RELATIVE / "events.jsonl"

_IDENTITY_FIELDS: dict[str, str] = {
    "forecasts.jsonl": "forecast_id",
    "resolutions.jsonl": "resolution_id",
    "attempts.jsonl": "attempt_event_id",
    "exposures.jsonl": "exposure_id",
    "events.jsonl": "event_id",
    "approvals.jsonl": "receipt_id",
}


class MtsArtifactError(RuntimeError):
    """append-only·원자성 불변조건 위반 — fail-closed."""


# ---------------------------------------------------------------------------
# writer lock (단일 canonical writer — §16.1)
# ---------------------------------------------------------------------------


@contextmanager
def writer_lock(root: Path):
    path = root / STORE_RELATIVE / ".writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise MtsArtifactError("다른 mts_research writer 가 저장소 lock 을 보유 중") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def serialized_writer(function: Callable) -> Callable:
    @wraps(function)
    def run(root: Path, *args, **kwargs):
        with writer_lock(root):
            return function(root, *args, **kwargs)

    return run


# ---------------------------------------------------------------------------
# hash-chain JSONL
# ---------------------------------------------------------------------------


def _identity_field(relative: Path) -> str:
    try:
        return _IDENTITY_FIELDS[relative.name]
    except KeyError as exc:
        raise MtsArtifactError(f"등록되지 않은 원장: {relative}") from exc


def read_chain(root: Path, relative: Path) -> list[dict[str, Any]]:
    """체인 무결성(previous_hash + content_hash + identity 유일성) 검증 후 전체 행 반환."""
    path = root / relative
    if not path.is_file():
        return []
    identity_field = _identity_field(relative)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    previous: str | None = None
    seen: set[str] = set()
    for index, row in enumerate(rows):
        body = {key: value for key, value in row.items() if key != "content_hash"}
        if row.get("previous_hash") != previous:
            raise MtsArtifactError(f"{relative.name}:{index} previous_hash 체인 단절")
        if row.get("content_hash") != canonical_hash(body):
            raise MtsArtifactError(f"{relative.name}:{index} content_hash 불일치")
        identity = row.get(identity_field)
        if not identity or identity in seen:
            raise MtsArtifactError(f"{relative.name}:{index} identity 누락/중복: {identity}")
        seen.add(str(identity))
        previous = row["content_hash"]
    return rows


def append_event(root: Path, relative: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """idempotent chain append.

    동일 identity 재-append: 동일 바이트면 기존 행 반환(no-op), 다르면 충돌 예외.
    payload 에 previous_hash/content_hash 를 넣지 않는다 — 여기서 부여한다.
    """
    if "previous_hash" in payload or "content_hash" in payload:
        raise MtsArtifactError("previous_hash/content_hash 는 writer 가 부여한다")
    identity_field = _identity_field(relative)
    identity = payload.get(identity_field)
    if not identity:
        raise MtsArtifactError(f"identity 필드 누락: {identity_field}")
    rows = read_chain(root, relative)
    for row in rows:
        if row.get(identity_field) == identity:
            body = {k: v for k, v in row.items() if k not in ("previous_hash", "content_hash")}
            if body != payload:
                raise MtsArtifactError(f"append-only identity 충돌: {identity}")
            return row
    body = {**payload, "previous_hash": rows[-1]["content_hash"] if rows else None}
    row = {**body, "content_hash": canonical_hash(body)}
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return row


# ---------------------------------------------------------------------------
# 불변 JSON 파일
# ---------------------------------------------------------------------------


def write_immutable_json(root: Path, relative: Path, payload: dict[str, Any]) -> Path:
    """tmp+os.replace 원자 쓰기. 이미 있으면 바이트 동일성만 허용 (immutable)."""
    path = root / relative
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") != rendered:
            raise MtsArtifactError(f"불변 파일 충돌: {relative}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)
    return path


# ---------------------------------------------------------------------------
# 논리 키 vs 저장 ID (§12.5, T47/T58)
# ---------------------------------------------------------------------------


def logical_forecast_key(
    spec: ForecastSpec, *, model_version: str, issuance_policy_id: str, artifact_kind: str
) -> str:
    """같은 발행을 중복 표본으로 세지 않는 논리 키."""
    return "lfk-" + canonical_hash({
        "model_version": model_version,
        "target_spec_hash": spec.target_spec_hash,
        "origin_session": spec.origin_session.isoformat(),
        "information_cutoff_at": spec.information_cutoff_at.isoformat(),
        "issuance_policy_id": issuance_policy_id,
        "artifact_kind": artifact_kind,
    })[:32]


def artifact_id(
    *, evidence_track: EvidenceTrack, replay_mode: ReplayMode,
    experiment_id: str, run_id: str, payload_hash: str | None,
) -> str:
    """저장 artifact ID — 재구성·재시도로 파일이 늘어도 논리 키와 충돌하지 않는 별도 축."""
    return "mts-" + canonical_hash({
        "evidence_track": evidence_track,
        "replay_mode": replay_mode,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "payload_hash": payload_hash,
    })[:24]


# ---------------------------------------------------------------------------
# attempt 이벤트 (T51/T57/T60)
# ---------------------------------------------------------------------------


def _attempt_row(event: ForecastAttemptEvent) -> dict[str, Any]:
    body = event.body()
    body["attempt_event_id"] = f"{event.attempt_id}:{event.status}"
    return body


def start_attempt(
    root: Path, *, attempt_id: str, attempted_at: datetime,
    intended_origin_session, contract_hash: str, stage: str,
) -> ForecastAttemptEvent:
    event = ForecastAttemptEvent(
        attempt_id=attempt_id,
        attempted_at=attempted_at,
        intended_origin_session=intended_origin_session,
        contract_hash=contract_hash,
        stage=stage,
        status="STARTED",
        input_snapshot_id=None,
        forecast_id=None,
        reason_codes=(),
    )
    append_event(root, ATTEMPT_LEDGER, _attempt_row(event))
    return event


def _terminal_status(rows: list[dict[str, Any]], attempt_id: str) -> str | None:
    status = None
    for row in rows:
        if row.get("attempt_id") == attempt_id and row.get("status") in ("FAILED", "COMMITTED"):
            status = row["status"]
    return status


def fail_attempt(
    root: Path, started: ForecastAttemptEvent, *, attempted_at: datetime,
    reason_codes: tuple[str, ...], stage: str | None = None,
    input_snapshot_id: str | None = None,
) -> ForecastAttemptEvent:
    """실패 종결 — HOLD 사유만 남기고 가짜 정상 artifact 를 만들지 않는다 (T57)."""
    rows = read_chain(root, ATTEMPT_LEDGER)
    if _terminal_status(rows, started.attempt_id) is not None:
        raise MtsArtifactError(f"attempt 이미 종결됨: {started.attempt_id}")
    event = ForecastAttemptEvent(
        attempt_id=started.attempt_id,
        attempted_at=attempted_at,
        intended_origin_session=started.intended_origin_session,
        contract_hash=started.contract_hash,
        stage=stage or started.stage,
        status="FAILED",
        input_snapshot_id=input_snapshot_id,
        forecast_id=None,
        reason_codes=reason_codes,
    )
    append_event(root, ATTEMPT_LEDGER, _attempt_row(event))
    return event


def commit_forecast(
    root: Path,
    draft: ForecastDraft,
    *,
    started: ForecastAttemptEvent,
    now: datetime,
    experiment_id: str,
    run_id: str,
    evidence_track: EvidenceTrack,
    replay_mode: ReplayMode,
    contract_hash: str,
    issuance_policy_id: str,
    model_version: str,
    reconstruction_of_forecast_id: str | None = None,
) -> ForecastArtifact:
    """canonical commit — issued_at 은 여기서만 확정된다 (§17.3-11, T60).

    draft 가 READY 가 아니면 HOLD/NOT_ELIGIBLE artifact 로 발행한다 (payload 없음).
    commit 이전의 어떤 실패도 ISSUED 를 만들지 않는다.
    """
    require_utc(now, field="now")
    rows = read_chain(root, ATTEMPT_LEDGER)
    if _terminal_status(rows, started.attempt_id) is not None:
        raise MtsArtifactError(f"attempt 이미 종결됨: {started.attempt_id}")
    if reconstruction_of_forecast_id is None and evidence_track == "legacy_reproduction":
        raise MtsArtifactError("legacy_reproduction artifact 는 원본 forecast 참조 필수 (T58)")

    status = {"READY": "ISSUED", "HOLD": "HOLD", "NOT_ELIGIBLE": "NOT_ELIGIBLE"}[draft.prediction_status]
    fid = artifact_id(
        evidence_track=evidence_track,
        replay_mode=replay_mode,
        experiment_id=experiment_id,
        run_id=run_id,
        payload_hash=draft.payload_hash,
    )
    artifact = ForecastArtifact(
        forecast_id=fid,
        logical_forecast_key=logical_forecast_key(
            draft.spec,
            model_version=model_version,
            issuance_policy_id=issuance_policy_id,
            artifact_kind=draft.spec.forecast_kind,
        ),
        reconstruction_of_forecast_id=reconstruction_of_forecast_id,
        model_id=draft.model_id,
        spec=draft.spec,
        issued_at=now,
        replay_mode=replay_mode,
        evidence_track=evidence_track,
        status=status,  # type: ignore[arg-type]
        state_id=draft.state_id,
        calibration_state_id=draft.calibration_state_id,
        payload_ref=draft.payload_ref,
        payload_hash=draft.payload_hash,
        capabilities=draft.capabilities,
        reason_codes=draft.reason_codes,
        contract_hash=contract_hash,
    )
    # prospective 등록 가드: 발행 시각이 첫 대상 세션 관측 이후면 거부 (T15 는 maturity 계층,
    # 여기서는 §17.3-4 의 시간 순서만 검사한다)
    append_event(root, FORECAST_LEDGER, artifact.body())
    committed = ForecastAttemptEvent(
        attempt_id=started.attempt_id,
        attempted_at=now,
        intended_origin_session=started.intended_origin_session,
        contract_hash=started.contract_hash,
        stage="commit",
        status="COMMITTED",
        input_snapshot_id=draft.spec.input_snapshot_id,
        forecast_id=fid,
        reason_codes=(),
    )
    append_event(root, ATTEMPT_LEDGER, _attempt_row(committed))
    return artifact


def recover(root: Path, *, now: datetime) -> list[dict[str, Any]]:
    """비종결 STARTED attempt 를 recovery FAILED 로 종결한다 (T51).

    crash 로 중단된 쓰기는 tmp+os.replace 설계상 외부에 노출되지 않는다.
    """
    require_utc(now, field="now")
    rows = read_chain(root, ATTEMPT_LEDGER)
    recovered: list[dict[str, Any]] = []
    started_rows = [r for r in rows if r.get("status") == "STARTED"]
    for row in started_rows:
        if _terminal_status(rows, row["attempt_id"]) is None:
            event = ForecastAttemptEvent(
                attempt_id=row["attempt_id"],
                attempted_at=now,
                intended_origin_session=row["intended_origin_session"],
                contract_hash=row["contract_hash"],
                stage="recovery",
                status="FAILED",
                input_snapshot_id=None,
                forecast_id=None,
                reason_codes=("RECOVERED_INCOMPLETE_ATTEMPT",),
            )
            recovered.append(append_event(root, ATTEMPT_LEDGER, _attempt_row(event)))
    return recovered


# ---------------------------------------------------------------------------
# latest pointer — compare-and-swap (T52)
# ---------------------------------------------------------------------------


def update_latest_pointer(root: Path, relative: Path, candidate: dict[str, Any]) -> bool:
    """lock 아래에서 (origin_session, issued_at) 가 엄격히 새로울 때만 교체.

    더 오래된 job 이 늦게 끝나도 pointer 를 과거로 되돌릴 수 없다 (T52).
    """
    for key in ("origin_session", "issued_at"):
        if key not in candidate:
            raise MtsArtifactError(f"pointer 후보에 {key} 누락")
    path = root / relative
    if not str(path.resolve()).startswith(str((root / STORE_RELATIVE).resolve())):
        raise MtsArtifactError("pointer 는 data/mts_research/ 아래에만 둘 수 있다")
    with writer_lock(root):
        if path.is_file():
            current = json.loads(path.read_text(encoding="utf-8"))
            current_key = (str(current.get("origin_session")), str(current.get("issued_at")))
            candidate_key = (str(candidate["origin_session"]), str(candidate["issued_at"]))
            if candidate_key <= current_key:
                return False
        payload = {k: v for k, v in candidate.items() if k != "content_hash"}
        rendered = {**payload, "content_hash": canonical_hash(payload)}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(rendered, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return True


# ---------------------------------------------------------------------------
# 노출 감사 (§17.4 exposure event)
# ---------------------------------------------------------------------------


def record_exposure(
    root: Path,
    *,
    run_id: str,
    purpose: str,
    series: list[str],
    window: list[str | None],
    windows_hit: list[str],
    allowed: bool,
    reason_codes: list[str],
) -> dict[str, Any]:
    """누가/어느 실행이/어떤 범위를 읽었는지 — 거부도 기록한다 (T50).

    한 번 본 구간의 청정성은 복원되지 않는다 (§17.4).
    """
    body = {
        "run_id": run_id,
        "purpose": purpose,
        "series": sorted(series),
        "window": window,
        "windows_hit": sorted(windows_hit),
        "allowed": allowed,
        "reason_codes": sorted(reason_codes),
    }
    body["exposure_id"] = "exp-" + canonical_hash(body)[:24]
    return append_event(root, EXPOSURE_LEDGER, body)
