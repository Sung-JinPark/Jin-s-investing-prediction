"""§17.3 최소 타입 계약 — 불변(pydantic frozen) 레코드와 Protocol.

규약:
- 모든 datetime 은 timezone-aware UTC 만 허용한다. naive 입력은 검증 오류다
  (날짜 문자열에 timezone 을 추정해 붙이지 않는다 — 설계서 §17.3-1).
- 디스크 직렬화는 ``model_dump(mode="json")`` dict 를
  ``ai_fc.timeseries_v8.contracts.canonical_hash`` (무수정 import — V13 전례)로 해시한다.
- ISSUED 는 검증된 payload·hash·state 가 필수이고, HOLD/NOT_ELIGIBLE 은 수치 0 이나
  가짜 state ID 를 만들지 않는다 (§17.3-3, T57·T60).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..timeseries_v8.contracts import canonical_hash

ReplayMode = Literal[
    "operational_replay",
    "historical_information_set_reconstruction",
]
ForecastKind = Literal[
    "marginal_distribution",
    "quantile_grid",
    "event_probability",
    "joint_path",
]
ForecastStatus = Literal["ISSUED", "HOLD", "NOT_ELIGIBLE"]
ResolutionStatus = Literal["PENDING", "MATURE", "UNRESOLVED", "RESTATED", "INVALIDATED"]
EvidenceTrack = Literal["legacy_reproduction", "historical_research", "prospective"]
AttemptStatus = Literal["STARTED", "FAILED", "COMMITTED"]


class MtsRecordError(ValueError):
    """§17.3 레코드 불변조건 위반 — fail-closed."""


def require_utc(value: datetime, *, field: str) -> datetime:
    """timezone-aware UTC 만 통과시킨다. naive/타 시간대는 거부한다."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise MtsRecordError(f"{field}: naive datetime 금지 — timezone-aware UTC 필요")
    if value.utcoffset() != timezone.utc.utcoffset(None):
        raise MtsRecordError(f"{field}: UTC 가 아닌 시간대 금지 (offset={value.utcoffset()})")
    return value


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def body(self) -> dict[str, Any]:
        """canonical_hash 입력용 JSON-호환 dict."""
        return self.model_dump(mode="json")

    def content_hash(self) -> str:
        return canonical_hash(self.body())


class EventEnvelope(_Frozen):
    """canonical writer 가 모든 이벤트에 부여하는 공통 봉투 (§17.3-10)."""

    event_id: str
    recorded_at: datetime
    experiment_id: str
    evidence_track: EvidenceTrack
    commit_id: str
    payload_hash: str
    previous_event_hash: str | None

    @field_validator("recorded_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="recorded_at")


class ForecastSpec(_Frozen):
    """예측 좌표 — target hash 가 threshold·boundary·관측 필드·단위·estimator·
    만기·eligibility·label revision policy 를 모두 결정해야 한다 (§17.3-2)."""

    target_spec_hash: str
    instrument_id: str
    horizon_sessions: int
    origin_session: date
    information_cutoff_at: datetime
    input_snapshot_id: str
    calendar_hash: str
    eligibility_rule_hash: str
    forecast_kind: ForecastKind

    @field_validator("information_cutoff_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="information_cutoff_at")

    @field_validator("horizon_sessions")
    @classmethod
    def _horizon(cls, value: int) -> int:
        if value < 1:
            raise MtsRecordError("horizon_sessions 는 1 이상의 거래 세션 수")
        return value


class TrainingBatchRef(_Frozen):
    manifest_id: str
    manifest_hash: str
    fit_cutoff_at: datetime
    read_scope_receipt_id: str
    target_spec_hash: str
    feature_spec_hash: str
    matured_label_policy_hash: str

    @field_validator("fit_cutoff_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="fit_cutoff_at")


class FittedStateRef(_Frozen):
    state_id: str
    state_hash: str
    model_id: str
    code_hash: str
    training_manifest_id: str
    fit_cutoff_at: datetime
    environment_lock_hash: str

    @field_validator("fit_cutoff_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="fit_cutoff_at")


class CalibrationStateRef(_Frozen):
    """보정 상태 — base state 와 별도로 cutoff 를 검사한다 (§17.3-9, T56).

    학습 라벨이 없는 identity state 만 ``max_used_label_available_at: None`` 을 허용한다.
    """

    calibration_state_id: str
    fit_information_cutoff_at: datetime
    oof_cohort_manifest_hash: str
    max_used_label_available_at: datetime | None
    target_spec_hash: str
    label_revision_policy_hash: str
    method: str

    @field_validator("fit_information_cutoff_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="fit_information_cutoff_at")

    @field_validator("max_used_label_available_at")
    @classmethod
    def _utc_opt(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value, field="max_used_label_available_at")

    @model_validator(mode="after")
    def _identity_null_rule(self) -> "CalibrationStateRef":
        if self.max_used_label_available_at is None and self.method != "identity":
            raise MtsRecordError(
                "max_used_label_available_at=None 은 identity state 에만 허용 (§17.3-9)"
            )
        return self


class ForecastAttemptEvent(_Frozen):
    """시도 이벤트 — snapshot/fit 실패도 기록하되 정상 artifact 를 만들지 않는다 (T57)."""

    attempt_id: str
    attempted_at: datetime
    intended_origin_session: date
    contract_hash: str
    stage: str
    status: AttemptStatus
    input_snapshot_id: str | None
    forecast_id: str | None
    reason_codes: tuple[str, ...]

    @field_validator("attempted_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="attempted_at")


class ForecastDraft(_Frozen):
    """ModelAdapter.predict 의 반환물 — 발행 전 상태 (§17.3-11).

    issued_at 은 canonical writer 의 실제 commit 에서만 확정된다.
    """

    model_id: str
    spec: ForecastSpec
    state_id: str | None
    calibration_state_id: str | None
    prediction_status: Literal["READY", "HOLD", "NOT_ELIGIBLE"]
    payload_ref: str | None
    payload_hash: str | None
    capabilities: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def _status_payload_rule(self) -> "ForecastDraft":
        if self.prediction_status == "READY":
            if not (self.payload_ref and self.payload_hash and self.state_id):
                raise MtsRecordError("READY draft 는 payload_ref·payload_hash·state_id 필수")
        else:
            if self.payload_ref or self.payload_hash:
                raise MtsRecordError(
                    f"{self.prediction_status} draft 는 payload 를 가질 수 없다 — 수치 0 가장 금지"
                )
        return self


class ForecastArtifact(_Frozen):
    """불변 발행물 (§17.3-3·4·12).

    - ISSUED: 검증된 payload·hash·state 필수.
    - HOLD/NOT_ELIGIBLE: payload 금지 (가짜 수치 금지).
    - fit_cutoff_at <= information_cutoff_at <= issued_at 는 commit 경로에서 검사.
    - 역사 재구성의 issued_at 는 실제 재구성 시각이며 과거로 위조하지 않는다.
    """

    forecast_id: str
    logical_forecast_key: str
    reconstruction_of_forecast_id: str | None
    model_id: str
    spec: ForecastSpec
    issued_at: datetime
    replay_mode: ReplayMode
    evidence_track: EvidenceTrack
    status: ForecastStatus
    state_id: str | None
    calibration_state_id: str | None
    payload_ref: str | None
    payload_hash: str | None
    capabilities: tuple[str, ...]
    reason_codes: tuple[str, ...]
    contract_hash: str

    @field_validator("issued_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value, field="issued_at")

    @model_validator(mode="after")
    def _status_rules(self) -> "ForecastArtifact":
        if self.status == "ISSUED":
            if not (self.payload_ref and self.payload_hash and self.state_id):
                raise MtsRecordError("ISSUED 에는 검증된 payload·hash·state_id 가 필요 (§17.3-3)")
        else:
            if self.payload_ref or self.payload_hash:
                raise MtsRecordError(f"{self.status} 는 payload 를 가질 수 없다 (§17.3-3)")
        if self.issued_at < self.spec.information_cutoff_at:
            raise MtsRecordError("issued_at < information_cutoff_at — 발행 시각 위조 금지 (§17.3-4)")
        if self.evidence_track == "prospective" and self.replay_mode != "operational_replay":
            raise MtsRecordError("prospective 증거는 operational_replay 로만 생산된다 (§12.1)")
        return self


class ResolutionEvent(_Frozen):
    """해소 이벤트 — RESTATED 는 이전 resolution 을 참조하는 새 이벤트다 (§17.3-5)."""

    resolution_id: str
    forecast_id: str
    target_spec_hash: str
    input_snapshot_id: str
    outcome_snapshot_id: str | None
    status: ResolutionStatus
    observed_value: float | None
    label_available_at: datetime | None
    label_revision_id: str | None
    scoring_policy_hash: str
    supersedes_resolution_id: str | None

    @field_validator("label_available_at")
    @classmethod
    def _utc_opt(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value, field="label_available_at")

    @model_validator(mode="after")
    def _restated_rule(self) -> "ResolutionEvent":
        if self.status == "RESTATED" and not self.supersedes_resolution_id:
            raise MtsRecordError("RESTATED 는 supersedes_resolution_id 필수 (§6.3-3)")
        if self.status == "MATURE" and self.observed_value is None:
            raise MtsRecordError("MATURE 해소는 observed_value 필수")
        return self


class DistributionForecast(Protocol):
    """CDF capability 가 확인된 객체에만 부여한다 (§17.3-8)."""

    def cdf(self, x: float) -> float: ...

    def quantile(self, q: float) -> float: ...


class ModelAdapter(Protocol):
    def fit(self, batch: TrainingBatchRef) -> FittedStateRef: ...

    def predict(self, state: FittedStateRef, spec: ForecastSpec) -> ForecastDraft: ...
