from __future__ import annotations

import math

from ai_fc.timeseries_v7_r4.asymmetric_evt import build_family, fit_tail


def test_sparse_tail_uses_explicit_e0_guard() -> None:
    fitted = fit_tail([0.1, 0.2, 0.3], side="positive", minimum_exceedances=30)

    assert fitted["exceedance_count"] == 3
    assert fitted["shrinkage_guard_to_e0"] is True
    assert fitted["reference_family"] == "E0_exponential"


def test_family_has_numeric_horizon_and_distinct_guarded_tails() -> None:
    values = [(-1.0 if index % 3 == 0 else 0.25 + index / 100) for index in range(80)]
    family = build_family(5, values, calibration_role_origin_count=634)

    assert family["horizon"] == 5
    assert family["fit_role"] == "calibration_temporal_cross_fit"
    assert family["state_available_at_origin"] is True
    assert family["positive_tail"] != family["negative_tail"]
    for tail in (family["positive_tail"], family["negative_tail"]):
        assert tail["exceedance_count"] >= 30 or tail["shrinkage_guard_to_e0"] is True
    assert math.isfinite(family["extreme_q4_score"])
    assert math.isfinite(family["tail_score"])
