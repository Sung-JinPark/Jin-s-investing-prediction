from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ai_fc.timeseries.model import fit_ridge_varx
from ai_fc.timeseries_daily6m import model as M
from ai_fc.timeseries_daily6m.contracts import (
    CONTRACT_RELATIVE, Daily6mContractError, ENDOGENOUS_NAMES, EXOGENOUS_NAMES,
    MODEL_ID, PATH_COUNT, canonical_hash, load_contract,
)

ROOT = Path(__file__).resolve().parents[2]


def test_exact_calendar_six_months_crosses_default_calendar_end_and_excludes_holidays() -> None:
    dates, end, calendar_hash = M.future_session_dates("2026-10-09")
    assert end == "2027-04-09"
    assert dates[0] == "2026-10-12"
    assert dates[-1] == "2027-04-09"
    assert "2026-11-26" not in dates and "2026-12-25" not in dates
    assert "2027-01-18" not in dates and "2027-03-26" not in dates
    assert len(dates) == len(set(dates)) and len(calendar_hash) == 64
    assert M.add_calendar_months(date(2024, 8, 31)) == date(2025, 2, 28)
    assert M.add_calendar_months(date(2023, 8, 31)) == date(2024, 2, 29)
    assert M.add_calendar_months(date(2026, 4, 30)) == date(2026, 10, 31)
    assert M.add_calendar_months(date(2026, 2, 28)) == date(2026, 8, 31)
    assert M.add_calendar_months(date(2024, 2, 29)) == date(2024, 8, 31)
    assert M.add_calendar_months(date(2026, 1, 31)) == date(2026, 7, 31)
    assert M.add_calendar_months(date(2026, 4, 29)) == date(2026, 10, 29)
    april_dates, april_end, _ = M.future_session_dates("2026-04-30")
    assert april_end == "2026-10-31" and april_dates[-1] == "2026-10-30"
    with pytest.raises(Daily6mContractError, match="not an XNAS session"):
        M.future_session_dates("2026-10-10")


def test_probability_is_pathwise_previous_close_not_marginal_median_change() -> None:
    # The marginal median increases from 100 to 101, but only one of three
    # actual paths rises.  This is the central probability-contract regression.
    paths = np.array([[1.0, 101.0], [100.0, 99.0], [200.0, 199.0]])
    rows, samples = M.summarize_joint_paths(paths, anchor=100, future_dates=["2026-10-12", "2026-10-13"])
    assert rows[0]["median_index"] == 100
    assert rows[1]["median_index"] == 101
    assert rows[1]["probability_up_from_previous"] == pytest.approx(1 / 3)
    assert rows[0]["probability_up_from_previous"] == pytest.approx(1 / 3)  # tie excluded
    assert rows[1]["probability_up_from_origin"] == pytest.approx(2 / 3)
    assert rows[1]["median_return_from_previous"] < 0
    assert len(samples) == 5
    for sample in samples:
        index = int(sample["path_id"].split("-")[-1])
        assert sample["values"] == paths[index].tolist()


@pytest.mark.parametrize("paths", [np.array([[0.0]]), np.array([[np.inf]]), np.array([[np.nan]])])
def test_invalid_joint_prices_are_rejected_without_clipping(paths: np.ndarray) -> None:
    with pytest.raises(Daily6mContractError, match="finite positive"):
        M.summarize_joint_paths(paths, anchor=100, future_dates=["2026-10-12"])


def test_fhs_joint_windows_reproduce_own_start_scaling_without_endpoint_stitching() -> None:
    returns = np.random.default_rng(4).normal(0.0003, 0.009, 800)
    paths = M.historical_fhs_paths(returns, anchor=200, horizon=3)
    variance = M._ewma_variance_series(returns, 0.97)
    mu = returns.mean()
    expected = mu + (returns[60:63] - mu) * np.sqrt(variance[-1] / variance[60])
    assert paths.shape == (800 - 3 + 1 - 60, 3)
    np.testing.assert_allclose(paths[0], 200 * np.exp(np.cumsum(expected)), rtol=1e-13)
    assert np.array_equal(paths, M.historical_fhs_paths(returns, anchor=200, horizon=3))
    with pytest.raises(Daily6mContractError):
        M.historical_fhs_paths(returns[:-1], anchor=200, horizon=3)


def test_captured_vix_tail_is_current_only_fully_linked_and_never_native_relabelled() -> None:
    tail = {"series_id": "VIXCLS", "source_id": "cboe_vix_archive", "data_grade": "captured_forward",
            "session": "2026-10-09", "observation_time": "2026-10-09", "raw_sha256": "a" * 64,
            "source_hash": "a" * 64, "receipt_id": "raw-receipt-vix", "receipt_verified": True,
            "receipt_raw_path": "data/timeseries_v2/raw/market/cboe_vix_archive/a.gz",
            "receipt_source_uri": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
            "receipt_http_status": 200, "source_unit": "index",
            "retrieved_at": "2026-10-10T07:48:15+00:00", "available_at": "2026-10-10T07:48:15+00:00",
            "vintage_start": "2026-10-10T07:48:15+00:00"}
    M._validate_registered_captured_tail({"market_rows": [tail]}, "2026-10-09")
    for changed in ({"session": "2026-10-08"}, {"data_grade": "native_pit"},
                    {"source_hash": "b" * 64}, {"receipt_id": None}, {"series_id": "NASDAQCOM"},
                    {"receipt_verified": False}, {"available_at": "2026-10-09T23:00:00+00:00"}):
        with pytest.raises(Daily6mContractError, match="captured VIX tail"):
            M._validate_registered_captured_tail({"market_rows": [{**tail, **changed}]}, "2026-10-09")
    with pytest.raises(Daily6mContractError, match="only one"):
        M._validate_registered_captured_tail({"market_rows": [tail, tail]}, "2026-10-09")


@pytest.fixture
def bundle() -> SimpleNamespace:
    import exchange_calendars as xcals

    exchange = xcals.get_calendar("XNAS", start="2020-01-01", end="2026-10-09")
    dates = tuple(stamp.date().isoformat() for stamp in exchange.sessions[-800:])
    rng = np.random.default_rng(75)
    y = rng.normal(0, 0.008, (800, 5))
    y[:, 0] += 0.0003
    x = rng.normal(0, 0.2, (800, 3))
    return SimpleNamespace(dates=dates, endogenous=y, exogenous=x,
                           endogenous_names=ENDOGENOUS_NAMES, exogenous_names=EXOGENOUS_NAMES,
                           history={"dates": dates[-3:], "index": [100, 101, 102]},
                           lineage={"max_available_at": "2026-10-10T01:00:00+00:00"}, issues=[])


@pytest.fixture
def quick_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the real immutable fitted coefficients and both actual simulators;
    # only suppress exhaustive lag/distribution selection in this fixture.
    def select(y, x, *, endog_names, exog_names, train_start=0):
        fitted = fit_ridge_varx(y, x, lag=1, alpha=1.0, endog_names=endog_names,
                                exog_names=exog_names, train_start=train_start)
        return replace(fitted, selection_score=0.0)

    monkeypatch.setattr(M, "select_ridge_varx_v2", select)
    monkeypatch.setattr(M, "select_distribution_parameters_v2", lambda _residuals, **_kwargs: (10, 0.97, {"selected": 1.0}))


@pytest.mark.usefixtures("quick_selector")
def test_reproducible_forecast_keeps_multivariate_paths_primary_and_comparator_separate(
    bundle: SimpleNamespace,
) -> None:
    dates, end, _ = M.future_session_dates(bundle.dates[-1])
    kwargs = dict(anchor=102, as_of="2026-10-12T00:00:00+00:00", future_dates=dates, path_count=64)
    payload, paths = M.generate_forecast_with_paths(bundle, **kwargs)
    again = M.generate_forecast(bundle, **kwargs)
    assert payload == again
    assert payload["content_hash"] == canonical_hash({k: v for k, v in payload.items() if k != "content_hash"})
    assert payload["model_id"] == MODEL_ID and payload["predictive_validation"] == "not_established"
    assert payload["calendar_end_date"] == end and payload["forecast_end_date"] == dates[-1]
    assert paths.shape == (64, len(dates)) and len(payload["records"]) == len(dates)
    assert payload["comparison"]["v8_raw_identity"]["pass"]
    assert payload["comparison"]["v8_raw_identity"]["max_abs_index_difference"] == 0
    assert payload["comparison"]["fhs"]["role"] == "independent_benchmark_only"
    assert payload["comparison"]["fhs"]["path_hash"] != payload["path_hash"]
    assert payload["comparison"]["v8_calibrated_endpoints"]["status"] == "unavailable"
    assert len(payload["comparison"]["v8_calibrated_endpoints"]["horizons"]) == 4
    rows, samples = M.summarize_joint_paths(paths, anchor=102, future_dates=dates)
    assert rows == payload["records"] and samples == payload["sample_paths"]
    assert json.dumps(payload, allow_nan=False)


def test_bad_availability_missing_features_and_truncated_dates_fail_before_fitting(bundle: SimpleNamespace) -> None:
    dates, _, _ = M.future_session_dates(bundle.dates[-1])
    with pytest.raises(Daily6mContractError, match="availability"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-09T23:00:00+00:00", future_dates=dates)
    with pytest.raises(Daily6mContractError, match="completed"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-09T00:00:00+00:00", future_dates=dates)
    with pytest.raises(Daily6mContractError, match="already closed"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-13T00:00:00+00:00", future_dates=dates)
    with pytest.raises(Daily6mContractError, match="timezone-aware"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-12T00:00:00", future_dates=dates)
    with pytest.raises(Daily6mContractError, match="complete exact"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-12T00:00:00+00:00", future_dates=dates[:-1])
    bundle.lineage = {"available_at_max": "2026-10-13T00:00:00+00:00"}
    with pytest.raises(Daily6mContractError, match="availability"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-12T00:00:00+00:00", future_dates=dates)
    bundle.lineage = {"market_rows": [{"available_at": "2026-10-13T00:00:00+00:00"}]}
    with pytest.raises(Daily6mContractError, match="market_rows"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-12T00:00:00+00:00", future_dates=dates)
    bundle.endogenous[10, 1] = np.nan
    with pytest.raises(Daily6mContractError, match="complete named"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-12T00:00:00+00:00", future_dates=dates)


@pytest.mark.usefixtures("quick_selector")
def test_source_provenance_only_change_keeps_identical_numerical_joint_paths(
    bundle: SimpleNamespace,
) -> None:
    dates, _, _ = M.future_session_dates(bundle.dates[-1])
    native = SimpleNamespace(**vars(bundle))
    native.lineage = {"market_rows": [{"source_id": "alfred", "series_id": "VIXCLS",
        "available_at": "2026-10-10T07:48:15+00:00"}]}
    tail = SimpleNamespace(**vars(bundle))
    tail.lineage = {"market_rows": [{"series_id": "VIXCLS", "source_id": "cboe_vix_archive",
        "session": bundle.dates[-1], "observation_time": bundle.dates[-1], "data_grade": "captured_forward",
        "raw_sha256": "a" * 64, "source_hash": "a" * 64, "receipt_id": "shadow-receipt",
        "receipt_verified": True, "receipt_http_status": 200, "source_unit": "index",
        "receipt_raw_path": "data/timeseries_daily6m/raw/cboe_vix_archive/a.gz",
        "receipt_source_uri": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        "retrieved_at": "2026-10-10T07:48:15+00:00", "available_at": "2026-10-10T07:48:15+00:00",
        "vintage_start": "2026-10-10T07:48:15+00:00"}]}
    kwargs = dict(anchor=102, as_of="2026-10-12T00:00:00+00:00", future_dates=dates, path_count=32)
    old, old_paths = M.generate_forecast_with_paths(native, **kwargs)
    new, new_paths = M.generate_forecast_with_paths(tail, **kwargs)
    np.testing.assert_array_equal(old_paths, new_paths)
    assert old["records"] == new["records"] and old["sample_paths"] == new["sample_paths"]
    assert new["comparison"]["v8_raw_identity"]["pass"] is True


@pytest.mark.usefixtures("quick_selector")
@pytest.mark.parametrize("lineage_shape", ["mapping", "list"])
def test_issuance_macro_state_is_used_without_overwriting_historical_training(
    bundle: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, lineage_shape: str,
) -> None:
    dates, _, _ = M.future_session_dates(bundle.dates[-1])
    original_training = bundle.exogenous.copy()
    bundle.issuance_exogenous = np.array([2.0, -3.0, 1.0])
    factor = {"cutoff": "2026-10-12T12:00:00+00:00", "cache_materialized_at": "2026-10-12T12:00:00+00:00"}
    bundle.issuance_factor_lineage = factor if lineage_shape == "mapping" else [factor]
    simulate = M.simulate_correlated_paths_v2

    def capture(fits, **kwargs):
        np.testing.assert_array_equal(kwargs["exog_last"], bundle.issuance_exogenous)
        return simulate(fits, **kwargs)

    monkeypatch.setattr(M, "simulate_correlated_paths_v2", capture)
    payload = M.generate_forecast(bundle, anchor=102, as_of="2026-10-12T14:00:00+00:00",
                                  future_dates=dates, path_count=64)
    np.testing.assert_array_equal(bundle.exogenous, original_training)
    assert payload["model_config"]["issuance_exogenous"]["growth_factor"] == 2.0
    assert payload["comparison"]["v8_raw_identity"]["pass"]
    for field in ("cutoff", "cache_materialized_at"):
        future = {**factor, field: "2026-10-12T15:00:00+00:00"}
        bundle.issuance_factor_lineage = future if lineage_shape == "mapping" else [future]
        with pytest.raises(Daily6mContractError, match="issuance_factor_lineage"):
            M.generate_forecast(bundle, anchor=102, as_of="2026-10-12T14:00:00+00:00",
                                future_dates=dates, path_count=64)


@pytest.mark.parametrize("malformed", ["cutoff", ["cutoff"], 1, 0, False, ""])
def test_malformed_issuance_factor_lineage_fails_before_fitting(bundle: SimpleNamespace, malformed) -> None:
    dates, _, _ = M.future_session_dates(bundle.dates[-1])
    bundle.issuance_factor_lineage = malformed
    with pytest.raises(Daily6mContractError, match="explicit lineage mappings"):
        M.generate_forecast(bundle, anchor=102, as_of="2026-10-12T14:00:00+00:00",
                            future_dates=dates, path_count=64)


def test_contract_never_inherits_a_predictive_pass_and_rejects_hidden_model_change(tmp_path: Path) -> None:
    import yaml

    target = tmp_path / CONTRACT_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / CONTRACT_RELATIVE).read_bytes())
    contract = load_contract(tmp_path)
    assert contract["model"]["path_count"] == PATH_COUNT
    assert contract["preview_gate"]["requires_predictive_performance_pass"] is False
    assert contract["publication"]["official_ledger_write"] is False
    contract["model"]["per_horizon_calibration"] = "v8"
    target.write_text(yaml.safe_dump(contract), encoding="utf-8")
    with pytest.raises(Daily6mContractError, match="model coordinates"):
        load_contract(tmp_path)
