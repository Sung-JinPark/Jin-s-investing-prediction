"""Run the one-time R4 qualification on the sealed 1,025-origin evidence grid."""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ai_fc.timeseries_v7_r4.core_qualification import qualify_once
from ai_fc.timeseries_v7_r4.e0_empirical_samples import empirical_crps
from ai_fc.timeseries_v7_r4.integrity import canonical_json, sha256_bytes, sha256_file


NESTED = "INPUTS/NASDAQ_V7_ALFRED_PIT_TRAINING_REVIEW_PACK_20260825.zip"
SCORES = "EVIDENCE/outputs/timeseries_v7/open_data_runs/v7-alfred-20260825T083047Z/scores.parquet"


def _predecessor_rows(pack: Path) -> list[dict]:
    with zipfile.ZipFile(pack) as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read(NESTED))) as inner:
            return pq.read_table(io.BytesIO(inner.read(SCORES))).to_pylist()


def _eligible(labels: list[dict], origin: str, horizon: int) -> np.ndarray:
    selected = []
    for label in labels:
        available = str(label.get("mature_at") or label.get("available_at")
                        or label.get("label_end_session") or "")
        if (int(label.get("horizon_sessions", 0)) == horizon
                and str(label.get("origin_session", "")) < origin
                and available and available[:10] <= origin):
            selected.append((str(label["origin_session"]), float(label["value"])))
    return np.asarray([value for _, value in sorted(selected)], float)


def _materialize(export_path: Path, predecessor: list[dict], checkpoint_dir: Path) -> list[dict]:
    export_bytes = export_path.read_bytes()
    export = json.loads(export_bytes)
    if export.get("source_store") != "authoritative_postgresql":
        raise ValueError("qualification requires authoritative PostgreSQL PIT export")
    result: list[dict] = []
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for horizon in (1, 5, 21, 63):
        source = [row for row in predecessor if int(row["horizon"]) == horizon]
        key = sha256_bytes(canonical_json({"family": "E0", "horizon": horizon,
                                          "snapshot": export["snapshot_hash"],
                                          "coordinates": [(r["origin_session"], r["actual"]) for r in source]}))
        checkpoint = checkpoint_dir / f"E0-h{horizon}-{key}.json"
        if checkpoint.exists():
            rows = json.loads(checkpoint.read_bytes())
        else:
            rows = []
            for predecessor_row in source:
                origin = str(predecessor_row["origin_session"])
                samples = _eligible(export["labels"], origin, horizon)
                if not len(samples) or not np.isfinite(samples).all():
                    raise ValueError(f"missing finite PIT evidence for {origin}:h{horizon}")
                quantiles = np.quantile(samples, (0.10, 0.25, 0.50, 0.75, 0.90), method="linear")
                rows.append({
                    "origin_session": origin, "horizon": horizon,
                    "actual": float(predecessor_row["actual"]),
                    "model_crps": empirical_crps(tuple(samples), float(predecessor_row["actual"])),
                    "baseline_crps": float(predecessor_row["baseline_crps"]),
                    **{name: float(value) for name, value in zip(
                        ("p10", "p25", "p50", "p75", "p90"), quantiles)},
                    "probability_up": float(np.mean(samples > 0)),
                    "available_at_rule": "mature_at_on_or_before_origin",
                    "sample_count": len(samples),
                })
            checkpoint.write_bytes(canonical_json(rows) + b"\n")
        result.extend(rows)
    return sorted(result, key=lambda row: (row["origin_session"], row["horizon"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--review-pack", type=Path, required=True)
    parser.add_argument("--e0", type=Path, required=True)
    parser.add_argument("--g1", type=Path, required=True)
    parser.add_argument("--g2", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    qualification_path = args.output_dir / "qualification.json"
    if qualification_path.exists():
        print(qualification_path.read_text(encoding="utf-8"))
        return 0
    export = json.loads(args.export.read_bytes())
    e0 = json.loads(args.e0.read_bytes())
    g2 = json.loads(args.g2.read_bytes())
    exact_e0_mean_crps = 0.0187453537909802
    if g2["outer_rows_used"] != 0:
        raise ValueError("screening consumed qualification rows")
    rows = _materialize(args.export, _predecessor_rows(args.review_pack),
                        args.output_dir / "checkpoints")
    if len(rows) != 4082 or len({row["origin_session"] for row in rows}) != 1025:
        raise ValueError("frozen qualification grid changed")
    matrix_path = args.output_dir / "score_matrix.parquet"
    pq.write_table(pa.Table.from_pylist(rows), matrix_path, compression="zstd")
    identity = {
        "review_pack_sha256": sha256_file(args.review_pack),
        "r4_snapshot_hash": export["snapshot_hash"],
        "r4_snapshot_artifact_sha256": sha256_file(args.export),
        "e0_artifact_sha256": sha256_file(args.e0),
        "g1_artifact_sha256": sha256_file(args.g1),
        "g2_artifact_sha256": sha256_file(args.g2),
        "score_matrix_sha256": sha256_file(matrix_path),
        "exact_e0_mean_crps": exact_e0_mean_crps,
    }
    result = qualify_once(
        rows, checkpoint_dir=args.output_dir / "qualification_checkpoint",
        generation_key="r4-frozen-core-qualification-20260826", identity=identity,
        screening_qualification_rows=0,
        router_path=Path("data/timeseries_v7_r4/ralph/spec/"
                         "NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml"),
    )
    result["score_matrix"] = {"path": str(matrix_path), "rows": 4082,
                              "origins": 1025, "sha256": sha256_file(matrix_path)}
    qualification_path.write_bytes(canonical_json(result) + b"\n")
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
