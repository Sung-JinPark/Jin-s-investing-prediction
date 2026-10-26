"""mts_research 계약·레코드·scope 가드 테스트 — T08·T21·T50·T55·T56 + 등록 단언.

합성 데이터는 tmp_path 아래에만 만들고, 실계약 yaml 은 사본으로 읽기만 한다.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from ai_fc.mts_research import artifacts
from ai_fc.mts_research.contracts import (
    DRAFT_CONTRACT_RELATIVE,
    MtsContractError,
    MtsScopeError,
    SourceSpec,
    load_research_contract,
    protected_windows,
    read_scope_guard,
    register_baseline,
    validate_calibration_state,
    validate_fitted_state,
    validate_for,
)
from ai_fc.mts_research.records import (
    CalibrationStateRef,
    FittedStateRef,
    ForecastArtifact,
    ForecastDraft,
    MtsRecordError,
)
from mts_research_fixtures import (
    ROOT,
    load_draft,
    make_ready_draft,
    make_spec,
    research_root,
    utc,
    write_approval_receipt,
)


# ---------------------------------------------------------------------------
# 레코드 불변조건 (§17.3)
# ---------------------------------------------------------------------------


def test_naive_datetime_rejected():
    """timezone 없는 datetime 은 어떤 레코드에도 들어갈 수 없다 (§17.3-1)."""
    with pytest.raises(Exception):
        make_spec(information_cutoff_at=datetime(2026, 10, 20, 21, 30))


def test_issued_requires_payload_and_hold_forbids_it():
    """ISSUED 는 payload·state 필수, HOLD 는 payload 금지 — 가짜 0 차단 (§17.3-3)."""
    with pytest.raises(Exception):
        make_ready_draft(payload_ref=None, payload_hash=None)
    with pytest.raises(Exception):
        ForecastDraft(
            model_id="m",
            spec=make_spec(),
            state_id=None,
            calibration_state_id=None,
            prediction_status="HOLD",
            payload_ref="x.json",
            payload_hash="h",
            capabilities=(),
            reason_codes=("DATA_INVALID",),
        )


def test_issued_at_cannot_precede_cutoff():
    """issued_at < information_cutoff_at 인 artifact 는 생성 불가 (§17.3-4)."""
    spec = make_spec()
    with pytest.raises(Exception):
        ForecastArtifact(
            forecast_id="f1",
            logical_forecast_key="k1",
            reconstruction_of_forecast_id=None,
            model_id="m",
            spec=spec,
            issued_at=utc(2026, 10, 19),
            replay_mode="operational_replay",
            evidence_track="historical_research",
            status="HOLD",
            state_id=None,
            calibration_state_id=None,
            payload_ref=None,
            payload_hash=None,
            capabilities=(),
            reason_codes=("DATA_INVALID",),
            contract_hash="c",
        )


def test_calibration_identity_null_rule():
    """max_used_label_available_at=None 은 identity method 에만 허용 (§17.3-9)."""
    with pytest.raises(Exception):
        CalibrationStateRef(
            calibration_state_id="cal-1",
            fit_information_cutoff_at=utc(2026, 10, 1),
            oof_cohort_manifest_hash="h",
            max_used_label_available_at=None,
            target_spec_hash="t" * 16,
            label_revision_policy_hash="l",
            method="intercept_only",
        )


# ---------------------------------------------------------------------------
# T08 / T56 — 상태 cutoff 검증
# ---------------------------------------------------------------------------


def _fitted(fit_cutoff: datetime) -> FittedStateRef:
    return FittedStateRef(
        state_id="s1",
        state_hash="h",
        model_id="m",
        code_hash="c",
        training_manifest_id="tm",
        fit_cutoff_at=fit_cutoff,
        environment_lock_hash="env",
    )


def test_t08_fit_cutoff_after_information_cutoff_blocked():
    """원점 이후 자료로 적합한 상태는 fit cutoff mismatch 로 차단 (T08)."""
    spec = make_spec()
    validate_fitted_state(_fitted(utc(2026, 10, 20, 21, 30)), spec)  # 경계 동일은 허용
    with pytest.raises(MtsContractError):
        validate_fitted_state(_fitted(utc(2026, 10, 21)), spec)


def test_t56_future_label_calibrator_blocked():
    """예측 cutoff 뒤 라벨로 적합한 calibrator state 주입 차단 (T56)."""
    spec = make_spec()
    good = CalibrationStateRef(
        calibration_state_id="cal-1",
        fit_information_cutoff_at=utc(2026, 10, 1),
        oof_cohort_manifest_hash="h",
        max_used_label_available_at=utc(2026, 9, 30),
        target_spec_hash=spec.target_spec_hash,
        label_revision_policy_hash="l",
        method="intercept_only",
    )
    validate_calibration_state(good, spec)
    with pytest.raises(MtsContractError):
        validate_calibration_state(
            good.model_copy(update={"max_used_label_available_at": utc(2026, 10, 21)}), spec
        )
    with pytest.raises(MtsContractError):
        validate_calibration_state(
            good.model_copy(update={"fit_information_cutoff_at": utc(2026, 10, 21)}), spec
        )
    with pytest.raises(MtsContractError):
        validate_calibration_state(
            good.model_copy(update={"target_spec_hash": "다른표적"}), spec
        )


# ---------------------------------------------------------------------------
# T21 — 기대값 indicator 를 확률 baseline 으로 등록 거부
# ---------------------------------------------------------------------------


def test_t21_expectation_indicator_baseline_refused():
    register_baseline("window_mechanics_probability", baseline_id="wm1")
    with pytest.raises(MtsContractError):
        register_baseline("expectation_threshold_indicator", baseline_id="ev1")


# ---------------------------------------------------------------------------
# T55 — draft 필수 null / 상속 충돌 → run 차단, 합성 검증은 계속
# ---------------------------------------------------------------------------


def test_t55_draft_contract_blocks_run_but_allows_validate(tmp_path: Path):
    root = research_root(tmp_path)
    contract, conflicts = load_draft(root)
    assert conflicts == [], f"초안이 상속 계약과 충돌하면 안 된다: {conflicts}"

    run_report = validate_for("run", contract, root=root, conflicts=conflicts)
    assert not run_report.ok
    joined = " / ".join(run_report.blockers)
    assert "state=draft" in joined
    assert "필수 null 미해결" in joined
    assert "audit_only" in joined

    validate_report = validate_for("validate", contract, root=root, conflicts=conflicts)
    assert validate_report.ok
    assert any("필수 null" in note for note in validate_report.notes)


def test_t55_inheritance_conflict_detected(tmp_path: Path):
    """상속 챔피언 ID 가 틀리면 조용한 덮어쓰기 대신 충돌로 보고된다 (§18.1)."""
    root = research_root(tmp_path)
    draft_path = root / DRAFT_CONTRACT_RELATIVE
    payload = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    payload["inherit"]["frozen_price_champion"] = "wrong.model_id"
    payload["execution"]["auto_promote"] = True
    draft_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    contract, conflicts = load_research_contract(draft_path, root)
    assert any("frozen_price_champion" in c for c in conflicts)
    assert any("auto_promote" in c for c in conflicts)
    report = validate_for("run", contract, root=root, conflicts=conflicts)
    assert not report.ok


def test_source_spec_disabled_by_default():
    """§7.4 — 전 좌표 확인 전에는 연구 입력으로 켜지지 않는다."""
    spec = SourceSpec(source_id="cboe_datashop_options")
    allowed, reasons = spec.research_input_allowed()
    assert not allowed
    assert "SOURCE_DISABLED" in reasons and "ENTITLEMENT_UNVERIFIED" in reasons


# ---------------------------------------------------------------------------
# T50 — 보호 창 read-scope 가드 (거부도 감사 기록)
# ---------------------------------------------------------------------------


def test_protected_windows_derived_from_contracts(tmp_path: Path):
    root = research_root(tmp_path)
    contract, _ = load_draft(root)
    windows = {w.window_id: w for w in protected_windows(root, contract)}
    assert windows["v8_holdout"].date_start == "2015-01-01"
    assert windows["v8_holdout"].date_end == "2018-12-31"
    assert windows["v8_sealed"].date_start == "2019-01-01"
    assert windows["v8_sealed"].date_end is None  # 'latest' → 열린 끝


def test_t50_guarded_purpose_without_receipt_refused_and_audited(tmp_path: Path):
    root = research_root(tmp_path)
    contract, _ = load_draft(root)
    with pytest.raises(MtsScopeError):
        read_scope_guard(
            root,
            contract,
            requested_series={"VIXCLS"},
            requested_window=("2016-01-01", "2017-12-31"),
            purpose="research_fit",
            run_id="run-guard-1",
            record_exposure=artifacts.record_exposure,
        )
    rows = artifacts.read_chain(root, artifacts.EXPOSURE_LEDGER)
    assert len(rows) == 1 and rows[0]["allowed"] is False
    assert "READ_SCOPE_RECEIPT_MISSING" in rows[0]["reason_codes"]
    assert "v8_holdout" in rows[0]["windows_hit"]


def test_t50_audit_purpose_allowed_but_logged(tmp_path: Path):
    root = research_root(tmp_path)
    contract, _ = load_draft(root)
    check = read_scope_guard(
        root,
        contract,
        requested_series={"VIXCLS"},
        requested_window=("2016-01-01", "2026-10-01"),
        purpose="replay_identity",
        run_id="run-guard-2",
        record_exposure=artifacts.record_exposure,
    )
    assert check.allowed
    rows = artifacts.read_chain(root, artifacts.EXPOSURE_LEDGER)
    assert len(rows) == 1 and rows[0]["allowed"] is True


def test_t50_receipt_scope_must_cover_request(tmp_path: Path):
    root = research_root(tmp_path)
    contract, _ = load_draft(root)
    write_approval_receipt(
        root,
        receipt_id="mts-approval:TEST:2026-10-26:r1",
        windows=["v8_holdout", "v13_holdout"],
        series=["VIXCLS"],
        purposes=["research_fit"],
    )
    exec_block = contract.execution.model_copy(update={
        "read_scope_receipt_id": "mts-approval:TEST:2026-10-26:r1",
        "protected_holdout_read_enabled": True,
    })
    granted = contract.model_copy(update={"execution": exec_block})

    check = read_scope_guard(
        root,
        granted,
        requested_series={"VIXCLS"},
        requested_window=("2016-01-01", "2016-12-31"),
        purpose="research_fit",
        run_id="run-guard-3",
    )
    assert check.allowed and check.windows_hit == ("v8_holdout", "v13_holdout")

    # 영수증 series 범위를 벗어나면 거부
    with pytest.raises(MtsScopeError):
        read_scope_guard(
            root,
            granted,
            requested_series={"VIXCLS", "NASDAQCOM"},
            requested_window=("2016-01-01", "2016-12-31"),
            purpose="research_fit",
            run_id="run-guard-4",
        )

    # flag 하나만으로는 불충분 (§18.1): 영수증 없는 사본
    flag_only = contract.model_copy(update={
        "execution": contract.execution.model_copy(update={"protected_holdout_read_enabled": True})
    })
    with pytest.raises(MtsScopeError):
        read_scope_guard(
            root,
            flag_only,
            requested_series={"VIXCLS"},
            requested_window=("2016-01-01", "2016-12-31"),
            purpose="research_fit",
            run_id="run-guard-5",
        )


# ---------------------------------------------------------------------------
# 원장 등록 단언 (V14 패턴) + 실계약 스모크
# ---------------------------------------------------------------------------


def test_mts_ledgers_registered_in_registry():
    registry = yaml.safe_load(
        (ROOT / "data/contracts/ledger_registry.yaml").read_text(encoding="utf-8")
    )
    ids = {entry["id"]: entry for entry in registry["ledgers"]}
    for ledger_id, path in {
        "mts_research_events": "data/mts_research/ledgers/events.jsonl",
        "mts_research_forecasts": "data/mts_research/ledgers/forecasts.jsonl",
        "mts_research_resolutions": "data/mts_research/ledgers/resolutions.jsonl",
        "mts_research_attempts": "data/mts_research/ledgers/attempts.jsonl",
        "mts_research_approvals": "data/mts_research/ledgers/approvals.jsonl",
        "mts_research_exposures": "data/mts_research/ledgers/exposures.jsonl",
    }.items():
        assert ledger_id in ids, f"{ledger_id} 가 ledger_registry.yaml 에 없다"
        assert ids[ledger_id]["path"] == path


def test_real_contracts_load_through_inheritance(tmp_path: Path):
    """실계약 4종이 상속 로더를 통과한다 (메타데이터 스모크)."""
    root = research_root(tmp_path)
    contract, conflicts = load_draft(root)
    assert contract.inherit.frozen_price_champion == "shadow.mf_dfm_varx_calibrated_v8"
    assert contract.inherit.frozen_event_champion == "persistence_pb"
    assert conflicts == []
