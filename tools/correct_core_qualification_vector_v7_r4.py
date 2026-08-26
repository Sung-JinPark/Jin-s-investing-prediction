"""Append a reporting-only qualification revision from the sealed score matrix."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_fc.timeseries_v7_r4.core_qualification import compute_gate_evidence
from ai_fc.timeseries_v7_r4.integrity import canonical_json, sha256_file
from ai_fc.timeseries_v7_r4.router import GateDeficitRouter


def main() -> int:
    output = REPO_ROOT / "outputs/timeseries_v7_r4/R4-M3-008"
    original_path = output / "qualification.json"
    matrix_path = output / "score_matrix.parquet"
    original = json.loads(original_path.read_bytes())
    evidence = compute_gate_evidence(pq.read_table(matrix_path).to_pylist())
    revision = dict(original)
    revision.update(evidence)
    revision["schema"] = "r4_core_qualification_v1_revision_2"
    revision["supersedes_sha256"] = sha256_file(original_path)
    revision["correction_scope"] = "deficit_vector_taxonomy_only_scores_unchanged"
    routed = GateDeficitRouter.from_yaml(REPO_ROOT / "data/timeseries_v7_r4/ralph/spec/"
                                         "NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml").route(
        evidence["gate_deficit_vector"],
        dataset_snapshot_hash=revision["identity"]["r4_snapshot_hash"],
        code_hash=revision["identity"]["g2_artifact_sha256"],
        runtime_hash=revision["identity"]["g1_artifact_sha256"])
    revision["routed_tasks"] = [task.__dict__ for task in routed]
    target = output / "qualification_revision_2.json"
    target.write_bytes(canonical_json(revision) + b"\n")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
