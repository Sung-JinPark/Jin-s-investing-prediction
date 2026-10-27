"""§15.1 신규 evidence gate — E0~E8 판정 객체와 결과 축 분리.

- 기존 V8/V13 계약을 대체하는 임계표가 아니다. legacy gate 는 기존 구현이 재현한다.
- 추정이 실행됐다는 것과 증거가 충분하다는 것은 다른 판정이다 (T46).
- 귀무 통과율(passes/B)과 Monte Carlo permutation p((1+c)/(B+1))는 다른 통계다 (T45).
- calibration/coherence/incremental_skill/operational 은 하나의 '예측 정확도 상승' 으로
  합쳐 쓰지 않는다 (§3.3, T54).
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict

from ..timeseries_v8.contracts import canonical_hash

GateId = Literal["E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]
GateStatus = Literal["PASS", "HOLD", "FAIL"]

REASON_CODES: dict[str, str] = {
    "E0": "BASELINE_MISMATCH",
    "E1": "DATA_INVALID",
    "E2": "COHERENCE_FAILED",
    "E3": "EVIDENCE_INSUFFICIENT",
    "E4": "NO_INCREMENTAL_EVIDENCE",
    "E5": "CALIBRATION_FAILED",
    "E6": "FRAGILE_RESULT",
    "E7": "OPERATIONAL_HOLD",
    "E8": "AWAITING_AUTHORIZATION",
}


class MtsGateError(RuntimeError):
    """게이트 계약 위반 — fail-closed."""


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: GateId
    status: GateStatus
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    inputs_hash: str
    contract_hash: str

    @classmethod
    def build(
        cls, gate_id: GateId, *, status: GateStatus, contract_hash: str,
        inputs: Mapping[str, Any], evidence_refs: tuple[str, ...] = (),
        extra_reasons: tuple[str, ...] = (),
    ) -> "GateResult":
        reasons: tuple[str, ...] = extra_reasons
        if status != "PASS" and not reasons:
            reasons = (REASON_CODES[gate_id],)
        return cls(
            gate_id=gate_id, status=status, reason_codes=reasons,
            evidence_refs=evidence_refs, inputs_hash=canonical_hash(dict(inputs)),
            contract_hash=contract_hash,
        )


class ResultAxes(BaseModel):
    """§3.3 — 실험 결과의 네 축. 단일 숫자로 합치는 API 를 제공하지 않는다 (T54)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    calibration_pass: bool | None    # None = 미판정
    coherence_pass: bool | None
    incremental_skill_pass: bool | None
    operational_pass: bool | None

    def claim(self) -> dict[str, str]:
        """각 축의 허용 가능한 서술 — '예측 정확도 상승' 단일 문구 생성 금지."""
        names = {
            "calibration_pass": "보정 개선 후보",
            "coherence_pass": "정합성 개선",
            "incremental_skill_pass": "예측력 개선 증거",
            "operational_pass": "운영 개선",
        }
        out: dict[str, str] = {}
        for field, label in names.items():
            value = getattr(self, field)
            out[field] = ("미판정" if value is None else (label if value else f"{label} 아님"))
        return out


class NullDiagnostics(BaseModel):
    """T45 — 귀무 통과율과 MC permutation p 를 별개 필드로 보관한다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    surrogate_runs: int
    surrogate_passes: int
    observed_statistic: float
    surrogate_at_least_as_extreme: int

    @property
    def legacy_null_pass_rate(self) -> float:
        if self.surrogate_runs < 1:
            raise MtsGateError("surrogate_runs >= 1")
        return self.surrogate_passes / self.surrogate_runs

    @property
    def monte_carlo_permutation_p(self) -> float:
        """(1 + c) / (B + 1) — 0 이 될 수 없다 (§13.7, Phipson–Smyth)."""
        return (1 + self.surrogate_at_least_as_extreme) / (self.surrogate_runs + 1)


def sample_sufficiency_gate(
    *, contract_hash: str, n_origin: int, n_positive: int, n_episode: int,
    minimum_origins: int, minimum_positive: int, minimum_episodes: int,
    estimate_succeeded: bool, uncertainty_acceptable: bool,
) -> GateResult:
    """E3 — 추정 성공 != 증거 충분 (T46).

    최저 guard 를 넘겨도 불확실성이 크면 EVIDENCE_INSUFFICIENT.
    """
    inputs = {
        "n_origin": n_origin, "n_positive": n_positive, "n_episode": n_episode,
        "minimum_origins": minimum_origins, "minimum_positive": minimum_positive,
        "minimum_episodes": minimum_episodes, "estimate_succeeded": estimate_succeeded,
        "uncertainty_acceptable": uncertainty_acceptable,
    }
    reasons: list[str] = []
    if n_origin < minimum_origins:
        reasons.append(f"n_origin {n_origin} < {minimum_origins}")
    if n_positive < minimum_positive:
        reasons.append(f"n_positive {n_positive} < {minimum_positive}")
    if n_episode < minimum_episodes:
        reasons.append(f"n_episode {n_episode} < {minimum_episodes}")
    if not uncertainty_acceptable:
        reasons.append("불확실성 과대 — 추정 성공과 무관 (T46)")
    status: GateStatus = "PASS" if not reasons else "HOLD"
    return GateResult.build(
        "E3", status=status, contract_hash=contract_hash, inputs=inputs,
        extra_reasons=tuple([REASON_CODES["E3"], *reasons]) if reasons else (),
    )


def enforce_candidate_failure_policy(
    *,
    contract_hash: str,
    policy: str,
    candidate_failure_count: int,
    evidence_refs: tuple[str, ...] = (),
) -> GateResult:
    """E7 — 계약의 candidate_failure_policy 를 실제로 집행한다 (외부 리뷰 F02, 2026-10-27).

    `hold_confirmatory_verdict`: eligible 원점에서 후보 실패가 1건이라도 있으면 확증
    판정을 HOLD — 성공 원점만의 paired 평균(성공 교집합)으로 확증하지 않는다.
    실패를 평가에서 지우는 정책(NOT_ELIGIBLE 재분류·결측 대체)은 등록 불가.
    """
    if policy != "hold_confirmatory_verdict":
        raise MtsGateError(f"등록되지 않은 candidate_failure_policy: {policy}")
    if candidate_failure_count < 0:
        raise MtsGateError("failure_count >= 0")
    inputs = {"policy": policy, "candidate_failure_count": candidate_failure_count}
    if candidate_failure_count == 0:
        return GateResult.build(
            "E7", status="PASS", contract_hash=contract_hash, inputs=inputs,
            evidence_refs=evidence_refs,
        )
    return GateResult.build(
        "E7", status="HOLD", contract_hash=contract_hash, inputs=inputs,
        evidence_refs=evidence_refs,
        extra_reasons=(
            REASON_CODES["E7"],
            f"후보 실패 {candidate_failure_count}건 — 확증 판정 보류 (F02, "
            "성공 교집합 평균으로 확증 금지)",
        ),
    )


def evaluate_gates(
    *, contract_hash: str, gate_inputs: Mapping[GateId, Mapping[str, Any]],
    required_nulls_resolved: bool,
) -> dict[str, Any]:
    """등록된 입력으로 E0~E8 을 일괄 판정한다.

    - 미정 입력(gate 누락)은 자동 PASS 가 아니라 HOLD 다 (§15.1 — 미정인 채 PASS 금지).
    - 필수 null 미해결 계약으로는 어떤 gate 도 PASS 하지 않는다 (T55 연계).
    """
    results: list[GateResult] = []
    for gate_id in ("E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"):
        inputs = gate_inputs.get(gate_id)  # type: ignore[arg-type]
        if inputs is None or not required_nulls_resolved:
            results.append(GateResult.build(
                gate_id, status="HOLD", contract_hash=contract_hash,  # type: ignore[arg-type]
                inputs={"missing": True},
                extra_reasons=(REASON_CODES[gate_id], "입력 미등록 또는 필수 null 미해결"),
            ))
            continue
        status: GateStatus = "PASS" if inputs.get("pass") is True else (
            "FAIL" if inputs.get("fail") is True else "HOLD"
        )
        results.append(GateResult.build(
            gate_id, status=status, contract_hash=contract_hash,  # type: ignore[arg-type]
            inputs=inputs,
            evidence_refs=tuple(inputs.get("evidence_refs", ())),
        ))
    overall = (
        "PASS" if all(r.status == "PASS" for r in results)
        else ("FAIL" if any(r.status == "FAIL" for r in results) else "HOLD")
    )
    return {"overall": overall, "gates": results}
