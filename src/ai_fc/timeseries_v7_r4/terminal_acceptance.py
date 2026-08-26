"""Build the content-bound R4 autonomous-loop terminal receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


COMPLETED_DEPENDENCIES = ["R4-S4-006", *(f"R4-A5-00{i}" for i in range(1, 6))]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_terminal_acceptance(
    *, g3_path: Path, proposal_path: Path, output_path: Path,
    protected_manifest_sha256: str,
) -> dict:
    g3 = json.loads(g3_path.read_text(encoding="utf-8"))
    if g3.get("decision") != "HOLD_RESEARCH_GATE" or g3.get("research_gate_pass") is not False:
        raise ValueError("accepted G3 receipt must record HOLD_RESEARCH_GATE")
    if g3.get("replan_outcome") is not True:
        raise ValueError("ordinary Gate failure must have created a replan outcome")

    components = g3.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("accepted G3 receipt has no preregistered stress components")
    ineligible = [
        {"component_id": item["component_id"],
         "oos_stacking_advantage": item["oos_stacking_advantage"],
         "weight": item["weight"]}
        for item in components
        if item.get("oos_stacking_advantage", 0.0) <= 0.0
    ]
    if any(item["weight"] != 0.0 for item in ineligible):
        raise ValueError("stress component without positive calibration OOS advantage has nonzero weight")
    if len(ineligible) != len(components):
        raise ValueError("terminal HOLD receipt unexpectedly contains a positive-advantage component")

    result = {
        "schema": "r4_autonomous_terminal_v1",
        "terminal_state": "REVIEW_PROPOSAL",
        "next_action": "HUMAN_REVIEW_UNAPPROVED_V8_CONTRACT_PROPOSAL",
        "v8_proposal_approved": False,
        "research_gate_pass": False,
        "model_gate_state": "HOLD_RESEARCH_GATE",
        "data_deficit": False,
        "hard_block": False,
        "completed_dependencies": COMPLETED_DEPENDENCIES,
        "ordinary_gate_failure": {
            "state": "RESEARCH_GATE_FAILED_REPLAN",
            "created_replan_tasks": True,
            "process_terminated": False,
        },
        "zero_weight_stress_components": ineligible,
        "g3_receipt": {"path": g3_path.as_posix(), "sha256": _sha256(g3_path)},
        "g3_receipt_sha256": _sha256(g3_path),
        "protected_manifest_sha256": protected_manifest_sha256,
        "v8_proposal": {"path": proposal_path.as_posix(), "sha256": _sha256(proposal_path)},
        "v8_proposal_sha256": _sha256(proposal_path),
        "frozen_research_coordinates_unchanged": True,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    build_terminal_acceptance(
        g3_path=repo / "outputs/timeseries_v7_r4/R4-S4-006/g3/acceptance_summary.json",
        proposal_path=repo / "docs/timeseries_v7_r4/V8_OPEN_DATA_CHALLENGER_PROPOSAL.md",
        output_path=(repo / args.output) if not args.output.is_absolute() else args.output,
        protected_manifest_sha256="62945a0e7f0f5f4f5467885441e0bcaa4f9a3caa361aff54a4b82a8bd2ae1dfe",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
