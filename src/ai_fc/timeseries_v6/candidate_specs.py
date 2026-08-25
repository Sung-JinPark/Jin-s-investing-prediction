"""Contract-derived candidate specs and fail-closed runtime binding."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import ContractError, canonical_json, contract_hash, validate_contract


class RuntimeParameterMismatch(ContractError):
    """Raised before fit when runtime coordinates diverge from the contract."""


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    family: str
    role: str
    horizons: tuple[int, ...]
    parameters: Mapping[str, Any]
    contract_hash: str
    candidate_spec_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "role": self.role,
            "horizons": list(self.horizons),
            "parameters": copy.deepcopy(dict(self.parameters)),
            "contract_hash": self.contract_hash,
            "candidate_spec_hash": self.candidate_spec_hash,
        }


def compile_candidate_specs(contract: Mapping[str, Any]) -> dict[str, CandidateSpec]:
    """Compile E0--E10 from the validated frozen contract, adding no defaults."""

    receipt = validate_contract(contract)
    if contract["contract_status"] != "frozen":
        raise ContractError("candidate specs may only compile from a frozen contract")
    compiled: dict[str, CandidateSpec] = {}
    for candidate in contract["candidate_contract"]["candidates"]:
        canonical = {
            "contract_hash": receipt["contract_hash"],
            "candidate_id": candidate["id"],
            "family": candidate["family"],
            "role": candidate["role"],
            "horizons": candidate["horizons"],
            "parameters": candidate["parameters"],
        }
        spec = CandidateSpec(
            candidate_id=candidate["id"],
            family=candidate["family"],
            role=candidate["role"],
            horizons=tuple(candidate["horizons"]),
            parameters=copy.deepcopy(candidate["parameters"]),
            contract_hash=receipt["contract_hash"],
            candidate_spec_hash=_hash(canonical),
        )
        compiled[spec.candidate_id] = spec
    return compiled


def compile_runtime_parameters(
    spec: CandidateSpec,
    selected_grid_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve a fit coordinate from registered grids without implicit choices.

    A parameter named ``foo_grid`` becomes runtime parameter ``foo`` and the
    caller must supply an allowed value. Non-grid parameters are copied exactly
    from the contract. Missing, extra, or off-grid selections fail closed.
    """

    grid_names = {
        key.removesuffix("_grid"): values
        for key, values in spec.parameters.items()
        if key.endswith("_grid")
    }
    missing = sorted(set(grid_names) - set(selected_grid_values))
    extra = sorted(set(selected_grid_values) - set(grid_names))
    if missing or extra:
        raise RuntimeParameterMismatch(
            f"{spec.candidate_id} grid selection mismatch: missing={missing}, extra={extra}"
        )
    runtime: dict[str, Any] = {}
    for key, value in spec.parameters.items():
        if key.endswith("_grid"):
            name = key.removesuffix("_grid")
            selected = selected_grid_values[name]
            if selected not in value:
                raise RuntimeParameterMismatch(
                    f"{spec.candidate_id}.{name}={selected!r} is outside contract grid {value!r}"
                )
            runtime[name] = copy.deepcopy(selected)
        else:
            runtime[key] = copy.deepcopy(value)
    return runtime


def bind_runtime_parameters(
    spec: CandidateSpec,
    selected_grid_values: Mapping[str, Any],
    actual_runtime_parameters: Mapping[str, Any],
    *,
    fit_id: str,
    estimator_class: str,
) -> dict[str, Any]:
    """Create a fit receipt only when actual and compiled coordinates match."""

    expected = compile_runtime_parameters(spec, selected_grid_values)
    actual = copy.deepcopy(dict(actual_runtime_parameters))
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(
            key
            for key in set(expected) & set(actual)
            if canonical_json(expected[key]) != canonical_json(actual[key])
        )
        raise RuntimeParameterMismatch(
            f"{spec.candidate_id} runtime parameter mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    payload = {
        "schema_version": 1,
        "fit_id": fit_id,
        "candidate_id": spec.candidate_id,
        "family": spec.family,
        "estimator_class": estimator_class,
        "contract_hash": spec.contract_hash,
        "candidate_spec_hash": spec.candidate_spec_hash,
        "runtime_parameters": actual,
        "runtime_parameter_hash": _hash(actual),
        "binding_pass": True,
    }
    return payload


def candidate_manifest(contract: Mapping[str, Any]) -> dict[str, Any]:
    specs = compile_candidate_specs(contract)
    return {
        "schema_version": 1,
        "contract_hash": contract_hash(contract),
        "model_id": contract["model_id"],
        "contract_status": contract["contract_status"],
        "candidate_count": len(specs),
        "candidates": [specs[key].as_dict() for key in sorted(specs, key=lambda item: int(item[1:]))],
    }
