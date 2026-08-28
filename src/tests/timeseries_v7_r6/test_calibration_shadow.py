import json
from pathlib import Path

import numpy as np

from ai_fc.timeseries_v7_r6.calibration_shadow import (
    LEVELS,
    apply_pit_map,
    implied_up_probability,
    run_calibration_shadow,
    scale_quantiles,
    temporal_splits,
)


ROOT = Path(__file__).resolve().parents[3]


def test_temporal_split_excludes_purge_and_embargo_without_overlap() -> None:
    origins = [f"2026-01-{index:03d}" for index in range(300)]
    splits = temporal_splits(origins, folds=5, warmup_folds=2, purge_and_embargo=68)
    assert len(splits) == 3
    for split in splits:
        fit = set(split["fit_origins"])
        test = set(split["test_origins"])
        assert not (fit & test)
        assert split["excluded_origin_count"] == 68


def test_c1_scale_one_is_exact_identity() -> None:
    quantiles = np.asarray([[-0.2, -0.1, 0.0, 0.1, 0.3]])
    transformed = scale_quantiles(quantiles, 1.0)
    assert np.array_equal(transformed, quantiles)


def test_c2_identity_probability_map_and_t3_bounds() -> None:
    quantiles = np.asarray(
        [
            [-0.20, -0.10, 0.00, 0.10, 0.20],
            [-0.30, -0.05, 0.04, 0.14, 0.40],
        ]
    )
    transformed = apply_pit_map(quantiles, LEVELS)
    assert np.allclose(transformed, quantiles)
    probabilities = implied_up_probability(transformed)
    assert np.all((probabilities >= 0.0) & (probabilities <= 1.0))
    assert len(np.unique(probabilities)) > 1


def test_full_calibration_run_is_outer_free_reproducible_and_protected(tmp_path: Path) -> None:
    first = run_calibration_shadow(ROOT, tmp_path / "first")
    second = run_calibration_shadow(ROOT, tmp_path / "second")
    assert first == second
    assert first["status"] == "WAIT_USER_DECISIONS"
    assert first["research_gate_pass"] is False
    assert first["outer_rows_used"] == 0
    assert first["protected_non_mutation"] is True

    metrics = json.loads(
        (tmp_path / "first/calibration_candidate_metrics.json").read_text()
    )
    assert metrics["row_use_counters"]["outer_rows_used"] == 0
    assert {row["candidate"] for row in metrics["metrics"]} == {
        "C0",
        "C1",
        "C2",
        "T2",
    }
    nesting = json.loads((tmp_path / "first/e0_nesting_proof.json").read_text())
    assert nesting["all_exact"] is True
    assert all(row["exact_identity"] for row in nesting["coordinates"])
    first_manifest = json.loads((tmp_path / "first/artifact_manifest.json").read_text())
    second_manifest = json.loads((tmp_path / "second/artifact_manifest.json").read_text())
    assert first_manifest == second_manifest
    assert first_manifest["outer_rows_used"] == 0
