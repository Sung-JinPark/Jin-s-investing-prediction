"""P0 freeze and PIT preflight for the prospective-only R6 generation."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from .governance import protected_manifest, role_hash, verify_inputs, write_json
from .outer_guard import R5OuterDenylist


QUANTILE_COLUMNS = ("p10", "p25", "p50", "p75", "p90")
HORIZONS = (1, 5, 21, 63)


def run_preflight(repo_root: Path, output_dir: Path) -> dict[str, object]:
    root = repo_root.resolve()
    contract_path = (
        root / "data/timeseries_v7_r6/contracts/r6_sharpen_tilt_shadow_v1.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    inputs = verify_inputs(root, contract)
    if not inputs["all_matched"]:
        raise RuntimeError("R6 registered input hash mismatch")

    guard = R5OuterDenylist.load(root)
    score_record = contract["input_artifacts"]["r5_calibration_scores"]
    score_path = root / score_record["path"]
    guard.assert_role_allowed("calibration")
    guard.assert_path_allowed(score_path)
    frame = pd.read_parquet(score_path)
    required = {"origin_session", "horizon", "role", "actual", *QUANTILE_COLUMNS}
    if not required.issubset(frame.columns):
        raise ValueError(f"missing calibration columns: {sorted(required - set(frame.columns))}")
    if set(frame["role"].astype(str)) != {"calibration"}:
        raise ValueError("R6 preflight accepts calibration rows only")
    if set(frame["horizon"].astype(int)) != set(HORIZONS):
        raise ValueError("R6 horizons differ from the frozen contract")
    origins = sorted(frame["origin_session"].astype(str).unique())
    expected_hash = contract["role_hashes"]["calibration"]
    actual_hash = role_hash(origins)
    if actual_hash != expected_hash:
        raise ValueError("calibration role hash drift")
    duplicate_count = int(frame.duplicated(["origin_session", "horizon"]).sum())
    values = frame[["actual", *QUANTILE_COLUMNS]].astype(float)
    finite = bool(values.map(math.isfinite).to_numpy().all())
    monotone = bool(
        (frame["p10"] <= frame["p25"]).all()
        and (frame["p25"] <= frame["p50"]).all()
        and (frame["p50"] <= frame["p75"]).all()
        and (frame["p75"] <= frame["p90"]).all()
    )
    complete_grid = len(frame) == len(origins) * len(HORIZONS)

    market_record = contract["input_artifacts"]["nasdaq_observations"]
    market_path = root / market_record["path"]
    guard.assert_role_allowed("market_history")
    guard.assert_path_allowed(market_path)
    market_dates = set()
    with market_path.open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            market_dates.add(str(row["date"]))
    missing_market_origins = sorted(set(origins) - market_dates)

    result: dict[str, object] = {
        "schema": "r6_pit_preflight_v1",
        "status": "PASS" if all(
            (
                finite,
                monotone,
                complete_grid,
                duplicate_count == 0,
                not missing_market_origins,
            )
        ) else "BLOCKED",
        "proof_boundary": {
            "source": "content-bound R5 calibration artifact",
            "feature_value_pit_proof": "inherited_from_frozen_R5_generation",
            "row_level_origin_cutoff_fields_in_derived_artifact": False,
            "claim": "No R5 outer row was read; calibration lineage is hash-bound.",
        },
        "calibration": {
            "rows": len(frame),
            "origin_count": len(origins),
            "horizons": list(HORIZONS),
            "role_hash": actual_hash,
            "role_hash_match": actual_hash == expected_hash,
            "duplicate_coordinates": duplicate_count,
            "complete_grid": complete_grid,
            "finite": finite,
            "quantiles_monotone": monotone,
        },
        "market_history": {
            "origin_dates_present": len(origins) - len(missing_market_origins),
            "missing_origin_dates": missing_market_origins,
        },
        "row_use_counters": {
            "train_rows_used": 0,
            "selection_rows_used": 0,
            "stacking_rows_used": 0,
            "calibration_rows_used": len(frame),
            "outer_rows_used": 0,
        },
        "inputs": inputs,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "pit_preflight.json", result)
    write_json(output_dir / "input_verification.json", inputs)
    write_json(output_dir / "protected_manifest_before.json", protected_manifest(root))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_preflight(args.repo, args.output_dir)
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
