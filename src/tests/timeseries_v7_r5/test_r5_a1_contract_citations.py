import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CITATIONS = ROOT / "outputs/timeseries_v7_r5/R5-A1/contract_citations.json"
BLUEPRINT = ROOT / "data/timeseries_v7_r5/ralph/spec/R5_GATE_PASS_BLUEPRINT_MATH_20260827.md"


def test_r5_a1_serializes_three_contract_citations_and_differences() -> None:
    payload = json.loads(CITATIONS.read_text(encoding="utf-8"))
    citations = {row["id"]: row for row in payload["citations"]}

    assert set(citations) == {"horizon_gate", "e0_floor", "component_admission"}
    assert citations["e0_floor"]["value_by_horizon"] == {
        "1": 0.2,
        "5": 0.25,
        "21": 0.4,
        "63": 0.5,
    }
    assert "h1·h5 skill 양수는 별도 Gate가 아니다" in citations["horizon_gate"]["interpretation"]
    assert citations["component_admission"]["contract_explicit_universal_positive_advantage_rule"] is False
    assert payload["outer_rows_used"] == 0
    assert payload["official_snapshot_or_ledger_accessed"] is False
    assert payload["contract_modified"] is False
    assert len(payload["differences"]) == 3
    assert all(row["resolution"] == "blueprint_aligned_to_contract" for row in payload["differences"])


def test_r5_a1_blueprint_is_aligned_without_changing_gate_contract() -> None:
    text = BLUEPRINT.read_text(encoding="utf-8")
    assert "R5-A1 계약 정렬" in text
    assert "0.20/0.25/0.40/0.50" in text
    assert "21·63일 평균 CRPS skill ≥2%" in text
    assert "별도 Gate로 재해석하지 않는다" in text
