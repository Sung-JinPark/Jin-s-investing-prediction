"""generate_v2_forecast: synthetic bundles, v1 module-attribute monkeypatch (review N12)."""
from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import ai_fc.timeseries_daily6m.contracts as v1C
import ai_fc.timeseries_daily6m.model as v1M
from ai_fc.timeseries.model import fit_ridge_varx
from ai_fc.timeseries_daily6m.contracts import ENDOGENOUS_NAMES, EXOGENOUS_NAMES
from ai_fc.timeseries_daily6m_v2 import kernel as K
from ai_fc.timeseries_daily6m_v2 import model as M
from ai_fc.timeseries_daily6m_v2.contracts import ARMS, Daily6mV2ContractError, canonical_hash

REPO = Path(__file__).resolve().parents[2]
AS_OF = "2026-10-12T00:00:00+00:00"
CONSTANTS = {
    "persistence_by_column": {"nasdaq_return": 0.98708, "vix_change": 0.88011, "dgs2_change_bps": 0.99947,
                              "curve_change_bps": 0.99350, "dollar_change": 0.99535},
    "long_run_rule": {"registered": "slow_ewma_0.996"},
    "selection": {"seed": 20261111, "replicates": 2, "paths": 100, "validation_horizon": 21,
                  "hysteresis_mc_sd": 1.0, "default_incumbent": [10, 0.97]},
}


@pytest.fixture
def bundle() -> SimpleNamespace:
    import exchange_calendars as xcals
    exchange = xcals.get_calendar("XNAS", start="2020-01-01", end="2026-10-09")
    dates = tuple(stamp.date().isoformat() for stamp in exchange.sessions[-800:])
    rng = np.random.default_rng(75)
    y = rng.normal(0, 0.008, (800, 5))
    y[:, 0] += 0.0003
    x = rng.normal(0, 0.2, (800, 3))
    return SimpleNamespace(dates=dates, endogenous=y, exogenous=x, endogenous_names=ENDOGENOUS_NAMES,
                           exogenous_names=EXOGENOUS_NAMES, history={"dates": dates[-3:], "index": [100, 101, 102]},
                           lineage={"max_available_at": "2026-10-10T01:00:00+00:00"}, issues=[],
                           issuance_exogenous=x[-1].copy())


@pytest.fixture
def quick_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    def select(y, x, *, endog_names, exog_names, train_start=0):
        fitted = fit_ridge_varx(y, x, lag=1, alpha=1.0, endog_names=endog_names, exog_names=exog_names, train_start=train_start)
        return replace(fitted, selection_score=0.0)
    # one patch point: v2 calls the v1 module attribute
    monkeypatch.setattr(v1M, "select_ridge_varx_v2", select)
    monkeypatch.setattr(v1M, "select_distribution_parameters_v2", lambda _r, **_k: (10, 0.97, {"selected": 1.0}))


def v1_run_for(bundle) -> dict:
    dates, _, _ = v1M.future_session_dates(bundle.dates[-1])
    payload, _ = v1M.generate_forecast_with_paths(bundle, anchor=102, as_of=AS_OF, future_dates=dates, path_count=64)
    return {**payload, "run_id": "daily6m-fixture", "anchor_date": bundle.dates[-1], "dates": dates,
            "anchor": {"series_id": "NASDAQCOM", "date": bundle.dates[-1], "value": 102.0, "available_at": AS_OF},
            "model_code_hash": v1C.model_code_hash(REPO), "contract_hash": "c" * 64}


def generate(bundle, v1_run, **overrides):
    kwargs = dict(anchor=102.0, as_of=AS_OF, future_dates=v1_run["dates"], v1_run=v1_run, previous_selection=None,
                  constants=CONSTANTS, root=REPO)
    kwargs.update(overrides)
    return M.generate_v2_forecast(bundle, **kwargs)


@pytest.mark.usefixtures("quick_selector")
def test_deterministic_identical_inputs_and_v1_grid(bundle):
    v1_run = v1_run_for(bundle)
    payload, paths = generate(bundle, v1_run)
    again, _ = generate(bundle, v1_run)
    assert payload == again
    assert payload["content_hash"] == canonical_hash({k: v for k, v in payload.items() if k != "content_hash"})
    assert payload["pair_status"] == "identical_inputs" and payload["inputs_differ_reason"] is None
    assert payload["reduction_identity"]["resimulated_path_hash"] == v1_run["path_hash"]
    assert payload["reduction_identity"]["fit_residual_hash_equal"] == {"expanding": True, "rolling": True}
    assert payload["reduction_identity"]["runtime"]["numpy"]
    grid = np.array(payload["v1_reference"]["quantile_grid"])
    for row, name in zip(K.BAND_ROWS, K.BAND_NAMES):
        expected = np.log(np.array([r["band_index"][name] for r in v1_run["records"]]) / 102.0)
        assert np.max(np.abs(grid[row] - expected)) <= 1e-9
    assert set(paths) == set(ARMS) and payload["selection"]["previous"] is None
    horizon = len(v1_run["dates"])
    for arm in ARMS:
        records = payload["arms"][arm]["records"]
        assert len(records) == horizon and len(payload["arms"][arm]["quantile_grid"]) == 39
        for record in records:
            bands = [record["band_index"][n] for n in K.BAND_NAMES]
            assert bands == sorted(bands)
            assert 0 <= record["probability_up_from_previous"] <= 1 and 0 <= record["probability_up_from_origin"] <= 1
    assert payload["arms"]["main"]["quantile_grid"][19][0] == payload["arms"]["term_structure"]["quantile_grid"][19][0]
    assert payload["numbers_visible"] is False and payload["probability_unit"] == "fraction"


@pytest.mark.usefixtures("quick_selector")
def test_inputs_differ_paths_and_exogenous_reuse(bundle, monkeypatch):
    v1_run = v1_run_for(bundle)
    shifted = SimpleNamespace(**vars(bundle))
    shifted.issuance_exogenous = bundle.issuance_exogenous + np.array([0.0, 0.0, 1.0])
    payload, _ = generate(shifted, v1_run)
    assert payload["pair_status"] == "identical_inputs"   # v1 recorded projection exogenous is used (D14)
    assert payload["v2_bundle_issuance_exogenous"][2] == pytest.approx(bundle.issuance_exogenous[2] + 1)
    changed = SimpleNamespace(**vars(bundle))
    changed.endogenous = bundle.endogenous.copy()
    changed.endogenous[-1, 0] += 0.01
    differ, _ = generate(changed, v1_run)
    assert differ["pair_status"] == "inputs_differ" and differ["inputs_differ_reason"] == "path_hash"
    assert differ["v1_reference"]["quantile_grid"] is None
    assert differ["reduction_identity"]["fit_residual_hash_equal"]["expanding"] is False
    monkeypatch.setattr(v1C, "model_code_hash", lambda _root: "0" * 64)
    code, _ = generate(bundle, v1_run)
    assert code["pair_status"] == "inputs_differ" and code["inputs_differ_reason"] == "v1_code_hash"


@pytest.mark.usefixtures("quick_selector")
def test_forward_only_and_pairing_guards(bundle):
    v1_run = v1_run_for(bundle)
    with pytest.raises(Daily6mV2ContractError, match="closed"):
        generate(bundle, v1_run, as_of="2026-10-12T21:00:00+00:00")
    with pytest.raises(Daily6mV2ContractError, match="anchor"):
        generate(bundle, {**v1_run, "anchor_date": "2026-10-08"})
    with pytest.raises(Daily6mV2ContractError, match="future dates"):
        generate(bundle, v1_run, future_dates=v1_run["dates"][:-1])
    with pytest.raises(Daily6mV2ContractError):
        generate(bundle, v1_run, previous_selection=None, path_count=128)


@pytest.mark.usefixtures("quick_selector")
def test_previous_selection_is_threaded(bundle):
    v1_run = v1_run_for(bundle)
    payload, _ = generate(bundle, v1_run, previous_selection=[21, 0.94])
    assert payload["selection"]["previous"] == [21, 0.94] and payload["selection"]["incumbent"] == [21, 0.94]


def test_no_v8_b4_or_fhs_inheritance():
    source = inspect.getsource(K) + inspect.getsource(M)
    for name in ("bounded_location_shift", "fhs_horizon_samples", "historical_fhs_paths"):
        assert name not in source
