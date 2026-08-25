from pathlib import Path

import numpy as np

from ai_fc.timeseries_v6.research_dataset import build_research_dataset


ROOT = Path(__file__).resolve().parents[3]


def test_live_public_archive_builds_version_linked_weekly_direct_dataset() -> None:
    manifest = ROOT / "data/timeseries_v6/manifests/public_archive_latest.json"
    if not manifest.exists():
        return
    dataset = build_research_dataset(ROOT, manifest)
    assert len(dataset.origins) > 1000
    assert dataset.features.shape == (len(dataset.origins), len(dataset.feature_names))
    assert set(dataset.labels) == {1, 5, 21, 63}
    assert all(len(values) == len(dataset.origins) for values in dataset.labels.values())
    assert dataset.provenance_rate > 0.95
    assert np.isfinite(dataset.anchors).all()
