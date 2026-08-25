from ai_fc.timeseries_v6.research_backtest import (
    CANDIDATE_IMPLEMENTATION_VERSION,
    candidate_grid,
    development_folds,
)


def test_candidate_grids_and_purged_folds_are_frozen() -> None:
    assert len(candidate_grid("E1")) == 12
    assert len(candidate_grid("E2")) == 12
    assert len(candidate_grid("E3")) == 32
    origins = tuple(f"{year:04d}-{month:02d}-01" for year in range(2007, 2020) for month in range(1, 13) for _ in range(4))
    folds = development_folds(origins)
    assert len(folds) == 3
    assert all(max(train) + 68 <= min(validation) for train, validation in folds)


def test_corrected_implementation_identity_is_versioned() -> None:
    assert CANDIDATE_IMPLEMENTATION_VERSION["E1"] == "quantile_elastic_net_deterministic_runtime_v2"
    assert len(set(CANDIDATE_IMPLEMENTATION_VERSION.values())) == 7
