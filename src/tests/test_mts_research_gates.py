"""evidence gate 테스트 — T45·T46·T54 + 미등록 입력의 자동 PASS 금지."""

from __future__ import annotations

import pytest

from ai_fc.mts_research.gates import (
    GateResult,
    MtsGateError,
    NullDiagnostics,
    ResultAxes,
    evaluate_gates,
    sample_sufficiency_gate,
)


def test_t45_null_pass_rate_vs_permutation_p_distinct():
    """귀무 통과율 0 과 MC permutation p 는 다른 통계 — p 는 0 이 될 수 없다 (T45)."""
    diagnostics = NullDiagnostics(
        surrogate_runs=2000, surrogate_passes=0,
        observed_statistic=-0.12, surrogate_at_least_as_extreme=0,
    )
    assert diagnostics.legacy_null_pass_rate == 0.0
    assert diagnostics.monte_carlo_permutation_p == pytest.approx(1 / 2001)
    assert diagnostics.monte_carlo_permutation_p > 0.0


def test_t46_estimate_success_is_not_evidence():
    """guard 수치를 넘겨도 불확실성이 크면 EVIDENCE_INSUFFICIENT (T46)."""
    passing = sample_sufficiency_gate(
        contract_hash="ch", n_origin=80, n_positive=25, n_episode=6,
        minimum_origins=60, minimum_positive=20, minimum_episodes=5,
        estimate_succeeded=True, uncertainty_acceptable=True,
    )
    assert passing.status == "PASS"
    wide = sample_sufficiency_gate(
        contract_hash="ch", n_origin=80, n_positive=25, n_episode=6,
        minimum_origins=60, minimum_positive=20, minimum_episodes=5,
        estimate_succeeded=True, uncertainty_acceptable=False,
    )
    assert wide.status == "HOLD"
    assert "EVIDENCE_INSUFFICIENT" in wide.reason_codes
    thin = sample_sufficiency_gate(
        contract_hash="ch", n_origin=80, n_positive=12, n_episode=3,
        minimum_origins=60, minimum_positive=20, minimum_episodes=5,
        estimate_succeeded=True, uncertainty_acceptable=True,
    )
    assert thin.status == "HOLD" and any("n_episode" in r for r in thin.reason_codes)


def test_t54_result_axes_stay_separate():
    """calibration/coherence/skill/운영은 하나의 문구로 합쳐지지 않는다 (T54, §3.3)."""
    axes = ResultAxes(
        calibration_pass=None, coherence_pass=True,
        incremental_skill_pass=False, operational_pass=True,
    )
    claims = axes.claim()
    assert claims["coherence_pass"] == "정합성 개선"
    assert claims["incremental_skill_pass"] == "예측력 개선 증거 아님"
    assert claims["calibration_pass"] == "미판정"
    assert claims["operational_pass"] == "운영 개선"
    assert not hasattr(axes, "overall_accuracy")  # 단일 합산 API 를 제공하지 않는다


def test_unregistered_gate_inputs_hold_not_pass():
    """입력이 미등록인 gate 는 자동 PASS 가 아니라 HOLD (§15.1)."""
    verdict = evaluate_gates(
        contract_hash="ch",
        gate_inputs={"E0": {"pass": True}, "E2": {"pass": True}},
        required_nulls_resolved=True,
    )
    by_id = {g.gate_id: g for g in verdict["gates"]}
    assert by_id["E0"].status == "PASS" and by_id["E2"].status == "PASS"
    assert by_id["E4"].status == "HOLD"
    assert "NO_INCREMENTAL_EVIDENCE" in by_id["E4"].reason_codes
    assert verdict["overall"] == "HOLD"

    blocked = evaluate_gates(
        contract_hash="ch",
        gate_inputs={gid: {"pass": True} for gid in
                     ("E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8")},
        required_nulls_resolved=False,
    )
    assert blocked["overall"] == "HOLD"  # 필수 null 미해결 — 어떤 gate 도 PASS 금지


def test_gate_result_reason_codes():
    result = GateResult.build(
        "E1", status="FAIL", contract_hash="ch", inputs={"pit_leaks": 2},
    )
    assert result.reason_codes == ("DATA_INVALID",)
    ok = GateResult.build("E1", status="PASS", contract_hash="ch", inputs={"pit_leaks": 0})
    assert ok.reason_codes == ()


def test_null_diagnostics_guard():
    with pytest.raises(MtsGateError):
        NullDiagnostics(
            surrogate_runs=0, surrogate_passes=0,
            observed_statistic=0.0, surrogate_at_least_as_extreme=0,
        ).legacy_null_pass_rate
