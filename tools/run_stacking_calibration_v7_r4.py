"""Generate compact R4 G2 stacking and calibration evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_fc.timeseries_v7_r4.integrity import canonical_json
from ai_fc.timeseries_v7_r4.stacking_calibration_generation import generate_stacking_calibration


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("export", type=Path)
    parser.add_argument("g1", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--e0-artifact-sha256", required=True)
    parser.add_argument("--e0-crps", required=True, type=float)
    parser.add_argument("--checkpoint-dir", type=Path)
    args = parser.parse_args()
    report = generate_stacking_calibration(
        args.export, g1_path=args.g1, e0_artifact_sha256=args.e0_artifact_sha256,
        e0_mean_crps=args.e0_crps,
        checkpoint_dir=args.checkpoint_dir or args.output.parent / "checkpoints",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
