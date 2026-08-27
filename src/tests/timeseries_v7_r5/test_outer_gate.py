from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v7_r5.outer_gate import claim_outer_once, probability_up, six_outer_blocks


def test_six_outer_blocks_preserve_every_origin_once() -> None:
    origins = [f"2024-01-{day:02d}" for day in range(1, 31)]
    blocks = six_outer_blocks(origins)
    assert len(blocks) == 6
    assert sum(block["origin_count"] for block in blocks) == len(origins)
    assert blocks[0]["first"] == origins[0]
    assert blocks[-1]["last"] == origins[-1]


def test_probability_up_is_fraction_weighted_empirical_mass() -> None:
    result = probability_up([np.asarray([-1.0, 1.0]), np.asarray([1.0, 2.0])], [0.4, 0.6])
    assert result == pytest.approx(0.8)
    assert 0.0 <= result <= 1.0


def test_outer_claim_is_atomic_and_forbids_retry(tmp_path: Path) -> None:
    path = tmp_path / "outer_exposure_receipt.json"
    approval = {"decision_id": "G4-OUTER-ONCE", "approved": True}
    receipt = claim_outer_once(path, approval_record=approval,
                               generation_id="R5-G3-test", outer_role_hash="a" * 64)
    assert receipt["exposure_count"] == 1
    assert receipt["retry_allowed"] is False
    with pytest.raises(RuntimeError, match="already been exposed"):
        claim_outer_once(path, approval_record=approval,
                         generation_id="R5-G3-test", outer_role_hash="a" * 64)
