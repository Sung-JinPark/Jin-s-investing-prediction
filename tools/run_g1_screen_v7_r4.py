"""Execute the R4 G1 screen from the Supervisor's credential-free PIT export."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_fc.timeseries_v7_r4.g1_candidate_funnel import run_g1_screen_from_export
from ai_fc.timeseries_v7_r4.integrity import canonical_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("export", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--e0-crps", required=True, type=float)
    parser.add_argument("--e0-artifact-sha256", required=True)
    parser.add_argument("--evaluation-origin-grid-hash", required=True)
    parser.add_argument("--generation-hash", required=True)
    parser.add_argument("--checkpoint-dir", type=Path)
    args = parser.parse_args()
    report = run_g1_screen_from_export(
        args.export, e0_crps=args.e0_crps,
        e0_artifact_sha256=args.e0_artifact_sha256,
        evaluation_origin_grid_hash=args.evaluation_origin_grid_hash,
        generation_hash=args.generation_hash,
        checkpoint_dir=args.checkpoint_dir or args.output.parent / "checkpoints",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
