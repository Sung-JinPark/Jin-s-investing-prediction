from datetime import datetime, timedelta, timezone

import exchange_calendars as xcals
import pytest

from ai_fc.timeseries_v6.dfm_cache import DfmCacheError, PitDfmCache
from ai_fc.timeseries_v6.feature_registry import FeatureDefinition, FeatureRegistryError, validate_feature_registry
from ai_fc.timeseries_v6.labels import LabelError, build_direct_labels
from ai_fc.timeseries_v6.legacy_quarantine import LegacyQuarantineError, validate_v6_training_inputs


NOW = datetime(2026, 8, 21, 20, 15, tzinfo=timezone.utc)


def test_legacy_derived_inputs_and_ex_post_features_are_blocked() -> None:
    with pytest.raises(LegacyQuarantineError, match="legacy"):
        validate_v6_training_inputs(["data/timeseries_v5/features.parquet"], [])
    with pytest.raises(LegacyQuarantineError, match="ex-post"):
        validate_v6_training_inputs([], ["future_move_quartile"])


def test_dfm_cache_is_cutoff_and_input_hash_specific_and_no_stale_reuse() -> None:
    cache = PitDfmCache()
    calls = 0
    def fit():
        nonlocal calls
        calls += 1
        return {"factor_names": ["growth", "inflation"], "parameters": [1, 2], "last_factors": [0.1, -0.2], "convergence_status": "converged"}
    one = cache.fit_or_get(contract_hash="a" * 64, cutoff=NOW, input_hash="b" * 64, input_available_at=(NOW - timedelta(days=1),), fitter=fit)
    two = cache.fit_or_get(contract_hash="a" * 64, cutoff=NOW, input_hash="b" * 64, input_available_at=(NOW - timedelta(days=1),), fitter=fit)
    assert one == two and calls == 1
    assert cache.latest_before(NOW) == one
    with pytest.raises(DfmCacheError, match="future"):
        cache.fit_or_get(contract_hash="a" * 64, cutoff=NOW, input_hash="c" * 64, input_available_at=(NOW + timedelta(seconds=1),), fitter=fit)
    with pytest.raises(DfmCacheError, match="convergence"):
        cache.fit_or_get(contract_hash="a" * 64, cutoff=NOW, input_hash="d" * 64, input_available_at=(NOW,), fitter=lambda: {"factor_names": [], "parameters": [], "last_factors": [], "convergence_status": "failed"})


def test_feature_registry_rejects_semantic_duplicates() -> None:
    one = FeatureDefinition("vix_change", ("cboe_vix",), "log_change_v1", "signed_fraction", "scale")
    assert validate_feature_registry([one])["vix_change"] == one
    two = FeatureDefinition("renamed_same", ("cboe_vix",), "log_change_v1", "signed_fraction", "scale")
    with pytest.raises(FeatureRegistryError, match="semantics"):
        validate_feature_registry([one, two])


def test_direct_labels_use_exact_future_sessions_not_recursive_values() -> None:
    calendar = xcals.get_calendar("XNAS")
    origin = calendar.date_to_session("2026-01-02", direction="next")
    prices = {str(calendar.session_offset(origin, offset).date()): 100.0 + offset for offset in range(64)}
    origin_text = str(origin.date())
    labels = build_direct_labels(prices, origin_session=origin_text)
    assert [row.horizon_sessions for row in labels] == [1, 5, 21, 63]
    assert labels[-1].maturity_close == 163.0
    del prices[labels[-1].maturity_session]
    with pytest.raises(LabelError, match="not matured"):
        build_direct_labels(prices, origin_session=origin_text)
