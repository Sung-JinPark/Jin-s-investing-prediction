from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ai_fc.timeseries_v6.research_dataset import build_research_dataset


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    research = root / "outputs/timeseries_v6/research"
    audit = root / "outputs/timeseries_v6/audit"
    audit.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "data/timeseries_v6/manifests/public_archive_latest.json"
    manifest = load_json(manifest_path)
    dataset = build_research_dataset(root, manifest_path)
    receipts = {(row["source_id"], row["series_id"]): row for row in manifest["receipts"]}
    sources = []
    observations = []
    vintages = []
    for partition in manifest["partitions"]:
        path = root / partition["path"]
        frame = pq.ParquetFile(path).read().to_pandas()
        receipt = receipts[(partition["source_id"], partition["series_id"])]
        observation = pd.to_datetime(frame["observation_time"], utc=True)
        available = pd.to_datetime(frame["available_at"], utc=True)
        sources.append({
            "source_id": partition["source_id"], "series_id": partition["series_id"],
            "data_grade": partition["data_grade"], "row_count": len(frame),
            "receipt_id": receipt["receipt_id"], "raw_sha256": receipt["object"]["object_sha256"],
        })
        observations.append({
            "source_id": partition["source_id"], "series_id": partition["series_id"],
            "row_count": len(frame), "first_observation": observation.min().isoformat(),
            "last_observation": observation.max().isoformat(), "parquet_sha256": partition["sha256"],
            "unique_observation_versions": int(frame["observation_version_id"].nunique()),
        })
        vintages.append({
            "source_id": partition["source_id"], "series_id": partition["series_id"],
            "data_grade": partition["data_grade"], "first_available_at": available.min().isoformat(),
            "last_available_at": available.max().isoformat(), "collected_at": receipt["collected_at"],
            "native_pit": partition["data_grade"] == "native_pit",
        })
    features = []
    for index, name in enumerate(dataset.feature_names):
        values = dataset.features[:, index]
        features.append({
            "feature_name": name, "source_series_id": dataset.feature_series_ids[index],
            "data_grade": dataset.feature_data_grades[index], "origin_count": len(values),
            "missing_count": int(np.sum(~np.isfinite(values))),
            "missing_indicator": name.endswith("__missing"),
        })
    sealed_pointer = load_json(research / "sealed_latest.json", {})
    sealed_path = root / sealed_pointer["scores_path"] if sealed_pointer.get("scores_path") else research / "sealed_scores.jsonl"
    sealed = [] if not sealed_path.exists() else [json.loads(line) for line in sealed_path.read_text(encoding="utf-8").splitlines() if line]
    forecasts = []
    for horizon in (1, 5, 21, 63):
        rows = [row for row in sealed if row["horizon"] == horizon]
        if rows:
            row = rows[-1]
            forecasts.append({key: row.get(key) for key in ("origin", "horizon", "candidate_id", "feature_profile", "actual", "p10", "p25", "p50", "p75", "p90", "up_probability", "model_crps", "baseline_crps")})
    gate = load_json(research / "gate_result.json", {})
    backtest = []
    for horizon, row in gate.get("research_gate", {}).get("by_horizon", {}).items():
        backtest.append({"horizon": int(horizon), **row})
    selections = [load_json(path) for path in sorted(research.glob("e[1-7]_selection.json"))]
    model_card = {
        "model_id": "shadow.nasdaq_pit_hierarchical_distribution_v6",
        "probability_space": "research_timeseries_v6_conditional",
        "status": gate.get("status", "not_evaluated"),
        "numbers_visible": gate.get("numbers_visible", False),
        "integrity_pass": gate.get("integrity_gate", {}).get("pass", False),
        "research_pass": gate.get("research_gate", {}).get("pass", False),
        "operational_pass": gate.get("operational_gate", {}).get("pass", False),
        "research_reasons": gate.get("research_gate", {}).get("reasons", []),
        "dataset_hash": dataset.content_hash,
        "origin_count": len(dataset.origins),
        "first_origin": dataset.origins[0],
        "last_mature_origin": dataset.origins[-1],
        "candidate_selections": selections,
        "deferred_candidates": load_json(research / "deferred_candidate_eligibility.json", {}),
    }
    artifact_paths = [
        manifest_path,
        research / "verification_result.json",
        research / "gate_result.json",
        research / "sealed_latest.json",
        sealed_path,
        (root / sealed_pointer["run_path"] / "selection.json") if sealed_pointer.get("run_path") else research / "sealed_selection.json",
        research / "preliminary_run_invalidations.jsonl",
        research / "deferred_candidate_eligibility.json",
        root / "data/timeseries_v6/manifests/candidate_specs.json",
        root / "data/timeseries_v6/atlas/research_plan.json",
    ] + sorted(research.glob("e[1-7]_selection.json")) + sorted(research.glob("e[1-7]*_experiments.jsonl"))
    run_manifest = [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in artifact_paths if path.exists()
    ]
    payload = {
        "schema_version": 1,
        "sources": sources,
        "observations": observations,
        "vintages": vintages,
        "features": features,
        "forecasts": forecasts,
        "backtest": backtest,
        "model_card": model_card,
        "run_manifest": run_manifest,
    }
    output = audit / "workbook_input.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sha256": sha256(output), "sheets": 8}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
