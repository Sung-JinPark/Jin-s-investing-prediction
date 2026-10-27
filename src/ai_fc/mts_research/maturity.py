"""§4.6·§17.3-10 라벨 성숙 — append-only 상태 이벤트와 완전 성숙 코호트.

- 기본 라벨 정책: **완전 성숙 코호트**. h일 사건이 일찍 발생해 양성임을 알더라도
  만기·라벨 가용 시각이 지날 때까지 학습·보정·비교 집계에서 제외한다 (T16).
- PENDING→MATURE 등 상태 변화는 기존 행 수정이 아니라 **새 이벤트**다.
- ``label_available_at`` 은 라벨 원천/확정 정책의 가용 시각, ``recorded_at`` 은 우리
  시스템의 실제 기록 시각 — 별개 축이다. operational replay 의 학습·보정에는 당시
  checkpoint 에서 보였던 resolution 만 포함한다 (T59).
- 발행 시각이 첫 대상 관측의 가용 시각보다 늦으면 prospective 등록을 거부한다 (T15).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .records import ReplayMode, require_utc

LabelStatus = Literal["PENDING", "MATURE", "UNRESOLVED", "RESTATED", "INVALIDATED"]

TERMINAL_STATUSES: tuple[LabelStatus, ...] = ("MATURE", "UNRESOLVED", "RESTATED", "INVALIDATED")


class MtsMaturityError(RuntimeError):
    """라벨 성숙 규칙 위반 — fail-closed."""


class LabelEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label_event_id: str
    target_spec_hash: str
    origin_session: str
    status: LabelStatus
    observed_value: float | None
    first_touch_session: str | None
    early_event_observed_at: datetime | None  # §4.6 — 운영 메타데이터일 뿐, 성숙 전 집계 금지
    label_available_at: datetime | None
    label_revision_id: str | None
    recorded_at: datetime
    outcome_snapshot_id: str | None
    anchor_revision_id: str | None  # 발행 anchor 판 (§6.3 — terminal 판과 별도 보존, T11)
    supersedes_label_event_id: str | None

    @field_validator("recorded_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="recorded_at")

    @field_validator("label_available_at", "early_event_observed_at")
    @classmethod
    def _utc_opt(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value, field="label timestamp")

    @model_validator(mode="after")
    def _rules(self) -> "LabelEvent":
        if self.status in ("MATURE", "RESTATED"):
            if self.observed_value is None:
                raise MtsMaturityError(f"{self.status} 는 observed_value 필수")
            if self.label_available_at is None:
                raise MtsMaturityError(f"{self.status} 는 label_available_at 필수")
            if self.label_revision_id is None:
                raise MtsMaturityError(f"{self.status} 는 label_revision_id 필수 (T11)")
            if self.outcome_snapshot_id is None:
                # 외부 리뷰 F06 (2026-10-27): within-horizon·rolling 라벨은 경로 전체에
                # 의존한다 — 단일 revision id 로는 재현이 안 되므로 전체 경로 판을 커밋한
                # outcome snapshot 결박을 의무화한다.
                raise MtsMaturityError(
                    f"{self.status} 는 outcome_snapshot_id 필수 (F06 — 경로형 라벨의 "
                    "전체 경로 revision 결박)"
                )
        if self.status == "RESTATED" and self.supersedes_label_event_id is None:
            raise MtsMaturityError("RESTATED 는 이전 이벤트 참조 필수 (§6.3)")
        if self.status == "PENDING" and self.observed_value is not None:
            raise MtsMaturityError("PENDING 은 observed_value 를 가질 수 없다 — 조기 양성 선반영 금지")
        return self


def validate_label_chain(events: list[LabelEvent]) -> None:
    """같은 (target, origin) 의 이벤트 열에서 supersedes 참조 무결성을 검사한다 (T48 상태측)."""
    seen: dict[str, LabelEvent] = {}
    for event in events:
        if event.label_event_id in seen:
            raise MtsMaturityError(f"label_event_id 중복: {event.label_event_id}")
        if event.supersedes_label_event_id is not None:
            target = seen.get(event.supersedes_label_event_id)
            if target is None:
                raise MtsMaturityError("supersedes 가 존재하지 않는 이벤트를 가리킨다")
            if (target.target_spec_hash, target.origin_session) != (
                event.target_spec_hash, event.origin_session
            ):
                raise MtsMaturityError("supersedes 는 같은 (target, origin) 안에서만 유효")
        seen[event.label_event_id] = event


def latest_label_state(events: Iterable[LabelEvent]) -> dict[tuple[str, str], LabelEvent]:
    """(target, origin) 별 최신 비-superseded 이벤트 — 원판은 체인에 그대로 남는다."""
    ordered = list(events)
    validate_label_chain(ordered)
    superseded = {
        event.supersedes_label_event_id
        for event in ordered
        if event.supersedes_label_event_id is not None
    }
    latest: dict[tuple[str, str], LabelEvent] = {}
    for event in ordered:
        if event.label_event_id in superseded:
            continue
        key = (event.target_spec_hash, event.origin_session)
        if key in latest:
            # 체인 참조 없는 동일 키 중복 종결은 금지 — 정정은 supersedes 로만
            if latest[key].status != "PENDING" and event.status != "PENDING":
                raise MtsMaturityError(
                    f"같은 (target, origin) 의 중복 종결 이벤트 — supersedes 필요: {key}"
                )
        latest[key] = event
    return latest


def matured_view(
    events: Iterable[LabelEvent],
    *,
    as_of: datetime,
    replay_mode: ReplayMode = "operational_replay",
    recorded_cutoff: datetime | None = None,
) -> dict[tuple[str, str], LabelEvent]:
    """완전 성숙 코호트 — 학습·보정·비교 집계의 유일한 라벨 입력 (T16·T59).

    - PENDING(조기 양성 포함)은 절대 반환하지 않는다.
    - MATURE/RESTATED 는 ``label_available_at <= as_of`` 일 때만.
    - operational replay 면 ``recorded_at <= recorded_cutoff`` 도 요구한다 — 원천상
      과거 가용이지만 나중에 기록된 resolution 은 당시 checkpoint 밖이다 (T59).
    """
    require_utc(as_of, field="as_of")
    if replay_mode == "operational_replay":
        bound = recorded_cutoff if recorded_cutoff is not None else as_of
        require_utc(bound, field="recorded_cutoff")
    result: dict[tuple[str, str], LabelEvent] = {}
    for key, event in latest_label_state(events).items():
        if event.status == "PENDING":
            continue
        if event.status in ("MATURE", "RESTATED"):
            if event.label_available_at is None or event.label_available_at > as_of:
                continue
        if replay_mode == "operational_replay" and event.recorded_at > (
            recorded_cutoff if recorded_cutoff is not None else as_of
        ):
            continue
        result[key] = event
    return result


def resolutions_available_before(
    events: Iterable[LabelEvent],
    *,
    cutoff: datetime,
    replay_mode: ReplayMode,
    recorded_cutoff: datetime | None = None,
) -> list[LabelEvent]:
    """§12.2 — 원점 cutoff 이전에 '보였던' 해소만 (보정·causal update 입력)."""
    view = matured_view(
        events, as_of=cutoff, replay_mode=replay_mode, recorded_cutoff=recorded_cutoff
    )
    return sorted(view.values(), key=lambda e: (e.target_spec_hash, e.origin_session))


def assert_prospective_issue(*, issued_at: datetime, first_target_available_at: datetime) -> None:
    """prospective 등록 가드 (T15, §4.1).

    변경 불가능한 issued_at 가 첫 대상 관측의 이용 가능 시각보다 앞서야 한다.
    cutoff 만 과거로 기입한 backdated forecast 를 라이브로 등록할 수 없다.
    """
    require_utc(issued_at, field="issued_at")
    require_utc(first_target_available_at, field="first_target_available_at")
    if issued_at >= first_target_available_at:
        raise MtsMaturityError(
            "prospective 등록 거부: issued_at 이 첫 대상 관측 가용 시각 이후다 — "
            f"{issued_at.isoformat()} >= {first_target_available_at.isoformat()} (T15)"
        )
