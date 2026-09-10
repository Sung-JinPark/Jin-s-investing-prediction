"""T01 — 게이트 표시층 이중 단위.

게이트 산술은 이 태스크에서 한 글자도 바뀌지 않는다. 바꾸는 대신 **드러낸다**:
같은 원장이 행 평균 0.15986(게이트 정본)과 문항 등가중 0.22079(게이밍 감시용)를 동시에 낸다.
전자는 문턱 0.18 아래, 후자는 위다 — 어느 쪽도 거짓이 아니고 분모가 다를 뿐이다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: 2026-09-10 착수 시점 원장(11행 / primary 10행 / 7문항) 기준 재현값.
#: 원장이 append 되면 이 값들은 바뀐다 — 그때는 테스트가 실패하며 값을 다시 기록해야 한다.
EXPECTED = {
    "brier_primary_rows": 0.15986,
    "brier_per_question": 0.22079,
    "se": 0.06175,
    "sharpness_mean_p1mp": 0.16214,
}
TOLERANCE = 5e-4


def _facts():
    from ai_fc.gate_display import gate_display_facts
    return gate_display_facts(ROOT)


def test_reproduces_the_pack_arithmetic() -> None:
    facts = _facts()
    if facts["n_rows_primary"] != 10 or facts["n_questions_primary"] != 7:
        pytest.skip(f"원장이 갱신됨 (primary {facts['n_rows_primary']}행 / "
                    f"{facts['n_questions_primary']}문항) — 착수 기준값과 다르다")
    for key, want in EXPECTED.items():
        got = facts[key]
        assert abs(got - want) < TOLERANCE, f"{key}: {got} vs {want}"


def test_margin_is_reported_in_standard_errors() -> None:
    facts = _facts()
    if facts["n_rows_primary"] != 10:
        pytest.skip("원장 갱신")
    assert abs(facts["margin_se"] - 0.33) < 0.02, "문턱까지의 여유는 0.33 SE 여야 한다"


def test_the_two_units_disagree_about_the_threshold() -> None:
    """이 사실이 T01 의 존재 이유다 — 한쪽만 보여주면 오도한다."""
    facts = _facts()
    if facts["n_rows_primary"] != 10:
        pytest.skip("원장 갱신")
    assert facts["brier_primary_rows"] < facts["threshold_brier"]
    assert facts["brier_per_question"] > facts["threshold_brier"]


def test_gaming_surface_is_exposed() -> None:
    """쉬운 질문 회차 반복은 행 평균을 낮추지만 문항 수를 늘리지 않는다."""
    facts = _facts()
    repeated = facts["questions_with_multiple_rounds"]
    assert isinstance(repeated, dict)
    if facts["n_rows_primary"] == 10:
        assert repeated.get("fomc-2026-07-29-hike") == 3
        share = sum(repeated.values()) / facts["n_rows_primary"]
        assert share >= 0.5, "복수 회차가 primary 행의 절반 — 반드시 노출돼야 한다"


def test_display_never_renders_a_verdict_word() -> None:
    """게이트 상태 표현은 '미결'로 고정한다 — 표시층은 판정하지 않는다."""
    from ai_fc.gate_display import gate_display_lines

    facts = _facts()
    lines = gate_display_lines(facts)
    joined = " ".join(lines)
    assert "미결" in joined
    assert "통과" not in joined, "표시층이 '통과'를 말하면 안 된다"
    assert facts["status_wording"] == "미결"
    for key in ("gate_p3", "gate_p2", "passed"):
        assert key not in facts, f"표시층이 판정 필드 {key} 를 만들면 안 된다"


def test_legacy_field_is_kept_not_deleted() -> None:
    facts = _facts()
    assert "brier_all_rows" in facts, "기존 전량 기준값은 삭제하지 않는다"
    assert "brier_primary_rows" in facts


def test_gate_sql_and_thresholds_are_untouched() -> None:
    """게이트 산술 무변경 — 이 태스크의 하드 라인."""
    schema = (ROOT / "src/ai_fc/db/schema.sql").read_text(encoding="utf-8")
    assert "COUNT(DISTINCT r.question_id) >= 50 AND AVG(r.brier) < 0.18" in schema
    assert "COUNT(DISTINCT r.question_id) >= 30 AND AVG(r.brier) < 0.20" in schema
    config = (ROOT / "src/ai_fc/config.py").read_text(encoding="utf-8")
    assert 'GATE_P3 = {"n": 50, "brier": 0.18}' in config


def test_display_module_never_writes() -> None:
    source = (ROOT / "src/ai_fc/gate_display.py").read_text(encoding="utf-8")
    for forbidden in ("write_text(", "open(", "to_csv", "INSERT", "UPDATE", "DELETE"):
        assert forbidden not in source, f"표시층에 쓰기 호출 {forbidden} 이 있으면 안 된다"


def test_cluster_bootstrap_uses_questions_not_rows() -> None:
    """행 단위 재표집은 같은 질문의 회차를 독립 표본으로 취급해 CI 를 좁힌다."""
    source = (ROOT / "src/ai_fc/gate_display.py").read_text(encoding="utf-8")
    assert "by_question" in source and "keys[rng.randrange(len(keys))]" in source
    facts = _facts()
    ci = facts.get("ci90")
    if facts["n_rows_primary"] == 10:
        assert ci and len(ci) == 2 and ci[0] < facts["brier_primary_rows"] < ci[1]


def test_ledger_is_not_modified_by_reading() -> None:
    ledger = ROOT / "calibration/ledger.csv"
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    _facts()
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == before
