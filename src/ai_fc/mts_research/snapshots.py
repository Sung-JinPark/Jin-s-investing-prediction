"""§6.5 비동기 as-of snapshot + §6.7 manifest/cache key.

- 가용 시각 필터링 뒤 (series_id, observation_period) 별 최신 가용 판을 선택해
  **전체 과거 history 를 보존**한다. 계열당 최신 한 행만 남기면 lag·rolling 계산에
  필요한 이력이 사라진다 (§6.5). head 와 age 는 그 history 위에서 별도로 계산한다.
- snapshot_id 는 manifest 전체의 canonical_hash — 같은 데이터라도 code/policy/lock
  hash 가 바뀌면 키가 바뀐다 (T09).
- 입력 snapshot 과 outcome snapshot 은 kind 로 구분되는 다른 객체다. outcome 을
  feature 경로에 전달하면 타입 검사가 거부한다 (T14).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict

from ..timeseries_v8.contracts import canonical_hash
from .availability import AvailabilityEvent, LedgerCheckpoint, effective_available_at, visible_events
from .records import ReplayMode, require_utc
from .sessions import CalendarRef

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOTS_RELATIVE = Path("data/mts_research/snapshots")


class MtsSnapshotError(RuntimeError):
    """snapshot 불변조건 위반 — fail-closed."""


class HeadState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    series_id: str
    observation_period_end: str
    value: float | None
    revision_id: str
    age_since_observation_days: float
    age_since_publication_days: float | None  # 공개 증거 없으면 None — 승격 금지
    availability_precision: str


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    schema_version: int
    kind: Literal["input", "outcome"]
    replay_mode: ReplayMode
    information_cutoff_at: datetime
    ledger_checkpoint_id: str
    transaction_cutoff_at: datetime
    observation_revision_ids_hash: str
    raw_receipts_hash: str
    source_specs_hash: str
    availability_policy_hash: str
    target_contract_hash: str | None
    calendar_hash: str
    transform_code_hash: str
    environment_lock_hash: str
    series_heads: dict[str, HeadState]


class InputSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    manifest: SnapshotManifest
    history: tuple[AvailabilityEvent, ...]


class OutcomeSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    manifest: SnapshotManifest
    history: tuple[AvailabilityEvent, ...]


def assert_input_snapshot(obj: object) -> InputSnapshot:
    """feature 경로의 타입 가드 — outcome snapshot 유입 거부 (T14)."""
    if isinstance(obj, OutcomeSnapshot) or (
        isinstance(obj, InputSnapshot) and obj.manifest.kind != "input"
    ):
        raise MtsSnapshotError("outcome snapshot 을 feature 생성에 전달할 수 없다 (T14)")
    if not isinstance(obj, InputSnapshot):
        raise MtsSnapshotError(f"InputSnapshot 이 아니다: {type(obj).__name__}")
    return obj


def resolve_latest_visible_revision_per_period(
    visible: Iterable[AvailabilityEvent],
) -> list[AvailabilityEvent]:
    """(series_id, observation_period) 별 최신 가용 판 1행 — 전체 기간 이력 보존 (§6.5, T02·T06).

    정렬 키: (availability_upper_bound, revision_seq, revision_id) — 결정적 tie-break.
    """
    chosen: dict[tuple[str, str], AvailabilityEvent] = {}
    for event in visible:
        key = (event.series_id, event.observation_period_end)
        current = chosen.get(key)
        candidate_rank = (
            event.availability_upper_bound,
            event.revision_seq if event.revision_seq is not None else -1,
            event.revision_id,
        )
        if current is None:
            chosen[key] = event
            continue
        current_rank = (
            current.availability_upper_bound,
            current.revision_seq if current.revision_seq is not None else -1,
            current.revision_id,
        )
        if candidate_rank > current_rank:
            chosen[key] = event
    return sorted(
        chosen.values(), key=lambda e: (e.series_id, e.observation_period_end, e.revision_id)
    )


def select_heads(history: list[AvailabilityEvent], *, cutoff: datetime) -> dict[str, HeadState]:
    """계열별 최신 head 와 age — history 위에서 별도 계산한다 (§6.5)."""
    heads: dict[str, AvailabilityEvent] = {}
    for event in history:
        current = heads.get(event.series_id)
        if current is None or event.observation_period_end > current.observation_period_end:
            heads[event.series_id] = event
    result: dict[str, HeadState] = {}
    for series_id, event in sorted(heads.items()):
        observation_end = datetime.fromisoformat(event.observation_period_end + "T00:00:00+00:00")
        age_obs = (cutoff - observation_end).total_seconds() / 86400.0
        age_pub = (
            (cutoff - event.source_published_at).total_seconds() / 86400.0
            if event.source_published_at is not None
            else None
        )
        result[series_id] = HeadState(
            series_id=series_id,
            observation_period_end=event.observation_period_end,
            value=event.value,
            revision_id=event.revision_id,
            age_since_observation_days=age_obs,
            age_since_publication_days=age_pub,
            availability_precision=event.availability_precision,
        )
    return result


def environment_lock_hash() -> str:
    """실행 환경 지문 — 다른 환경의 cache 재사용을 차단하는 축 (§6.7)."""
    import numpy
    import pandas
    import scipy

    versions = {
        "python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "scipy": scipy.__version__,
    }
    try:
        import statsmodels

        versions["statsmodels"] = statsmodels.__version__
    except ImportError:  # pragma: no cover
        versions["statsmodels"] = None
    return canonical_hash(versions)


def build_snapshot(
    *,
    cutoff: datetime,
    replay_mode: ReplayMode,
    events: Iterable[AvailabilityEvent],
    checkpoint: LedgerCheckpoint,
    calendar: CalendarRef,
    source_specs_hash: str,
    availability_policy_hash: str,
    transform_code_hash: str,
    environment_lock: str,
    kind: Literal["input", "outcome"] = "input",
    target_contract_hash: str | None = None,
    transaction_cutoff_at: datetime | None = None,
    completed_batches: set[str] | None = None,
) -> InputSnapshot | OutcomeSnapshot:
    """§6.5 의사코드의 구현 — committed → visible → history → heads → freeze."""
    require_utc(cutoff, field="cutoff")
    visible = visible_events(
        events, cutoff=cutoff, replay_mode=replay_mode, completed_batches=completed_batches
    )
    history = resolve_latest_visible_revision_per_period(visible)
    for event in history:
        if effective_available_at(event, replay_mode=replay_mode) > cutoff:  # pragma: no cover
            raise MtsSnapshotError("가시성 위반 행이 history 에 남았다")
    revision_ids = sorted(event.revision_id for event in history)
    receipts = sorted({event.raw_sha256 for event in history if event.raw_sha256})
    body = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "kind": kind,
        "replay_mode": replay_mode,
        "information_cutoff_at": cutoff.isoformat(),
        "ledger_checkpoint_id": checkpoint.checkpoint_id,
        "transaction_cutoff_at": (transaction_cutoff_at or checkpoint.created_at).isoformat(),
        "observation_revision_ids_hash": canonical_hash(revision_ids),
        "raw_receipts_hash": canonical_hash(receipts),
        "source_specs_hash": source_specs_hash,
        "availability_policy_hash": availability_policy_hash,
        "target_contract_hash": target_contract_hash,
        "calendar_hash": calendar.calendar_hash,
        "transform_code_hash": transform_code_hash,
        "environment_lock_hash": environment_lock,
    }
    manifest = SnapshotManifest(
        snapshot_id="mts-snap-" + canonical_hash(body)[:24],
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        kind=kind,
        replay_mode=replay_mode,
        information_cutoff_at=cutoff,
        ledger_checkpoint_id=checkpoint.checkpoint_id,
        transaction_cutoff_at=transaction_cutoff_at or checkpoint.created_at,
        observation_revision_ids_hash=body["observation_revision_ids_hash"],
        raw_receipts_hash=body["raw_receipts_hash"],
        source_specs_hash=source_specs_hash,
        availability_policy_hash=availability_policy_hash,
        target_contract_hash=target_contract_hash,
        calendar_hash=calendar.calendar_hash,
        transform_code_hash=transform_code_hash,
        environment_lock_hash=environment_lock,
        series_heads=select_heads(history, cutoff=cutoff),
    )
    cls = InputSnapshot if kind == "input" else OutcomeSnapshot
    return cls(manifest=manifest, history=tuple(history))


def persist_manifest(root: Path, snapshot: InputSnapshot | OutcomeSnapshot) -> Path:
    from .artifacts import write_immutable_json

    relative = SNAPSHOTS_RELATIVE / f"{snapshot.manifest.snapshot_id}.json"
    return write_immutable_json(root, relative, snapshot.manifest.model_dump(mode="json"))
