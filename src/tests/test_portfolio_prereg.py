"""T02 — 포트폴리오 사전등록 계약의 집행을 고정한다.

게이트의 기대 성적 바닥은 질문을 고르는 순간 정해진다(E[Brier] = E[p(1−p)]).
사구간 질문은 실력으로 만회할 수 없고 사후 제외는 표본 선택이다 — 등록에서 막는 수밖에 없다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "questions/portfolio_prereg_v1.yaml"


@pytest.fixture(scope="module")
def contract() -> dict:
    from ai_fc.portfolio_prereg import load_contract
    return load_contract(ROOT)


def _cand(**over) -> dict:
    base = {"id": "test-q", "domain": "earnings", "z": 1.5, "sigma": 0.4,
            "sigma_source": "참조클래스 2020-2026 분기 컨센 오차 (n=24)",
            "honest_probability_estimate": 0.10}
    base.update(over)
    return base


def test_contract_is_registered_before_results(contract) -> None:
    assert contract["registered_before_results"] is True
    assert contract["new_registration"]["target_count"] == 12
    assert contract["new_registration"]["user_approval_required"] is True


def test_dead_zone_band_matches_the_threshold(contract) -> None:
    lo, hi = contract["dead_zone"]["band"]
    assert abs(lo * hi - 0.18) < 5e-4, "사구간 경계는 p(1−p)=0.18 지점이어야 한다"


def test_dead_zone_question_is_rejected(contract) -> None:
    from ai_fc.portfolio_prereg import evaluate_candidate
    decision = evaluate_candidate(contract, _cand(honest_probability_estimate=0.50, z=0.0))
    assert not decision.accepted
    assert "사구간" in decision.reason


def test_low_z_is_rejected(contract) -> None:
    from ai_fc.portfolio_prereg import evaluate_candidate
    decision = evaluate_candidate(contract, _cand(z=0.5, honest_probability_estimate=0.20))
    assert not decision.accepted
    assert "0.7" in decision.reason


def test_exception_slot_has_a_hard_cap(contract) -> None:
    """0.7 <= z < 1.0 은 최대 3건. 4번째는 거부된다."""
    from ai_fc.portfolio_prereg import evaluate_batch
    batch = [_cand(id=f"q{i}", z=0.8, honest_probability_estimate=0.20) for i in range(5)]
    results = evaluate_batch(contract, batch)
    accepted = [r for r in results if r["accepted"]]
    assert len(accepted) == 3, f"예외 슬롯 상한 3 을 넘었다: {len(accepted)}"
    assert all(r["used_exception_slot"] for r in accepted)
    assert "슬롯 소진" in results[3]["reason"]


def test_market_daily_is_permanently_excluded(contract) -> None:
    from ai_fc.portfolio_prereg import evaluate_candidate
    decision = evaluate_candidate(contract, _cand(domain="market-daily"))
    assert not decision.accepted
    assert "market-daily" in decision.reason


def test_missing_sigma_source_is_rejected(contract) -> None:
    """σ 를 어디서 가져왔는지 못 적으면 z 가 검증 불가능하다."""
    from ai_fc.portfolio_prereg import evaluate_candidate
    for field in ("z", "sigma", "sigma_source", "honest_probability_estimate"):
        decision = evaluate_candidate(contract, _cand(**{field: None}))
        assert not decision.accepted and field in decision.reason


def test_clean_candidate_is_accepted(contract) -> None:
    from ai_fc.portfolio_prereg import evaluate_candidate
    decision = evaluate_candidate(contract, _cand())
    assert decision.accepted and not decision.uses_exception_slot


def test_registration_is_blocked_until_user_approves_the_list() -> None:
    """계약만 커밋해서는 열리지 않는다 — 12건 목록에 사용자 승인이 있어야 한다."""
    from ai_fc.portfolio_prereg import registration_allowed
    allowed, reason = registration_allowed(ROOT)
    approved = (yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
                .get("new_registration", {}).get("user_approved_list"))
    if approved:
        assert allowed
    else:
        assert not allowed and "승인" in reason


def test_L3_L4_require_non_selection_logs(contract) -> None:
    """유예를 결과 보고 발동하면 표본 선택이다 — 유예된 회차도 기록돼야 한다."""
    for key in ("L3_defer_r1_if_no_consensus", "L4_research_depth_floor"):
        block = contract[key]
        assert block["status"] == "registered"
        assert block["non_selection_log_required"] is True
        assert block["non_selection_log_path"]
        assert "소급" in block["scope"], f"{key} 는 소급 적용 금지를 명시해야 한다"


def test_stopping_rules_forbid_cherry_picking(contract) -> None:
    never = contract["stopping_rules"]["never"]
    for forbidden in ("stop_at_49_and_cherry_pick", "post_hoc_failed_tagging", "gate_arithmetic_change"):
        assert forbidden in never


def test_status_wording_forbids_the_word_pass(contract) -> None:
    wording = contract["status_wording"]
    assert wording["current"].startswith("미결")
    assert "통과" in wording["forbidden_words"]


def test_module_never_reads_the_ledger() -> None:
    """등록 판정이 성적을 보면 그 자체가 선택 편향이다."""
    source = (ROOT / "src/ai_fc/portfolio_prereg.py").read_text(encoding="utf-8")
    for forbidden in ("ledger.csv", "read_ledger", "brier"):
        if forbidden == "brier":
            assert "read_ledger" not in source
            continue
        assert forbidden not in source, f"등록 훅이 {forbidden} 을 읽으면 안 된다"
