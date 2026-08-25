from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest

from ai_fc.timeseries_v7.contract import (
    ContractError,
    contract_hash,
    feasibility_report,
    friday_capacity,
    load_contract,
    validate_contract,
)


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "data/contracts/multivariate_timeseries_v7.yaml"


def test_frozen_contract_loads_with_explicit_probability_space() -> None:
    contract = load_contract(CONTRACT_PATH)
    assert contract["contract_status"] == "frozen_v7_p0_003"
    assert contract["probability_unit"] == "fraction"
    assert contract["probability_space"] == "research_timeseries_v7_conditional"
    assert len(contract_hash(contract)) == 64


def test_all_candidates_and_direct_horizons_are_frozen() -> None:
    contract = load_contract(CONTRACT_PATH)
    assert set(contract["candidates"]) == {f"E{index}" for index in range(11)}
    assert contract["target"]["horizons_sessions"] == [1, 5, 21, 63]
    assert contract["target"]["direct_horizon_required"] is True
    assert contract["target"]["path_samples"] == 20_000


def test_contract_rejects_ambiguous_probability_unit() -> None:
    contract = load_contract(CONTRACT_PATH)
    changed = copy.deepcopy(contract)
    changed["probability_unit"] = "percent_or_fraction"
    with pytest.raises(ContractError, match="probability unit"):
        validate_contract(changed)


def test_contract_rejects_weekly_row_purge() -> None:
    contract = load_contract(CONTRACT_PATH)
    changed = copy.deepcopy(contract)
    changed["validation"]["weekly_row_offset_purge"] = "allowed"
    with pytest.raises(ContractError, match="weekly-row purge"):
        validate_contract(changed)


def test_contract_rejects_automatic_publication_or_trading() -> None:
    contract = load_contract(CONTRACT_PATH)
    changed = copy.deepcopy(contract)
    changed["publication"]["automatic_customer_publication"] = "allowed"
    with pytest.raises(ContractError, match="automatic publication"):
        validate_contract(changed)
    changed = copy.deepcopy(contract)
    changed["publication"]["automatic_trading"] = "allowed"
    with pytest.raises(ContractError, match="automatic trading"):
        validate_contract(changed)


def test_gfc_is_feasible_in_open_historical_window() -> None:
    contract = load_contract(CONTRACT_PATH)
    report = feasibility_report(contract, as_of=date(2026, 8, 25))
    gfc = next(row for row in report["checks"] if row["gate"] == "historical_stress.gfc")
    assert gfc["available_capacity"] >= gfc["required"]
    assert gfc["feasible"] is True
    assert report["pass"] is True


def test_all_mandatory_sample_requirements_are_feasible() -> None:
    report = feasibility_report(load_contract(CONTRACT_PATH), as_of=date(2026, 8, 25))
    assert report["impossible_sample_requirement_count"] == 0
    assert all(row["feasible"] for row in report["checks"])


def test_prospective_gate_is_open_ended_not_falsely_satisfied() -> None:
    report = feasibility_report(load_contract(CONTRACT_PATH), as_of=date(2026, 8, 25))
    prospective = next(
        row for row in report["checks"]
        if row["gate"] == "prospective.minimum_forecast_origins"
    )
    assert prospective["available_capacity"] is None
    assert prospective["required"] == 126
    assert prospective["feasible"] is True
    assert "not_currently_mature" in prospective["basis"]


def test_weekly_capacity_detects_impossible_closed_window() -> None:
    assert friday_capacity(date(2020, 2, 1), date(2020, 2, 10)) == 1
    assert friday_capacity(date(2020, 2, 10), date(2020, 2, 1)) == 0
