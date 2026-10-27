"""§6.1 가용성 계층 — 기존 두 저장소의 read-only 정규화 투영과 두 재생 모드 (§6.2).

필드 매핑 (설계서 §6.1 → 저장소 실체, inventory §5 대응표):

- legacy 행의 ``source_published_at``/``provider_available_at`` 은 **항상 None** 이다.
  추가 증거 없는 과거 자료를 exact timestamp 로 승격하지 않는다 (§6.1 불변조건).
- ``first_seen_at`` ← market ``vintage_start`` / ALFRED ``retrieved_at`` (수집기가 바이트를
  실제 받은 시각). ``recorded_at`` ← ``vintage_start`` (canonical commit).
- ``availability_upper_bound`` ← ``available_at``:
  - market ``reconstructed_market_archive`` 1판: 보수적 post-close 역사 상계 (원장 설계).
  - market ``captured_forward`` / 정정판: 수집 시각 — **역사적 공개 증거 없음**.
  - ALFRED: 날짜 단위 실시간 구간을 당일 말 ET 보수 상계로 이미 저장.
- ``availability_precision``: native_pit→date, reconstructed→inferred, captured_forward→captured_only.

재생 모드 (§6.2):
- ``operational_replay``: max(first_seen_at, recorded_at) <= cutoff — 실제 수신 경계 (T04·T05).
- ``historical_information_set_reconstruction``: availability_upper_bound <= cutoff —
  증거 기반 보수 상계 (T03·T12). 나중에 받은 backfill(captured_forward)은 상계가 수집
  시각이므로 과거 cutoff 에서 자동으로 보이지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from .records import ReplayMode, require_utc

MARKET_LEDGER_RELATIVE = Path("data/timeseries_v2/ledgers/market_observations.jsonl")
ALFRED_PARQUET_RELATIVE = Path("data/timeseries/facts/observations.parquet")

AvailabilityPrecision = Literal["exact", "date", "inferred", "captured_only"]

_GRADE_PRECISION: dict[str, AvailabilityPrecision] = {
    "native_pit": "date",
    "reconstructed_market_archive": "inferred",
    "captured_forward": "captured_only",
}


class MtsAvailabilityError(RuntimeError):
    """가용성 계층 불변조건 위반 — fail-closed."""


class AvailabilityEvent(BaseModel):
    """기존 저장소 행(또는 합성 이벤트)의 §6.1 정규화 투영 — read-only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    series_id: str
    observation_period_start: str
    observation_period_end: str
    value: float | None
    unit: str | None
    source_published_at: datetime | None
    provider_available_at: datetime | None
    first_seen_at: datetime
    recorded_at: datetime
    availability_lower_bound: datetime | None
    availability_upper_bound: datetime
    availability_precision: AvailabilityPrecision
    availability_policy_id: str
    data_grade: str
    revision_id: str
    supersedes_id: str | None
    revision_seq: int | None
    raw_sha256: str | None
    receipt_id: str | None
    source_id: str
    ingestion_batch_id: str | None
    instrument_id: str | None

    @field_validator("first_seen_at", "recorded_at", "availability_upper_bound")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="availability timestamp")


class LedgerCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_id: str
    ledger_path: str
    row_count: int
    content_sha256: str
    created_at: datetime


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise MtsAvailabilityError(f"timezone 없는 timestamp — 자정 가정 금지: {value}")
    return parsed.astimezone(timezone.utc)


def normalize_market_row(row: dict, *, policy_id: str = "legacy_store_v1") -> AvailabilityEvent:
    """market_observations.jsonl 행 → AvailabilityEvent.

    legacy 행의 publication/provider 시각은 **무조건 None** — 입력에 무엇이 있어도
    승격하지 않는다.
    """
    grade = str(row["data_grade"])
    if grade not in _GRADE_PRECISION:
        raise MtsAvailabilityError(f"알 수 없는 data_grade: {grade}")
    vintage_start = _dt(row["vintage_start"])
    return AvailabilityEvent(
        series_id=str(row["series_id"]),
        observation_period_start=str(row["observation_time"]),
        observation_period_end=str(row["observation_time"]),
        value=float(row["value"]),
        unit=row.get("unit"),
        source_published_at=None,
        provider_available_at=None,
        first_seen_at=vintage_start,
        recorded_at=vintage_start,
        availability_lower_bound=None,
        availability_upper_bound=_dt(row["available_at"]),
        availability_precision=_GRADE_PRECISION[grade],
        availability_policy_id=policy_id,
        data_grade=grade,
        revision_id=str(row["observation_id"]),
        supersedes_id=row.get("supersedes"),
        revision_seq=int(row["revision_seq"]),
        raw_sha256=row.get("raw_sha256"),
        receipt_id=row.get("receipt_id"),
        source_id=str(row["source_id"]),
        ingestion_batch_id=row.get("receipt_id"),
        instrument_id=None,
    )


def normalize_alfred_row(row: dict, *, policy_id: str = "legacy_alfred_v1") -> AvailabilityEvent:
    """ALFRED 빈티지 행 → AvailabilityEvent. 날짜 단위 실시간 구간은 보수 상계로 저장돼 있다."""
    retrieved = _dt(row["retrieved_at"]) if row.get("retrieved_at") else _dt(row["vintage_start"])
    return AvailabilityEvent(
        series_id=str(row["series_id"]),
        observation_period_start=str(row["observation_time"]),
        observation_period_end=str(row["observation_time"]),
        value=None if row.get("value") is None else float(row["value"]),
        unit=None,
        source_published_at=None,
        provider_available_at=None,
        first_seen_at=retrieved,
        recorded_at=_dt(row["vintage_start"]),
        availability_lower_bound=None,
        availability_upper_bound=_dt(row["available_at"]),
        availability_precision="date",
        availability_policy_id=policy_id,
        data_grade="alfred_vintage",
        revision_id=f"{row['series_id']}:{row['observation_time']}:{row.get('source_revision_id')}:{row['vintage_start']}",
        supersedes_id=None,
        revision_seq=None,
        raw_sha256=row.get("source_hash"),
        receipt_id=None,
        source_id=str(row["source_id"]),
        ingestion_batch_id=row.get("source_revision_id"),
        instrument_id=None,
    )


# ---------------------------------------------------------------------------
# 저장소 로더 (read-only)
# ---------------------------------------------------------------------------


def take_checkpoint(root: Path, ledger_relative: Path, *, now: datetime) -> LedgerCheckpoint:
    """원장 접두(row_count 줄)의 checkpoint — operational replay 의 commit 경계 (T07·T59)."""
    require_utc(now, field="now")
    path = root / ledger_relative
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = [line for line in text.splitlines() if line.strip()]
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return LedgerCheckpoint(
        checkpoint_id=f"ckpt-{digest[:24]}",
        ledger_path=str(ledger_relative).replace("\\", "/"),
        row_count=len(lines),
        content_sha256=digest,
        created_at=now,
    )


def load_market_events(
    root: Path,
    *,
    series_ids: set[str] | None = None,
    checkpoint: LedgerCheckpoint | None = None,
) -> list[AvailabilityEvent]:
    """market_observations.jsonl 의 read-only 로드.

    checkpoint 가 있으면 그 행수까지만 읽고 접두 sha 를 검증한다 — checkpoint 이후
    append 된 행은 snapshot 에 들어갈 수 없다 (T07).
    """
    path = root / MARKET_LEDGER_RELATIVE
    if not path.is_file():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if checkpoint is not None:
        if checkpoint.row_count > len(lines):
            raise MtsAvailabilityError("checkpoint 가 원장보다 길다 — 원장 축소는 append-only 위반")
        lines = lines[: checkpoint.row_count]
        digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
        if digest != checkpoint.content_sha256:
            raise MtsAvailabilityError("checkpoint 접두 sha 불일치 — 원장 변조 또는 비-append 변경")
    events: list[AvailabilityEvent] = []
    for line in lines:
        row = json.loads(line)
        if series_ids is not None and row.get("series_id") not in series_ids:
            continue
        events.append(normalize_market_row(row))
    return events


def load_alfred_events(root: Path, *, series_ids: set[str]) -> list[AvailabilityEvent]:
    """ALFRED 빈티지 parquet 의 read-only 로드 (pyarrow 필터)."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    path = root / ALFRED_PARQUET_RELATIVE
    table = pq.read_table(path, filters=[("series_id", "in", sorted(series_ids))])
    events = [normalize_alfred_row(row) for row in table.to_pylist()]
    return events


# ---------------------------------------------------------------------------
# 가시성 (§6.2)
# ---------------------------------------------------------------------------


def effective_available_at(event: AvailabilityEvent, *, replay_mode: ReplayMode) -> datetime:
    if replay_mode == "operational_replay":
        return max(event.first_seen_at, event.recorded_at)
    return event.availability_upper_bound


def visible_events(
    events: Iterable[AvailabilityEvent],
    *,
    cutoff: datetime,
    replay_mode: ReplayMode,
    completed_batches: set[str] | None = None,
) -> list[AvailabilityEvent]:
    """cutoff 에서 보이는 이벤트.

    completed_batches 가 주어지면 완료 marker 없는 batch 의 이벤트를 제외한다 (T07).
    """
    require_utc(cutoff, field="cutoff")
    selected: list[AvailabilityEvent] = []
    for event in events:
        if completed_batches is not None and event.ingestion_batch_id not in completed_batches:
            continue
        if effective_available_at(event, replay_mode=replay_mode) <= cutoff:
            selected.append(event)
    return selected
