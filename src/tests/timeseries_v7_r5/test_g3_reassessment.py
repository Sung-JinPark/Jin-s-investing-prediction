from __future__ import annotations

import json
from pathlib import Path

from ai_fc.timeseries_v7_r5.g3_reassessment import build_g3_reassessment


def test_real_s1_g3_admits_only_positive_weight_positive_advantage_components(tmp_path: Path) -> None:
    repo = Path(__file__).parents[3]
    result = build_g3_reassessment(
        stacking_summary=repo / "outputs/timeseries_v7_r5/R5-S1/stacking_summary.json",
        r4_g3_summary=repo / "outputs/timeseries_v7_r4/R4-S4-006/g3/acceptance_summary.json",
        r4_qualification=repo / "outputs/timeseries_v7_r4/R4-M3-008/qualification_revision_3.json",
        r4_score_matrix=repo / "outputs/timeseries_v7_r4/R4-M3-008/score_matrix.parquet",
        output_path=tmp_path / "acceptance_summary.json",
    )
    assert result["admitted_components"] == ["E1_prime", "E2_prime"]
    assert result["g4_eligible"] is True
    assert result["outer_opened"] is False
    assert result["row_use_counters"]["outer_rows_used"] == 0
    assert result["decision"] == "WAIT_USER_APPROVAL_OUTER_ONCE"
    assert result["prior_sealed_result_mutated"] is False
    assert result["research_gate_pass"] is None
    assert json.loads((tmp_path / "acceptance_summary.json").read_text())["generation_id"].startswith(
        "R5-G3-")
