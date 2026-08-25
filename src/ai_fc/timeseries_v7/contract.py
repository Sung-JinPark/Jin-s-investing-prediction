"""Frozen V7 contract loader and structural feasibility checks."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml


class ContractError(ValueError):
    """The V7 preregistration contract is invalid or structurally infeasible."""


REQUIRED_TOP_LEVEL = {
    "schema_version", "contract_id", "contract_status", "model_id",
    "model_version", "probability_space", "probability_unit",
    "immutable_predecessor", "target", "data_integrity", "validation",
    "historical_stress", "candidates", "ensemble", "calibration",
    "path_forecast", "gates", "publication", "ralph",
}
DATE_STRESS_SUITES = (
    "gfc", "pandemic", "tightening_2022", "rebound_2009",
    "rebound_2020", "bull_2023",
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def contract_hash(contract: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(contract).encode("utf-8")).hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError("contract must be a mapping")
    validate_contract(value)
    return value


def _fraction(value: Any, name: str) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ContractError(f"{name} must be a fraction in [0,1]")
    return number


def _range(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ContractError(f"{name} must be a two-element range")
    lower, upper = float(value[0]), float(value[1])
    if lower > upper:
        raise ContractError(f"{name} lower bound exceeds upper bound")
    return lower, upper


def validate_contract(contract: dict[str, Any]) -> None:
    missing = REQUIRED_TOP_LEVEL - set(contract)
    if missing:
        raise ContractError(f"missing contract sections: {sorted(missing)}")
    if contract["schema_version"] != 7 or contract["model_version"] != 7:
        raise ContractError("V7 schema/model version mismatch")
    if contract["contract_status"] != "frozen_v7_p0_003":
        raise ContractError("contract is not frozen at V7-P0-003")
    if contract["model_id"] != "shadow.nasdaq_pit_hierarchical_distribution_v7":
        raise ContractError("unexpected model id")
    if contract["probability_space"] != "research_timeseries_v7_conditional":
        raise ContractError("unexpected probability space")
    if contract["probability_unit"] != "fraction":
        raise ContractError("stored probability unit must be fraction")
    target = contract["target"]
    if target["horizons_sessions"] != [1, 5, 21, 63]:
        raise ContractError("direct horizons differ from preregistration")
    if target["stored_probability_unit"] != "fraction":
        raise ContractError("target probability unit must be fraction")
    quantiles = [float(value) for value in target["quantile_levels"]]
    if quantiles != sorted(set(quantiles)) or any(not 0 < value < 1 for value in quantiles):
        raise ContractError("quantile levels must be unique and monotonic")
    if int(target["path_samples"]) < 20_000:
        raise ContractError("path sample count is below 20,000")
    validation = contract["validation"]
    if validation["purge_rule"] != "train.label_end_session + embargo_sessions < validation.origin_session":
        raise ContractError("purge rule is not label-session based")
    if validation["weekly_row_offset_purge"] != "prohibited":
        raise ContractError("weekly-row purge must be prohibited")
    if len(set(validation["roles_per_outer_origin"])) != 5:
        raise ContractError("five disjoint fold roles are required")
    floors = contract["candidates"]["E0"]["minimum_ensemble_weight"]
    for horizon in (1, 5, 21, 63):
        _fraction(floors[str(horizon)], f"E0 floor h{horizon}")
    if set(contract["candidates"]) != {f"E{index}" for index in range(11)}:
        raise ContractError("candidate registry must contain exactly E0-E10")
    gates = contract["gates"]
    _range(gates["historical_research"]["coverage_80_range"], "coverage_80_range")
    _range(gates["historical_research"]["coverage_50_range"], "coverage_50_range")
    for key in (
        "long_horizon_mean_crps_skill_min", "each_long_horizon_skill_min",
        "balanced_direction_accuracy_min", "extreme_q4_coverage_min",
        "catastrophic_phase_underperformance_max",
    ):
        _fraction(gates["historical_research"][key], key)
    if contract["publication"]["automatic_customer_publication"] != "prohibited":
        raise ContractError("automatic publication must remain prohibited")
    if contract["publication"]["automatic_trading"] != "prohibited":
        raise ContractError("automatic trading must remain prohibited")


def friday_capacity(start: date, end: date) -> int:
    if start > end:
        return 0
    cursor = start + timedelta(days=(4 - start.weekday()) % 7)
    count = 0
    while cursor <= end:
        count += 1
        cursor += timedelta(days=7)
    return count


def feasibility_report(contract: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    validate_contract(contract)
    validation = contract["validation"]
    historical = validation["historical_research"]
    start = date.fromisoformat(historical["start"])
    # Conservative maturity allowance: 63 sessions plus holidays/weekends.
    mature_end = as_of - timedelta(days=105)
    historical_capacity = friday_capacity(start, mature_end)
    minimum_total = int(historical["minimum_total_origins"])
    checks: list[dict[str, Any]] = [{
        "gate": "historical_research.total_origins",
        "available_capacity": historical_capacity,
        "required": minimum_total,
        "feasible": historical_capacity >= minimum_total,
        "basis": "conservative_weekly_capacity_through_last_63_session_maturity",
    }]
    binding_minimum = int(contract["historical_stress"]["binding_coverage_minimum_origins"])
    for name in DATE_STRESS_SUITES:
        suite = contract["historical_stress"]["suites"][name]
        capacity = friday_capacity(date.fromisoformat(suite["start"]), date.fromisoformat(suite["end"]))
        checks.append({
            "gate": f"historical_stress.{name}",
            "available_capacity": capacity,
            "required": binding_minimum,
            "feasible": capacity >= binding_minimum,
            "basis": "declared_open_historical_window",
        })
    prospective = contract["gates"]["prospective"]
    checks.append({
        "gate": "prospective.minimum_forecast_origins",
        "available_capacity": None,
        "required": int(prospective["minimum_forecast_origins"]),
        "feasible": prospective["open_ended_collection"] is True,
        "basis": "open_ended_post_freeze_collection_temporally_feasible_not_currently_mature",
    })
    checks.append({
        "gate": "prospective.active_regime",
        "available_capacity": None,
        "required": int(prospective["active_regime_binding_minimum_origins"]),
        "feasible": prospective["absent_regime_policy"] == "not_applicable",
        "basis": "absent_regime_is_not_a_failure",
    })
    failures = [row for row in checks if not row["feasible"]]
    return {
        "schema_version": 1,
        "contract_id": contract["contract_id"],
        "contract_hash": contract_hash(contract),
        "as_of": as_of.isoformat(),
        "mature_historical_end_conservative": mature_end.isoformat(),
        "checks": checks,
        "impossible_sample_requirement_count": len(failures),
        "failures": failures,
        "pass": not failures,
    }
