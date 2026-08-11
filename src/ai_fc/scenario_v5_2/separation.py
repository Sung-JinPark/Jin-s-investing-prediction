"""Preregistered complete-separation and structural event-adapter contract."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import yaml


SEPARATION_CONTRACT_RELATIVE = Path("data/contracts/scenario_v5_3_separation.yaml")
SCENARIOS = ("S1", "S2", "S3")


class SeparationContractError(ValueError):
    """Raised when the complete-separation contract is unsafe or ambiguous."""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SeparationContractError(f"{label} must be a non-boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise SeparationContractError(f"{label} must be finite")
    return result


def _intervals_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_start, left_end = date.fromisoformat(left["start"]), date.fromisoformat(left["end"])
    right_start, right_end = date.fromisoformat(right["start"]), date.fromisoformat(right["end"])
    return max(left_start, right_start) <= min(left_end, right_end)


def validate_separation_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("contract_id") != "scenario_v5_3_complete_separation_v1":
        raise SeparationContractError("complete-separation contract identity mismatch")
    if contract.get("official_or_champion_use") is not False:
        raise SeparationContractError("separation candidate must remain research-only")
    if set(contract.get("shared_runtime_inputs_allowed", [])) != {
        "current_index_anchor", "trading_calendar",
    }:
        raise SeparationContractError("only anchor and trading calendar may be shared")
    schemas = contract.get("scenario_feature_schemas", {})
    libraries = contract.get("episode_libraries", {})
    if set(schemas) != set(SCENARIOS) or set(libraries) != set(SCENARIOS):
        raise SeparationContractError("S1/S2/S3 schemas and episode libraries are required")
    active_schemas = [tuple(schemas[key].get("active_coordinates", [])) for key in SCENARIOS]
    if any(not row for row in active_schemas) or len(set(active_schemas)) != 3:
        raise SeparationContractError("active feature schemas must be non-empty and distinct")
    episodes_by_scenario = {
        key: list(libraries[key].get("episodes", [])) for key in SCENARIOS
    }
    ids = [row["id"] for rows in episodes_by_scenario.values() for row in rows]
    if len(ids) != len(set(ids)):
        raise SeparationContractError("episode ids must be globally unique")
    overlaps: list[dict[str, str]] = []
    for left_index, left in enumerate(SCENARIOS):
        for right in SCENARIOS[left_index + 1:]:
            for left_episode in episodes_by_scenario[left]:
                for right_episode in episodes_by_scenario[right]:
                    if _intervals_overlap(left_episode, right_episode):
                        overlaps.append({
                            "left": left_episode["id"], "right": right_episode["id"]
                        })
    if overlaps:
        raise SeparationContractError(f"cross-scenario episode intervals overlap: {overlaps}")
    phase = contract.get("phase_duration_model", {})
    if phase.get("fixed_template_prohibited") is not True:
        raise SeparationContractError("fixed phase templates must be prohibited")
    return {
        "contract_id": contract["contract_id"],
        "feature_schema_hashable": {key: active_schemas[index]
                                    for index, key in enumerate(SCENARIOS)},
        "episode_counts": {key: len(value) for key, value in episodes_by_scenario.items()},
        "cross_scenario_interval_overlaps": overlaps,
        "cross_scenario_interval_overlap_count": 0,
        "D0_blocked_features": {
            key: list(schemas[key].get("blocked_D0_coordinates", []))
            for key in SCENARIOS
        },
    }


def load_separation_contract(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = root / SEPARATION_CONTRACT_RELATIVE
    if not path.is_file():
        raise SeparationContractError("complete-separation contract is missing")
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise SeparationContractError("complete-separation contract must be an object")
    return contract, validate_separation_contract(contract)


def structural_event_adapter(
    scores: dict[str, Any], contract: dict[str, Any],
) -> dict[str, Any]:
    """Map PIT-safe event scores into episode and duration selection parameters.

    The adapter never edits a path or endpoint.  It changes which observed
    episode segments are sampled and which observed durations are preferred.
    """
    policy = _finite(scores["policy_relief"]["bounded_score"], "policy_relief")
    growth = _finite(scores["labor_growth_risk"]["bounded_score"], "growth_risk")
    inflation = _finite(scores["inflation_risk"]["bounded_score"], "inflation_risk")
    rules = contract["event_adapter"]["rules"]
    log_weights = {
        "S1": {
            "dotcom": (
                _finite(rules["labor_growth_risk"]["S1_expansion_episode_log_weight"], "S1 growth rule") * growth
                + _finite(rules["inflation_risk"]["S1_expansion_episode_log_weight"], "S1 inflation rule") * inflation
            ),
            "easing": (
                _finite(rules["policy_relief"]["S1_easing_episode_log_weight"], "S1 policy rule") * policy
                + _finite(rules["labor_growth_risk"]["S1_expansion_episode_log_weight"], "S1 growth rule") * growth
            ),
            "ai_expansion": (
                _finite(rules["labor_growth_risk"]["S1_expansion_episode_log_weight"], "S1 growth rule") * growth
                + _finite(rules["inflation_risk"]["S1_expansion_episode_log_weight"], "S1 inflation rule") * inflation
            ),
        },
        "S2": {
            "soft_landing": (
                _finite(
                    rules["labor_growth_risk"]["S2_soft_landing_episode_log_weight"],
                    "S2 soft-landing growth rule",
                ) * growth
                + _finite(
                    rules["balanced_policy_relief"][
                        "S2_soft_landing_episode_log_weight"
                    ],
                    "S2 policy rule",
                ) * policy
            ),
            "balanced": (
                _finite(rules["labor_growth_risk"]["S2_balanced_episode_log_weight"], "S2 growth rule") * growth
                + _finite(rules["inflation_risk"]["S2_balanced_episode_log_weight"], "S2 inflation rule") * inflation
            ),
        },
        "S3": {
            "stress": (
                _finite(rules["labor_growth_risk"]["S3_stress_episode_log_weight"], "S3 growth rule") * growth
                + _finite(rules["inflation_risk"]["S3_tightening_episode_log_weight"], "S3 inflation rule") * inflation
            ),
            "tightening": (
                _finite(rules["policy_relief"]["S3_tightening_episode_log_weight"], "S3 policy rule") * policy
                + _finite(rules["inflation_risk"]["S3_tightening_episode_log_weight"], "S3 inflation rule") * inflation
            ),
        },
    }
    duration_tilts = {
        "S1": {
            "reacceleration": _finite(
                rules["policy_relief"]["S1_reacceleration_duration_tilt"],
                "S1 duration rule",
            ) * policy,
        },
        "S2": {
            "mean_reversion": _finite(
                rules["labor_growth_risk"]["S2_mean_reversion_duration_tilt"],
                "S2 mean-reversion duration rule",
            ) * growth,
        },
        "S3": {
            "drawdown": _finite(
                rules["labor_growth_risk"]["S3_drawdown_duration_tilt"],
                "S3 drawdown duration rule",
            ) * growth,
            "stress_persistence": _finite(
                rules["inflation_risk"]["S3_stress_persistence_duration_tilt"],
                "S3 persistence duration rule",
            ) * inflation,
        },
    }
    multipliers = {
        scenario: {group: math.exp(value) for group, value in groups.items()}
        for scenario, groups in log_weights.items()
    }
    dependency_cap = _finite(
        contract["event_adapter"]["dependency_cluster_cap"],
        "event adapter dependency cap",
    )
    maximum_absolute_adjustment = max(
        abs(value)
        for groups in [*log_weights.values(), *duration_tilts.values()]
        for value in groups.values()
    )
    if maximum_absolute_adjustment > dependency_cap + 1e-12:
        raise SeparationContractError(
            "structural event adjustment exceeds the registered dependency cap"
        )
    revision_ids = list(dict.fromkeys(
        str(value) for value in scores.get("source_event_revision_ids", [])
    ))
    return {
        "adapter_id": contract["event_adapter"]["contract_version"],
        "inputs": {
            "policy_relief": policy,
            "labor_growth_risk": growth,
            "inflation_risk": inflation,
        },
        "episode_group_log_weight_adjustments": log_weights,
        "episode_group_weight_multipliers": multipliers,
        "phase_duration_selection_tilts": duration_tilts,
        "structural_update_applied": any(
            abs(value) > 1e-12
            for groups in [*log_weights.values(), *duration_tilts.values()]
            for value in groups.values()
        ),
        "dependency_cap": dependency_cap,
        "maximum_absolute_log_weight_adjustment": maximum_absolute_adjustment,
        "dependency_cap_gate_pass": True,
        "probability_only_update": False,
        "source_event_revision_ids": revision_ids,
        "available_at_lte_as_of_verified_upstream": True,
    }
