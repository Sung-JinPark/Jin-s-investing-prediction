from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ai_fc.timeseries_v6.research_backtest import (
    CANDIDATE_IMPLEMENTATION_VERSION,
    candidate_feature_profile,
    candidate_grid,
    canonical_hash,
)
from ai_fc.timeseries_v6.research_dataset import build_research_dataset
from ai_fc.timeseries_v6.research_verify import verify_archive, verify_dataset_pit, verify_runtime_selections


ROOT = Path(__file__).resolve().parents[3]


def _require_private_partitions(manifest: Path) -> None:
    if not manifest.exists():
        pytest.skip("V6 public archive manifest is not available")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    partitions = payload.get("partitions", [])
    if not partitions or any(not (ROOT / item["path"]).is_file() for item in partitions):
        pytest.skip("V6 private Parquet archive is not distributed in the Git checkout")


def _dataset():
    manifest = ROOT / "data/timeseries_v6/manifests/public_archive_latest.json"
    _require_private_partitions(manifest)
    return build_research_dataset(ROOT, manifest)


def test_archive_bytes_receipts_observations_and_pit_are_independently_reopened() -> None:
    manifest = ROOT / "data/timeseries_v6/manifests/public_archive_latest.json"
    _require_private_partitions(manifest)
    archive = verify_archive(ROOT, manifest)
    dataset = _dataset()
    pit = verify_dataset_pit(dataset)
    assert archive["pass"] is True
    assert archive["receipt_observation_link_rate"] == 1.0
    assert archive["verified_raw_object_count"] == archive["receipt_count"]
    assert pit["pass"] is True
    assert pit["pit_leakage_count"] == 0
    assert pit["initial_training_origin_count"] > 400


def test_pit_verifier_detects_a_post_cutoff_input() -> None:
    dataset = _dataset()
    maximum = list(dataset.max_input_available_at)
    maximum[0] = "2099-01-01T00:00:00+00:00"
    result = verify_dataset_pit(replace(dataset, max_input_available_at=tuple(maximum)))
    assert result["pass"] is False
    assert result["pit_leakage_count"] == 1


def test_runtime_selection_must_match_frozen_grid_dataset_and_grade_profile() -> None:
    dataset = _dataset()
    _, profile, profile_hash = candidate_feature_profile(dataset, "E1")
    spec = candidate_grid("E1")[0]
    selection = {
        "candidate_id": "E1",
        "implementation_version": CANDIDATE_IMPLEMENTATION_VERSION["E1"],
        "dataset_hash": dataset.content_hash,
        "feature_profile": profile,
        "feature_profile_hash": profile_hash,
        "selection": {
            "1": {
                "spec": spec,
                "spec_hash": canonical_hash(spec),
                "implementation_version": CANDIDATE_IMPLEMENTATION_VERSION["E1"],
            }
        },
    }
    assert verify_runtime_selections(dataset, [selection])["pass"] is True
    selection["selection"]["1"]["spec"]["alpha"] = 999
    assert verify_runtime_selections(dataset, [selection])["pass"] is False


def test_runtime_selection_rejects_unversioned_estimator_receipt() -> None:
    dataset = _dataset()
    _, profile, profile_hash = candidate_feature_profile(dataset, "E1")
    spec = candidate_grid("E1")[0]
    selection = {
        "candidate_id": "E1",
        "dataset_hash": dataset.content_hash,
        "feature_profile": profile,
        "feature_profile_hash": profile_hash,
        "selection": {"1": {"spec": spec, "spec_hash": canonical_hash(spec)}},
    }
    result = verify_runtime_selections(dataset, [selection])
    assert result["pass"] is False
    assert result["contract_runtime_mismatch_count"] == 2
