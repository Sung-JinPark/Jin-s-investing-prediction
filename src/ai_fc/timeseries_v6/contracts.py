"""Machine validation for the preregistered V6 research contract.

The contract is the sole source of model/data/evaluation coordinates.  This
module validates; it never supplies a missing default.  Candidate compilation
and runtime parameter receipts are implemented in the next P0 task.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml


MODEL_ID = "shadow.nasdaq_pit_hierarchical_distribution_v6"
PROBABILITY_SPACE = "research_timeseries_v6_conditional"
EXPECTED_CANDIDATES = tuple(f"E{index}" for index in range(11))
EXPECTED_HORIZONS = [1, 5, 21, 63]
EXPECTED_QUANTILES = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
EXPECTED_SOURCE_COUNT = 37


class ContractError(RuntimeError):
    """Raised when a V6 contract coordinate is missing or inconsistent."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def contract_hash(contract: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(contract).encode("utf-8")).hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ContractError("V6 contract must be a mapping")
    return payload


def _require(mapping: Mapping[str, Any], key: str, location: str) -> Any:
    if key not in mapping:
        raise ContractError(f"missing contract coordinate: {location}.{key}")
    return mapping[key]


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _validate_top_level_schema(contract: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    required = schema.get("required", [])
    missing = sorted(set(required) - set(contract))
    _assert(not missing, f"schema-required V6 coordinates missing: {missing}")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(contract) - set(schema.get("properties", {})))
        _assert(not unknown, f"unknown top-level V6 contract coordinates: {unknown}")
    for key, rule in schema.get("properties", {}).items():
        if key not in contract:
            continue
        if "const" in rule:
            _assert(contract[key] == rule["const"], f"{key} must equal {rule['const']!r}")
        if "enum" in rule:
            _assert(contract[key] in rule["enum"], f"{key} is outside schema enum")


def validate_contract(
    contract: Mapping[str, Any],
    *,
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed on every fixed V6 coordinate and return a validation receipt."""

    if schema is not None:
        _validate_top_level_schema(contract, schema)

    _assert(_require(contract, "schema_version", "root") == 6, "schema_version must be 6")
    _assert(_require(contract, "model_id", "root") == MODEL_ID, "V6 model_id mismatch")
    _assert(
        _require(contract, "probability_space", "root") == PROBABILITY_SPACE,
        "V6 probability space mismatch",
    )
    _assert(_require(contract, "probability_unit", "root") == "fraction", "probability unit must be fraction")

    predecessor = _require(contract, "immutable_predecessor", "root")
    _assert(predecessor["may_modify"] is False, "V5 predecessor must be immutable")
    _assert(predecessor["status"] == "shadow_gate_hold", "V5 HOLD status must be preserved")
    _assert(len(predecessor["protected_content_hash"]) == 64, "protected manifest hash is invalid")

    runtime = _require(contract, "runtime", "root")
    for key in (
        "python", "platform", "requirements_lock", "requirements_lock_sha256",
        "replay_container", "runtime_receipt", "deterministic_environment",
        "prohibited_runtime_defaults",
    ):
        _require(runtime, key, "runtime")
    _assert(runtime["prohibited_runtime_defaults"] is True, "runtime defaults must be prohibited")
    _assert(len(runtime["requirements_lock_sha256"]) == 64, "runtime lock hash is invalid")

    target = _require(contract, "target", "root")
    _assert(target["exchange"] == "XNAS", "target exchange must be XNAS")
    _assert(target["series_id"] == "NASDAQCOM", "target series must be NASDAQCOM")
    _assert(target["horizons_sessions"] == EXPECTED_HORIZONS, "target horizons changed")
    _assert(target["quantile_levels"] == EXPECTED_QUANTILES, "target quantiles changed")
    _assert(target["stored_probability_unit"] == "fraction", "stored probability unit changed")
    _assert(target["recursive_one_day_to_long_horizon"] == "prohibited", "recursive long-horizon target is prohibited")

    data = _require(contract, "data_contract", "root")
    _assert(data["append_only"] is True, "V6 facts must be append-only")
    _assert(data["raw_before_derived"] == "required", "raw-before-derived is required")
    _assert(data["eligibility_rule"] == "max_available_at_lte_origin_cutoff_at", "PIT rule changed")
    _assert(data["date_only_join"] == "prohibited", "date-only PIT joins are prohibited")
    _assert(data["generic_jsonb_core_entity_writes"] == "prohibited", "typed storage may not be bypassed")

    sources = _require(contract, "source_registry_contract", "root")
    ids = sources["canonical_ids"]
    _assert(sources["expected_source_count"] == EXPECTED_SOURCE_COUNT, "source count coordinate changed")
    _assert(len(ids) == EXPECTED_SOURCE_COUNT, "contract must contain exactly 37 canonical sources")
    _assert(len(ids) == len(set(ids)), "canonical source IDs must be unique")

    features = _require(contract, "feature_contract", "root")
    _assert(features["feature_value_provenance_required"] is True, "feature-value PIT proof required")
    _assert(features["legacy_without_v6_proof"] == "quarantined", "unproven legacy feature must be quarantined")

    candidate_contract = _require(contract, "candidate_contract", "root")
    _assert(candidate_contract["runtime_parameter_binding_required"] is True, "runtime binding required")
    _assert(candidate_contract["outer_result_retuning"] == "prohibited", "outer-result retuning prohibited")
    candidates = candidate_contract["candidates"]
    ids = [candidate["id"] for candidate in candidates]
    _assert(tuple(ids) == EXPECTED_CANDIDATES, "candidate IDs/order must be E0 through E10")
    for candidate in candidates:
        for key in ("id", "family", "role", "horizons", "parameters"):
            _require(candidate, key, f"candidate.{candidate.get('id', '?')}")
        _assert(candidate["parameters"], f"candidate {candidate['id']} parameters may not be empty")
        _assert(set(candidate["horizons"]).issubset(EXPECTED_HORIZONS), f"candidate {candidate['id']} horizon invalid")
    hgb = candidates[3]["parameters"]
    _assert(hgb["learning_rate_grid"] == [0.03, 0.07], "E3 learning-rate grid mismatch")
    _assert(hgb["max_leaf_nodes_grid"] == [7, 15], "E3 max-leaf grid mismatch")
    _assert(hgb["quantiles"] == EXPECTED_QUANTILES, "E3 must model all contract quantiles")
    _assert(candidates[8]["parameters"]["minimum_independent_resolved_events"] == 60, "event minimum changed")
    _assert(candidates[10]["parameters"]["default_weight"] == 0.0, "foundation challenger must start at zero")

    validation = _require(contract, "validation_contract", "root")
    _assert(validation["purge_sessions"] == 63, "purge changed")
    _assert(validation["embargo_sessions"] == 5, "embargo changed")
    _assert(validation["selection_stacking_calibration_disjoint"] is True, "adaptive folds must be disjoint")
    _assert(validation["comparator_identity_exact"] is True, "comparator identity must be exact")

    ensemble = _require(contract, "ensemble_contract", "root")
    _assert(ensemble["anchor_floor"] == {1: 0.20, 5: 0.25, 21: 0.40, 63: 0.50}, "anchor floors changed")
    _assert(ensemble["rowwise_oracle"] == "prohibited", "rowwise oracle is prohibited")

    paths = _require(contract, "path_contract", "root")
    _assert(paths["deterministic_endpoint_interpolation"] == "prohibited", "fake path interpolation prohibited")
    _assert(paths["sample_count"] == 20_000, "path sample count changed")

    gates = _require(contract, "gate_contract", "root")
    _assert(gates["integrity_precedes_performance"] is True, "integrity Gate must run first")
    _assert(gates["research"]["long_horizon_mean_crps_improvement_min"] == 0.02, "CRPS Gate changed")
    _assert(gates["gate_threshold_change_after_outer_result"] == "prohibited", "Gate retuning prohibited")

    atlas = _require(contract, "atlas_contract", "root")
    _assert(atlas["one_codex_task_per_invocation"] is True, "one-task worker boundary required")
    _assert(atlas["same_blocker_stop_count"] == 3, "blocker circuit-breaker changed")
    _assert(atlas["automatic_model_retuning_after_gate"] == "prohibited", "automatic Gate tuning prohibited")

    publication = _require(contract, "publication_contract", "root")
    for key in ("automatic_promotion", "automatic_publication", "automatic_trading"):
        _assert(publication[key] is False, f"{key} must remain false")
    _assert(publication["explicit_owner_approval_required"] is True, "owner approval required")

    return {
        "schema_version": 1,
        "contract_id": contract["contract_id"],
        "model_id": contract["model_id"],
        "contract_status": contract["contract_status"],
        "contract_hash": contract_hash(contract),
        "candidate_count": len(candidates),
        "source_count": len(sources["canonical_ids"]),
        "horizons": target["horizons_sessions"],
        "quantile_count": len(target["quantile_levels"]),
        "pass": True,
    }


def validate_contract_files(contract_path: Path, schema_path: Path) -> dict[str, Any]:
    contract = load_contract(contract_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return validate_contract(contract, schema=schema)


def mutated_copy(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Test helper that makes an isolated mutable copy without adding defaults."""

    return copy.deepcopy(dict(contract))
