"""Evidence-backed identity and schema gates for scenario shadow artifacts."""

from __future__ import annotations

import math
from typing import Any


RCFHS_REQUIRED_CAPABILITIES = (
    "approved_pit_history",
    "observable_regime",
    "state_conditioned_drift",
    "conditional_volatility",
    "standardized_empirical_residuals",
    "stationary_block_bootstrap",
    "source_block_lineage",
    "continuous_252_session_recursion",
    "adaptive_joint_simulation",
    "pointwise_conditional_quantiles",
    "actual_member_representative",
)

ALLOWED_STATUSES = {
    "shadow_only",
    "stale_source",
    "blocked_missing_data",
    "retired_misidentified",
}
ALLOWED_QUANTILES = {"p05", "p10", "p25", "p50", "p75", "p90", "p95"}


class ScenarioShadowContractError(ValueError):
    """A shadow candidate failed an identity, probability, or lineage gate."""


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioShadowContractError(f"{name} must be an object")
    return value


def validate_model_identity(payload: dict[str, Any]) -> dict[str, Any]:
    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ScenarioShadowContractError("candidate_id is required")
    status = payload.get("status")
    if status not in ALLOWED_STATUSES:
        raise ScenarioShadowContractError("unsupported shadow candidate status")
    promotion = payload.get("promotion_state")
    if not isinstance(promotion, str) or not promotion:
        raise ScenarioShadowContractError("promotion_state is required")
    lowered_promotion = promotion.lower()
    if "official" in lowered_promotion or "champion" in lowered_promotion:
        raise ScenarioShadowContractError("shadow candidate cannot be official or champion")

    identity = _require_mapping(payload.get("model_identity"), "model_identity")
    family = identity.get("family")
    if family not in {"legacy_gbm", "rcfhs_sb"}:
        raise ScenarioShadowContractError("unsupported model family")
    capabilities = _require_mapping(identity.get("capabilities"), "capabilities")
    identity_flag = identity.get("is_rcfhs")
    if family == "legacy_gbm" and identity_flag is not False:
        raise ScenarioShadowContractError("legacy_gbm model_identity.is_rcfhs must be false")
    if family == "rcfhs_sb" and identity_flag is not True:
        raise ScenarioShadowContractError("rcfhs_sb model_identity.is_rcfhs must be true")

    claims_rcfhs = family == "rcfhs_sb" or "rcfhs" in candidate_id.lower()
    if claims_rcfhs:
        evidence = _require_mapping(
            identity.get("capability_evidence"), "capability_evidence"
        )
        for capability in RCFHS_REQUIRED_CAPABILITIES:
            if capabilities.get(capability) is not True:
                raise ScenarioShadowContractError(
                    f"RCFHS capability missing: {capability}"
                )
            row = _require_mapping(evidence.get(capability), f"evidence.{capability}")
            for field in ("implementation_component", "test_receipt", "input_lineage"):
                if not row.get(field):
                    raise ScenarioShadowContractError(
                        f"RCFHS evidence missing: {capability}.{field}"
                    )
    return payload


def validate_fraction_weights(weights: Any, name: str) -> None:
    row = _require_mapping(weights, name)
    if row.get("unit") != "fraction":
        raise ScenarioShadowContractError(f"{name}.unit must be fraction")
    values = _require_mapping(row.get("values"), f"{name}.values")
    if set(values) != {"S1", "S2", "S3"}:
        raise ScenarioShadowContractError(f"{name} must contain S1/S2/S3")
    for key, value in values.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ScenarioShadowContractError(f"{name}.{key} must be numeric")
        if not 0.0 <= float(value) <= 1.0:
            raise ScenarioShadowContractError(f"{name}.{key} must be in [0,1]")
    if not math.isclose(
        sum(float(value) for value in values.values()),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ScenarioShadowContractError(f"{name} values must sum to 1")


def validate_candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != 2:
        raise ScenarioShadowContractError("scenario shadow schema_version must be 2")
    if payload.get("status") != "shadow_only":
        raise ScenarioShadowContractError("stored candidate status must be shadow_only")
    validate_model_identity(payload)
    source = _require_mapping(payload.get("source"), "source")
    for field in ("snapshot_id", "snapshot_sha256", "asof", "method"):
        if not source.get(field):
            raise ScenarioShadowContractError(f"source.{field} is required")
    if "official_weights" in payload:
        validate_fraction_weights(payload["official_weights"], "official_weights")
    if "candidate_implied_weights" in payload:
        validate_fraction_weights(
            payload["candidate_implied_weights"], "candidate_implied_weights"
        )
    week_dates = payload.get("week_dates")
    if not isinstance(week_dates, list) or not week_dates:
        raise ScenarioShadowContractError("week_dates must be a non-empty array")
    distributions = _require_mapping(
        payload.get("scenario_distributions"), "scenario_distributions"
    )
    if set(distributions) != {"S1", "S2", "S3"}:
        raise ScenarioShadowContractError(
            "scenario_distributions must contain S1/S2/S3"
        )
    for scenario, distribution in distributions.items():
        row = _require_mapping(distribution, f"scenario_distributions.{scenario}")
        quantiles = _require_mapping(
            row.get("quantiles"), f"scenario_distributions.{scenario}.quantiles"
        )
        if not set(quantiles) <= ALLOWED_QUANTILES or "p50" not in quantiles:
            raise ScenarioShadowContractError(
                f"{scenario} quantiles must be an allowed set containing p50"
            )
        available = row.get("available_quantiles")
        if not isinstance(available, list) or set(available) != set(quantiles):
            raise ScenarioShadowContractError(
                f"{scenario} available_quantiles must match stored quantiles"
            )
        ordered = [
            key for key in ("p05", "p10", "p25", "p50", "p75", "p90", "p95")
            if key in quantiles
        ]
        arrays: list[list[int | float]] = []
        for key in ordered:
            values = quantiles[key]
            if not isinstance(values, list) or len(values) != len(week_dates):
                raise ScenarioShadowContractError(
                    f"{scenario}.{key} quantile length mismatch"
                )
            arrays.append(values)
        for left, right in zip(arrays, arrays[1:]):
            if any(float(a) > float(b) for a, b in zip(left, right)):
                raise ScenarioShadowContractError(
                    f"{scenario} quantiles are not monotone"
                )
    representatives = _require_mapping(payload.get("representatives"), "representatives")
    if not set(representatives) <= {"S1", "S2", "S3"}:
        raise ScenarioShadowContractError("representatives contain an unknown scenario")
    for scenario, representative in representatives.items():
        row = _require_mapping(representative, f"representatives.{scenario}")
        if not isinstance(row.get("original_global_path_index"), int):
            raise ScenarioShadowContractError(
                f"{scenario} representative global path index is required"
            )
        values = row.get("weekly_values")
        if not isinstance(values, list) or len(values) != len(week_dates):
            raise ScenarioShadowContractError(
                f"{scenario} representative weekly values length mismatch"
            )
    return payload
