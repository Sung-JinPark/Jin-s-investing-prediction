"""R5 G3 admission reassessment without opening the sealed outer role."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .conditional_scale_selection import canonical_json


GRID_HASH = "1f2403b7b15c100741a29816304056c2ad7b91cd777b29534a96a567068fa7e8"
FAMILIES = ("E1_prime", "E2_prime", "E3_prime", "E4_prime", "F_location")
WEIGHT_TOLERANCE = 1e-12


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_g3_reassessment(*, stacking_summary: Path, r4_g3_summary: Path,
                          r4_qualification: Path, r4_score_matrix: Path,
                          output_path: Path) -> dict[str, Any]:
    s1 = json.loads(stacking_summary.read_text(encoding="utf-8"))
    prior = json.loads(r4_g3_summary.read_text(encoding="utf-8"))
    if s1.get("schema") != "r5_s1_stacking_reassessment_v1":
        raise ValueError("R5 S1 summary schema mismatch")
    if s1["row_use_counters"].get("outer_rows_used") != 0:
        raise ValueError("outer role was exposed before G4")
    if prior.get("prior_sealed_result_mutated") is not False:
        raise ValueError("R4 sealed prior is not immutable")

    components: list[dict[str, Any]] = []
    for family in FAMILIES:
        weights = {h: float(s1["horizons"][h]["weights"][family])
                   for h in ("1", "5", "21", "63")}
        advantages = {h: float(s1["horizons"][h]["component_diagnostics"][family]
                                      ["calibration_mean_advantage"])
                      for h in ("1", "5", "21", "63")}
        active = [h for h, weight in weights.items() if weight > WEIGHT_TOLERANCE]
        mean_active_advantage = (sum(advantages[h] for h in active) / len(active)
                                 if active else 0.0)
        admitted = bool(active and mean_active_advantage > 0.0)
        components.append({
            "component_id": family, "weights_by_horizon": weights,
            "calibration_advantage_by_horizon": advantages,
            "active_horizons": [int(h) for h in active],
            "mean_active_calibration_advantage": mean_active_advantage,
            "positive_calibration_cross_fit_stacking_advantage": mean_active_advantage > 0.0,
            "admitted": admitted,
        })
    admitted = [row["component_id"] for row in components if row["admitted"]]
    e0_weights = {h: float(s1["horizons"][h]["weights"]["E0"])
                  for h in ("1", "5", "21", "63")}
    for horizon in e0_weights:
        total = e0_weights[horizon] + sum(float(row["weights_by_horizon"][horizon])
                                         for row in components)
        if abs(total - 1.0) > 1e-12:
            raise ValueError(f"h{horizon} mixture weights do not sum to one")

    material = {"s1_sha256": _sha(stacking_summary), "grid_hash": GRID_HASH,
                "admitted_components": admitted}
    summary = {
        "schema": "r5_g3_admission_reassessment_v1",
        "generation_id": "R5-G3-" + hashlib.sha256(canonical_json(material)).hexdigest()[:16],
        "frozen_evaluation": {"comparator": "E0", "horizons": [1, 5, 21, 63],
                              "weekly_origins": True, "origin_count": 1025,
                              "score_rows": 4082,
                              "evaluation_coordinate_grid_hash": GRID_HASH},
        "components": components, "admitted_components": admitted,
        "admitted_component_exists": bool(admitted),
        "e0_anchor_weight_by_horizon": e0_weights,
        "stacking_evaluation_role": "calibration_cross_fit_holdout",
        "role_hashes": s1["role_hashes"],
        "r5_s1": {"path": stacking_summary.as_posix(), "sha256": _sha(stacking_summary)},
        "sealed_prior": {
            "r4_g3_path": r4_g3_summary.as_posix(), "r4_g3_sha256": _sha(r4_g3_summary),
            "r4_qualification_path": r4_qualification.as_posix(),
            "r4_qualification_sha256": _sha(r4_qualification),
            "r4_score_matrix_path": r4_score_matrix.as_posix(),
            "r4_score_matrix_sha256": _sha(r4_score_matrix),
        },
        "prior_sealed_result_mutated": False,
        "row_use_counters": {"train_rows_used": 0, "selection_rows_used": 0,
                             "stacking_rows_used": 0, "calibration_rows_used": 2536,
                             "outer_rows_used": 0},
        "research_gate_pass": None,
        "decision": ("WAIT_USER_APPROVAL_OUTER_ONCE" if admitted
                     else "WAIT_USER_DECISION_ALL_COMPONENTS_REJECTED"),
        "g4_eligible": bool(admitted), "outer_opened": False,
        "promotion_claimed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_json(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stacking-summary", type=Path, required=True)
    parser.add_argument("--r4-g3-summary", type=Path, required=True)
    parser.add_argument("--r4-qualification", type=Path, required=True)
    parser.add_argument("--r4-score-matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_g3_reassessment(stacking_summary=args.stacking_summary,
                          r4_g3_summary=args.r4_g3_summary,
                          r4_qualification=args.r4_qualification,
                          r4_score_matrix=args.r4_score_matrix,
                          output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
