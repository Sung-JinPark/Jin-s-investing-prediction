"""T02 — 질문 포트폴리오 사전등록 계약의 **집행 훅**.

계약 원문은 `questions/portfolio_prereg_v1.yaml` 이고 이 모듈은 그것을 읽어 등록을 검증한다.
계약이 없으면 **모든 신규 등록을 거부한다** — 규칙 없이 등록하는 것이 이 태스크가 막으려는 것이다.

## 왜 등록 시점에 막는가

P3 게이트의 기대 성적 바닥은 **질문을 고르는 순간** 정해진다. 완전 캘리브레이션 하의 기대
Brier 가 `E[p(1−p)]` 이기 때문이다. 정직 확률이 사구간 `[0.235, 0.765]` 에 떨어지는 질문은
실력과 무관하게 문턱 위 성적을 낸다. 예측을 잘해서 만회할 수 없고, 사후에 빼면 표본 선택이다.
그래서 **등록을 막는 것이 유일한 정직한 개입 지점**이다.

이 모듈은 성적을 보지 않는다. 원장을 읽지 않으며 등록 후보의 z·σ 만 본다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_RELATIVE = Path("questions/portfolio_prereg_v1.yaml")


class PortfolioPreregError(RuntimeError):
    """계약 부재 또는 등록 규칙 위반."""


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str
    uses_exception_slot: bool = False


def load_contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        raise PortfolioPreregError(
            "질문 포트폴리오 사전등록 계약이 없다 — 신규 등록은 계약 커밋 이후에만 가능하다 "
            f"({CONTRACT_RELATIVE})")
    import yaml

    contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not contract.get("registered_before_results"):
        raise PortfolioPreregError("계약이 결과 전 등록임을 선언하지 않았다")
    return contract


def expected_brier_floor(honest_probability: float) -> float:
    """완전 캘리브레이션 하의 기대 Brier = p(1−p)."""
    p = float(honest_probability)
    return p * (1.0 - p)


def evaluate_candidate(contract: dict[str, Any], candidate: dict[str, Any], *,
                       exception_slots_used: int = 0) -> Decision:
    """등록 후보 하나를 계약에 비춰 판정한다. 성적은 보지 않는다."""
    z_rule = contract.get("z_rule") or {}
    dead = contract.get("dead_zone") or {}
    band = dead.get("band") or [0.235, 0.765]
    cap = float(dead.get("per_question_expected_brier_cap") or 0.21)
    slot_max = int(z_rule.get("exception_slot_max") or 0)

    for field in ("z", "sigma", "sigma_source", "honest_probability_estimate"):
        value = candidate.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return Decision(False, f"필수 항목 누락: {field} — 계약 z_rule.required_fields_on_registration")

    domain = str(candidate.get("domain") or "")
    mix = contract.get("domain_mix") or {}
    if domain == "market-daily" and (mix.get("market_daily") or {}).get("status") == "permanently_excluded":
        return Decision(False, "market-daily 는 영구 제외(coin_flip) — 계약 domain_mix.market_daily")

    p = float(candidate["honest_probability_estimate"])
    if not 0.0 < p < 1.0:
        return Decision(False, f"정직 확률이 (0,1) 밖: {p}")
    if band[0] <= p <= band[1]:
        return Decision(False,
                        f"사구간 [{band[0]}, {band[1]}] 안({p:.3f}) — 완전 캘리브레이션이어도 "
                        f"기대 Brier {expected_brier_floor(p):.4f} 로 문턱 위다")

    floor = expected_brier_floor(p)
    z = float(candidate["z"])
    if z < 0.7:
        return Decision(False, f"z={z:.3f} < 0.7 — 계약 z_rule.bands.reject")

    needs_slot = z < 1.0 or floor > cap
    if needs_slot:
        if exception_slots_used >= slot_max:
            return Decision(False,
                            f"예외 슬롯 소진({exception_slots_used}/{slot_max}) — "
                            f"z={z:.3f}, 기대 Brier {floor:.4f}")
        why = []
        if z < 1.0:
            why.append(f"z={z:.3f} < 1.0")
        if floor > cap:
            why.append(f"기대 Brier {floor:.4f} > 문항 상한 {cap}")
        return Decision(True, "예외 슬롯 사용 — " + " · ".join(why), uses_exception_slot=True)

    return Decision(True, f"z={z:.3f} >= 1.0 · 기대 Brier {floor:.4f} <= {cap}")


def evaluate_batch(contract: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """후보 묶음을 순서대로 판정한다 — 예외 슬롯은 선착순으로 소모된다.

    슬롯을 성적이 좋아 보이는 순서로 배분하면 그것이 곧 선택 편향이므로, 입력 순서를 그대로 쓴다.
    """
    used = 0
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        decision = evaluate_candidate(contract, candidate, exception_slots_used=used)
        if decision.accepted and decision.uses_exception_slot:
            used += 1
        out.append({"id": candidate.get("id"), "accepted": decision.accepted,
                    "reason": decision.reason, "used_exception_slot": decision.uses_exception_slot,
                    "z": candidate.get("z"),
                    "honest_probability_estimate": candidate.get("honest_probability_estimate"),
                    "expected_brier_floor": round(
                        expected_brier_floor(candidate["honest_probability_estimate"]), 5)
                    if candidate.get("honest_probability_estimate") is not None else None})
    return out


def registration_allowed(root: Path) -> tuple[bool, str]:
    """신규 등록이 열려 있는가 — 계약 부재면 닫힌다."""
    try:
        contract = load_contract(root)
    except PortfolioPreregError as exc:
        return False, str(exc)
    plan = contract.get("new_registration") or {}
    if plan.get("user_approval_required") and not plan.get("user_approved_list"):
        return False, ("계약은 커밋됐으나 최종 목록에 대한 사용자 승인이 기록되지 않았다 — "
                       "new_registration.user_approved_list 가 비어 있다")
    return True, "등록 가능"
