import pytest

from ai_fc.timeseries_v7_r4.g1_candidate_funnel import screen_g1_candidates


def _candidate(name, score, *, exposure=None):
    return {
        "candidate_id": name,
        "hypothesis": {"model": name, "mechanism": "direct_horizon"},
        "exposure": exposure or {"features": ["returns"], "horizons": [1, 5, 21, 63]},
        "smoke_crps": score,
        "inner_crps": score,
        "robust_inner_crps": score,
        "full_nested_crps": score,
    }


def test_bounded_funnel_zeroes_underperformers_and_records_lineage_hashes():
    candidates = [_candidate("good", .08), _candidate("bad", .12)]

    report = screen_g1_candidates(
        candidates,
        e0_crps=.10,
        budgets={"smoke": 2, "inner_screen": 2, "robust_inner": 1,
                 "full_nested": 1, "qualification": 1},
        generation_hash="a" * 64,
    )

    assert report["candidate_counts"] == {
        "smoke": 2, "inner_screen": 2, "robust_inner": 1,
        "full_nested": 1, "qualification": 1,
    }
    rows = {row["candidate_id"]: row for row in report["candidates"]}
    assert rows["bad"]["weight"] == 0.0
    assert rows["good"]["weight"] > 0.0
    assert len(rows["good"]["hypothesis_hash"]) == 64
    assert len(rows["good"]["exposure_hash"]) == 64


def test_funnel_rejects_budget_over_contract_and_nonfinite_scores():
    with pytest.raises(ValueError, match="funnel budget"):
        screen_g1_candidates([], e0_crps=.1,
                             budgets={"smoke": 161}, generation_hash="a" * 64)
    with pytest.raises(ValueError, match="finite"):
        screen_g1_candidates([_candidate("bad", float("nan"))], e0_crps=.1,
                             generation_hash="a" * 64)
