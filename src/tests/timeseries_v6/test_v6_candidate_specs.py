from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.timeseries_v6.candidate_specs import (
    RuntimeParameterMismatch,
    bind_runtime_parameters,
    candidate_manifest,
    compile_candidate_specs,
    compile_runtime_parameters,
)
from ai_fc.timeseries_v6.contracts import ContractError, load_contract, mutated_copy


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "data/contracts/multivariate_timeseries_v6.yaml"


def test_frozen_contract_compiles_exactly_e0_through_e10_deterministically() -> None:
    contract = load_contract(CONTRACT_PATH)
    first = compile_candidate_specs(contract)
    second = compile_candidate_specs(contract)
    assert list(first) == [f"E{index}" for index in range(11)]
    assert {key: value.candidate_spec_hash for key, value in first.items()} == {
        key: value.candidate_spec_hash for key, value in second.items()
    }
    assert len(set(value.candidate_spec_hash for value in first.values())) == 11
    assert candidate_manifest(contract)["candidate_count"] == 11


def test_unfrozen_contract_is_rejected() -> None:
    contract = load_contract(CONTRACT_PATH)
    changed = mutated_copy(contract)
    changed["contract_status"] = "preregistered_unfrozen_until_v6_p0_005"
    with pytest.raises(ContractError, match="frozen"):
        compile_candidate_specs(changed)


def test_e3_hidden_learning_rate_is_rejected_before_fit() -> None:
    spec = compile_candidate_specs(load_contract(CONTRACT_PATH))["E3"]
    selected = {
        "learning_rate": 0.03,
        "max_leaf_nodes": 7,
        "max_iter": 100,
        "l2_regularization": 0.0,
        "min_samples_leaf": 20,
    }
    expected = compile_runtime_parameters(spec, selected)
    receipt = bind_runtime_parameters(
        spec,
        selected,
        expected,
        fit_id="fit-e3-test",
        estimator_class="HistGradientBoostingRegressor",
    )
    assert receipt["binding_pass"] is True
    assert receipt["runtime_parameters"]["learning_rate"] == 0.03
    assert len(receipt["runtime_parameter_hash"]) == 64

    hidden = dict(expected)
    hidden["learning_rate"] = 0.05
    with pytest.raises(RuntimeParameterMismatch, match="changed"):
        bind_runtime_parameters(
            spec,
            selected,
            hidden,
            fit_id="fit-e3-hidden",
            estimator_class="HistGradientBoostingRegressor",
        )


def test_grid_selection_requires_every_and_only_registered_coordinate() -> None:
    spec = compile_candidate_specs(load_contract(CONTRACT_PATH))["E2"]
    with pytest.raises(RuntimeParameterMismatch, match="missing"):
        compile_runtime_parameters(spec, {"degrees_of_freedom": 6})
    with pytest.raises(RuntimeParameterMismatch, match="extra"):
        compile_runtime_parameters(
            spec,
            {"degrees_of_freedom": 6, "ridge_alpha": 0.1, "secret_alpha": 9},
        )
    with pytest.raises(RuntimeParameterMismatch, match="outside"):
        compile_runtime_parameters(
            spec,
            {"degrees_of_freedom": 5, "ridge_alpha": 0.1},
        )


def test_runtime_binding_rejects_missing_and_extra_parameters() -> None:
    spec = compile_candidate_specs(load_contract(CONTRACT_PATH))["E5"]
    selected = {"global_shrinkage": 0.5}
    expected = compile_runtime_parameters(spec, selected)
    missing = dict(expected)
    missing.pop("regime_count")
    with pytest.raises(RuntimeParameterMismatch, match="missing"):
        bind_runtime_parameters(spec, selected, missing, fit_id="missing", estimator_class="Gate")
    extra = dict(expected, hidden_default=True)
    with pytest.raises(RuntimeParameterMismatch, match="extra"):
        bind_runtime_parameters(spec, selected, extra, fit_id="extra", estimator_class="Gate")
