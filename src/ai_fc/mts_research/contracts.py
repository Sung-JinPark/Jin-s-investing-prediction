"""연구 계약(§18)·source_spec(§7.4)·read-scope 가드.

원칙:
- 상속 계약(V8/V13/V14/daily6m)은 read-only 로 로드해 **충돌을 검사**한다.
  마지막에 읽은 YAML 이 조용히 덮어쓰는 방식은 금지 (§18.1).
- ``state: draft`` 또는 필수 null 이 남은 계약으로는 run 을 거부한다 (T55).
  validate/audit/dry-run 은 부족한 항목을 구체적으로 보고한다.
- 보호 창 접근은 **어떤 payload read 보다 먼저** 검사하고, 거부도 노출 원장에
  감사 기록을 남긴다 (T50). 저장소에 'read_scope' 라는 개념이 없으므로
  V13 의 named_verb_guarded + approvals.jsonl 영수증 모델로 대응한다
  (대응표: docs/research/mts_upgrade/repository_inventory.md §5).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from ..timeseries_v8.contracts import canonical_hash
from .records import CalibrationStateRef, FittedStateRef, ForecastSpec

DRAFT_CONTRACT_RELATIVE = Path("data/mts_research/contracts/mts_research_v1.draft.yaml")
SOURCE_SPECS_RELATIVE = Path("data/mts_research/source_specs")
APPROVALS_LEDGER_RELATIVE = Path("data/mts_research/ledgers/approvals.jsonl")

Action = Literal["validate", "audit", "dry_run", "run", "evaluate"]


class MtsContractError(RuntimeError):
    """계약 검증 실패 — fail-closed."""


class MtsScopeError(MtsContractError):
    """보호 창 접근 거부 — 어떤 데이터 read 보다 먼저 발생한다 (T50)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# §7.4 source_spec
# ---------------------------------------------------------------------------


class SourceSpec(_Frozen):
    """신규 원천 사용 허용 계약 — 전 좌표 확인 전에는 연구 입력으로 켜지 않는다."""

    source_id: str
    instrument_ids: tuple[str, ...] = ()
    entitlement_status: Literal["unverified", "verified"] = "unverified"
    permitted_uses: tuple[str, ...] = ()
    redistribution_policy: str = "unverified"
    actual_coverage_verified: bool = False
    delivery_latency_policy_id: str | None = None
    correction_policy_id: str | None = None
    methodology_version: str | None = None
    availability_evidence_grade: str | None = None
    enabled: bool = False

    def research_input_allowed(self) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not self.enabled:
            reasons.append("SOURCE_DISABLED")
        if self.entitlement_status != "verified":
            reasons.append("ENTITLEMENT_UNVERIFIED")
        if not self.actual_coverage_verified:
            reasons.append("COVERAGE_UNVERIFIED")
        if self.delivery_latency_policy_id is None:
            reasons.append("LATENCY_POLICY_MISSING")
        if self.correction_policy_id is None:
            reasons.append("CORRECTION_POLICY_MISSING")
        if self.redistribution_policy == "unverified":
            reasons.append("REDISTRIBUTION_UNVERIFIED")
        return (not reasons, reasons)


def load_source_specs(root: Path) -> dict[str, SourceSpec]:
    directory = root / SOURCE_SPECS_RELATIVE
    specs: dict[str, SourceSpec] = {}
    if not directory.is_dir():
        return specs
    for path in sorted(directory.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "source" not in payload:
            raise MtsContractError(f"source_spec 형식 오류: {path.name}")
        body = dict(payload["source"])
        for key in ("instrument_ids", "permitted_uses"):
            if isinstance(body.get(key), list):
                body[key] = tuple(body[key])
        spec = SourceSpec(**body)
        if spec.source_id in specs:
            raise MtsContractError(f"source_id 중복: {spec.source_id}")
        specs[spec.source_id] = spec
    return specs


def source_specs_hash(specs: dict[str, SourceSpec]) -> str:
    return canonical_hash({key: specs[key].model_dump(mode="json") for key in sorted(specs)})


# ---------------------------------------------------------------------------
# §18 연구 계약
# ---------------------------------------------------------------------------


class InheritBlock(_Frozen):
    v8_contract: str
    v13_contract: str
    v14_contract: str
    daily6m_contract: str
    frozen_price_champion: str
    frozen_event_champion: str
    protected_manifest_hash: str | None


class ExecutionBlock(_Frozen):
    namespace: str
    mode: Literal["audit_only", "registered_research"]
    enabled_experiments: tuple[str, ...] = ()
    enabled_candidates: tuple[str, ...] = ()
    read_scope_receipt_id: str | None
    allowed_input_manifest_hash: str | None
    allowed_outcome_manifest_hash: str | None
    experiment_budget_receipt_id: str | None
    network_fetch_enabled: bool
    protected_holdout_read_enabled: bool
    auto_promote: bool
    production_publish_enabled: bool


class TimeTargetsBlock(_Frozen):
    replay_mode: str | None
    availability_policy_hash: str | None
    source_registry_hash: str | None
    calendar_hash: str | None
    target_spec_hash: str | None
    eligibility_rule_hash: str | None
    label_revision_policy_hash: str | None
    maturity_policy: Literal["complete_horizon"]
    partial_censoring_training_enabled: bool
    original_origin_grid_required: bool
    # F04 (2026-10-27): 원점별 발행 마감 — cutoff 이후 허용 지연(초). 등록 시 필수
    # (null 인 채로는 prospective run 불가; artifacts.commit_forecast 가 강제).
    max_issuance_latency_seconds: int | None = None


class HazardBlock(_Frozen):
    enabled: bool
    family: Literal["penalized_discrete_time_logit"]
    origin_features_only: bool
    proposed_time_bins_sessions: tuple[tuple[int, int], ...]
    penalty_grid_manifest_hash: str | None

    @field_validator("proposed_time_bins_sessions", mode="before")
    @classmethod
    def _tuples(cls, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(tuple(item) for item in value)
        return value


class CalibrationBlock(_Frozen):
    default: Literal["identity"]
    candidate: Literal["intercept_only", "intercept_and_slope"]
    oof_only: bool
    mature_labels_only: bool
    parameter_grid_manifest_hash: str | None


class ModelsBlock(_Frozen):
    hazard: HazardBlock
    calibration: CalibrationBlock
    conformal_enabled: bool
    foundation_model_integration_enabled: bool
    learned_ensemble_enabled: bool
    new_source_blocks_enabled: tuple[str, ...] = ()


class EvaluationBlock(_Frozen):
    evidence_track: str | None
    prospective_cohort_manifest_hash: str | None
    candidate_failure_policy: Literal["hold_confirmatory_verdict"]
    registered_fallback_policy_hash: str | None
    primary_metric_spec_hash: str | None
    primary_comparison_manifest_hash: str | None
    minimum_practical_effect_in_score_units: float | None
    noninferiority_margin_manifest_hash: str | None
    family_manifest_hash: str | None
    familywise_alpha: float
    inference_method: Literal["centered_paired_stationary_bootstrap"]
    multiplicity_method: Literal["holm"]
    studentized: bool
    original_grid_and_eligibility_mask_resampled_together: bool
    bootstrap_replicates: int | None
    mean_block_length_in_origin_grid_rows: int | None
    block_sensitivity_manifest_hash: str | None
    random_seed_manifest_hash: str | None
    degenerate_replicate_policy_hash: str | None
    fixed_mature_cohort_look: bool
    sequential_evidence_enabled: bool
    legacy_gates_unchanged: bool

    @field_validator("familywise_alpha")
    @classmethod
    def _alpha(cls, value: float) -> float:
        if not (0.0 < value < 1.0):
            raise ValueError("familywise_alpha 는 (0,1)")
        return value


class OutputsBlock(_Frozen):
    root: str
    append_only: bool
    require_atomic_commit: bool
    require_baseline_identity_report: bool
    require_negative_result_record: bool


class ResearchContract(_Frozen):
    schema_version: Literal["mts_research_contract_proposal_v1"]
    state: Literal["draft", "registered", "frozen"]
    purpose: str
    source_document: str
    actual_repository_revision: str | None
    environment_lock_hash: str | None
    inherit: InheritBlock
    execution: ExecutionBlock
    time_and_targets: TimeTargetsBlock
    models: ModelsBlock
    evaluation: EvaluationBlock
    outputs: OutputsBlock

    def contract_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def required_null_fields(self, action: Action) -> list[str]:
        """해당 action 에 반드시 채워져 있어야 하는데 null 인 필드 목록."""
        missing: list[str] = []
        if action in ("run", "evaluate", "dry_run"):
            checks = {
                "actual_repository_revision": self.actual_repository_revision,
                "environment_lock_hash": self.environment_lock_hash,
                "inherit.protected_manifest_hash": self.inherit.protected_manifest_hash,
                "time_and_targets.replay_mode": self.time_and_targets.replay_mode,
                "time_and_targets.availability_policy_hash": self.time_and_targets.availability_policy_hash,
                "time_and_targets.source_registry_hash": self.time_and_targets.source_registry_hash,
                "time_and_targets.calendar_hash": self.time_and_targets.calendar_hash,
                "time_and_targets.target_spec_hash": self.time_and_targets.target_spec_hash,
                "time_and_targets.eligibility_rule_hash": self.time_and_targets.eligibility_rule_hash,
                "time_and_targets.label_revision_policy_hash": self.time_and_targets.label_revision_policy_hash,
                "time_and_targets.max_issuance_latency_seconds": self.time_and_targets.max_issuance_latency_seconds,
                "evaluation.evidence_track": self.evaluation.evidence_track,
            }
            missing.extend(name for name, value in checks.items() if value is None)
        if action in ("run", "evaluate"):
            checks = {
                "execution.read_scope_receipt_id": self.execution.read_scope_receipt_id,
                "execution.allowed_input_manifest_hash": self.execution.allowed_input_manifest_hash,
                "execution.experiment_budget_receipt_id": self.execution.experiment_budget_receipt_id,
                "evaluation.primary_metric_spec_hash": self.evaluation.primary_metric_spec_hash,
                "evaluation.primary_comparison_manifest_hash": self.evaluation.primary_comparison_manifest_hash,
                "evaluation.minimum_practical_effect_in_score_units": self.evaluation.minimum_practical_effect_in_score_units,
                "evaluation.family_manifest_hash": self.evaluation.family_manifest_hash,
                "evaluation.bootstrap_replicates": self.evaluation.bootstrap_replicates,
                "evaluation.mean_block_length_in_origin_grid_rows": self.evaluation.mean_block_length_in_origin_grid_rows,
                "evaluation.random_seed_manifest_hash": self.evaluation.random_seed_manifest_hash,
                "evaluation.degenerate_replicate_policy_hash": self.evaluation.degenerate_replicate_policy_hash,
            }
            missing.extend(name for name, value in checks.items() if value is None)
        return missing


class ValidationReport(_Frozen):
    action: Action
    ok: bool
    blockers: tuple[str, ...]
    notes: tuple[str, ...] = ()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MtsContractError(f"계약 파일 없음: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MtsContractError(f"계약이 mapping 이 아님: {path}")
    return payload


def load_research_contract(path: Path, root: Path) -> tuple[ResearchContract, list[str]]:
    """계약 로드 + 상속 계약과의 충돌 검사. (contract, conflicts) 반환.

    충돌이 있어도 예외를 던지지 않고 목록으로 반환한다 — validate 가 보고하고,
    run 류 action 이 차단한다.
    """
    raw = _load_yaml(path)
    try:
        contract = ResearchContract(**raw)
    except Exception as exc:  # pydantic ValidationError 포함
        raise MtsContractError(f"연구 계약 schema 위반: {exc}") from exc

    conflicts: list[str] = []

    # 헌법 수준 고정값 (어떤 action 에서도 틀리면 충돌)
    if contract.execution.auto_promote:
        conflicts.append("execution.auto_promote 는 false 여야 한다 (§18.1)")
    if contract.execution.production_publish_enabled:
        conflicts.append("execution.production_publish_enabled 는 false 여야 한다 (§18.1)")
    if contract.models.learned_ensemble_enabled:
        conflicts.append("learned_ensemble 은 해소 200+ 게이트 전 금지 (CLAUDE.md ML 게이트)")
    if contract.models.foundation_model_integration_enabled:
        conflicts.append("foundation model 통합은 이 설계서가 활성화하지 않는다 (§22.1)")
    if contract.models.conformal_enabled:
        conflicts.append("conformal 은 §10.5 조건 충족 전 기본 OFF")
    if contract.evaluation.sequential_evidence_enabled:
        conflicts.append("sequential evidence 는 §15.3 조건 충족 전 기본 OFF")
    if not contract.evaluation.legacy_gates_unchanged:
        conflicts.append("legacy_gates_unchanged=false — 기존 게이트 변경은 범위 밖 (§2.2)")
    if not contract.evaluation.original_grid_and_eligibility_mask_resampled_together:
        conflicts.append("원 grid+eligibility mask 공동 재표집은 필수 (§13.1)")
    if contract.time_and_targets.partial_censoring_training_enabled:
        conflicts.append("부분 검열 학습은 별도 censoring 계약 필요 (§4.6)")

    # 상속 계약 대조 (read-only)
    try:
        v8 = _load_yaml(root / contract.inherit.v8_contract)
        if v8.get("model_id") != contract.inherit.frozen_price_champion:
            conflicts.append(
                "inherit.frozen_price_champion 이 V8 계약 model_id 와 불일치: "
                f"{contract.inherit.frozen_price_champion} != {v8.get('model_id')}"
            )
        if v8.get("status") != "frozen_for_sealed_evaluation":
            conflicts.append(f"V8 계약 status 변동: {v8.get('status')}")
    except MtsContractError as exc:
        conflicts.append(str(exc))

    try:
        v13 = _load_yaml(root / contract.inherit.v13_contract)
        cells = (v13.get("gates") or {}).get("champion", {}).get("cells", {})
        champions = set(cells.values()) if isinstance(cells, dict) else set()
        if champions and champions != {contract.inherit.frozen_event_champion}:
            conflicts.append(
                "inherit.frozen_event_champion 이 V13 챔피언 셀과 불일치: "
                f"{contract.inherit.frozen_event_champion} vs {sorted(champions)}"
            )
    except MtsContractError as exc:
        conflicts.append(str(exc))

    for label in ("v14_contract", "daily6m_contract"):
        rel = getattr(contract.inherit, label)
        if not (root / rel).is_file():
            conflicts.append(f"상속 계약 파일 없음: {rel}")

    return contract, conflicts


def validate_for(action: Action, contract: ResearchContract, *, root: Path,
                 conflicts: list[str] | None = None) -> ValidationReport:
    """action 별 실행 가능성 판정. run 은 draft·필수 null·audit_only 에서 거부 (T55)."""
    blockers: list[str] = list(conflicts or [])
    notes: list[str] = []

    # validate/audit 도 run 기준의 미해결 항목을 '보고'는 한다 (§18.1 — 부족한 항목을 구체적으로).
    report_action: Action = action if action in ("run", "evaluate", "dry_run") else "run"
    missing = contract.required_null_fields(report_action)
    if missing:
        message = "필수 null 미해결: " + ", ".join(missing)
        if action in ("run", "evaluate", "dry_run"):
            blockers.append(message)
        else:
            notes.append(message)

    if action in ("run", "evaluate"):
        if contract.state == "draft":
            blockers.append("state=draft — 실자료 실험·평가 거부 (§18.1, T55)")
        if contract.execution.mode == "audit_only":
            blockers.append("execution.mode=audit_only — run/evaluate 불가")
        if action == "run" and not contract.execution.enabled_experiments:
            blockers.append("enabled_experiments 비어 있음 — 등록된 실험 없음")

    return ValidationReport(
        action=action,
        ok=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# fitted/calibration state 검증 (T08, T56)
# ---------------------------------------------------------------------------


def validate_fitted_state(state: FittedStateRef, spec: ForecastSpec) -> None:
    """fit cutoff 가 예측 information cutoff 를 넘으면 차단 (T08)."""
    if state.fit_cutoff_at > spec.information_cutoff_at:
        raise MtsContractError(
            "fit_cutoff_at > information_cutoff_at — 원점 이후 자료로 적합한 상태 주입 금지 (T08): "
            f"{state.fit_cutoff_at.isoformat()} > {spec.information_cutoff_at.isoformat()}"
        )


def validate_calibration_state(state: CalibrationStateRef, spec: ForecastSpec) -> None:
    """보정 상태의 cutoff·라벨 가용성·target/정책 hash 일치 검사 (§17.3-9, T56)."""
    if state.fit_information_cutoff_at > spec.information_cutoff_at:
        raise MtsContractError(
            "calibration fit cutoff 가 예측 cutoff 이후 — 미래 보정 상태 주입 금지 (T56)"
        )
    if state.max_used_label_available_at is not None:
        if state.max_used_label_available_at > spec.information_cutoff_at:
            raise MtsContractError(
                "보정 학습에 쓴 라벨의 available_at 이 예측 cutoff 이후 — 미래 라벨 보정 금지 (T56)"
            )
    if state.target_spec_hash != spec.target_spec_hash:
        raise MtsContractError("보정 상태와 예측의 target_spec_hash 불일치 — 다른 표적 보정기 혼용 금지")


# ---------------------------------------------------------------------------
# baseline 등록 가드 (T21)
# ---------------------------------------------------------------------------

_FORBIDDEN_BASELINE_KINDS = {"expectation_threshold_indicator"}


def register_baseline(kind: str, *, baseline_id: str) -> dict[str, Any]:
    """기대값에 임계 indicator 를 적용한 값은 사건확률 baseline 으로 등록 거부 (T21, §4.5-2)."""
    if kind in _FORBIDDEN_BASELINE_KINDS:
        raise MtsContractError(
            f"baseline '{baseline_id}' (kind={kind}) 등록 거부 — 분산 기대값의 임계 indicator 는 "
            "사건확률이 아니다 (not_a_probability, §4.5-2·T21)"
        )
    return {"baseline_id": baseline_id, "kind": kind, "registered": True}


# ---------------------------------------------------------------------------
# 보호 창 + read-scope 가드 (T50)
# ---------------------------------------------------------------------------


class ProtectedWindow(_Frozen):
    window_id: str
    date_start: str
    date_end: str | None  # None = 열린 끝 (sealed 2019+ 류)
    guarded_purposes: tuple[str, ...]


# 감사·동결출력 재현은 이미 공개된 산출물의 legacy reproduction 이므로 보호 창 가드의
# 대상이 아니다. 보호되는 것은 보호 창 위에서의 **새 후보 적합·평가** 다 (§12.1).
GUARDED_PURPOSES = ("research_fit", "evaluation")
OPEN_PURPOSES = ("audit", "replay_identity")


def protected_windows(root: Path, contract: ResearchContract) -> list[ProtectedWindow]:
    """보호 창을 상속 계약에서 파생한다 — 하드코딩 금지."""
    windows: list[ProtectedWindow] = []
    v8 = _load_yaml(root / contract.inherit.v8_contract)
    model_windows = (v8.get("model") or {}).get("windows") or {}

    def _iso(value: Any) -> str:
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    holdout = model_windows.get("holdout")
    if holdout:
        windows.append(ProtectedWindow(
            window_id="v8_holdout",
            date_start=_iso(holdout[0]),
            date_end=_iso(holdout[1]),
            guarded_purposes=GUARDED_PURPOSES,
        ))
    sealed = model_windows.get("sealed")
    if sealed:
        end = None if str(sealed[1]) == "latest" else _iso(sealed[1])
        windows.append(ProtectedWindow(
            window_id="v8_sealed",
            date_start=_iso(sealed[0]),
            date_end=end,
            guarded_purposes=GUARDED_PURPOSES,
        ))
    # V13 홀드아웃(2015-2018)은 v8 holdout 과 동일 창이지만 별도 ID 로 추적한다.
    v13 = _load_yaml(root / contract.inherit.v13_contract)
    v13_holdout = ((v13.get("stopping_points") or {}).get("holdout") or {}).get("window")
    if v13_holdout:
        windows.append(ProtectedWindow(
            window_id="v13_holdout",
            date_start=_iso(v13_holdout[0]),
            date_end=_iso(v13_holdout[1]),
            guarded_purposes=GUARDED_PURPOSES,
        ))
    return windows


def _overlaps(window: ProtectedWindow, start: str, end: str | None) -> bool:
    if window.date_end is not None and start > window.date_end:
        return False
    if end is not None and end < window.date_start:
        return False
    return True


class ScopeCheck(_Frozen):
    allowed: bool
    windows_hit: tuple[str, ...]
    receipt_id: str | None
    reason_codes: tuple[str, ...]


def _load_receipt(root: Path, receipt_id: str) -> dict[str, Any] | None:
    path = root / APPROVALS_LEDGER_RELATIVE
    if not path.is_file():
        return None
    import json

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("receipt_id") == receipt_id:
            return row
    return None


def read_scope_guard(
    root: Path,
    contract: ResearchContract,
    *,
    requested_series: set[str],
    requested_window: tuple[str, str | None],
    purpose: str,
    run_id: str,
    record_exposure=None,
) -> ScopeCheck:
    """모든 보호 payload read 이전에 호출한다 (T50).

    - purpose ∈ OPEN_PURPOSES: 이미 공개된 산출물의 재현·감사 — 허용하되 노출 기록.
    - purpose ∈ GUARDED_PURPOSES 이고 요청 창이 보호 창과 겹치면: 계약의
      read_scope_receipt_id 영수증 scope 가 요청을 포함해야 한다.
      ``protected_holdout_read_enabled: true`` 하나만으로는 불충분 (§18.1).
    - 거부 시에도 노출 원장에 allowed=False 를 append 한 뒤 MtsScopeError.
    """
    start, end = requested_window
    hits = tuple(
        w.window_id
        for w in protected_windows(root, contract)
        if purpose in w.guarded_purposes and _overlaps(w, start, end)
    )

    def _log(allowed: bool, reasons: tuple[str, ...]) -> None:
        if record_exposure is not None:
            record_exposure(
                root,
                run_id=run_id,
                purpose=purpose,
                series=sorted(requested_series),
                window=[start, end],
                windows_hit=list(hits),
                allowed=allowed,
                reason_codes=list(reasons),
            )

    if purpose in OPEN_PURPOSES or not hits:
        _log(True, ())
        return ScopeCheck(allowed=True, windows_hit=hits, receipt_id=None, reason_codes=())

    reasons: list[str] = []
    receipt_id = contract.execution.read_scope_receipt_id
    if receipt_id is None:
        reasons.append("READ_SCOPE_RECEIPT_MISSING")
    receipt = _load_receipt(root, receipt_id) if receipt_id else None
    if receipt_id and receipt is None:
        reasons.append("RECEIPT_NOT_FOUND_IN_APPROVALS_LEDGER")
    if receipt is not None:
        scope = receipt.get("approval_scope") or {}
        allowed_windows = set(scope.get("windows") or [])
        allowed_series = set(scope.get("series") or [])
        allowed_purposes = set(scope.get("purposes") or [])
        if not set(hits) <= allowed_windows:
            reasons.append("RECEIPT_WINDOW_SCOPE_INSUFFICIENT")
        if not requested_series <= allowed_series:
            reasons.append("RECEIPT_SERIES_SCOPE_INSUFFICIENT")
        if purpose not in allowed_purposes:
            reasons.append("RECEIPT_PURPOSE_SCOPE_INSUFFICIENT")
    if not contract.execution.protected_holdout_read_enabled:
        reasons.append("PROTECTED_READ_FLAG_DISABLED")

    if reasons:
        check = ScopeCheck(allowed=False, windows_hit=hits, receipt_id=receipt_id,
                           reason_codes=tuple(reasons))
        _log(False, check.reason_codes)
        raise MtsScopeError(
            "보호 창 접근 거부 (데이터 read 이전): "
            + ", ".join(check.reason_codes)
            + f" — windows={list(hits)}"
        )

    check = ScopeCheck(allowed=True, windows_hit=hits, receipt_id=receipt_id, reason_codes=())
    _log(True, ())
    return check
