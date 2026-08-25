from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_fc.timeseries_v6.contracts import (
    ContractError,
    contract_hash,
    load_contract,
    mutated_copy,
    validate_contract,
    validate_contract_files,
)


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "data/contracts/multivariate_timeseries_v6.yaml"
SCHEMA_PATH = ROOT / "data/contracts/multivariate_timeseries_v6.schema.json"


def test_repository_v6_contract_validates_without_defaults() -> None:
    receipt = validate_contract_files(CONTRACT_PATH, SCHEMA_PATH)
    assert receipt["pass"] is True
    assert receipt["candidate_count"] == 11
    assert receipt["source_count"] == 37
    assert receipt["horizons"] == [1, 5, 21, 63]
    assert receipt["quantile_count"] == 9
    assert len(receipt["contract_hash"]) == 64


def test_missing_coordinate_and_unknown_top_level_key_fail_closed() -> None:
    contract = load_contract(CONTRACT_PATH)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    missing = mutated_copy(contract)
    del missing["target"]
    with pytest.raises(ContractError, match="missing"):
        validate_contract(missing, schema=schema)
    unknown = mutated_copy(contract)
    unknown["hidden_runtime_default"] = 0.05
    with pytest.raises(ContractError, match="unknown"):
        validate_contract(unknown, schema=schema)


def test_hgb_runtime_coordinates_and_gate_thresholds_are_frozen() -> None:
    contract = load_contract(CONTRACT_PATH)
    bad_hgb = mutated_copy(contract)
    bad_hgb["candidate_contract"]["candidates"][3]["parameters"]["learning_rate_grid"] = [0.05]
    with pytest.raises(ContractError, match="learning-rate"):
        validate_contract(bad_hgb)

    bad_gate = mutated_copy(contract)
    bad_gate["gate_contract"]["research"]["long_horizon_mean_crps_improvement_min"] = 0.0
    with pytest.raises(ContractError, match="CRPS"):
        validate_contract(bad_gate)


def test_probability_and_pit_units_cannot_be_inferred_or_clipped() -> None:
    contract = load_contract(CONTRACT_PATH)
    percent = mutated_copy(contract)
    percent["probability_unit"] = "percent"
    with pytest.raises(ContractError, match="probability"):
        validate_contract(percent)
    date_join = mutated_copy(contract)
    date_join["data_contract"]["date_only_join"] = "allowed"
    with pytest.raises(ContractError, match="date-only"):
        validate_contract(date_join)


def test_contract_hash_is_canonical_and_changes_on_any_coordinate() -> None:
    contract = load_contract(CONTRACT_PATH)
    first = contract_hash(contract)
    reordered = {key: contract[key] for key in reversed(list(contract))}
    assert contract_hash(reordered) == first
    changed = mutated_copy(contract)
    changed["candidate_contract"]["candidates"][1]["parameters"]["alpha_grid"][0] = 0.0002
    assert contract_hash(changed) != first
