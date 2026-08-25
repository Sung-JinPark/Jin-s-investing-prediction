import json
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v6.research_dataset import build_research_dataset


ROOT = Path(__file__).resolve().parents[3]


def _require_private_partitions(manifest: Path) -> None:
    if not manifest.exists():
        pytest.skip("V6 public archive manifest is not available")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    partitions = payload.get("partitions", [])
    if not partitions or any(not (ROOT / item["path"]).is_file() for item in partitions):
        pytest.skip("V6 private Parquet archive is not distributed in the Git checkout")


def test_live_public_archive_builds_version_linked_weekly_direct_dataset() -> None:
    manifest = ROOT / "data/timeseries_v6/manifests/public_archive_latest.json"
    _require_private_partitions(manifest)
    dataset = build_research_dataset(ROOT, manifest)
    assert len(dataset.origins) > 1000
    assert dataset.features.shape == (len(dataset.origins), len(dataset.feature_names))
    assert set(dataset.labels) == {1, 5, 21, 63}
    assert all(len(values) == len(dataset.origins) for values in dataset.labels.values())
    assert dataset.provenance_rate > 0.95
    assert np.isfinite(dataset.anchors).all()
