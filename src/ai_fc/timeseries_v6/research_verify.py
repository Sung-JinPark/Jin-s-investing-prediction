"""Independent integrity and operational verification for V6 research runs.

Performance code cannot self-assert PIT, lineage, or freshness.  This module
reopens immutable artifacts and recomputes those decisions from stored bytes.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .public_archive import PUBLIC_SERIES
from .research_backtest import (
    CANDIDATE_IMPLEMENTATION_VERSION,
    candidate_feature_profile,
    candidate_grid,
    canonical_hash,
)
from .research_dataset import ResearchDataset
from .sessions import missing_completed_sessions
from .source_coverage import build_source_coverage


class ResearchVerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_hash(payload: dict[str, Any]) -> str:
    core = {key: value for key, value in payload.items() if key != "content_hash"}
    return canonical_hash(core)


def _local_raw_path(root: Path, object_sha256: str) -> Path:
    return root / "outputs/timeseries_v6/private_store/raw" / object_sha256[:2] / f"{object_sha256}.raw.gz"


def verify_archive(root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if _manifest_hash(manifest) != manifest.get("content_hash"):
        errors.append("manifest_content_hash_mismatch")
    receipts = {(row["source_id"], row["series_id"]): row for row in manifest.get("receipts", [])}
    receipt_rows = 0
    partition_rows = 0
    verified_objects = 0
    series_latest_observation: dict[str, str] = {}
    series_latest_available: dict[str, str] = {}
    for partition in manifest.get("partitions", []):
        key = (partition["source_id"], partition["series_id"])
        receipt = receipts.get(key)
        if receipt is None:
            errors.append(f"missing_receipt:{key[0]}:{key[1]}")
            continue
        path = root / partition["path"]
        if not path.exists() or _sha256(path) != partition["sha256"]:
            errors.append(f"partition_hash:{key[0]}:{key[1]}")
            continue
        frame = pq.ParquetFile(path).read().to_pandas()
        partition_rows += len(frame)
        receipt_rows += int(receipt["observation_count"])
        if len(frame) != int(partition["row_count"]) or len(frame) != int(receipt["observation_count"]):
            errors.append(f"row_count:{key[0]}:{key[1]}")
        raw_sha = receipt["object"]["object_sha256"]
        if set(frame["raw_object_sha256"].astype(str)) != {raw_sha}:
            errors.append(f"raw_link:{key[0]}:{key[1]}")
        if set(frame["source_id"].astype(str)) != {key[0]} or set(frame["series_id"].astype(str)) != {key[1]}:
            errors.append(f"series_binding:{key[0]}:{key[1]}")
        if frame["observation_version_id"].isna().any() or frame["observation_version_id"].duplicated().any():
            errors.append(f"observation_identity:{key[0]}:{key[1]}")
        raw_path = _local_raw_path(root, raw_sha)
        if not raw_path.exists() or _sha256(raw_path) != receipt["object"]["stored_sha256"]:
            errors.append(f"stored_raw_hash:{key[0]}:{key[1]}")
        else:
            try:
                body = gzip.decompress(raw_path.read_bytes())
                if hashlib.sha256(body).hexdigest() != raw_sha:
                    errors.append(f"decompressed_raw_hash:{key[0]}:{key[1]}")
                else:
                    verified_objects += 1
            except OSError:
                errors.append(f"raw_gzip:{key[0]}:{key[1]}")
        observation = pd.to_datetime(frame["observation_time"], utc=True)
        available = pd.to_datetime(frame["available_at"], utc=True)
        series_latest_observation[key[1]] = observation.max().isoformat()
        series_latest_available[key[1]] = available.max().isoformat()
    return {
        "pass": not errors,
        "errors": sorted(errors),
        "manifest_content_hash": manifest.get("content_hash"),
        "receipt_count": len(receipts),
        "partition_count": len(manifest.get("partitions", [])),
        "verified_raw_object_count": verified_objects,
        "receipt_observation_link_rate": 1.0 if not errors and receipt_rows == partition_rows else 0.0,
        "observation_rows": partition_rows,
        "series_latest_observation": series_latest_observation,
        "series_latest_available": series_latest_available,
    }


def verify_dataset_pit(dataset: ResearchDataset) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    for origin, cutoff, maximum in zip(
        dataset.origins, dataset.origin_cutoffs, dataset.max_input_available_at, strict=True
    ):
        if maximum and pd.Timestamp(maximum) > pd.Timestamp(cutoff):
            violations.append({"origin": origin, "origin_cutoff_at": cutoff, "max_input_available_at": maximum})
    missing_indicator_count = sum(name.endswith("__missing") for name in dataset.feature_names)
    grade_counts = {
        grade: dataset.feature_data_grades.count(grade)
        for grade in sorted(set(dataset.feature_data_grades))
    }
    return {
        "pass": not violations and dataset.provenance_rate == 1.0,
        "pit_leakage_count": len(violations),
        "pit_leakage_examples": violations[:20],
        "active_feature_provenance_rate": dataset.provenance_rate,
        "feature_count": len(dataset.feature_names),
        "explicit_missing_indicator_count": missing_indicator_count,
        "feature_data_grade_counts": grade_counts,
        "initial_training_origin_count": sum(origin <= "2006-12-31" for origin in dataset.origins),
        "development_origin_count": sum("2007-01-01" <= origin <= "2018-12-31" for origin in dataset.origins),
        "sealed_origin_count": sum(origin >= "2019-01-01" for origin in dataset.origins),
    }


def verify_runtime_selections(
    dataset: ResearchDataset,
    selections: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    mismatches: list[str] = []
    checked = 0
    for selection in selections:
        candidate_id = selection["candidate_id"]
        expected_implementation = CANDIDATE_IMPLEMENTATION_VERSION[candidate_id]
        if selection.get("implementation_version") != expected_implementation:
            mismatches.append(f"{candidate_id}:implementation_version")
        _, expected_profile, expected_profile_hash = candidate_feature_profile(dataset, candidate_id)
        if selection.get("dataset_hash") != dataset.content_hash:
            mismatches.append(f"{candidate_id}:dataset_hash")
        if selection.get("feature_profile") != expected_profile:
            mismatches.append(f"{candidate_id}:feature_profile")
        if selection.get("feature_profile_hash") != expected_profile_hash:
            mismatches.append(f"{candidate_id}:feature_profile_hash")
        allowed = {canonical_hash(spec) for spec in candidate_grid(candidate_id)}
        for horizon, row in selection.get("selection", {}).items():
            checked += 1
            if row.get("implementation_version") != expected_implementation:
                mismatches.append(f"{candidate_id}:h{horizon}:implementation_version")
            if canonical_hash(row["spec"]) not in allowed:
                mismatches.append(f"{candidate_id}:h{horizon}:off_grid")
            if row.get("spec_hash") != canonical_hash(row["spec"]):
                mismatches.append(f"{candidate_id}:h{horizon}:spec_hash")
    return {
        "pass": not mismatches,
        "contract_runtime_mismatch_count": len(mismatches),
        "mismatches": sorted(mismatches),
        "selection_coordinate_count": checked,
    }


def verify_operational_freshness(
    archive_report: dict[str, Any],
    *,
    collected_at: datetime,
    snapshot_compatible: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    series: dict[str, Any] = {}
    latest = archive_report["series_latest_observation"]
    for spec in PUBLIC_SERIES:
        observed = latest.get(spec.series_id)
        if not observed:
            reasons.append(f"missing_series:{spec.series_id}")
            continue
        observed_day = pd.Timestamp(observed).date().isoformat()
        if spec.frequency == "daily":
            try:
                age = missing_completed_sessions(last_observed_session=observed_day, as_of=collected_at)
            except Exception:
                age = 999
            allowed = 1
            status = age <= allowed
            series[spec.series_id] = {"frequency": spec.frequency, "missing_completed_sessions": age, "allowed": allowed, "pass": status}
        else:
            days = (collected_at.astimezone(timezone.utc) - pd.Timestamp(observed).to_pydatetime()).days
            allowed = 14 if spec.frequency == "weekly" else 70
            status = days <= allowed
            series[spec.series_id] = {"frequency": spec.frequency, "calendar_age_days": days, "allowed": allowed, "pass": status}
        if not status:
            reasons.append(f"stale:{spec.series_id}")
    if not snapshot_compatible:
        reasons.append("fit_snapshot_incompatible")
    return {
        "pass": not reasons,
        "reasons": sorted(reasons),
        "fit_snapshot_compatibility": snapshot_compatible,
        "source_specific_freshness": series,
    }


def verify_research_run(
    root: Path,
    dataset: ResearchDataset,
    selections: Iterable[dict[str, Any]],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    selections = list(selections)
    archive = verify_archive(root, manifest_path)
    source_coverage = build_source_coverage(
        root / "data/timeseries_v6/registry/sources.yaml",
        manifest_path,
        PUBLIC_SERIES,
    )
    pit = verify_dataset_pit(dataset)
    runtime = verify_runtime_selections(dataset, selections)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    collected_at = datetime.fromisoformat(manifest["collected_at"])
    snapshot_compatible = all(row.get("dataset_hash") == dataset.content_hash for row in selections)
    operational = verify_operational_freshness(
        archive, collected_at=collected_at, snapshot_compatible=snapshot_compatible
    )
    integrity_pass = (
        archive["pass"]
        and source_coverage["model_required_pass"]
        and pit["pass"]
        and runtime["pass"]
    )
    return {
        "schema_version": 1,
        "integrity_pass": integrity_pass,
        "archive": archive,
        "source_coverage": source_coverage,
        "pit": pit,
        "runtime": runtime,
        "operational": operational,
    }
