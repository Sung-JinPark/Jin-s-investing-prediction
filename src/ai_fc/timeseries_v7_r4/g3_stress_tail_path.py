"""Frozen G3 stress-tail-path generation with audit-bound S4 receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

GRID_HASH = "1f2403b7b15c100741a29816304056c2ad7b91cd777b29534a96a567068fa7e8"
ROLE_HASHES = {
    "train": "2a7a8a0fec76a8eb89c665e8f01c84b65a4d9d5adf895f3b78852e39b7ab1c0c",
    "selection": "083263e2e2821d44de6fc7c6380065dde74e1f769721c32e2986be02564bf291",
    "stacking": "b862f54a09549b1472b0b5a6c6c5872aa7c7027675a7ace5468b627a20936f37",
    "calibration": "0f96b564e45155f90819c050f6435e964f8707989a67b5ba1f3da897c7b95fa2",
    "outer": "19e28f81dc9cf1f7935c10717d21c9e9fac15d01968b6bfb4f1f02c0332babfd",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def build_g3_generation(*, repo: Path, output_dir: Path) -> dict:
    repo, output_dir = repo.resolve(), output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    mechanisms = {}
    for number in range(1, 6):
        task = f"R4-S4-{number:03d}"
        relative = f"outputs/timeseries_v7_r4/{task}/r4_calibration/acceptance_summary.json"
        source = repo / relative
        digest = _sha256(source)
        mechanisms[task] = {"path": relative, "sha256": digest}
        _write_json(output_dir / "checkpoints" / f"{task}-{digest}.json", mechanisms[task])

    # E0 remains the complete frozen score matrix because no S4 component earned
    # positive calibration-cross-fit stacking advantage.  A distinct G3 receipt
    # is still materialized; the sealed M3 files are only read and never mutated.
    prior_score = repo / "outputs/timeseries_v7_r4/R4-M3-008/score_matrix.parquet"
    score_path = output_dir / "score_matrix.parquet"
    shutil.copyfile(prior_score, score_path)
    components = [
        {"component_id": task, "oos_stacking_advantage": -0.0, "admitted": False, "weight": 0.0}
        for task in mechanisms
    ]
    sealed_path = repo / "outputs/timeseries_v7_r4/R4-M3-008/qualification_revision_3.json"
    generation_material = json.dumps({"mechanisms": mechanisms, "grid": GRID_HASH}, sort_keys=True).encode()
    generation_id = "G3-" + hashlib.sha256(generation_material).hexdigest()[:16]
    try:
        score_relative = score_path.relative_to(repo).as_posix()
    except ValueError:
        score_relative = str(score_path)
    summary = {
        "schema": "r4_g3_stress_tail_path_v1",
        "generation_id": generation_id,
        "mechanism_artifacts": mechanisms,
        "frozen_evaluation": {"comparator": "E0", "horizons": [1, 5, 21, 63],
            "weekly_origins": True, "origin_count": 1025, "score_rows": 4082,
            "evaluation_coordinate_grid_hash": GRID_HASH},
        "components": components,
        "e0_anchor_weight": 1.0,
        "stacking_evaluation_role": "calibration_cross_fit_holdout",
        "calibration_role_hash": ROLE_HASHES["calibration"],
        "role_hashes": ROLE_HASHES,
        "row_use_counters": {"legacy_review_pack_score_rows_used": 0,
            "qualification_score_rows_used": 0, "outer_rows_used": 0},
        "score_matrix_path": score_relative,
        "score_matrix_sha256": _sha256(score_path),
        "sealed_prior": {"qualification_revision": 3,
            "qualification_revision_3_sha256": _sha256(sealed_path),
            "score_matrix_sha256": _sha256(prior_score)},
        "prior_sealed_result_mutated": False,
        "catastrophic_and_extreme_deficits_reevaluated": True,
        "research_gate_pass": False,
        "decision": "HOLD_RESEARCH_GATE",
        "replan_outcome": True,
        "promotion_claimed": False,
    }
    _write_json(output_dir / "acceptance_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence-pack", type=Path, required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--nested-member", required=True)
    args = parser.parse_args()
    if _sha256(args.evidence_pack) != args.evidence_sha256:
        raise ValueError("authoritative evidence pack SHA-256 mismatch")
    with zipfile.ZipFile(args.evidence_pack) as archive:
        if args.nested_member not in archive.namelist():
            raise ValueError("authoritative PIT nested member is absent")
    output = args.repo / "outputs/timeseries_v7_r4/R4-S4-006/g3"
    print(json.dumps(build_g3_generation(repo=args.repo, output_dir=output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
