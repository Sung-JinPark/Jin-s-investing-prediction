import hashlib
import json
from pathlib import Path

from ai_fc.timeseries_v7_r4.terminal_acceptance import build_terminal_acceptance


def test_builds_content_bound_review_proposal(tmp_path: Path) -> None:
    g3 = tmp_path / "g3.json"
    proposal = tmp_path / "proposal.md"
    output = tmp_path / "acceptance.json"
    g3.write_text(json.dumps({
        "schema": "r4_g3_stress_tail_path_v1",
        "decision": "HOLD_RESEARCH_GATE",
        "research_gate_pass": False,
        "replan_outcome": True,
        "components": [
            {"component_id": f"R4-S4-00{i}", "oos_stacking_advantage": 0.0, "weight": 0.0}
            for i in range(1, 6)
        ],
    }), encoding="utf-8")
    proposal.write_text("unapproved V8 contract proposal\n", encoding="utf-8")

    result = build_terminal_acceptance(
        g3_path=g3,
        proposal_path=proposal,
        output_path=output,
        protected_manifest_sha256="6" * 64,
    )

    assert result["schema"] == "r4_autonomous_terminal_v1"
    assert result["terminal_state"] == "REVIEW_PROPOSAL"
    assert result["model_gate_state"] == "HOLD_RESEARCH_GATE"
    assert result["ordinary_gate_failure"]["created_replan_tasks"] is True
    assert result["ordinary_gate_failure"]["process_terminated"] is False
    assert all(item["weight"] == 0.0 for item in result["zero_weight_stress_components"])
    assert result["g3_receipt_sha256"] == hashlib.sha256(g3.read_bytes()).hexdigest()
    assert result["v8_proposal_sha256"] == hashlib.sha256(proposal.read_bytes()).hexdigest()
    assert json.loads(output.read_text(encoding="utf-8")) == result
